"""标准 A* 的小地图手算与终止状态测试。"""

import math
from pathlib import Path

import numpy as np
import pytest

from src.algorithms.astar import AStarPlanner
from src.core.types import PLANNERS, PathResult, PlanRequest
from src.io.scene import SceneData


def _request(
    building_cells: tuple[tuple[int, int, int], ...] = (),
    start: tuple[float, float, float] = (0.0, 0.0, 30.0),
    goal: tuple[float, float, float] = (20.0, 0.0, 30.0),
    time_budget_s: float | None = None,
) -> PlanRequest:
    """创建分辨率 10 m、形状 5×5×3 的测试场景。"""
    config: dict[str, object] = {
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
            "H_HIGH": 30,
            "STEP": 10,
            "THETA_MAX": math.pi / 3,
        },
    }
    building_mask = np.zeros((5, 5, 3), dtype=bool)
    for cell in building_cells:
        building_mask[cell] = True
    risk_field = np.full((5, 5, 3), 1.0, dtype=np.float64)
    risk_field[building_mask] = np.nan
    scene = SceneData(
        scene_name="toy",
        scene_dir=Path("."),
        R=risk_field,
        building_mask=building_mask,
        pop_density=np.ones((5, 5), dtype=np.float32),
        h_low=30.0,
        h_high=30.0,
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
        time_budget_s=time_budget_s,
    )


def test_straight_path_is_reached_with_geometric_cost_only() -> None:
    result = AStarPlanner().plan(_request(goal=(20.0, 0.0, 30.0)))

    assert isinstance(result, PathResult)
    assert result.status == "success"
    assert result.waypoints == ((0.0, 0.0, 30.0), (10.0, 0.0, 30.0), (20.0, 0.0, 30.0))
    # 手算：两个 10 m 水平边，总长度 10+10=20 m。
    assert result.length_m == pytest.approx(20.0)
    assert math.isnan(result.risk_expected)
    assert math.isnan(result.composite_cost)
    assert result.failure_reason is None
    assert result.iterations_or_expansions > 0
    assert PLANNERS["astar"] is AStarPlanner


def test_obstacle_forces_shortest_turn_compliant_detour() -> None:
    request = _request(
        building_cells=((1, 0, 0),),
        goal=(30.0, 0.0, 30.0),
    )

    result = AStarPlanner().plan(request)

    assert result.status == "success"
    assert (10.0, 0.0, 30.0) not in result.waypoints
    # 手算最短合规路径：(0,0)->(10,10)->(20,10)->(30,0)；
    # 两条对角边各 √(10²+10²)，中间水平边 10 m，总长 10+2√200 m。
    assert result.length_m == pytest.approx(10.0 + 2.0 * math.sqrt(200.0))


@pytest.mark.parametrize(
    ("start", "goal", "building_cell", "failure_reason"),
    [
        ((0.0, 0.0, 30.0), (20.0, 0.0, 30.0), (0, 0, 0), "start_in_obstacle"),
        ((0.0, 0.0, 30.0), (20.0, 0.0, 30.0), (2, 0, 0), "goal_in_obstacle"),
    ],
)
def test_obstacle_at_start_or_goal_returns_invalid(
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    building_cell: tuple[int, int, int],
    failure_reason: str,
) -> None:
    # 手算：起点或终点映射的体素被标记为建筑，规划应在搜索前拒绝。
    result = AStarPlanner().plan(
        _request(building_cells=(building_cell,), start=start, goal=goal)
    )

    assert result.status == "invalid"
    assert result.failure_reason == failure_reason
    assert result.waypoints == ()


def test_open_list_exhaustion_returns_no_path() -> None:
    wall = tuple((1, j, 0) for j in range(5))
    result = AStarPlanner().plan(_request(building_cells=wall, goal=(40.0, 0.0, 30.0)))

    assert result.status == "no_path"
    assert result.failure_reason == "open_empty"
    assert result.waypoints == ()


def test_zero_time_budget_returns_timeout() -> None:
    result = AStarPlanner().plan(_request(time_budget_s=0.0))

    assert result.status == "timeout"
    assert result.failure_reason == "timeout"
    assert result.iterations_or_expansions == 0


def test_off_grid_start_returns_invalid() -> None:
    result = AStarPlanner().plan(_request(start=(5.0, 0.0, 30.0)))

    assert result.status == "invalid"
    assert result.failure_reason == "start_not_search_node"
