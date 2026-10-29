"""公共规划请求、结果和抽象规划器接口测试。"""

from dataclasses import fields
from typing import cast

import pytest

from src.algorithms.astar import AStarPlanner
from src.core.types import PLANNERS, PathResult, PlanRequest, PlannerBase
from src.io.scene import SceneData


def test_plan_request_and_result_expose_common_contract() -> None:
    request = PlanRequest(
        scene_data=cast(SceneData, object()),
        mission="1",
        start=(1.0, 2.0, 30.0),
        goal=(3.0, 4.0, 30.0),
        seed=5,
        time_budget_s=10.0,
        iteration_budget=100,
    )
    result = PathResult(
        status="success",
        algorithm="test-planner",
        scene="A",
        mission="1",
        seed=request.seed,
        waypoints=(request.start, request.goal),
        path_points=2,
        length_m=2.8284271247461903,
        risk_expected=0.0,
        composite_cost=1.0,
        runtime_s=0.1,
        iterations_or_expansions=3,
        samples=None,
        failure_reason=None,
        config_hash="abc123",
    )

    assert request.mission == "1"
    assert result.waypoints == (request.start, request.goal)
    assert {field.name for field in fields(PathResult)} == {
        "status",
        "algorithm",
        "scene",
        "mission",
        "seed",
        "waypoints",
        "path_points",
        "length_m",
        "risk_expected",
        "composite_cost",
        "runtime_s",
        "iterations_or_expansions",
        "samples",
        "failure_reason",
        "config_hash",
    }


def test_planner_base_is_abstract_and_astar_is_registered() -> None:
    assert PLANNERS["astar"] is AStarPlanner
    with pytest.raises(TypeError):
        PlannerBase()  # type: ignore[abstract]

