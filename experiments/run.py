"""冻结路线驱动的正式实验运行器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
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
import os
import tempfile

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
from src.experiments.config import (
    FormalConfig,
    LoadedConfig,
    RunOutputConfig,
    SmokeConfig,
    load_config,
)
from src.experiments.route_generator import RouteSpec, load_route_manifest
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


@dataclass(frozen=True, slots=True)
class MatrixTask:
    """一条路线与一个算法 seed 的独立运行条件。"""

    route: RouteSpec
    algorithm: str
    seed: int
    seed_kind: str
    time_budget_s: float
    iteration_budget: int | None
    spacing_m: float
    experiment_config_hash: str
    scene_config_hash: str
    run_kind: str
    run_id: str
    record_path: Path
    workers: int
    executor_kind: str


_PROCESS_SCENE: SceneData | None = None


def _resolve_project_path(path_value: str, label: str) -> Path:
    """把配置中的项目相对路径解析为绝对路径。"""
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    if not resolved.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError(f"{label} 必须位于项目目录内：{resolved}")
    return resolved


def save_config_snapshot(
    snapshot_dir: Path,
    config_bytes: bytes,
    digest: str,
    *,
    source_suffix: str = ".json",
) -> Path:
    """按内容哈希保存原始配置快照，不覆盖已有快照。"""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_suffix.lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    snapshot_path = snapshot_dir / f"config-{digest}{suffix}"
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
    """检查端点、节点/边碰撞、NaN 风险和转角。"""
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
        return PathAssessment(
            "invalid",
            result.failure_reason or "planner_invalid",
            None,
            validation,
            len(resampled),
        )
    if result.status == "no_path":
        if path:
            issues.append("no_path_contains_waypoints")
        if issues:
            return PathAssessment(
                "invalid",
                "path_validation_failed:" + ";".join(issues),
                None,
                validation,
                len(resampled),
            )
        if result.failure_reason == "iteration_budget_exhausted":
            return PathAssessment(
                "timeout_no_solution",
                result.failure_reason,
                None,
                validation,
                0,
            )
        return PathAssessment(
            "no_path",
            result.failure_reason or "no_path",
            None,
            validation,
            0,
        )
    if result.status == "timeout" and not path:
        return PathAssessment(
            "timeout_no_solution",
            result.failure_reason or "timeout",
            None,
            validation,
            0,
        )
    if result.status not in {"success", "timeout"}:
        return PathAssessment(
            "invalid",
            f"unknown_planner_status:{result.status}",
            None,
            validation,
            len(resampled),
        )
    if not path:
        return PathAssessment(
            "invalid",
            "path_validation_failed:empty_solution_path",
            None,
            validation,
            0,
        )
    if issues:
        return PathAssessment(
            "invalid",
            "path_validation_failed:" + ";".join(issues),
            None,
            validation,
            len(resampled),
        )

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
    return PathAssessment(
        final_status,
        result.failure_reason,
        metrics,
        validation,
        len(resampled),
    )


def _result_metadata(result: PathResult) -> Mapping[str, object]:
    """读取有明确 metadata 契约的采样或 RiskA* 扩展字段。"""
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


def _route_record_fields(route: RouteSpec) -> dict[str, object]:
    """返回每条原始记录都必须携带的路线身份和诊断字段。"""
    return {
        "scene": route.scene,
        "group": route.route_group,
        "route_id": route.route_id,
        "route_seed": route.route_seed,
        "start": list(route.start),
        "goal": list(route.goal),
        "distance_m": route.distance_m,
        "height_delta_m": route.height_delta_m,
        "complexity_score": route.complexity_score,
        "complexity_band": route.complexity_band,
        "complexity_diagnostics": dict(route.diagnostics),
    }


def run_one(
    scene: SceneData,
    route: RouteSpec,
    algorithm: str,
    seed: int,
    time_budget_s: float | None,
    iteration_budget: int | None,
    spacing_m: float,
    experiment_config_hash: str,
    run_kind: str,
    execution_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """执行一个路线-算法-seed 条件并返回可写入 JSONL 的记录。"""
    if algorithm not in PLANNERS:
        raise KeyError(f"PLANNERS 中没有算法：{algorithm}")
    request = PlanRequest(
        scene_data=scene,
        mission=route.route_id,
        start=route.start,
        goal=route.goal,
        seed=seed,
        time_budget_s=time_budget_s,
        iteration_budget=iteration_budget,
    )
    planner_type: type[PlannerBase] = PLANNERS[algorithm]
    planner = planner_type()
    started_at = perf_counter()
    common = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **_route_record_fields(route),
        "algorithm": algorithm,
        "seed": seed,
        "config_hash": scene.config_hash,
        "experiment_config_hash": experiment_config_hash,
        "execution": {} if execution_metadata is None else dict(execution_metadata),
        "budget": {
            "time_budget_s": time_budget_s,
            "iteration_budget": iteration_budget,
            "run_kind": run_kind,
        },
    }
    try:
        result = planner.plan(request)
    except Exception as error:
        wall_runtime_s = perf_counter() - started_at
        return {
            **common,
            "status": "invalid",
            "planner_status": "exception",
            "length_m": None,
            "risk_expected": None,
            "composite_cost": None,
            "runtime_s": wall_runtime_s,
            "wall_runtime_s": wall_runtime_s,
            "tree_nodes": None,
            "iterations_or_expansions": None,
            "samples": None,
            "rewires": None,
            "first_feasible_time_s": None,
            "failure_reason": f"planner_exception:{type(error).__name__}:{error}",
            "path_points": 0,
            "resampled_points": 0,
            "path_sha256": _path_digest(()),
            "validation": {"checked": False, "issues": ["planner_exception"]},
        }

    wall_runtime_s = perf_counter() - started_at
    assessment = assess_path_result(scene, request, result, spacing_m)
    metadata = _result_metadata(result)
    metrics = assessment.metrics
    return {
        **common,
        "status": assessment.status,
        "planner_status": result.status,
        "length_m": None if metrics is None else metrics["length_m"],
        "risk_expected": None if metrics is None else metrics["risk_expected"],
        "composite_cost": None if metrics is None else metrics["composite_cost"],
        "runtime_s": result.runtime_s,
        "wall_runtime_s": wall_runtime_s,
        "tree_nodes": metadata.get("tree_nodes"),
        "iterations_or_expansions": result.iterations_or_expansions,
        "samples": result.samples,
        "rewires": metadata.get("rewires"),
        "first_feasible_time_s": metadata.get("first_feasible_time_s"),
        "failure_reason": assessment.failure_reason,
        "path_points": len(result.waypoints),
        "resampled_points": assessment.resampled_points,
        "path_sha256": _path_digest(result.waypoints),
        "validation": assessment.validation,
    }


def raw_record_path(
    raw_root: Path,
    template: str,
    route: RouteSpec,
    algorithm: str,
    seed: int,
) -> Path:
    """按配置模板解析一项运行对应的 JSONL 文件。"""
    relative = template.format(
        scene=route.scene,
        group=route.route_group,
        route_id=route.route_id,
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
    encoded = json.dumps(
        record,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    with path.open("a", encoding="utf-8", newline="\n") as output_file:
        output_file.write(encoded + "\n")


def _validate_registry(config: FormalConfig | SmokeConfig) -> None:
    """检查配置算法与公共注册表完全一致。"""
    algorithms = set(config.algorithms.all_algorithms)
    unknown = algorithms.difference(PLANNERS)
    if unknown:
        raise ValueError(f"配置算法未注册：{sorted(unknown)}")
    expected_registry = DETERMINISTIC_CLASSES + SAMPLING_CLASSES
    for planner_class in expected_registry:
        if PLANNERS.get(planner_class.name) is not planner_class:
            raise ValueError(f"规划器注册不一致：{planner_class.name}")
    if set(config.algorithms.deterministic) != {planner.name for planner in DETERMINISTIC_CLASSES}:
        raise ValueError("确定性算法名单与注册表不一致。")
    if set(config.algorithms.sampling) != {planner.name for planner in SAMPLING_CLASSES}:
        raise ValueError("采样算法名单与注册表不一致。")


def _scene_names_from_config(path: Path) -> tuple[str, ...]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    scenes = payload.get("scenes")
    if not isinstance(scenes, Mapping) or not scenes:
        raise ValueError(f"场景配置缺少非空 scenes：{path}")
    return tuple(sorted(str(name) for name in scenes))


def _validate_route_manifest(
    config: FormalConfig | SmokeConfig,
    routes: Sequence[RouteSpec],
    scene_config_path: Path,
) -> None:
    """核对冻结路线覆盖、组配额和 route_seed。"""
    if isinstance(config, SmokeConfig):
        if len(routes) != 1:
            raise ValueError(f"smoke 路线清单必须恰好包含 1 条路线，实际 {len(routes)} 条。")
        return

    expected_scenes = _scene_names_from_config(scene_config_path)
    actual_scenes = sorted({route.scene for route in routes})
    if tuple(actual_scenes) != expected_scenes:
        raise ValueError(
            f"路线清单场景覆盖不一致：manifest={actual_scenes}，"
            f"scene_config={list(expected_scenes)}"
        )
    for scene in expected_scenes:
        for group_name, group in config.route_groups.items():
            count = sum(
                route.scene == scene and route.route_group == group_name
                for route in routes
            )
            if count != group.routes_per_scene:
                raise ValueError(
                    f"{scene}/{group_name} 路线数应为 {group.routes_per_scene}，实际 {count}。"
                )
    wrong_seeds = sorted(
        route.route_id
        for route in routes
        if route.route_seed != config.route_pool.route_seed
    )
    if wrong_seeds:
        raise ValueError(f"路线 route_seed 与正式配置不一致：{wrong_seeds[:10]}")


def _filter_routes(
    routes: Sequence[RouteSpec],
    *,
    scene_names: Sequence[str] | None,
    group_names: Sequence[str] | None,
    route_ids: Sequence[str] | None,
    scope: str,
) -> tuple[RouteSpec, ...]:
    selected = list(routes)
    requested_scenes = set(scene_names or ())
    requested_groups = set(group_names or ())
    requested_routes = set(route_ids or ())
    unknown_scenes = requested_scenes.difference({route.scene for route in routes})
    unknown_groups = requested_groups.difference({route.route_group for route in routes})
    unknown_routes = requested_routes.difference({route.route_id for route in routes})
    if unknown_scenes:
        raise ValueError(f"路线清单中没有所选场景：{sorted(unknown_scenes)}")
    if unknown_groups:
        raise ValueError(f"路线清单中没有所选距离组：{sorted(unknown_groups)}")
    if unknown_routes:
        raise ValueError(f"路线清单中没有所选路线：{sorted(unknown_routes)}")
    if requested_scenes:
        selected = [route for route in selected if route.scene in requested_scenes]
    if requested_groups:
        selected = [route for route in selected if route.route_group in requested_groups]
    if requested_routes:
        selected = [route for route in selected if route.route_id in requested_routes]
    if scope == "sample":
        first_by_condition: dict[tuple[str, str], RouteSpec] = {}
        for route in sorted(selected, key=lambda item: (item.scene, item.route_group, item.route_id)):
            first_by_condition.setdefault((route.scene, route.route_group), route)
        selected = list(first_by_condition.values())
    elif scope != "full":
        raise ValueError("scope 只能是 `sample` 或 `full`。")
    if not selected:
        raise ValueError("当前筛选条件没有可运行路线。")
    return tuple(selected)


def _route_budget(
    config: FormalConfig | SmokeConfig,
    route: RouteSpec,
) -> tuple[float, int | None]:
    if isinstance(config, SmokeConfig):
        return config.time_budget_s, config.max_iterations
    group = config.route_groups.get(route.route_group)
    if group is None:
        raise ValueError(f"路线 {route.route_id} 的组 {route.route_group} 没有预算配置。")
    return group.time_budget_s, group.max_iterations


def build_run_tasks(
    config: FormalConfig | SmokeConfig,
    routes: Sequence[RouteSpec],
    *,
    scene_config_hashes: Mapping[str, str],
    experiment_config_hash: str,
    output: RunOutputConfig,
    workers: int,
    executor_kind: str,
    run_id: str,
    run_kind: str,
    spacing_m: float,
) -> list[MatrixTask]:
    """把冻结路线展开为完整运行矩阵。"""
    tasks: list[MatrixTask] = []
    deterministic = set(config.algorithms.deterministic)
    for route in routes:
        time_budget_s, max_iterations = _route_budget(config, route)
        for algorithm in config.algorithms.all_algorithms:
            if algorithm in deterministic:
                seeds = ((config.seeds.deterministic, "deterministic"),)
            else:
                seeds = tuple(
                    (seed, "sampling")
                    for seed in config.seeds.sampling
                )
            for seed, seed_kind in seeds:
                iteration_budget = max_iterations if seed_kind == "sampling" else None
                tasks.append(
                    MatrixTask(
                        route=route,
                        algorithm=algorithm,
                        seed=seed,
                        seed_kind=seed_kind,
                        time_budget_s=time_budget_s,
                        iteration_budget=iteration_budget,
                        spacing_m=spacing_m,
                        experiment_config_hash=experiment_config_hash,
                        scene_config_hash=scene_config_hashes[route.scene],
                        run_kind=run_kind,
                        run_id=run_id,
                        record_path=raw_record_path(
                            _resolve_project_path(output.raw_root, "raw_root"),
                            output.per_run_template,
                            route,
                            algorithm,
                            seed,
                        ),
                        workers=workers,
                        executor_kind=executor_kind,
                    )
                )
    return tasks


def _execution_metadata(task: MatrixTask) -> Mapping[str, object]:
    """返回原始记录中的运行批次和并发参数。"""
    return {
        "run_id": task.run_id,
        "workers": task.workers,
        "executor": task.executor_kind,
        "seed_kind": task.seed_kind,
    }


def _execute_task(task: MatrixTask, scene: SceneData) -> dict[str, object]:
    """在当前进程或线程里执行一个任务，不负责调度和写盘。"""
    return run_one(
        scene,
        task.route,
        task.algorithm,
        task.seed,
        task.time_budget_s,
        task.iteration_budget,
        task.spacing_m,
        task.experiment_config_hash,
        task.run_kind,
        _execution_metadata(task),
    )


def _write_risk_cache(scene: SceneData, cache_path: Path) -> None:
    """将父进程已校验的 R 写为只读进程共享缓存。"""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_name(cache_path.name + ".tmp")
    with temporary_path.open("wb") as cache_file:
        np.save(cache_file, scene.R, allow_pickle=False)
        cache_file.flush()
        os.fsync(cache_file.fileno())
    os.replace(temporary_path, cache_path)


def _initialize_process_scene(
    scene_name: str,
    scene_dir: Path,
    city_path: Path,
    risk_cache_path: Path,
    h_low: float,
    h_high: float,
    step: float,
    config: Mapping[str, Any],
    config_hash: str,
    r_norm: float,
) -> None:
    """每个进程只读映射同一 R，并独立载入较小场景数组。"""
    global _PROCESS_SCENE
    with np.load(city_path, allow_pickle=False) as archive:
        building_mask = np.array(archive["building_mask"], copy=True)
        pop_density = np.array(archive["pop_density"], copy=True)
    risk_field = np.load(risk_cache_path, mmap_mode="r", allow_pickle=False)
    if risk_field.shape != building_mask.shape or risk_field.ndim != 3:
        raise ValueError("进程 worker 的 R 缓存与建筑掩码形状不一致。")
    for array in (risk_field, building_mask, pop_density):
        array.setflags(write=False)
    _PROCESS_SCENE = SceneData(
        scene_name=scene_name,
        scene_dir=scene_dir,
        R=risk_field,
        building_mask=building_mask,
        pop_density=pop_density,
        h_low=h_low,
        h_high=h_high,
        step=step,
        missions={},
        config=config,
        config_hash=config_hash,
        r_norm=r_norm,
    )


def _execute_process_task(task: MatrixTask) -> dict[str, object]:
    """进程池入口；SceneData 由 initializer 加载，避免序列化大矩阵。"""
    if _PROCESS_SCENE is None:
        raise RuntimeError("实验 worker 未加载场景。")
    return _execute_task(task, _PROCESS_SCENE)


def _worker_failure_record(task: MatrixTask, error: BaseException) -> dict[str, object]:
    """把 worker 级异常也保存为 invalid 原始记录。"""
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **_route_record_fields(task.route),
        "algorithm": task.algorithm,
        "seed": task.seed,
        "status": "invalid",
        "planner_status": "worker_exception",
        "length_m": None,
        "risk_expected": None,
        "composite_cost": None,
        "runtime_s": None,
        "wall_runtime_s": None,
        "tree_nodes": None,
        "iterations_or_expansions": None,
        "samples": None,
        "rewires": None,
        "first_feasible_time_s": None,
        "failure_reason": f"worker_exception:{type(error).__name__}:{error}",
        "config_hash": task.scene_config_hash,
        "experiment_config_hash": task.experiment_config_hash,
        "execution": _execution_metadata(task),
        "budget": {
            "time_budget_s": task.time_budget_s,
            "iteration_budget": task.iteration_budget,
            "run_kind": task.run_kind,
        },
        "path_points": 0,
        "resampled_points": 0,
        "path_sha256": _path_digest(()),
        "validation": {"checked": False, "issues": ["worker_exception"]},
    }


def _task_already_complete(task: MatrixTask) -> bool:
    """识别完全相同的已完成记录；损坏或身份冲突时立即报错。"""
    if not task.record_path.exists():
        return False
    lines = task.record_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"已有原始记录为空文件：{task.record_path}")
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"已有原始记录含损坏 JSON：{task.record_path}") from error
        identity = (
            record.get("scene"),
            record.get("group"),
            record.get("route_id"),
            record.get("algorithm"),
            record.get("seed"),
            record.get("experiment_config_hash"),
        )
        expected = (
            task.route.scene,
            task.route.route_group,
            task.route.route_id,
            task.algorithm,
            task.seed,
            task.experiment_config_hash,
        )
        if identity == expected:
            return True
    raise ValueError(
        f"已有原始记录但身份或配置哈希不匹配：{task.record_path}"
    )


def _store_task_result(task: MatrixTask, record: Mapping[str, object]) -> None:
    """由父进程独占写入该任务记录，并输出实时进度 JSON。"""
    append_jsonl(task.record_path, record)
    print(
        json.dumps(
            {
                "scene": task.route.scene,
                "group": task.route.route_group,
                "route_id": task.route.route_id,
                "algorithm": task.algorithm,
                "seed": task.seed,
                "status": record["status"],
                "runtime_s": record["runtime_s"],
                "failure_reason": record["failure_reason"],
                "raw": str(task.record_path.relative_to(PROJECT_ROOT)),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _execute_scene_tasks(
    scene: SceneData,
    tasks: Sequence[MatrixTask],
    scene_config_path: Path,
) -> tuple[int, int]:
    """执行一个场景的待运行任务，并返回已运行和续跑跳过数量。"""
    if not tasks:
        return 0, 0
    pending = [task for task in tasks if not _task_already_complete(task)]
    skipped = len(tasks) - len(pending)
    if not pending:
        return 0, skipped

    if pending[0].workers == 1:
        for task in pending:
            _store_task_result(task, _execute_task(task, scene))
        return len(pending), skipped

    worker_count = min(pending[0].workers, len(pending))
    if pending[0].executor_kind == "thread":
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="formal-run",
        ) as executor:
            futures = {executor.submit(_execute_task, task, scene): task for task in pending}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    record = future.result()
                except Exception as error:
                    record = _worker_failure_record(task, error)
                _store_task_result(task, record)
        return len(pending), skipped

    paths = scene.config["paths"]
    scene_key = "scene_A" if scene.scene_name == "A" else "scene_B"
    scene_dir_name = str(paths[scene_key])
    city_relative_path = str(paths["city_npz"]).replace("<scene>", scene_dir_name)
    city_path = _resolve_project_path(
        str((scene_config_path.parent / city_relative_path).resolve()),
        "city_npz",
    )
    with tempfile.TemporaryDirectory(prefix=f"ffjj-{scene.scene_name}-") as cache_dir:
        risk_cache_path = Path(cache_dir) / "R.npy"
        _write_risk_cache(scene, risk_cache_path)
        with ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_initialize_process_scene,
            initargs=(
                scene.scene_name,
                scene.scene_dir,
                city_path,
                risk_cache_path,
                scene.h_low,
                scene.h_high,
                scene.step,
                dict(scene.config),
                scene.config_hash,
                scene.r_norm,
            ),
        ) as executor:
            futures = {executor.submit(_execute_process_task, task): task for task in pending}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    record = future.result()
                except Exception as error:
                    record = _worker_failure_record(task, error)
                _store_task_result(task, record)
    return len(pending), skipped


def execute_runs(
    loaded: LoadedConfig,
    *,
    workers: int,
    executor_kind: str,
    scope: str,
    run_id: str | None,
    scene_names: Sequence[str] | None,
    group_names: Sequence[str] | None,
    route_ids: Sequence[str] | None,
) -> int:
    """加载冻结路线并按场景执行实验矩阵。"""
    config = loaded.config
    if not isinstance(config, (FormalConfig, SmokeConfig)):
        raise TypeError("experiments.run 只接受 formal 或 smoke 配置。")
    _validate_registry(config)
    if workers < 1:
        raise ValueError("并行 worker 数必须是正整数。")
    if executor_kind not in {"process", "thread"}:
        raise ValueError("并行方式只能是 `process` 或 `thread`。")

    scene_config_path = _resolve_project_path(config.scene_config, "scene_config")
    route_manifest_path = _resolve_project_path(config.route_manifest, "route_manifest")
    routes = load_route_manifest(route_manifest_path)
    _validate_route_manifest(config, routes, scene_config_path)
    selected_routes = _filter_routes(
        routes,
        scene_names=scene_names,
        group_names=group_names,
        route_ids=route_ids,
        scope=scope,
    )

    snapshot_path = save_config_snapshot(
        _resolve_project_path(config.output.snapshot_dir, "snapshot_dir"),
        loaded.raw_bytes,
        loaded.sha256,
        source_suffix=loaded.source_path.suffix,
    )
    selected_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    if Path(selected_run_id).name != selected_run_id or selected_run_id in {".", ".."}:
        raise ValueError("run_id 只能是单段标识，不能包含路径。")

    scene_hashes: dict[str, str] = {}
    selected_scene_names = sorted({route.scene for route in selected_routes})
    for scene_name in selected_scene_names:
        scene = load_scene(scene_name, scene_config_path)
        scene_hashes[scene_name] = scene.config_hash
        del scene
        gc.collect()
    tasks = build_run_tasks(
        config,
        selected_routes,
        scene_config_hashes=scene_hashes,
        experiment_config_hash=loaded.sha256,
        output=config.output,
        workers=workers,
        executor_kind=executor_kind,
        run_id=selected_run_id,
        run_kind="smoke" if isinstance(config, SmokeConfig) else "matrix",
        spacing_m=config.validation.path_resample_spacing_m,
    )

    run_count = 0
    skipped_count = 0
    for scene_name in selected_scene_names:
        scene_tasks = [task for task in tasks if task.route.scene == scene_name]
        scene = load_scene(scene_name, scene_config_path)
        executed, skipped = _execute_scene_tasks(scene, scene_tasks, scene_config_path)
        run_count += executed
        skipped_count += skipped
        del scene
        gc.collect()

    print(f"实验：{config.experiment_name}")
    print(f"配置快照：{snapshot_path}")
    print(
        f"路线数：{len(selected_routes)}；算法数：{len(config.algorithms.all_algorithms)}；"
        f"任务数：{len(tasks)}"
    )
    print(f"并行方式：{executor_kind}；worker 数：{workers}")
    print(f"运行 ID：{selected_run_id}")
    print(f"本次运行：{run_count}；断点续跑跳过：{skipped_count}")
    return run_count


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析路线筛选、运行范围和并行参数。"""
    parser = argparse.ArgumentParser(description="运行冻结的 S/M/L 路线实验矩阵")
    parser.add_argument(
        "--config",
        type=Path,
        help="显式配置路径；默认根据 --smoke 选择 formal.toml 或 smoke.toml",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="读取 smoke.toml，运行一条冻结冒烟路线",
    )
    parser.add_argument(
        "--scope",
        choices=("sample", "full"),
        default="sample",
        help="sample 为每个场景/组取首条路线；full 遍历整个清单",
    )
    parser.add_argument("--scene", dest="scenes", nargs="+", help="只运行指定场景")
    parser.add_argument("--group", dest="groups", nargs="+", help="只运行指定距离组")
    parser.add_argument("--route-id", dest="route_ids", nargs="+", help="只运行指定路线 ID")
    parser.add_argument("--workers", type=int, help="并行 worker 数，默认读取配置")
    parser.add_argument(
        "--executor",
        choices=("process", "thread"),
        help="并行方式，默认读取配置",
    )
    parser.add_argument("--run-id", help="原始记录中的批次标识")
    args = parser.parse_args(argv)
    if args.config is None:
        args.config = Path(
            "experiments/configs/smoke.toml"
            if args.smoke
            else "experiments/configs/formal.toml"
        )
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """加载配置并执行所选路线矩阵。"""
    args = _parse_args(argv)
    loaded = load_config(args.config)
    config = loaded.config
    if not isinstance(config, (FormalConfig, SmokeConfig)):
        raise TypeError("experiments.run 只接受 formal 或 smoke 配置。")
    if args.smoke and not isinstance(config, SmokeConfig):
        raise TypeError("--smoke 必须配合 smoke 配置。")
    workers = config.execution.workers if args.workers is None else args.workers
    executor_kind = config.execution.executor if args.executor is None else args.executor
    execute_runs(
        loaded,
        workers=workers,
        executor_kind=executor_kind,
        scope=args.scope,
        run_id=args.run_id,
        scene_names=args.scenes,
        group_names=args.groups,
        route_ids=args.route_ids,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
