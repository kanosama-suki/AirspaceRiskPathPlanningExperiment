"""RC-A* 的加权边代价、动态风险启发和约束搜索手算测试。"""

from __future__ import annotations

from pathlib import Path
import math

import numpy as np
import pytest

from src.algorithms.rc_astar import (
    BoundingBoxRiskEstimator,
    RCAStarPlanner,
    RCParameters,
    rc_edge_cost,
    rc_heuristic,
)
from src.core.collision import edge_in_collision, node_in_collision
from src.core.types import PLANNERS, PlanRequest
from src.io.scene import SceneData


def _config() -> dict[str, object]:
    """构造 5×5×3、10 m 搜索步长的玩具配置。"""
    return {
        "coords": {
            "axes_order": "i,j,h_idx",
            "origin": [0, 0, 30],
            "resolution": 10,
        },
        "table1": {"V_CRUISE": 20},
        "table2": {
            "N_I": 5,
            "N_J": 5,
            "N_H": 3,
            "H_LOW": 30,
            "H_HIGH": 50,
            "STEP": 10,
            "THETA_MAX": math.pi / 3,
            "ALPHA1": 0.4,
            "ALPHA2": 0.6,
            "GRID_SIZE": 1,
        },
    }


def _request(
    risk_field: np.ndarray | None = None,
    building_cells: tuple[tuple[int, int, int], ...] = (),
    start: tuple[float, float, float] = (0.0, 0.0, 30.0),
    goal: tuple[float, float, float] = (30.0, 0.0, 30.0),
    time_budget_s: float | None = None,
) -> PlanRequest:
    """创建含指定风险场与建筑格的玩具规划请求。"""
    config = _config()
    building_mask = np.zeros((5, 5, 3), dtype=bool)
    for cell in building_cells:
        building_mask[cell] = True
    if risk_field is None:
        risk_field = np.full((5, 5, 3), 4.0e-10, dtype=np.float64)
    risk_copy = np.asarray(risk_field, dtype=np.float64).copy()
    risk_copy[building_mask] = np.nan
    scene = SceneData(
        scene_name="toy",
        scene_dir=Path("."),
        R=risk_copy,
        building_mask=building_mask,
        pop_density=np.ones((5, 5), dtype=np.float32),
        h_low=30.0,
        h_high=50.0,
        step=10.0,
        missions={"1": (start, goal), "2": (start, goal)},
        config=config,
        config_hash="toy-config",
        r_norm=4.0e-10,
    )
    return PlanRequest(
        scene_data=scene,
        mission="1",
        start=start,
        goal=goal,
        time_budget_s=time_budget_s,
    )


def test_rc_edge_cost_matches_hand_calculation() -> None:
    params = RCParameters.from_config(_config(), r_norm=4.0e-10)

    # R_seg=(2e-10+6e-10)/2=4e-10；归一化风险为 1。
    # norm_risk=1*(10/(20*3600))=1/7200；边代价为 .4*10+.6/7200。
    cost = rc_edge_cost(2.0e-10, 6.0e-10, 10.0, params)

    assert cost == pytest.approx(4.0 + 0.6 / 7200.0)


def test_bounding_box_heuristic_matches_hand_calculation() -> None:
    risk_field = np.ones((5, 5, 3), dtype=np.float64)
    risk_field[1:4, 1:4, 0:3] = np.arange(1.0, 28.0).reshape(3, 3, 3)
    risk_field[3, 3, 2] = 1000.0
    estimator = BoundingBoxRiskEstimator(risk_field)
    current_index = (1, 1, 0)
    goal_index = (3, 3, 2)

    r_avg, r_median = estimator.stats(current_index, goal_index)
    params = RCParameters.from_config(_config(), r_norm=10.0)
    current = (10.0, 10.0, 30.0)
    goal = (30.0, 30.0, 50.0)
    heuristic = rc_heuristic(current, goal, min(r_avg, r_median), params)

    # 盒内为 1..26 和 1000；均值 1351/27，27 个值的中位数为第 14 个值。
    assert r_avg == pytest.approx(1351.0 / 27.0)
    assert r_median == pytest.approx(14.0)
    distance = 20.0 * math.sqrt(3.0)
    expected_risk = 0.6 * (14.0 / 10.0) * (distance / (20.0 * 3600.0))
    assert heuristic == pytest.approx(0.4 * distance + expected_risk)


def test_box_median_cache_is_deterministic_and_exact() -> None:
    risk_field = np.arange(1.0, 126.0).reshape(5, 5, 5)
    estimator = BoundingBoxRiskEstimator(risk_field)

    first = estimator.stats((0, 0, 0), (4, 4, 4))
    second = estimator.stats((0, 0, 0), (4, 4, 4))

    assert first == second
    assert estimator.median_query_count == 1
    assert estimator.median_method == "小盒精确 nanmedian；大盒三维等距采样；按包围盒缓存"
    assert first == (float(np.mean(risk_field)), float(np.median(risk_field)))


def test_turn_over_limit_neighbor_is_filtered() -> None:
    planner = RCAStarPlanner()
    current = (10.0, 0.0, 30.0)
    previous = (0.0, 0.0, 30.0)
    successors = planner._turn_filtered_neighbors(current, previous, _config())
    successor_points = {point for point, _ in successors}

    # 从东向西南转 135° 的 (0,10,30) 被拒；向东南偏 45° 的节点仍合法。
    assert (0.0, 10.0, 30.0) not in successor_points
    assert (20.0, 10.0, 30.0) in successor_points


def test_obstacle_detour_is_feasible_and_collision_free() -> None:
    request = _request(building_cells=((1, 0, 0),))

    result = RCAStarPlanner().plan(request)

    assert result.status == "success"
    assert result.algorithm == "rc_astar"
    assert PLANNERS["rc_astar"] is RCAStarPlanner
    expected_cost = result.length_m * 0.4 + (result.length_m / (20.0 * 3600.0)) * 0.6
    assert result.composite_cost == pytest.approx(expected_cost, rel=1e-6)
    for point in result.waypoints:
        assert not node_in_collision(
            request.scene_data.building_mask,
            point,
            request.scene_data.config,
        )
    for start, end in zip(result.waypoints, result.waypoints[1:]):
        assert not edge_in_collision(
            request.scene_data.building_mask,
            start,
            end,
            request.scene_data.config,
        )


@pytest.mark.parametrize(
    ("building_cells", "time_budget_s", "status", "failure_reason"),
    [
        (((0, 0, 0),), None, "invalid", "start_in_obstacle"),
        (((3, 0, 0),), None, "invalid", "goal_in_obstacle"),
        (tuple((1, j, h) for j in range(5) for h in range(3)), None, "no_path", "open_empty"),
        ((), 0.0, "timeout", "timeout"),
    ],
)
def test_rc_astar_failure_reasons_are_explicit(
    building_cells: tuple[tuple[int, int, int], ...],
    time_budget_s: float | None,
    status: str,
    failure_reason: str,
) -> None:
    request = _request(building_cells=building_cells, time_budget_s=time_budget_s)

    result = RCAStarPlanner().plan(request)

    assert result.status == status
    assert result.failure_reason == failure_reason
