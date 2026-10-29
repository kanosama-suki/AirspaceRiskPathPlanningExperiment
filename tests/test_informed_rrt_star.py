"""Informed RRT* 椭球采样的手算几何和回退测试。"""

from __future__ import annotations

from pathlib import Path
import math

import numpy as np
import pytest

from src.algorithms.informed_rrt_star import (
    InformedRRTStarPlanner,
    ellipsoid_parameters,
)
from src.algorithms.rrt_star import RRTStarPlanner
from src.core.types import PLANNERS, PlanRequest
from src.io.scene import SceneData


def _config() -> dict[str, object]:
    """构造 101×101×101 的无建筑玩具场景配置。"""
    return {
        "coords": {
            "axes_order": "i,j,h_idx",
            "origin": [0, 0, 30],
            "resolution": 1,
        },
        "table1": {"V_CRUISE": 20},
        "table2": {
            "N_I": 101,
            "N_J": 101,
            "N_H": 101,
            "H_LOW": 30,
            "H_HIGH": 130,
            "STEP": 10,
            "THETA_MAX": math.pi / 3,
            "GRID_SIZE": 10,
            "ALPHA1": 0.4,
            "ALPHA2": 0.6,
        },
    }


def _request(
    start: tuple[float, float, float] = (10.0, 10.0, 30.0),
    goal: tuple[float, float, float] = (90.0, 10.0, 30.0),
) -> PlanRequest:
    """创建无建筑、单位风险场的采样请求。"""
    config = _config()
    building_mask = np.zeros((101, 101, 101), dtype=bool)
    scene = SceneData(
        scene_name="toy",
        scene_dir=Path("."),
        R=np.ones((101, 101, 101), dtype=np.float64),
        building_mask=building_mask,
        pop_density=np.ones((101, 101), dtype=np.float32),
        h_low=30.0,
        h_high=130.0,
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
        iteration_budget=100,
    )


def test_ellipsoid_parameters_match_hand_calculation() -> None:
    center, semi_major, semi_minor = ellipsoid_parameters(
        (0.0, 0.0, 30.0),
        (6.0, 0.0, 30.0),
        10.0,
    )

    # c_min=6；中心=(3,0,30)；半长轴=10/2=5；
    # 半短轴=sqrt(10²-6²)/2=sqrt(64)/2=4。
    assert center == pytest.approx(np.array([3.0, 0.0, 30.0]))
    assert semi_major == pytest.approx(5.0)
    assert semi_minor == pytest.approx(4.0)


def test_infinite_best_length_matches_parent_full_space_sample() -> None:
    request = _request()
    parent = RRTStarPlanner()
    informed = InformedRRTStarPlanner()
    parent._rng = np.random.default_rng(12)
    informed._rng = np.random.default_rng(12)

    parent_point = parent.sample(request)
    informed_point = informed.sample(request)

    # c_best=inf 时子类直接调用父类；相同 RNG 状态应得到完全相同的格心。
    assert informed.best_length == math.inf
    assert informed_point == parent_point
    assert informed.ellipsoid_enabled_count == 0


def test_finite_best_length_samples_inside_path_length_ellipsoid() -> None:
    request = _request(start=(20.0, 50.0, 80.0), goal=(80.0, 50.0, 80.0))
    planner = InformedRRTStarPlanner()
    planner._rng = np.random.default_rng(21)
    planner.best_length = 80.0

    points = [planner.sample(request) for _ in range(50)]

    # 起终点距离 60 m、c_best=80 m；每个格心都满足
    # ||start-x||+||x-goal|| <= 80 m，且椭球采样确实被启用。
    assert planner.ellipsoid_enabled_count == 50
    assert planner.ellipsoid_sample_count == 50
    assert planner.fallback_count == 0
    for point in points:
        path_length_bound = math.dist(request.start, point) + math.dist(point, request.goal)
        assert path_length_bound <= 80.0 + 1e-9


def test_ellipsoid_sampler_returns_continuous_world_point() -> None:
    class FixedUnitBallRng:
        """固定单位球方向和半径，便于手算连续椭球采样点。"""

        @staticmethod
        def normal(size: int) -> np.ndarray:
            assert size == 3
            return np.array([0.0, 1.0, 0.0])

        @staticmethod
        def random() -> float:
            return 0.5

    request = _request(start=(20.0, 50.0, 80.0), goal=(80.0, 50.0, 80.0))
    planner = InformedRRTStarPlanner()
    planner._rng = FixedUnitBallRng()  # type: ignore[assignment]
    planner.best_length = 80.0

    point = planner.sample(request)
    semi_minor = math.sqrt(80.0**2 - 60.0**2) / 2.0
    expected_y = 50.0 + semi_minor * (0.5 ** (1.0 / 3.0))

    # 单位球样本沿短轴，半径为 cuberoot(0.5)；不取整即可得到该手算坐标。
    assert point == pytest.approx((50.0, expected_y, 80.0))
    assert not math.isclose(point[1], round(point[1]))


def test_degenerate_foci_fall_back_to_parent_sampling() -> None:
    request = _request(start=(50.0, 50.0, 30.0), goal=(50.0, 50.0, 30.0))
    planner = InformedRRTStarPlanner()
    planner._rng = np.random.default_rng(31)
    planner.best_length = 10.0

    point = planner.sample(request)

    # 起终点重合时 c_min=0，椭球方向退化；应回退到父类全空间采样而不报错。
    assert planner.fallback_count == 1
    assert planner.full_space_sample_count == 1
    assert point != request.start


def test_best_length_shorter_than_direct_distance_falls_back() -> None:
    request = _request()
    planner = InformedRRTStarPlanner()
    planner._rng = np.random.default_rng(41)
    planner.best_length = 79.0

    planner.sample(request)

    # 起终点直线长 80 m，c_best=79 m 不可能形成可行椭球，因此走父类采样。
    assert planner.fallback_count == 1
    assert planner.ellipsoid_enabled_count == 0
    assert planner.full_space_sample_count == 1


def test_out_of_bounds_ellipsoid_samples_fall_back_to_parent() -> None:
    class OutsideEllipseRng:
        """反复生成椭球外的 y 方向候选，并让父类采样取地图首格。"""

        @staticmethod
        def normal(size: int) -> np.ndarray:
            assert size == 3
            return np.array([0.0, 1.0, 0.0])

        @staticmethod
        def random() -> float:
            return 0.999

        @staticmethod
        def integers(low: int, high: int) -> int:
            del high
            return low

    request = _request()
    planner = InformedRRTStarPlanner()
    planner._rng = OutsideEllipseRng()  # type: ignore[assignment]
    planner.best_length = 1000.0

    point = planner.sample(request)

    # 巨大椭球的采样候选超出 0..100 m 边界；100 次后回退到父类全空间采样。
    assert point == (0.0, 0.0, 30.0)
    assert planner.ellipsoid_enabled_count == 1
    assert planner.ellipsoid_sample_count == 0
    assert planner.fallback_count == 1
    assert planner.full_space_sample_count == 1


def test_informed_planner_reuses_parent_tree_methods_and_registers() -> None:
    assert RRTStarPlanner().best_length == math.inf
    assert InformedRRTStarPlanner.plan is RRTStarPlanner.plan
    assert InformedRRTStarPlanner.nearest is RRTStarPlanner.nearest
    assert InformedRRTStarPlanner.steer is RRTStarPlanner.steer
    assert InformedRRTStarPlanner.near is RRTStarPlanner.near
    assert InformedRRTStarPlanner.choose_parent is RRTStarPlanner.choose_parent
    assert InformedRRTStarPlanner.rewire is RRTStarPlanner.rewire
    assert {
        name
        for name, value in InformedRRTStarPlanner.__dict__.items()
        if callable(value)
    } == {"sample"}
    assert PLANNERS["informed_rrt_star"] is InformedRRTStarPlanner


def test_parent_plan_records_zero_length_solution() -> None:
    request = _request(start=(50.0, 50.0, 30.0), goal=(50.0, 50.0, 30.0))
    planner = InformedRRTStarPlanner()

    result = planner.plan(request)

    assert result.status == "success"
    assert planner.best_length == 0.0
