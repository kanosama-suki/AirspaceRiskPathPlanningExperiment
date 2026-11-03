"""命令行实验启动器的任务枚举和进度估算测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from experiments.launch import (
    ProgressState,
    build_launch_plan,
    format_duration,
    load_completed_records,
    matrix_task_key,
)


CONFIG_PATH = Path("experiments/configs/formal.toml")


def test_full_plan_matches_formal_matrix_size() -> None:
    plan = build_launch_plan(
        CONFIG_PATH,
        scope="full",
        workers=8,
        executor_kind="process",
        run_id="launcher-test",
    )

    assert len(plan.selected_routes) == 110
    assert len(plan.tasks) == 4730


def test_scene_group_filter_matches_route_multiplier() -> None:
    plan = build_launch_plan(
        CONFIG_PATH,
        scope="full",
        workers=8,
        executor_kind="process",
        run_id="launcher-test",
        scenes=("A",),
        groups=("S",),
    )

    assert len(plan.selected_routes) == 40
    assert len(plan.tasks) == 40 * 43


def test_sample_scope_runs_one_route_per_scene_group() -> None:
    plan = build_launch_plan(
        CONFIG_PATH,
        scope="sample",
        workers=8,
        executor_kind="process",
        run_id="launcher-test",
    )

    assert len(plan.selected_routes) == 6
    assert len(plan.tasks) == 6 * 43


def test_progress_state_counts_events_and_finishes_eta(tmp_path: Path) -> None:
    plan = build_launch_plan(
        CONFIG_PATH,
        scope="full",
        workers=8,
        executor_kind="process",
        run_id="launcher-test",
        scenes=("A",),
        groups=("S",),
        route_ids=("A_S_001",),
    )
    first = replace(plan.tasks[0], record_path=tmp_path / "record.jsonl")

    assert load_completed_records(plan.tasks) == {}
    state = ProgressState(
        (first,),
        {},
        workers=1,
        profile={},
    )
    event = {
        "scene": first.route.scene,
        "group": first.route.route_group,
        "route_id": first.route.route_id,
        "algorithm": first.algorithm,
        "seed": first.seed,
        "status": "success",
        "runtime_s": 2.0,
    }
    state.record_event(event)

    assert matrix_task_key(first) in state.completed_keys
    assert state.statuses["success"] == 1
    assert state.eta_seconds(1.0) == 0.0


def test_format_duration() -> None:
    assert format_duration(9) == "00:09"
    assert format_duration(65) == "01:05"
    assert format_duration(3661) == "01:01:01"
