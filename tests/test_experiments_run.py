"""路线驱动运行器、合法性复核、任务展开和断点续跑测试。"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math

import numpy as np
import pytest

from experiments.run import (
    MatrixTask,
    _execute_scene_tasks,
    _filter_routes,
    _parse_args,
    _task_already_complete,
    append_jsonl,
    assess_path_result,
    build_run_tasks,
    save_config_snapshot,
)
from src.core.types import PathResult, PlanRequest
from src.experiments.config import (
    AlgorithmConfig,
    ExecutionConfig,
    FormalConfig,
    RouteGroupConfig,
    RoutePoolConfig,
    RunOutputConfig,
    SeedConfig,
    ValidationConfig,
)
from src.experiments.route_generator import RouteSpec
from src.io.scene import SceneData


def _toy_config() -> dict[str, object]:
    """构造 1 m 分辨率的 5×5×1 测试场景配置。"""
    return {
        "coords": {
            "axes_order": "i,j,h_idx",
            "origin": [0.0, 0.0, 0.0],
            "resolution": 1.0,
        },
        "table1": {"V_CRUISE": 20.0},
        "table2": {
            "N_I": 5,
            "N_J": 5,
            "N_H": 1,
            "GRID_SIZE": 1.0,
            "ALPHA1": 0.4,
            "ALPHA2": 0.6,
            "H_LOW": 0,
            "H_HIGH": 0,
            "STEP": 1,
            "THETA_MAX": math.pi / 3,
        },
    }


def _toy_scene(
    tmp_path: Path,
    building_mask: np.ndarray | None = None,
) -> SceneData:
    """创建可直接用于公共评估器的有限风险玩具场景。"""
    config = _toy_config()
    mask = np.zeros((5, 5, 1), dtype=bool) if building_mask is None else building_mask.copy()
    risk = np.full(mask.shape, 2.0, dtype=np.float64)
    risk[mask] = np.nan
    return SceneData(
        scene_name="A",
        scene_dir=tmp_path,
        R=risk,
        building_mask=mask,
        pop_density=np.ones((5, 5), dtype=np.float64),
        h_low=0.0,
        h_high=0.0,
        step=1.0,
        missions={},
        config=config,
        config_hash="scene-hash",
        r_norm=2.0,
    )


def _route(
    route_id: str = "A_S_001",
    group: str = "S",
    scene: str = "A",
    start: tuple[float, float, float] = (0.0, 0.0, 0.0),
    goal: tuple[float, float, float] = (2.0, 0.0, 0.0),
) -> RouteSpec:
    return RouteSpec(
        scene=scene,
        route_group=group,
        route_id=route_id,
        route_seed=114514,
        start=start,
        goal=goal,
        distance_m=math.dist(start, goal),
        height_delta_m=0.0,
        complexity_score=0.2,
        complexity_band="low",
        diagnostics={"candidate_index": 1},
    )


def _result(
    scene: SceneData,
    status: str,
    waypoints: tuple[tuple[float, float, float], ...] = (),
    failure_reason: str | None = None,
) -> PathResult:
    """生成只填公共字段的测试结果。"""
    return PathResult(
        status=status,  # type: ignore[arg-type]
        algorithm="fake",
        scene=scene.scene_name,
        mission="A_S_001",
        seed=0,
        waypoints=waypoints,
        path_points=len(waypoints),
        length_m=math.nan,
        risk_expected=math.nan,
        composite_cost=math.nan,
        runtime_s=0.0,
        iterations_or_expansions=3,
        samples=None,
        failure_reason=failure_reason,
        config_hash=scene.config_hash,
    )


def test_timeout_with_solution_is_kept_as_distinct_status(tmp_path: Path) -> None:
    """合法 incumbent 的手算路径为 2 m，应标记 timeout_with_solution。"""
    scene = _toy_scene(tmp_path)
    route = _route()
    request = PlanRequest(scene, route.route_id, route.start, route.goal)
    assessment = assess_path_result(
        scene,
        request,
        _result(scene, "timeout", (request.start, request.goal), "timeout"),
        1.0,
    )
    assert assessment.status == "timeout_with_solution"
    assert assessment.metrics is not None
    assert assessment.metrics["length_m"] == pytest.approx(2.0)
    assert assessment.metrics["composite_cost"] == pytest.approx(0.8000166666666667)


def test_timeout_without_solution_and_iteration_exhaustion_are_distinguished(tmp_path: Path) -> None:
    """预算耗尽无路径必须是 timeout_no_solution；空间耗尽仍是 no_path。"""
    scene = _toy_scene(tmp_path)
    route = _route()
    request = PlanRequest(scene, route.route_id, route.start, route.goal)
    empty_timeout = assess_path_result(
        scene,
        request,
        _result(scene, "timeout", failure_reason="timeout"),
        1.0,
    )
    iteration_timeout = assess_path_result(
        scene,
        request,
        _result(scene, "no_path", failure_reason="iteration_budget_exhausted"),
        1.0,
    )
    open_empty = assess_path_result(
        scene,
        request,
        _result(scene, "no_path", failure_reason="open_empty"),
        1.0,
    )
    assert empty_timeout.status == "timeout_no_solution"
    assert iteration_timeout.status == "timeout_no_solution"
    assert open_empty.status == "no_path"


def test_collision_nan_and_turn_violation_force_invalid(tmp_path: Path) -> None:
    """建筑节点、NaN 风险和超过 π/3 的水平转角都必须阻断有效指标。"""
    mask = np.zeros((5, 5, 1), dtype=bool)
    mask[1, 0, 0] = True
    scene = _toy_scene(tmp_path, mask)
    route = _route()
    request = PlanRequest(scene, route.route_id, route.start, route.goal)
    collision = assess_path_result(
        scene,
        request,
        _result(scene, "success", (request.start, request.goal)),
        1.0,
    )
    assert collision.status == "invalid"
    assert "edge_collision" in str(collision.failure_reason)
    assert "nan_risk_hit" in str(collision.failure_reason)

    clear_scene = _toy_scene(tmp_path)
    turn_request = PlanRequest(clear_scene, "turn", (0.0, 0.0, 0.0), (2.0, 2.0, 0.0))
    turn = assess_path_result(
        clear_scene,
        turn_request,
        _result(
            clear_scene,
            "success",
            (
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 2.0, 0.0),
                (2.0, 2.0, 0.0),
            ),
        ),
        1.0,
    )
    assert turn.status == "invalid"
    assert "turn_limit_exceeded" in str(turn.failure_reason)


def test_append_and_snapshot_preserve_bytes(tmp_path: Path) -> None:
    """JSONL 追加不覆盖旧行，快照文件内容哈希与文件名一致。"""
    record_path = tmp_path / "records.jsonl"
    append_jsonl(record_path, {"run": 1})
    append_jsonl(record_path, {"run": 2})
    assert [
        json.loads(line)["run"]
        for line in record_path.read_text(encoding="utf-8").splitlines()
    ] == [1, 2]

    config_bytes = b'{"b":2,"a":1}\n'
    digest = hashlib.sha256(config_bytes).hexdigest()
    snapshot = save_config_snapshot(tmp_path / "snapshots", config_bytes, digest)
    assert snapshot.read_bytes() == config_bytes
    assert snapshot.name == f"config-{digest}.json"

    toml_snapshot = save_config_snapshot(
        tmp_path / "snapshots",
        config_bytes,
        digest,
        source_suffix=".toml",
    )
    assert toml_snapshot.name == f"config-{digest}.toml"


def _formal_config(tmp_path: Path) -> FormalConfig:
    groups = {
        name: RouteGroupConfig(
            name=name,
            target_percentile=target,
            percentile_min=low,
            percentile_max=high,
            routes_per_scene=1,
            time_budget_s=budget,
            max_iterations=100,
        )
        for name, target, low, high, budget in (
            ("S", 10.0, 5.0, 15.0, 1.0),
            ("M", 50.0, 45.0, 55.0, 2.0),
            ("L", 90.0, 85.0, 95.0, 3.0),
        )
    }
    return FormalConfig(
        experiment_name="toy",
        scene_config="lib/03_场景/config.json",
        route_manifest="experiments/routes/toy.jsonl",
        algorithms=AlgorithmConfig(
            deterministic=("astar", "risk_astar", "rc_astar"),
            sampling=("rrt_star", "informed_rrt_star"),
        ),
        seeds=SeedConfig(deterministic=114514, sampling=(0, 1)),
        route_pool=RoutePoolConfig(candidate_routes_per_scene=10, route_seed=114514),
        route_groups=groups,
        execution=ExecutionConfig(workers=1, executor="thread"),
        validation=ValidationConfig(path_resample_spacing_m=1.0),
        output=RunOutputConfig(
            raw_root="tmp/test_run/raw",
            snapshot_dir="tmp/test_run/snapshots",
            per_run_template="{scene}/{group}/{algorithm}/{route_id}_seed_{seed}.jsonl",
            tables_root="tmp/test_run/tables",
        ),
    )


def test_filter_sample_keeps_first_route_in_each_scene_group() -> None:
    """sample 范围每个 scene/group 只保留一个 route_id，防止误触全矩阵。"""
    routes = [
        _route("A_S_001", "S"),
        _route("A_S_002", "S"),
        _route("A_M_001", "M"),
        _route("B_S_001", "S", scene="B"),
    ]
    selected = _filter_routes(
        routes,
        scene_names=None,
        group_names=None,
        route_ids=None,
        scope="sample",
    )
    assert {route.route_id for route in selected} == {
        "A_S_001",
        "A_M_001",
        "B_S_001",
    }


def test_task_expansion_uses_shared_sampling_seeds_and_group_budget(tmp_path: Path) -> None:
    """一条路线展开 3 个确定性与 2×2 个采样任务，组预算传给全部算法。"""
    config = _formal_config(tmp_path)
    tasks = build_run_tasks(
        config,
        [_route()],
        scene_config_hashes={"A": "scene-hash"},
        experiment_config_hash="config-hash",
        output=config.output,
        workers=1,
        executor_kind="thread",
        run_id="test",
        run_kind="matrix",
        spacing_m=1.0,
    )
    assert len(tasks) == 7
    deterministic = [task for task in tasks if task.seed_kind == "deterministic"]
    sampling = [task for task in tasks if task.seed_kind == "sampling"]
    assert len(deterministic) == 3
    assert {task.seed for task in deterministic} == {114514}
    assert len(sampling) == 4
    assert {task.seed for task in sampling} == {0, 1}
    assert {task.iteration_budget for task in deterministic} == {None}
    assert {task.iteration_budget for task in sampling} == {100}
    assert {task.time_budget_s for task in tasks} == {1.0}


def test_cli_uses_route_filters_and_sample_default() -> None:
    """命令行不再暴露 profile/missions，默认 scope=sample。"""
    args = _parse_args(
        [
            "--scene",
            "A",
            "--group",
            "S",
            "--route-id",
            "A_S_001",
            "--workers",
            "4",
        ]
    )
    assert args.scope == "sample"
    assert args.scenes == ["A"]
    assert args.groups == ["S"]
    assert args.route_ids == ["A_S_001"]
    assert args.workers == 4
    assert not hasattr(args, "profile")
    assert not hasattr(args, "missions")


def test_process_executor_and_resume_skip_do_not_duplicate_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """玩具 A* 任务通过进程运行；第二次执行相同任务必须跳过已有记录。"""
    import experiments.run as runner

    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    scene = _toy_scene(tmp_path)
    scene.config["paths"] = {
        "scene_A": "toy_scene",
        "city_npz": "<scene>/city.npz",
    }
    scene_dir = tmp_path / "toy_scene"
    scene_dir.mkdir()
    np.savez_compressed(
        scene_dir / "city.npz",
        building_mask=scene.building_mask,
        pop_density=scene.pop_density,
    )
    scene_config_path = tmp_path / "scene.json"
    scene_config_path.write_text(json.dumps(scene.config), encoding="utf-8")
    route = _route()
    task = MatrixTask(
        route=route,
        algorithm="astar",
        seed=114514,
        seed_kind="deterministic",
        time_budget_s=2.0,
        iteration_budget=None,
        spacing_m=1.0,
        experiment_config_hash="experiment-hash",
        scene_config_hash=scene.config_hash,
        run_kind="test",
        run_id="process-test",
        record_path=tmp_path / "records" / "run.jsonl",
        workers=2,
        executor_kind="process",
    )
    executed, skipped = _execute_scene_tasks(scene, [task], scene_config_path)
    assert (executed, skipped) == (1, 0)
    record = json.loads(task.record_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["status"] == "success"
    assert record["route_id"] == route.route_id
    assert _task_already_complete(task)

    executed_again, skipped_again = _execute_scene_tasks(scene, [task], scene_config_path)
    assert (executed_again, skipped_again) == (0, 1)
