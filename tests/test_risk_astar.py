"""RiskA* 的纯风险代价、平局和 LOS 后优化手算测试。"""

from __future__ import annotations

from heapq import heappop, heappush
from pathlib import Path
import math

import numpy as np
import pytest

from src.algorithms.risk_astar import (
    RISK_ASTAR_K,
    RiskAStarPlanner,
    _line_of_sight_risk_cost,
    _make_open_entry,
    _path_risk_integral,
    post_optimize_path,
    risk_edge_cost,
    risk_heuristic,
)
from src.core.grid import turn_is_allowed
from src.core.types import PLANNERS, PlanRequest
from src.io.scene import SceneData


def _config() -> dict[str, object]:
    """创建 5×5×3、10 m 搜索步长的玩具配置。"""
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
            "GRID_SIZE": 1,
        },
    }


def _request(
    risk_field: np.ndarray,
    building_cells: tuple[tuple[int, int, int], ...] = (),
    start: tuple[float, float, float] = (0.0, 0.0, 30.0),
    goal: tuple[float, float, float] = (20.0, 0.0, 30.0),
) -> PlanRequest:
    config = _config()
    building_mask = np.zeros((5, 5, 3), dtype=bool)
    for cell in building_cells:
        building_mask[cell] = True
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
        r_norm=1.0,
    )
    return PlanRequest(
        scene_data=scene,
        mission="1",
        start=start,
        goal=goal,
    )


def test_risk_edge_and_heuristic_match_hand_calculation() -> None:
    # r_c=0.1，边长 10 m：c=((0.1+0.1)/2)*10=1。
    assert risk_edge_cost(0.1, 0.1, 10.0) == pytest.approx(1.0)
    # 距离 20 m、最小步长 10 m、r_cmin=0.1：
    # h=((0.1+0.1)/2)*10+(20-10)*0.1=2。
    assert risk_heuristic(0.1, 0.1, 20.0, 10.0, 0.1) == pytest.approx(2.0)


def test_risk_astar_output_risk_integral_matches_hand_calculation() -> None:
    risk_field = np.full((5, 5, 3), 0.1, dtype=np.float64)
    result = RiskAStarPlanner().plan(
        _request(risk_field, building_cells=((1, 1, 0),))
    )

    assert result.status == "success"
    assert PLANNERS["risk_astar"] is RiskAStarPlanner
    assert result.metadata["k"] == pytest.approx(RISK_ASTAR_K)
    # 20 m 的直线路径全程 r_c=0.1，所以风险积分为 0.1*20=2。
    assert math.isnan(result.risk_expected)
    assert result.metadata["post_optimization_risk_integral"] == pytest.approx(2.0)
    assert result.metadata["pre_optimization_risk_integral"] == pytest.approx(2.0)
    assert math.isnan(result.composite_cost)


def test_equal_f_prefers_lower_risk_key() -> None:
    # heap 的第一键 f 相同，生产排序键中 r_c 更小时先出队。
    high_risk_state = ((1, 0, 0), None)
    low_risk_state = ((0, 1, 0), None)
    queue = []
    heappush(queue, _make_open_entry(5.0, 0.2, 0, high_risk_state, 1.0))
    heappush(queue, _make_open_entry(5.0, 0.1, 1, low_risk_state, 1.0))
    assert heappop(queue)[3] == low_risk_state


def test_los_keeps_low_risk_detour_when_direct_line_is_high_risk() -> None:
    # 直线 y=0 穿过高风险带；绕行的斜边和 y=10 横边都保持低风险。
    direct_path = ((0.0, 0.0, 30.0), (30.0, 0.0, 30.0))
    low_detour = (
        (0.0, 0.0, 30.0),
        (10.0, 10.0, 30.0),
        (20.0, 10.0, 30.0),
        (30.0, 0.0, 30.0),
    )
    # 这个测试用可表达范围内的 5×5 网格配置，另用 31×11×1 局部数组的等价配置检验 LOS。
    local_risk = np.full((31, 11, 1), 0.1, dtype=np.float64)
    local_risk[8:23, 0:3, 0] = 1.0
    local_mask = np.zeros_like(local_risk, dtype=bool)
    local_config = {
        "coords": {"axes_order": "i,j,h_idx", "origin": [0, 0, 30], "resolution": 1},
        "table1": {"V_CRUISE": 20},
        "table2": {
            "N_I": 31,
            "N_J": 11,
            "N_H": 1,
            "H_LOW": 30,
            "H_HIGH": 30,
            "STEP": 10,
            "THETA_MAX": math.pi / 3,
            "GRID_SIZE": 1,
        },
    }
    optimized = post_optimize_path(
        low_detour,
        local_risk,
        local_mask,
        local_config,
        r_norm=1.0,
    )
    direct_cost = _line_of_sight_risk_cost(
        direct_path[0],
        direct_path[-1],
        local_risk,
        local_mask,
        local_config,
        r_norm=1.0,
        deadline=None,
    )
    detour_cost = 0.0
    for start, end in zip(low_detour, low_detour[1:]):
        segment_cost = _line_of_sight_risk_cost(
            start,
            end,
            local_risk,
            local_mask,
            local_config,
            r_norm=1.0,
            deadline=None,
        )
        assert segment_cost is not None
        detour_cost += segment_cost
    assert direct_cost is not None
    assert direct_cost > detour_cost
    # 所有低风险绕行边的代价更低；穿过高风险带的 LOS 不应替换绕行。
    assert optimized == low_detour


def test_los_replaces_redundant_low_risk_waypoint() -> None:
    risk_field = np.full((31, 11, 1), 0.1, dtype=np.float64)
    building_mask = np.zeros_like(risk_field, dtype=bool)
    config = {
        "coords": {"axes_order": "i,j,h_idx", "origin": [0, 0, 30], "resolution": 1},
        "table1": {"V_CRUISE": 20},
        "table2": {
            "N_I": 31,
            "N_J": 11,
            "N_H": 1,
            "H_LOW": 30,
            "H_HIGH": 30,
            "STEP": 10,
            "THETA_MAX": math.pi / 3,
            "GRID_SIZE": 1,
        },
    }
    path = (
        (0.0, 0.0, 30.0),
        (10.0, 10.0, 30.0),
        (20.0, 10.0, 30.0),
        (30.0, 0.0, 30.0),
    )
    optimized = post_optimize_path(
        path, risk_field, building_mask, config, r_norm=1.0
    )
    # 全场 r_c=0.1，直连代价与折线代价的最短路径比较会移除冗余点。
    assert optimized == (path[0], path[-1])


def test_los_shortcut_preserves_turn_limit_at_retained_waypoint() -> None:
    # 原路径的航向依次为 0°、45°、90°，每次转角均为 45°。
    # 删除中间点后，A->C 与 C->D 的夹角约为 63.4°，超过 60°。
    path = (
        (0.0, 0.0, 30.0),
        (10.0, 0.0, 30.0),
        (20.0, 10.0, 30.0),
        (20.0, 20.0, 30.0),
    )
    risk_field = np.ones((21, 21, 1), dtype=np.float64)
    risk_field[0:11, 0, 0] = 0.1
    risk_field[10:21, 0:11, 0] = 0.1
    risk_field[20, 10:21, 0] = 0.1
    for i in range(21):
        risk_field[i, round(i / 2), 0] = 0.1
    building_mask = np.zeros_like(risk_field, dtype=bool)
    config = {
        "coords": {"axes_order": "i,j,h_idx", "origin": [0, 0, 30], "resolution": 1},
        "table1": {"V_CRUISE": 20},
        "table2": {
            "N_I": 21,
            "N_J": 21,
            "N_H": 1,
            "H_LOW": 30,
            "H_HIGH": 30,
            "STEP": 10,
            "THETA_MAX": math.pi / 3,
            "GRID_SIZE": 1,
        },
    }

    assert turn_is_allowed(path[0], path[2], path[3], config) is False
    optimized = post_optimize_path(
        path, risk_field, building_mask, config, r_norm=1.0
    )

    assert optimized == path


@pytest.mark.parametrize(
    ("building_cells", "time_budget_s", "status", "failure_reason"),
    [
        (((0, 0, 0),), None, "invalid", "start_in_obstacle"),
        (((2, 0, 0),), None, "invalid", "goal_in_obstacle"),
        (
            tuple((1, j, h) for j in range(5) for h in range(3)),
            None,
            "no_path",
            "open_empty",
        ),
        ((), 0.0, "timeout", "timeout"),
    ],
)
def test_risk_astar_failure_reasons_are_explicit(
    building_cells: tuple[tuple[int, int, int], ...],
    time_budget_s: float | None,
    status: str,
    failure_reason: str,
) -> None:
    risk_field = np.full((5, 5, 3), 0.1, dtype=np.float64)
    result = RiskAStarPlanner().plan(
        _request(risk_field, building_cells=building_cells)
        if time_budget_s is None
        else PlanRequest(
            scene_data=_request(risk_field).scene_data,
            mission="1",
            start=(0.0, 0.0, 30.0),
            goal=(20.0, 0.0, 30.0),
            time_budget_s=time_budget_s,
        )
    )
    assert result.status == status
    assert result.failure_reason == failure_reason
