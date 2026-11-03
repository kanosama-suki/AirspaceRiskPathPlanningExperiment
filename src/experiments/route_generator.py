"""生成、分层抽样并冻结 A/B 场景的 S/M/L 随机起终点路线清单。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any
import argparse
import json
import math

import numpy as np

from src.core.collision import node_in_collision
from src.core.coords import index_to_world
from src.experiments.config import (
    FormalConfig,
    RouteGroupConfig,
    load_config,
)
from src.experiments.route_complexity import route_complexity
from src.io.scene import SceneData, load_scene


POINT = tuple[float, float, float]
COMPLEXITY_BANDS = ("low", "medium", "high")


@dataclass(frozen=True, slots=True)
class RouteSpec:
    """一条冻结路线及其复杂度诊断信息。"""

    scene: str
    route_group: str
    route_id: str
    route_seed: int
    start: POINT
    goal: POINT
    distance_m: float
    height_delta_m: float
    complexity_score: float
    complexity_band: str
    diagnostics: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _stable_scene_seed(route_seed: int, scene_name: str) -> int:
    """从公共 route_seed 和场景名派生独立且可复现的场景随机流。"""
    scene_digest = sha256(scene_name.encode("utf-8")).digest()
    scene_code = int.from_bytes(scene_digest[:8], "little")
    return int(np.random.SeedSequence([route_seed, scene_code]).generate_state(1)[0])


def _search_axis(length: int, step: int) -> np.ndarray:
    """生成算法层允许的离散索引轴，末端不会越过数组边界。"""
    return np.arange(0, length, step, dtype=np.int64)


def generate_candidate_routes(
    scene_data: SceneData,
    route_seed: int,
    count: int,
    config: Mapping[str, Any],
) -> list[dict[str, object]]:
    """生成合法候选路线，起终点均落在算法搜索节点上。"""
    if count <= 0:
        raise ValueError("候选路线数必须为正整数。")
    table = config["table2"]
    step = int(table["STEP"])
    x_indices = _search_axis(int(table["N_I"]), step)
    y_indices = _search_axis(int(table["N_J"]), step)
    h_indices = _search_axis(int(table["N_H"]), step)
    if min(len(x_indices), len(y_indices), len(h_indices)) == 0:
        raise ValueError("场景尺寸和搜索步长无法形成有效搜索节点。")

    rng = np.random.default_rng(_stable_scene_seed(route_seed, scene_data.scene_name))
    candidates: list[dict[str, object]] = []
    seen_endpoints: set[tuple[POINT, POINT]] = set()
    attempts = 0
    max_attempts = max(10_000, count * 100)
    while len(candidates) < count and attempts < max_attempts:
        attempts += 1
        start_index = (
            int(rng.choice(x_indices)),
            int(rng.choice(y_indices)),
            int(rng.choice(h_indices)),
        )
        goal_index = (
            int(rng.choice(x_indices)),
            int(rng.choice(y_indices)),
            int(rng.choice(h_indices)),
        )
        start = index_to_world(start_index, config)
        goal = index_to_world(goal_index, config)
        if start == goal:
            continue
        endpoint_pair = (start, goal)
        if endpoint_pair in seen_endpoints:
            continue
        if node_in_collision(scene_data.building_mask, start, config):
            continue
        if node_in_collision(scene_data.building_mask, goal, config):
            continue
        if not math.isfinite(float(scene_data.R[start_index])):
            continue
        if not math.isfinite(float(scene_data.R[goal_index])):
            continue

        distance = math.dist(start, goal)
        diagnostics = route_complexity(
            start,
            goal,
            scene_data.building_mask,
            scene_data.R,
            dict(config),
        )
        seen_endpoints.add(endpoint_pair)
        candidates.append(
            {
                "scene": scene_data.scene_name,
                "route_seed": route_seed,
                "candidate_index": len(candidates),
                "start": start,
                "goal": goal,
                "distance_m": distance,
                "height_delta_m": abs(start[2] - goal[2]),
                **diagnostics,
            }
        )
    if len(candidates) < count:
        raise RuntimeError(
            f"{scene_data.scene_name} 在 {attempts} 次尝试内只能生成 "
            f"{len(candidates)}/{count} 条合法候选路线。"
        )
    return candidates


def _distance_bands(
    distances: np.ndarray,
    groups: Mapping[str, RouteGroupConfig],
) -> tuple[dict[str, float], dict[str, tuple[float, float]]]:
    """计算目标分位和每个距离带的闭区间边界。"""
    percentiles = {
        name: float(np.percentile(distances, group.target_percentile))
        for name, group in groups.items()
    }
    bounds = {
        name: (
            float(np.percentile(distances, group.percentile_min)),
            float(np.percentile(distances, group.percentile_max)),
        )
        for name, group in groups.items()
    }
    return percentiles, bounds


def _complexity_allocation(target_count: int) -> dict[str, int]:
    """把组内路线尽量均匀分配到低、中、高复杂度层。"""
    base, remainder = divmod(target_count, len(COMPLEXITY_BANDS))
    allocation = {band: base for band in COMPLEXITY_BANDS}
    for band in COMPLEXITY_BANDS[:remainder]:
        allocation[band] += 1
    return allocation


def _seed_for_selection(route_seed: int, scene: str, group: str, band: str) -> int:
    payload = f"{route_seed}:{scene}:{group}:{band}".encode("utf-8")
    return int.from_bytes(sha256(payload).digest()[:8], "little")


def select_sml_routes(
    candidates: Sequence[Mapping[str, object]],
    scene: str,
    route_seed: int,
    groups: Mapping[str, RouteGroupConfig],
) -> tuple[list[RouteSpec], dict[str, object]]:
    """在每个距离带内按复杂度三分层抽取 S/M/L 正式路线。"""
    rows = [dict(row) for row in candidates]
    if not rows:
        raise ValueError("候选路线不能为空。")
    distances = np.asarray([float(row["distance_m"]) for row in rows], dtype=float)
    target_percentiles, band_bounds = _distance_bands(distances, groups)

    selected_routes: list[RouteSpec] = []
    selection_metadata: dict[str, object] = {
        "scene": scene,
        "candidate_count": len(rows),
        "target_percentiles": target_percentiles,
        "distance_bands_m": band_bounds,
        "groups": {},
    }
    used_candidate_indices: set[int] = set()
    for group_name in ("S", "M", "L"):
        group = groups[group_name]
        band_min, band_max = band_bounds[group_name]
        band_indices = [
            index
            for index, distance in enumerate(distances)
            if band_min <= float(distance) <= band_max
        ]
        if len(band_indices) < group.routes_per_scene:
            raise RuntimeError(
                f"{scene}/{group_name} 距离带只有 {len(band_indices)} 条候选，"
                f"不足 {group.routes_per_scene} 条。"
            )
        band_scores = np.asarray(
            [float(rows[index]["complexity_score"]) for index in band_indices],
            dtype=float,
        )
        low_threshold = float(np.percentile(band_scores, 100.0 / 3.0))
        high_threshold = float(np.percentile(band_scores, 200.0 / 3.0))
        strata: dict[str, list[int]] = {band: [] for band in COMPLEXITY_BANDS}
        for index in band_indices:
            score = float(rows[index]["complexity_score"])
            band = (
                "low"
                if score <= low_threshold
                else "medium"
                if score <= high_threshold
                else "high"
            )
            strata[band].append(index)

        allocation = _complexity_allocation(group.routes_per_scene)
        selected_indices: list[int] = []
        for complexity_band in COMPLEXITY_BANDS:
            quota = allocation[complexity_band]
            available = strata[complexity_band]
            if len(available) < quota:
                raise RuntimeError(
                    f"{scene}/{group_name}/{complexity_band} 只有 {len(available)} 条候选，"
                    f"不足配额 {quota}。"
                )
            rng = np.random.default_rng(
                _seed_for_selection(route_seed, scene, group_name, complexity_band)
            )
            chosen_positions = rng.choice(len(available), size=quota, replace=False)
            selected_indices.extend(available[int(position)] for position in chosen_positions)

        overlap = set(selected_indices).intersection(used_candidate_indices)
        if overlap:
            raise RuntimeError(f"{scene}/{group_name} 与其他距离组发生重复候选：{sorted(overlap)}")
        used_candidate_indices.update(selected_indices)
        selected_indices.sort(key=lambda index: (float(rows[index]["distance_m"]), index))
        selected_distances = [float(rows[index]["distance_m"]) for index in selected_indices]
        for route_number, candidate_index in enumerate(selected_indices, start=1):
            row = rows[candidate_index]
            score = float(row["complexity_score"])
            band = (
                "low"
                if score <= low_threshold
                else "medium"
                if score <= high_threshold
                else "high"
            )
            diagnostics = {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "scene",
                    "route_seed",
                    "candidate_index",
                    "start",
                    "goal",
                    "distance_m",
                    "height_delta_m",
                    "complexity_score",
                }
            }
            diagnostics["candidate_index"] = int(row["candidate_index"])
            selected_routes.append(
                RouteSpec(
                    scene=scene,
                    route_group=group_name,
                    route_id=f"{scene}_{group_name}_{route_number:03d}",
                    route_seed=route_seed,
                    start=tuple(float(value) for value in row["start"]),  # type: ignore[arg-type]
                    goal=tuple(float(value) for value in row["goal"]),  # type: ignore[arg-type]
                    distance_m=float(row["distance_m"]),
                    height_delta_m=float(row["height_delta_m"]),
                    complexity_score=score,
                    complexity_band=band,
                    diagnostics=diagnostics,
                )
            )
        selection_metadata["groups"][group_name] = {
            "target_percentile": group.target_percentile,
            "percentile_min": group.percentile_min,
            "percentile_max": group.percentile_max,
            "distance_min_m": min(selected_distances),
            "distance_max_m": max(selected_distances),
            "distance_mean_m": float(np.mean(selected_distances)),
            "distance_std_m": float(np.std(selected_distances, ddof=1)),
            "complexity_low_threshold": low_threshold,
            "complexity_high_threshold": high_threshold,
            "selected_per_complexity_band": allocation,
            "selected_count": len(selected_indices),
        }
    return selected_routes, selection_metadata


def write_routes(
    routes: Iterable[RouteSpec],
    path: Path,
    metadata: Mapping[str, object],
) -> str:
    """原子写入冻结路线 JSONL 和旁路 manifest，返回清单 SHA-256。"""
    route_rows = list(routes)
    payload = "".join(
        json.dumps(route.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for route in route_rows
    ).encode("utf-8")
    digest = sha256(payload).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_bytes(payload)
    temporary_path.replace(path)
    manifest = {
        **dict(metadata),
        "route_count": len(route_rows),
        "route_manifest_hash": digest,
    }
    manifest_path = path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return digest


def load_route_manifest(path: Path) -> tuple[RouteSpec, ...]:
    """读取并核对冻结路线清单、唯一 ID、坐标和文件哈希。"""
    resolved_path = path.expanduser().resolve()
    payload = resolved_path.read_bytes()
    manifest_path = resolved_path.with_suffix(".manifest.json")
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_hash = str(manifest.get("route_manifest_hash", ""))
        actual_hash = sha256(payload).hexdigest()
        if expected_hash and expected_hash != actual_hash:
            raise ValueError(
                f"冻结路线清单哈希不一致：{resolved_path}；"
                f"manifest={expected_hash}，actual={actual_hash}"
            )

    routes: list[RouteSpec] = []
    seen_route_ids: set[str] = set()
    for line_number, line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        try:
            start = tuple(float(value) for value in row["start"])
            goal = tuple(float(value) for value in row["goal"])
            route = RouteSpec(
                scene=str(row["scene"]),
                route_group=str(row["route_group"]),
                route_id=str(row["route_id"]),
                route_seed=int(row["route_seed"]),
                start=start,
                goal=goal,
                distance_m=float(row["distance_m"]),
                height_delta_m=float(row["height_delta_m"]),
                complexity_score=float(row["complexity_score"]),
                complexity_band=str(row["complexity_band"]),
                diagnostics=dict(row.get("diagnostics", {})),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"路线清单第 {line_number} 行格式错误：{error}") from error
        if len(start) != 3 or len(goal) != 3:
            raise ValueError(f"路线清单第 {line_number} 行起点/终点必须是三维坐标。")
        if not all(math.isfinite(value) for value in (*start, *goal)):
            raise ValueError(f"路线清单第 {line_number} 行包含非有限起点/终点。")
        if Path(route.route_id).name != route.route_id:
            raise ValueError(f"route_id 必须是不含路径分隔符的单段标识：{route.route_id!r}")
        if route.route_id in seen_route_ids:
            raise ValueError(f"route_id 重复：{route.route_id}")
        seen_route_ids.add(route.route_id)
        routes.append(route)
    if not routes:
        raise ValueError(f"路线清单为空：{resolved_path}")
    return tuple(routes)


def _resolve_config_path(value: str, config_path: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_path.parent.parent.parent / path
    return path.resolve()


def _build_formal_routes(
    formal: FormalConfig,
    scene_config_path: Path,
) -> tuple[list[RouteSpec], dict[str, object]]:
    """按正式配置生成两场景候选池并抽取冻结路线。"""
    scene_payload = json.loads(scene_config_path.read_text(encoding="utf-8-sig"))
    scene_names = sorted(str(name) for name in scene_payload["scenes"])
    all_routes: list[RouteSpec] = []
    scene_metadata: dict[str, object] = {}
    for scene_name in scene_names:
        scene = load_scene(scene_name, scene_config_path)
        candidates = generate_candidate_routes(
            scene,
            formal.route_pool.route_seed,
            formal.route_pool.candidate_routes_per_scene,
            scene.config,
        )
        selected, selection_metadata = select_sml_routes(
            candidates,
            scene_name,
            formal.route_pool.route_seed,
            formal.route_groups,
        )
        all_routes.extend(selected)
        distances = np.asarray([row["distance_m"] for row in candidates], dtype=float)
        scene_metadata[scene_name] = {
            "candidate_count": len(candidates),
            "candidate_distance_percentiles_m": {
                f"p{percentile:g}": float(np.percentile(distances, percentile))
                for percentile in (5, 10, 15, 45, 50, 55, 85, 90, 95)
            },
            "selection": selection_metadata,
        }
        del scene
    return all_routes, {
        "experiment_name": formal.experiment_name,
        "route_seed": formal.route_pool.route_seed,
        "candidate_routes_per_scene": formal.route_pool.candidate_routes_per_scene,
        "scene_metadata": scene_metadata,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成并冻结 A/B 场景 S/M/L 路线清单")
    parser.add_argument("--config", type=Path, default=Path("experiments/configs/formal.toml"))
    parser.add_argument("--output", type=Path, default=Path("experiments/routes/sml_routes.jsonl"))
    parser.add_argument(
        "--smoke-output",
        type=Path,
        default=Path("experiments/routes/smoke_routes.jsonl"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    loaded = load_config(args.config)
    if not isinstance(loaded.config, FormalConfig):
        raise TypeError("路线生成器需要 formal 配置。")
    formal = loaded.config
    scene_config_path = _resolve_config_path(formal.scene_config, loaded.source_path)
    routes, metadata = _build_formal_routes(formal, scene_config_path)
    digest = write_routes(routes, args.output, metadata)

    smoke_source = next(route for route in routes if route.scene == "A" and route.route_group == "S")
    smoke_route = replace(smoke_source, route_group="smoke", route_id="A_smoke_001")
    scene_metadata = metadata["scene_metadata"]
    assert isinstance(scene_metadata, Mapping)
    scene_a_metadata = scene_metadata["A"]
    assert isinstance(scene_a_metadata, Mapping)
    write_routes(
        [smoke_route],
        args.smoke_output,
        {
            "experiment_name": "smoke-route",
            "source_route_id": smoke_source.route_id,
            "source_route_seed": smoke_source.route_seed,
            "scene_metadata": {
                "A": {
                    "candidate_count": scene_a_metadata["candidate_count"],
                    "selection": "copied_from_formal_S_route",
                }
            },
        },
    )
    counts = {
        scene: {
            group: sum(route.scene == scene and route.route_group == group for route in routes)
            for group in ("S", "M", "L")
        }
        for scene in ("A", "B")
    }
    print(f"正式路线清单：{args.output.resolve()}")
    print(f"冒烟路线清单：{args.smoke_output.resolve()}")
    print(f"路线数量：{counts}")
    print(f"清单 SHA-256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
