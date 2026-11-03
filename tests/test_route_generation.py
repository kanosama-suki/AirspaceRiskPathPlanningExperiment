"""路线候选池、分位带、复杂度分层和冻结清单测试。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.experiments.config import RouteGroupConfig
from src.experiments.route_generator import (
    RouteSpec,
    generate_candidate_routes,
    load_route_manifest,
    select_sml_routes,
    write_routes,
)
from src.io.scene import SceneData


def _toy_scene(tmp_path: Path) -> SceneData:
    """构造 20×20×11 的无建筑玩具场景，起终点全部位于搜索节点。"""
    config = {
        "coords": {
            "axes_order": "i,j,h_idx",
            "origin": [0.0, 0.0, 0.0],
            "resolution": 1.0,
        },
        "table2": {
            "N_I": 20,
            "N_J": 20,
            "N_H": 11,
            "H_LOW": 0.0,
            "H_HIGH": 10.0,
            "GRID_SIZE": 1.0,
            "STEP": 1,
            "THETA_MAX": 1.0471975511965976,
            "ALPHA1": 0.4,
            "ALPHA2": 0.6,
        },
    }
    building_mask = np.zeros((20, 20, 11), dtype=bool)
    risk = np.full(building_mask.shape, 1e-9, dtype=np.float64)
    return SceneData(
        scene_name="A",
        scene_dir=tmp_path,
        R=risk,
        building_mask=building_mask,
        pop_density=np.ones((20, 20), dtype=np.float64),
        h_low=0.0,
        h_high=10.0,
        step=1.0,
        missions={},
        config=config,
        config_hash="toy-scene",
        r_norm=1e-9,
    )


def _group(name: str, target: float, low: float, high: float, count: int) -> RouteGroupConfig:
    return RouteGroupConfig(
        name=name,
        target_percentile=target,
        percentile_min=low,
        percentile_max=high,
        routes_per_scene=count,
        time_budget_s=1.0,
        max_iterations=10,
    )


def _synthetic_candidates() -> list[dict[str, object]]:
    """构造距离 1..300 的候选，让分位带边界可手算。"""
    candidates: list[dict[str, object]] = []
    for index in range(300):
        distance = float(index + 1)
        candidates.append(
            {
                "scene": "A",
                "route_seed": 114514,
                "candidate_index": index,
                "start": (float(index % 10), 0.0, 0.0),
                "goal": (distance, 0.0, 0.0),
                "distance_m": distance,
                "height_delta_m": 0.0,
                "complexity_score": float((index * 7) % 97) / 97.0,
                "obstacle_score": 0.0,
            }
        )
    return candidates


def test_candidate_generation_is_reproducible_and_uses_route_seed(tmp_path: Path) -> None:
    """同一场景和 route_seed 生成相同起终点；换 seed 后候选序列改变。"""
    scene = _toy_scene(tmp_path)
    first = generate_candidate_routes(scene, 114514, 20, scene.config)
    second = generate_candidate_routes(scene, 114514, 20, scene.config)
    changed = generate_candidate_routes(scene, 20261101, 20, scene.config)
    assert [row["start"] for row in first] == [row["start"] for row in second]
    assert [row["goal"] for row in first] == [row["goal"] for row in second]
    assert [row["start"] for row in first] != [row["start"] for row in changed]


def test_sml_selection_uses_disjoint_bands_and_complexity_strata() -> None:
    """9 条正式路线来自三个不重叠距离带，每层复杂度的配额可追溯。"""
    groups = {
        "S": _group("S", 10, 5, 15, 3),
        "M": _group("M", 50, 45, 55, 3),
        "L": _group("L", 90, 85, 95, 3),
    }
    routes, metadata = select_sml_routes(_synthetic_candidates(), "A", 114514, groups)
    assert [route.route_group for route in routes] == ["S"] * 3 + ["M"] * 3 + ["L"] * 3
    assert max(route.distance_m for route in routes if route.route_group == "S") < 46.0
    assert min(route.distance_m for route in routes if route.route_group == "M") > 135.0
    assert max(route.distance_m for route in routes if route.route_group == "M") < 166.0
    assert min(route.distance_m for route in routes if route.route_group == "L") > 255.0
    assert len({route.route_id for route in routes}) == 9
    group_metadata = metadata["groups"]
    assert isinstance(group_metadata, dict)
    assert group_metadata["S"]["selected_per_complexity_band"] == {
        "low": 1,
        "medium": 1,
        "high": 1,
    }


def test_manifest_round_trip_and_hash_detection(tmp_path: Path) -> None:
    """冻结清单可重读；修改 JSONL 后必须触发哈希失败。"""
    route = RouteSpec(
        scene="A",
        route_group="S",
        route_id="A_S_001",
        route_seed=114514,
        start=(0.0, 0.0, 30.0),
        goal=(10.0, 0.0, 30.0),
        distance_m=10.0,
        height_delta_m=0.0,
        complexity_score=0.2,
        complexity_band="low",
        diagnostics={"candidate_index": 0},
    )
    path = tmp_path / "routes.jsonl"
    digest = write_routes([route], path, {"route_seed": 114514})
    loaded = load_route_manifest(path)
    assert loaded == (route,)
    assert len(digest) == 64

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="哈希不一致"):
        load_route_manifest(path)
