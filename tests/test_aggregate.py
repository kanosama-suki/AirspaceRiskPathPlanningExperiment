"""正式实验汇总的成功率门槛、winner 和覆盖审计测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from experiments.aggregate import aggregate_runs
from src.experiments.config import load_config
from src.experiments.route_generator import RouteSpec


def _route() -> RouteSpec:
    return RouteSpec(
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
        diagnostics={},
    )


def _record(
    algorithm: str,
    seed: int,
    status: str,
    cost: float | None,
) -> dict[str, object]:
    return {
        "scene": "A",
        "group": "S",
        "route_id": "A_S_001",
        "algorithm": algorithm,
        "seed": seed,
        "status": status,
        "runtime_s": 1.0,
        "first_feasible_time_s": 0.5 if cost is not None else None,
        "composite_cost": cost,
        "length_m": 12.0 if cost is not None else None,
        "distance_m": 10.0,
        "risk_expected": 1e-6 if cost is not None else None,
        "iterations_or_expansions": 20,
        "complexity_band": "low",
    }


def test_winner_requires_eighty_percent_and_uses_composite_cost_median() -> None:
    """两算法中一个 80% 成功且代价更低者获胜；另一个低成功率不参与排名。"""
    formal = load_config(Path("experiments/configs/formal.toml")).config
    formal = replace(
        formal,
        algorithms=replace(
            formal.algorithms,
            deterministic=("astar", "rc_astar"),
            sampling=(),
        ),
        seeds=replace(formal.seeds, deterministic=114514, sampling=(0, 1, 2, 3)),
    )
    route = _route()
    records = [
        _record("astar", 114514, "success", 10.0),
        _record("rc_astar", 114514, "success", 12.0),
        _record("rc_astar", 0, "success", 12.0),
        _record("rc_astar", 1, "success", 12.0),
        _record("rc_astar", 2, "timeout_no_solution", None),
        _record("rc_astar", 3, "invalid", None),
    ]
    result = aggregate_runs(records, formal, [route])
    summary = {(row["algorithm"], row["not_ranked"]) for row in result.summary_rows}
    assert summary == {("astar", False), ("rc_astar", True)}
    winner = result.winner_rows[0]
    assert winner["winner_algorithm"] == "astar"

    below_threshold_records = [
        _record("astar", 114514, "success", 10.0),
        _record("rc_astar", 114514, "success", 12.0),
        _record("rc_astar", 0, "success", 12.0),
        _record("rc_astar", 1, "success", 12.0),
        _record("rc_astar", 2, "timeout_no_solution", None),
        _record("rc_astar", 3, "timeout_no_solution", None),
    ]
    result = aggregate_runs(below_threshold_records, formal, [route])
    rc_row = next(row for row in result.summary_rows if row["algorithm"] == "rc_astar")
    assert rc_row["strict_success_rate"] == 0.6
    assert rc_row["not_ranked"]
    assert result.winner_rows[0]["winner_algorithm"] == "astar"


def test_coverage_reports_missing_and_duplicate_keys() -> None:
    """缺一条任务和重复一项任务都必须进入覆盖审计。"""
    formal = load_config(Path("experiments/configs/formal.toml")).config
    formal = replace(
        formal,
        algorithms=replace(
            formal.algorithms,
            deterministic=("astar", "rc_astar"),
            sampling=(),
        ),
    )
    route = _route()
    records = [
        _record("astar", 114514, "success", 10.0),
        _record("astar", 114514, "success", 10.0),
    ]
    result = aggregate_runs(records, formal, [route])
    assert result.coverage["duplicate_key_count"] == 1
    assert result.coverage["missing_count"] == 1
    assert not result.coverage["complete"]
