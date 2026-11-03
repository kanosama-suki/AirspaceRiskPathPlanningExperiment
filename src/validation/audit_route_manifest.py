"""只读审计冻结路线清单的场景覆盖、端点和距离分位带。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import argparse
import json
import math

import numpy as np

from src.core.collision import node_in_collision
from src.core.coords import world_to_index
from src.experiments.config import FormalConfig, PROJECT_ROOT, load_config
from src.experiments.route_generator import RouteSpec, load_route_manifest
from src.io.scene import load_scene


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def audit_routes(
    config: FormalConfig,
    routes: tuple[RouteSpec, ...],
    scene_config_path: Path,
) -> dict[str, object]:
    """逐场景检查完整覆盖、节点合法性和搜索栅格对齐。"""
    payload = json.loads(scene_config_path.read_text(encoding="utf-8-sig"))
    scene_names = sorted(str(name) for name in payload["scenes"])
    actual_scenes = sorted({route.scene for route in routes})
    if actual_scenes != scene_names:
        raise ValueError(f"场景覆盖不一致：manifest={actual_scenes}，config={scene_names}")

    scene_reports: dict[str, object] = {}
    for scene_name in scene_names:
        scene = load_scene(scene_name, scene_config_path)
        step = int(scene.config["table2"]["STEP"])
        scene_routes = [route for route in routes if route.scene == scene_name]
        group_counts = Counter(route.route_group for route in scene_routes)
        expected_counts = {
            group: group_config.routes_per_scene
            for group, group_config in config.route_groups.items()
        }
        actual_counts = {
            group: group_counts.get(group, 0)
            for group in config.route_groups
        }
        if actual_counts != expected_counts:
            raise ValueError(
                f"{scene_name} 组配额不一致：actual={actual_counts}，"
                f"expected={expected_counts}"
            )

        violations: list[dict[str, object]] = []
        group_distances: dict[str, list[float]] = {
            group: [] for group in config.route_groups
        }
        for route in scene_routes:
            try:
                start_index = world_to_index(route.start, scene.config)
                goal_index = world_to_index(route.goal, scene.config)
            except ValueError as error:
                violations.append(
                    {"route_id": route.route_id, "reason": f"grid_alignment:{error}"}
                )
                continue
            if start_index[0] % step or start_index[1] % step:
                violations.append(
                    {"route_id": route.route_id, "reason": "start_not_on_xy_search_grid"}
                )
            if goal_index[0] % step or goal_index[1] % step:
                violations.append(
                    {"route_id": route.route_id, "reason": "goal_not_on_xy_search_grid"}
                )
            if node_in_collision(scene.building_mask, route.start, scene.config):
                violations.append(
                    {"route_id": route.route_id, "reason": "start_in_building"}
                )
            if node_in_collision(scene.building_mask, route.goal, scene.config):
                violations.append(
                    {"route_id": route.route_id, "reason": "goal_in_building"}
                )
            if not math.isfinite(float(scene.R[start_index])):
                violations.append(
                    {"route_id": route.route_id, "reason": "start_risk_nan"}
                )
            if not math.isfinite(float(scene.R[goal_index])):
                violations.append(
                    {"route_id": route.route_id, "reason": "goal_risk_nan"}
                )
            measured_distance = math.dist(route.start, route.goal)
            if not math.isclose(measured_distance, route.distance_m, rel_tol=0.0, abs_tol=1e-9):
                violations.append(
                    {
                        "route_id": route.route_id,
                        "reason": "distance_mismatch",
                        "recorded": route.distance_m,
                        "measured": measured_distance,
                    }
                )
            if not math.isfinite(route.complexity_score):
                violations.append(
                    {"route_id": route.route_id, "reason": "complexity_not_finite"}
                )
            group_distances[route.route_group].append(route.distance_m)

        group_stats = {
            group: {
                "count": len(values),
                "distance_min_m": min(values) if values else None,
                "distance_max_m": max(values) if values else None,
                "distance_mean_m": float(np.mean(values)) if values else None,
                "distance_std_m": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                "complexity_band_counts": dict(
                    Counter(
                        route.complexity_band
                        for route in scene_routes
                        if route.route_group == group
                    )
                ),
            }
            for group, values in group_distances.items()
        }
        scene_reports[scene_name] = {
            "route_count": len(scene_routes),
            "group_counts": dict(group_counts),
            "group_stats": group_stats,
            "violation_count": len(violations),
            "violations": violations,
        }
    return {
        "scene_config": str(scene_config_path),
        "route_seed": config.route_pool.route_seed,
        "route_count": len(routes),
        "scenes": scene_reports,
        "all_pass": all(
            int(report["violation_count"]) == 0
            for report in scene_reports.values()
            if isinstance(report, dict)
        ),
    }


def write_audit(report: dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计冻结 S/M/L 路线清单")
    parser.add_argument("--config", type=Path, default=Path("experiments/configs/formal.toml"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/validation/route_audit.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    loaded = load_config(args.config)
    if not isinstance(loaded.config, FormalConfig):
        raise TypeError("路线审计需要 formal 配置。")
    routes = load_route_manifest(_resolve_path(loaded.config.route_manifest))
    report = audit_routes(
        loaded.config,
        routes,
        _resolve_path(loaded.config.scene_config),
    )
    write_audit(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bool(report["all_pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
