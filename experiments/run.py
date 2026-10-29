"""正式实验运行器：执行规划并统一复核结果。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any
import argparse
import gc
import json
import math

import numpy as np

from src.algorithms import (
    AStarPlanner,
    InformedRRTStarPlanner,
    RCAStarPlanner,
    RRTStarPlanner,
    RRTStarResult,
    RiskAStarPlanner,
    RiskPathResult,
)
from src.core.collision import edge_in_collision, node_in_collision
from src.core.coords import Point3D, index_to_world, world_to_continuous_index, world_to_index
from src.core.grid import turn_is_allowed
from src.core.metrics import evaluate_path, sample_risk
from src.core.types import PLANNERS, PathResult, PlanRequest, PlannerBase
from src.io.scene import SceneData, load_scene


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DETERMINISTIC_CLASSES = (AStarPlanner, RiskAStarPlanner, RCAStarPlanner)
SAMPLING_CLASSES = (RRTStarPlanner, InformedRRTStarPlanner)


@dataclass(frozen=True, slots=True)
class PathAssessment:
    """合法性检查后的状态、问题列表和公共评估器指标。"""

    status: str
    failure_reason: str | None
    metrics: Mapping[str, float] | None
    validation: Mapping[str, object]
    resampled_points: int


def load_experiment_config(config_path: Path) -> tuple[dict[str, Any], bytes, str]:
    """读取实验配置并返回内容、原始字节和 SHA-256。"""
    resolved_path = config_path.expanduser()
    if not resolved_path.is_absolute():
        resolved_path = PROJECT_ROOT / resolved_path
    resolved_path = resolved_path.resolve()
    config_bytes = resolved_path.read_bytes()
    config = json.loads(config_bytes.decode("utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("实验配置顶层必须是 JSON 对象。")
    return config, config_bytes, sha256(config_bytes).hexdigest()


def _resolve_project_path(path_value: str, label: str) -> Path:
    """把配置中的项目相对路径解析为绝对路径。"""
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    if not resolved.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError(f"{label} 必须位于项目目录内：{resolved}")
    return resolved


def save_config_snapshot(snapshot_dir: Path, config_bytes: bytes, digest: str) -> Path:
    """按内容哈希保存原始实验配置快照，不覆盖已有快照。"""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"base-{digest}.json"
    if snapshot_path.exists():
        if snapshot_path.read_bytes() != config_bytes:
            raise ValueError(f"配置快照哈希冲突：{snapshot_path}")
    else:
        snapshot_path.write_bytes(config_bytes)
    return snapshot_path


def resample_path_1m(
    path: Sequence[Sequence[float]],
    config: Mapping[str, Any],
    spacing_m: float,
) -> tuple[Point3D, ...]:
    """沿线按指定米距取样，并映射到最近风险格心供公共 metrics 查询。"""
    if spacing_m <= 0 or not math.isfinite(spacing_m):
        raise ValueError("路径重采样间距必须为有限正数。")
    if not path:
        return ()
    if any(len(point) != 3 for point in path):
        raise ValueError("每个路径点都必须有三个坐标。")

    resampled: list[Point3D] = []

    def add_grid_point(point: np.ndarray) -> None:
        continuous_index = world_to_continuous_index(point, config)
        snapped_index = tuple(int(round(value)) for value in continuous_index)
        grid_point = index_to_world(snapped_index, config)
        if not resampled or grid_point != resampled[-1]:
            resampled.append(grid_point)

    first = np.asarray(path[0], dtype=np.float64)
    if not np.isfinite(first).all():
        raise ValueError("路径包含非有限坐标。")
    add_grid_point(first)

    for start_values, end_values in zip(path, path[1:]):
        start = np.asarray(start_values, dtype=np.float64)
        end = np.asarray(end_values, dtype=np.float64)
        if not np.isfinite(start).all() or not np.isfinite(end).all():
            raise ValueError("路径包含非有限坐标。")
        distance = float(np.linalg.norm(end - start))
        sample_count = max(1, math.ceil(distance / spacing_m))
        for sample_index in range(1, sample_count + 1):
            fraction = sample_index / sample_count
            add_grid_point(start + fraction * (end - start))
    return tuple(resampled)


def _inspect_path(
    scene: SceneData,
    request: PlanRequest,
    path: Sequence[Sequence[float]],
    spacing_m: float,
) -> tuple[list[str], Mapping[str, object], tuple[Point3D, ...]]:
    """检查端点、节点/边碰撞、NaN 和转角，并返回重采样路径。"""
    issues: list[str] = []
    node_collision_count = 0
    edge_collision_count = 0
    nan_hit_count = 0
    turn_violation_count = 0
    endpoint_mismatches: list[str] = []
    resampled: tuple[Point3D, ...] = ()

    if not path:
        return issues, {
            "checked": False,
            "path_points": 0,
            "resampled_points": 0,
            "node_collision_count": 0,
            "edge_collision_count": 0,
            "nan_hit_count": 0,
            "turn_violation_count": 0,
            "endpoint_mismatches": [],
            "issues": [],
        }, resampled

    if any(len(point) != 3 for point in path):
        issues.append("malformed_waypoint")
    elif any(not all(math.isfinite(float(value)) for value in point) for point in path):
        issues.append("non_finite_waypoint")
    else:
        try:
            expected_start = index_to_world(world_to_index(request.start, scene.config), scene.config)
            expected_goal = index_to_world(world_to_index(request.goal, scene.config), scene.config)
            if math.dist(path[0], expected_start) > 1e-9:
                endpoint_mismatches.append("start")
            if math.dist(path[-1], expected_goal) > 1e-9:
                endpoint_mismatches.append("goal")
            if endpoint_mismatches:
                issues.append("endpoint_mismatch:" + ",".join(endpoint_mismatches))
        except ValueError as error:
            endpoint_mismatches.append(f"endpoint_invalid:{error}")
            issues.append("endpoint_invalid")

        node_collision_count = sum(
            int(node_in_collision(scene.building_mask, point, scene.config))
            for point in path
        )
        if node_collision_count:
            issues.append("node_collision")

        edge_collision_count = sum(
            int(edge_in_collision(scene.building_mask, start, end, scene.config))
            for start, end in zip(path, path[1:])
        )
        if edge_collision_count:
            issues.append("edge_collision")

        turn_violation_count = sum(
            int(not turn_is_allowed(path[index - 1], path[index], path[index + 1], scene.config))
            for index in range(1, len(path) - 1)
        )
        if turn_violation_count:
            issues.append("turn_limit_exceeded")

        try:
            resampled = resample_path_1m(path, scene.config, spacing_m)
        except ValueError as error:
            issues.append(f"resampling_failed:{error}")

        if resampled:
            for point in resampled:
                if node_in_collision(scene.building_mask, point, scene.config):
                    node_collision_count += 1
                try:
                    risk_value = sample_risk(scene.R, point, scene.config)
                except ValueError:
                    risk_value = None
                    issues.append("risk_query_invalid")
                if risk_value is None:
                    nan_hit_count += 1
            if node_collision_count and "node_collision" not in issues:
                issues.append("resampled_node_collision")
            if nan_hit_count:
                issues.append("nan_risk_hit")

    validation: Mapping[str, object] = {
        "checked": True,
        "path_points": len(path),
        "resampled_points": len(resampled),
        "node_collision_count": node_collision_count,
        "edge_collision_count": edge_collision_count,
        "nan_hit_count": nan_hit_count,
        "turn_violation_count": turn_violation_count,
        "endpoint_mismatches": endpoint_mismatches,
        "issues": issues,
    }
    return issues, validation, resampled


def assess_path_result(
    scene: SceneData,
    request: PlanRequest,
    result: PathResult,
    spacing_m: float,
) -> PathAssessment:
    """重查规划器路径并按公共 metrics 得到最终状态和指标。"""
    path = result.waypoints
    issues: list[str] = []
    validation: Mapping[str, object] = {
        "checked": False,
        "path_points": len(path),
        "resampled_points": 0,
        "node_collision_count": 0,
        "edge_collision_count": 0,
        "nan_hit_count": 0,
        "turn_violation_count": 0,
        "endpoint_mismatches": [],
        "issues": [],
    }
    resampled: tuple[Point3D, ...] = ()
    if path:
        issues, validation, resampled = _inspect_path(scene, request, path, spacing_m)

    if result.status == "invalid":
        return PathAssessment("invalid", result.failure_reason or "planner_invalid", None, validation, len(resampled))
    if result.status == "no_path":
        if path:
            issues.append("no_path_contains_waypoints")
        if issues:
            return PathAssessment("invalid", "path_validation_failed:" + ";".join(issues), None, validation, len(resampled))
        if result.failure_reason == "iteration_budget_exhausted":
            return PathAssessment("timeout_no_solution", result.failure_reason, None, validation, 0)
        return PathAssessment("no_path", result.failure_reason or "no_path", None, validation, 0)
    if result.status == "timeout" and not path:
        return PathAssessment("timeout_no_solution", result.failure_reason or "timeout", None, validation, 0)
    if result.status not in {"success", "timeout"}:
        return PathAssessment("invalid", f"unknown_planner_status:{result.status}", None, validation, len(resampled))
    if not path:
        return PathAssessment("invalid", "path_validation_failed:empty_solution_path", None, validation, 0)
    if issues:
        return PathAssessment("invalid", "path_validation_failed:" + ";".join(issues), None, validation, len(resampled))

    try:
        metrics = evaluate_path(
            resampled,
            scene.R,
            scene.config,
            r_norm=scene.r_norm,
        )
    except ValueError as error:
        return PathAssessment(
            "invalid",
            f"path_metrics_failed:{error}",
            None,
            validation,
            len(resampled),
        )
    final_status = "success" if result.status == "success" else "timeout_with_solution"
    return PathAssessment(final_status, result.failure_reason, metrics, validation, len(resampled))


def _result_metadata(result: PathResult) -> Mapping[str, object]:
    """读取有明确 metadata 契约的采样/RiskA*结果扩展字段。"""
    if isinstance(result, (RRTStarResult, RiskPathResult)):
        return result.metadata
    return {}


def _path_digest(path: Sequence[Sequence[float]]) -> str:
    """为原始路径生成稳定 SHA-256，并用字符串标记非法非有限坐标。"""
    canonical_path: list[list[float | str]] = []
    for point in path:
        try:
            values = list(point)
        except TypeError:
            canonical_path.append([f"<invalid-point:{point!r}>"])
            continue
        canonical_point: list[float | str] = []
        for value in values:
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                canonical_point.append(f"<invalid-value:{value!r}>")
                continue
            if math.isnan(numeric_value):
                canonical_point.append("NaN")
            elif math.isinf(numeric_value):
                canonical_point.append("Infinity" if numeric_value > 0 else "-Infinity")
            else:
                canonical_point.append(numeric_value)
        canonical_path.append(canonical_point)
    payload = json.dumps(
        canonical_path,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return sha256(payload).hexdigest()


def run_one(
    scene: SceneData,
    mission: str,
    algorithm: str,
    seed: int,
    time_budget_s: float | None,
    iteration_budget: int | None,
    spacing_m: float,
    experiment_config_hash: str,
    run_kind: str,
) -> dict[str, object]:
    """执行一个规划条件，校验路径并返回可直接写入 JSONL 的记录。"""
    if algorithm not in PLANNERS:
        raise KeyError(f"PLANNERS 中没有算法：{algorithm}")
    if mission not in scene.missions:
        raise KeyError(f"场景 {scene.scene_name} 没有任务 {mission}")
    start, goal = scene.missions[mission]
    request = PlanRequest(
        scene_data=scene,
        mission=mission,
        start=start,
        goal=goal,
        seed=seed,
        time_budget_s=time_budget_s,
        iteration_budget=iteration_budget,
    )
    planner_type: type[PlannerBase] = PLANNERS[algorithm]
    planner = planner_type()
    started_at = perf_counter()
    try:
        result = planner.plan(request)
    except Exception as error:
        runtime_s = perf_counter() - started_at
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "scene": scene.scene_name,
            "mission": mission,
            "algorithm": algorithm,
            "seed": seed,
            "status": "invalid",
            "planner_status": "exception",
            "length_m": None,
            "risk_expected": None,
            "composite_cost": None,
            "runtime_s": runtime_s,
            "tree_nodes": None,
            "iterations_or_expansions": None,
            "samples": None,
            "rewires": None,
            "first_feasible_time_s": None,
            "failure_reason": f"planner_exception:{type(error).__name__}:{error}",
            "config_hash": scene.config_hash,
            "experiment_config_hash": experiment_config_hash,
            "budget": {
                "time_budget_s": time_budget_s,
                "iteration_budget": iteration_budget,
                "run_kind": run_kind,
            },
            "path_points": 0,
            "path_sha256": _path_digest(()),
            "validation": {"checked": False, "issues": ["planner_exception"]},
        }

    assessment = assess_path_result(scene, request, result, spacing_m)
    metadata = _result_metadata(result)
    metrics = assessment.metrics
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scene": scene.scene_name,
        "mission": mission,
        "algorithm": algorithm,
        "seed": seed,
        "status": assessment.status,
        "planner_status": result.status,
        "length_m": None if metrics is None else metrics["length_m"],
        "risk_expected": None if metrics is None else metrics["risk_expected"],
        "composite_cost": None if metrics is None else metrics["composite_cost"],
        "runtime_s": result.runtime_s,
        "tree_nodes": metadata.get("tree_nodes"),
        "iterations_or_expansions": result.iterations_or_expansions,
        "samples": result.samples,
        "rewires": metadata.get("rewires"),
        "first_feasible_time_s": metadata.get("first_feasible_time_s"),
        "failure_reason": assessment.failure_reason,
        "config_hash": scene.config_hash,
        "experiment_config_hash": experiment_config_hash,
        "budget": {
            "time_budget_s": time_budget_s,
            "iteration_budget": iteration_budget,
            "run_kind": run_kind,
        },
        "path_points": len(result.waypoints),
        "resampled_points": assessment.resampled_points,
        "path_sha256": _path_digest(result.waypoints),
        "validation": assessment.validation,
    }


def raw_record_path(
    raw_root: Path,
    template: str,
    scene: str,
    mission: str,
    algorithm: str,
    seed: int,
) -> Path:
    """按配置模板解析一项运行对应的 JSONL 文件。"""
    relative = template.format(
        scene=scene,
        mission=mission,
        algorithm=algorithm,
        seed=seed,
    )
    path = (raw_root / relative).resolve()
    if not path.is_relative_to(raw_root.resolve()):
        raise ValueError(f"raw 输出路径越出 raw 根目录：{path}")
    return path


def append_jsonl(path: Path, record: Mapping[str, object]) -> None:
    """向 JSONL 追加一条真实运行记录，不覆盖既有失败运行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as output_file:
        output_file.write(encoded + "\n")


def _validate_config(config: Mapping[str, Any]) -> None:
    """检查矩阵、算法注册和预算类别是否互相一致。"""
    required = ("scene_config", "scenes", "missions", "algorithms", "algorithm_groups", "seeds", "budgets", "smoke", "validation", "output")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"实验配置缺少字段：{missing}")
    algorithms = set(config["algorithms"])
    groups = set(config["algorithm_groups"]["deterministic"]) | set(config["algorithm_groups"]["sampling"])
    if algorithms != groups:
        raise ValueError("algorithms 必须与 deterministic/sampling 分组完全一致。")
    unknown = algorithms.difference(PLANNERS)
    if unknown:
        raise ValueError(f"配置算法未注册：{sorted(unknown)}")
    expected_registry = DETERMINISTIC_CLASSES + SAMPLING_CLASSES
    for planner_class in expected_registry:
        if PLANNERS.get(planner_class.name) is not planner_class:
            raise ValueError(f"规划器注册不一致：{planner_class.name}")


def execute_matrix(
    config: Mapping[str, Any],
    experiment_config_hash: str,
    smoke: bool = False,
    config_bytes: bytes | None = None,
) -> int:
    """执行 smoke 子集或配置指定的完整矩阵，逐项追加 JSONL。"""
    _validate_config(config)
    scene_config_path = _resolve_project_path(str(config["scene_config"]), "scene_config")
    output_settings = config["output"]
    raw_root = _resolve_project_path(str(output_settings["raw_root"]), "raw_root")
    snapshot_dir = _resolve_project_path(str(output_settings["snapshot_dir"]), "snapshot_dir")
    snapshot_bytes = (
        config_bytes
        if config_bytes is not None
        else json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    snapshot_digest = sha256(snapshot_bytes).hexdigest()
    if config_bytes is None:
        # 兼容直接调用旧接口的测试/脚本：没有原始字节时，使用当前规范化内容的哈希。
        experiment_config_hash = snapshot_digest
    elif snapshot_digest != experiment_config_hash:
        raise ValueError("实验配置哈希与要保存的配置快照内容不一致。")
    snapshot_path = save_config_snapshot(snapshot_dir, snapshot_bytes, experiment_config_hash)
    template = str(output_settings["per_run_template"])
    spacing_m = float(config["validation"]["path_resample_spacing_m"])

    if smoke:
        smoke_settings = config["smoke"]
        scenes = [str(smoke_settings["scene"])]
        missions = [str(smoke_settings["mission"])]
        algorithms = list(config["algorithms"])
        seed_by_algorithm = {algorithm: int(smoke_settings["seed"]) for algorithm in algorithms}
    else:
        scenes = [str(scene_name) for scene_name in config["scenes"]]
        missions = [str(mission) for mission in config["missions"]]
        algorithms = [str(algorithm) for algorithm in config["algorithms"]]
        deterministic = set(config["algorithm_groups"]["deterministic"])
        seeds_by_group = config["seeds"]
        seed_by_algorithm = {}
        for algorithm in algorithms:
            group = "deterministic" if algorithm in deterministic else "sampling"
            for seed in seeds_by_group[group]:
                seed_by_algorithm.setdefault(algorithm, []).append(int(seed))

    completed = 0
    for scene_name in scenes:
        scene = load_scene(scene_name, scene_config_path)
        for mission in missions:
            for algorithm in algorithms:
                seeds = (
                    [seed_by_algorithm[algorithm]]
                    if smoke
                    else seed_by_algorithm[algorithm]
                )
                for seed in seeds:
                    if smoke:
                        time_budget_s = float(config["smoke"]["time_budget_s"])
                        iteration_budget = (
                            int(config["smoke"]["max_iterations"])
                            if algorithm in config["algorithm_groups"]["sampling"]
                            else None
                        )
                        run_kind = "smoke"
                    elif algorithm in config["algorithm_groups"]["deterministic"]:
                        time_budget_s = float(config["budgets"]["deterministic"]["timeout_s"])
                        iteration_budget = None
                        run_kind = "matrix"
                    else:
                        time_budget_s = float(config["budgets"]["sampling"]["time_budget_s"])
                        iteration_budget = int(config["budgets"]["sampling"]["max_iterations"])
                        run_kind = "matrix"
                    record = run_one(
                        scene,
                        mission,
                        algorithm,
                        seed,
                        time_budget_s,
                        iteration_budget,
                        spacing_m,
                        experiment_config_hash,
                        run_kind,
                    )
                    record_path = raw_record_path(
                        raw_root,
                        template,
                        scene_name,
                        mission,
                        algorithm,
                        seed,
                    )
                    append_jsonl(record_path, record)
                    completed += 1
                    print(
                        json.dumps(
                            {
                                "scene": scene_name,
                                "mission": mission,
                                "algorithm": algorithm,
                                "seed": seed,
                                "status": record["status"],
                                "runtime_s": record["runtime_s"],
                                "failure_reason": record["failure_reason"],
                                "raw": str(record_path.relative_to(PROJECT_ROOT)),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
        del scene
        gc.collect()
    print(f"实验配置快照：{snapshot_path}")
    print(f"本次写入运行记录数：{completed}")
    return completed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析配置路径和快速 smoke 开关。"""
    parser = argparse.ArgumentParser(description="按正式矩阵运行规划器并统一复核路径")
    parser.add_argument("--config", type=Path, default=Path("experiments/configs/base.json"))
    parser.add_argument("--smoke", action="store_true", help="只运行 A 场景任务 1、五算法、seed 0")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """执行所选实验矩阵。"""
    args = _parse_args(argv)
    config, config_bytes, digest = load_experiment_config(args.config)
    execute_matrix(config, digest, smoke=args.smoke, config_bytes=config_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
