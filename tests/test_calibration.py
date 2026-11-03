"""S/M/L 预算校准的路线分层、统计和 80% 建议测试。"""

from __future__ import annotations

from pathlib import Path
import json

from src.experiments.route_generator import RouteSpec
from experiments.calibrate import (
    _read_records,
    recommend_budgets,
    select_calibration_routes,
    summarize_records,
)


def _route(scene: str, group: str, band: str, number: int) -> RouteSpec:
    return RouteSpec(
        scene=scene,
        route_group=group,
        route_id=f"{scene}_{group}_{band}_{number}",
        route_seed=114514,
        start=(0.0, 0.0, 30.0),
        goal=(float(10 + number), 0.0, 30.0),
        distance_m=float(10 + number),
        height_delta_m=0.0,
        complexity_score={"low": 0.1, "medium": 0.5, "high": 0.9}[band],
        complexity_band=band,
        diagnostics={},
    )


def test_calibration_routes_are_balanced_across_complexity_and_groups() -> None:
    """每个场景每组三类复杂度各选一条，共 18 条校准路线。"""
    routes = [
        _route(scene, group, band, number)
        for scene in ("A", "B")
        for group in ("S", "M", "L")
        for band in ("low", "medium", "high")
        for number in range(2)
    ]
    selected = select_calibration_routes(routes, 3)
    assert len(selected) == 18
    assert len({route.route_id for route in selected}) == 18
    assert {
        (route.scene, route.route_group)
        for route in selected
    } == {
        (scene, group)
        for scene in ("A", "B")
        for group in ("S", "M", "L")
    }


def test_summary_distinguishes_strict_success_from_legal_discovery() -> None:
    """timeout_with_solution 计入路径发现率，但不冒充严格成功。"""
    records = [
        {
            "scene": "A",
            "group": "S",
            "algorithm": "rrt_star",
            "status": "success",
            "runtime_s": 2.0,
            "first_feasible_time_s": 1.0,
            "composite_cost": 10.0,
            "budget": {
                "time_budget_s": 10.0,
                "iteration_budget": 1000,
                "run_kind": "calibration_time",
            },
        },
        {
            "scene": "A",
            "group": "S",
            "algorithm": "rrt_star",
            "status": "timeout_with_solution",
            "runtime_s": 10.0,
            "first_feasible_time_s": 8.0,
            "composite_cost": 12.0,
            "budget": {
                "time_budget_s": 10.0,
                "iteration_budget": 1000,
                "run_kind": "calibration_time",
            },
        },
    ]
    row = summarize_records(records)[0]
    assert row["strict_success_rate"] == 0.5
    assert row["legal_path_discovery_rate"] == 1.0


def test_budget_recommendation_uses_eighty_percent_strict_success() -> None:
    """两个采样算法均在 10 秒达到 80% 时，建议最小档位 10 秒。"""
    rows = [
        {
            "run_kind": "calibration_time",
            "scene": "A",
            "group": "S",
            "algorithm": algorithm,
            "time_budget_s": 10.0,
            "strict_success_rate": 0.8,
        }
        for algorithm in ("rrt_star", "informed_rrt_star")
    ]
    recommendation = recommend_budgets(rows)
    assert recommendation["minimum_budget_for_80_percent_strict_success"]["A/S"] == 10.0


def test_calibration_reader_excludes_other_batches(tmp_path: Path) -> None:
    """校准汇总只读取当前配置哈希和 scope 的记录。"""
    path = tmp_path / "record.jsonl"
    records = [
        {
            "experiment_config_hash": "current",
            "execution": {"run_id": "pilot"},
            "scene": "A",
        },
        {
            "experiment_config_hash": "current",
            "execution": {"run_id": "full"},
            "scene": "B",
        },
        {
            "experiment_config_hash": "old",
            "execution": {"run_id": "pilot"},
            "scene": "C",
        },
    ]
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    loaded = _read_records(tmp_path, "current", "pilot")

    assert loaded == [records[0]]
