"""RRT* 的步长、近邻、重连及玩具障碍路径测试。"""

from __future__ import annotations

from pathlib import Path
import math

import numpy as np
import pytest

from src.algorithms.rrt_star import (
    RRTStarPlanner,
    _TreeNode,
    rrt_star_radius,
    theoretical_gamma,
)
from src.core.collision import edge_in_collision, node_in_collision
from src.core.grid import turn_is_allowed
from src.core.types import PLANNERS, PlanRequest
from src.io.scene import SceneData


def _config() -> dict[str, object]:
    """构造 5×5×3、1 m 数据分辨率和 10 m 算法步长的小地图。"""
    return {
        "coords": {
            "axes_order": "i,j,h_idx",
            "origin": [0, 0, 30],
            "resolution": 1,
        },
        "table1": {"V_CRUISE": 20},
        "table2": {
            "N_I": 5,
            "N_J": 5,
            "N_H": 3,
            "H_LOW": 30,
            "H_HIGH": 32,
            "STEP": 10,
            "THETA_MAX": math.pi / 3,
            "GRID_SIZE": 10,
            "ALPHA1": 0.4,
            "ALPHA2": 0.6,
        },
    }


def _request(
    building_cells: tuple[tuple[int, int, int], ...] = (),
    start: tuple[float, float, float] = (0.0, 0.0, 30.0),
    goal: tuple[float, float, float] = (4.0, 0.0, 30.0),
    iteration_budget: int | None = 1000,
    time_budget_s: float | None = None,
) -> PlanRequest:
    """创建仅含玩具风险和建筑数组的请求。"""
    config = _config()
    building_mask = np.zeros((5, 5, 3), dtype=bool)
    for cell in building_cells:
        building_mask[cell] = True
    risk_field = np.ones((5, 5, 3), dtype=np.float64)
    risk_field[building_mask] = np.nan
    scene = SceneData(
        scene_name="toy",
        scene_dir=Path("."),
        R=risk_field,
        building_mask=building_mask,
        pop_density=np.ones((5, 5), dtype=np.float32),
        h_low=30.0,
        h_high=32.0,
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
        seed=7,
        iteration_budget=iteration_budget,
        time_budget_s=time_budget_s,
    )


def test_steer_limits_voxel_aligned_step_to_configured_distance() -> None:
    point = RRTStarPlanner.steer(
        (0.0, 0.0, 30.0),
        (30.0, 40.0, 30.0),
        max_distance=10.0,
        resolution=1.0,
    )

    # 手算方向比例为 10/50，偏移是 (6,8,0)，长度 sqrt(6²+8²)=10 m。
    assert point == (6.0, 8.0, 30.0)
    assert math.dist((0.0, 0.0, 30.0), point) <= 10.0


def test_near_radius_matches_theoretical_formula() -> None:
    n = 8
    gamma = 2.0
    eta = 10.0
    expected = min(gamma * (math.log(n) / n) ** (1.0 / 3.0), eta)

    # 手算代入 n=8；测试值同时确认结果未超过 eta 上限。
    assert rrt_star_radius(n, gamma, eta) == pytest.approx(expected)
    assert rrt_star_radius(n, gamma, eta) < eta


def test_gamma_is_strictly_above_theoretical_threshold() -> None:
    free_volume = 1000.0
    unit_ball_volume = 4.0 * math.pi / 3.0
    threshold = 2.0 * (1.0 + 1.0 / 3.0) ** (1.0 / 3.0) * (
        free_volume / unit_ball_volume
    ) ** (1.0 / 3.0)

    # 手算三维单位球体积为 4π/3；论文条件要求 gamma > 阈值而非等于阈值。
    assert theoretical_gamma(free_volume) > threshold


def test_uniform_sampler_rejects_building_voxels() -> None:
    request = _request(building_cells=((2, 2, 1),))
    planner = RRTStarPlanner()
    planner._rng = np.random.default_rng(3)

    samples = [planner.sample(request) for _ in range(100)]

    # 拒绝采样只重抽建筑格；返回点都来自空闲体素中心。
    assert all(
        not node_in_collision(request.scene_data.building_mask, point, request.scene_data.config)
        for point in samples
    )


def test_rewire_lowers_cost_and_updates_tree_parent() -> None:
    request = _request()
    planner = RRTStarPlanner()
    # Risk 恒为 1、R_norm=1 时，每米代价为 alpha1/GRID_SIZE + alpha2/(V_CRUISE*3600)。
    cost_per_meter = 0.4 / 10.0 + 0.6 / (20.0 * 3600.0)
    points = (
        (0.0, 0.0, 30.0),
        (0.0, 1.0, 30.0),
        (1.0, 1.0, 30.0),
        (2.0, 1.0, 30.0),
        (1.0, 0.0, 30.0),
    )
    nodes = [
        _TreeNode(points[0], None, 0.0),
        _TreeNode(points[1], 0, cost_per_meter),
        _TreeNode(points[2], 1, 2.0 * cost_per_meter),
        _TreeNode(points[3], 2, 3.0 * cost_per_meter),
        _TreeNode(points[4], 0, cost_per_meter),
    ]
    nodes[0].children.update((1, 4))
    nodes[1].children.add(2)
    nodes[2].children.add(3)
    old_cost = nodes[3].cost

    rewires = planner.rewire(request, new_index=4, near_indices=(3,), nodes=nodes)

    # 原路长 3 m；新路长 1+sqrt(2) m，对应公共边代价等比例降低。
    assert rewires == 1
    assert nodes[3].parent == 4
    assert nodes[3].cost == pytest.approx(cost_per_meter * (1.0 + math.sqrt(2.0)))
    assert 3 not in nodes[2].children
    assert 3 in nodes[4].children


def test_rewire_rejects_turn_violation_at_existing_child() -> None:
    request = _request(start=(20.0, 0.0, 30.0), goal=(40.0, 20.0, 30.0))
    planner = RRTStarPlanner()
    points = (
        (2.0, 0.0, 30.0),
        (1.0, 1.0, 30.0),
        (1.0, 2.0, 30.0),
        (2.0, 3.0, 30.0),
        (3.0, 3.0, 30.0),
        (4.0, 3.0, 30.0),
        (3.0, 1.0, 30.0),
        (3.0, 2.0, 30.0),
    )
    costs = (0.0, math.sqrt(2.0), math.sqrt(2.0) + 1.0,
             2.0 * math.sqrt(2.0) + 1.0,
             2.0 * math.sqrt(2.0) + 2.0,
             2.0 * math.sqrt(2.0) + 3.0,
             math.sqrt(2.0),
             math.sqrt(2.0) + 1.0)
    parents = (None, 0, 1, 2, 3, 4, 0, 6)
    nodes = [_TreeNode(points[i], parents[i], costs[i]) for i in range(len(points))]
    for child_index, parent_index in enumerate(parents):
        if parent_index is not None:
            nodes[parent_index].children.add(child_index)
    old_parent = nodes[4].parent
    old_cost = nodes[4].cost

    # 新边 new->q 向北可行；但 q 原有子边向东，北转东为 90°，超过 π/3。
    assert turn_is_allowed(points[6], points[7], points[4], request.scene_data.config)
    assert not turn_is_allowed(points[7], points[4], points[5], request.scene_data.config)
    rewires = planner.rewire(request, new_index=7, near_indices=(4,), nodes=nodes)

    assert rewires == 0
    assert nodes[4].parent == old_parent
    assert nodes[4].cost == old_cost


def test_obstacle_detour_is_found_and_collision_free() -> None:
    request = _request(building_cells=((2, 0, 0),), iteration_budget=1000)

    result = RRTStarPlanner().plan(request)

    assert result.status == "success"
    assert result.algorithm == "rrt_star"
    assert PLANNERS["rrt_star"] is RRTStarPlanner
    assert result.samples == result.iterations_or_expansions
    assert result.metadata["rewires"] >= 0
    assert result.metadata["gamma"] > 0
    assert result.metadata["eta"] == 10.0
    assert result.length_m > 4.0
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
    for index in range(1, len(result.waypoints) - 1):
        assert turn_is_allowed(
            result.waypoints[index - 1],
            result.waypoints[index],
            result.waypoints[index + 1],
            request.scene_data.config,
        )


def test_seed_reproduces_same_path_and_no_budget_is_invalid() -> None:
    request = _request(iteration_budget=100)
    first = RRTStarPlanner().plan(request)
    second = RRTStarPlanner().plan(request)
    no_budget = RRTStarPlanner().plan(
        PlanRequest(
            scene_data=request.scene_data,
            mission=request.mission,
            start=request.start,
            goal=request.goal,
            seed=request.seed,
        )
    )

    assert first.status == second.status
    assert first.waypoints == second.waypoints
    assert no_budget.status == "invalid"
    assert no_budget.failure_reason == "missing_search_budget"
