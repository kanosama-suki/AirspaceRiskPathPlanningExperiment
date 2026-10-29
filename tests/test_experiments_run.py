"""实验运行器的状态、合法性复核、快照和预算汇总测试。"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math

import numpy as np
import pytest

from experiments.budget_smoke import _recommend_budget, _rows_from_records
from experiments.run import (
    _path_digest,
    append_jsonl,
    assess_path_result,
    save_config_snapshot,
    run_one,
)
from src.core.types import PathResult, PlanRequest, PlannerBase
from src.io.scene import SceneData


def _toy_config() -> dict[str, object]:
    """构造 1 m 分辨率的 5×5×1 测试场景配置。"""
    return {
        "coords": {"axes_order": "i,j,h_idx", "origin": [0.0, 0.0, 0.0], "resolution": 1.0},
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
        scene_name="toy",
        scene_dir=tmp_path,
        R=risk,
        building_mask=mask,
        pop_density=np.ones((5, 5), dtype=np.float64),
        h_low=0.0,
        h_high=0.0,
        step=1.0,
        missions={"1": ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0))},
        config=config,
        config_hash="scene-hash",
        r_norm=2.0,
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
        mission="1",
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
    request = PlanRequest(scene, "1", scene.missions["1"][0], scene.missions["1"][1])
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
    """预算耗尽无路径必须是 timeout_no_solution；搜索空间耗尽仍是 no_path。"""
    scene = _toy_scene(tmp_path)
    request = PlanRequest(scene, "1", scene.missions["1"][0], scene.missions["1"][1])
    empty_timeout = assess_path_result(scene, request, _result(scene, "timeout", failure_reason="timeout"), 1.0)
    iteration_timeout = assess_path_result(
        scene,
        request,
        _result(scene, "no_path", failure_reason="iteration_budget_exhausted"),
        1.0,
    )
    open_empty = assess_path_result(scene, request, _result(scene, "no_path", failure_reason="open_empty"), 1.0)
    assert empty_timeout.status == "timeout_no_solution"
    assert iteration_timeout.status == "timeout_no_solution"
    assert open_empty.status == "no_path"


def test_collision_nan_and_turn_violation_force_invalid(tmp_path: Path) -> None:
    """建筑节点、NaN 风险和超过 π/3 的水平转角都必须阻断有效指标。"""
    mask = np.zeros((5, 5, 1), dtype=bool)
    mask[1, 0, 0] = True
    scene = _toy_scene(tmp_path, mask)
    request = PlanRequest(scene, "1", scene.missions["1"][0], scene.missions["1"][1])
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
    turn_request = PlanRequest(clear_scene, "1", (0.0, 0.0, 0.0), (2.0, 2.0, 0.0))
    turn = assess_path_result(
        clear_scene,
        turn_request,
        _result(clear_scene, "success", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 2.0, 0.0), (2.0, 2.0, 0.0))),
        1.0,
    )
    assert turn.status == "invalid"
    assert "turn_limit_exceeded" in str(turn.failure_reason)


def test_invalid_nonfinite_waypoint_still_gets_a_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非法 NaN 航点不能让失败记录在哈希阶段再次抛错。"""
    scene = _toy_scene(tmp_path)

    class NaNPlanner(PlannerBase):
        name = "nan_test"

        def plan(self, req: PlanRequest) -> PathResult:
            return _result(req.scene_data, "success", (req.start, (math.nan, 0.0, 0.0), req.goal))

    monkeypatch.setitem(__import__("experiments.run", fromlist=["PLANNERS"]).PLANNERS, "nan_test", NaNPlanner)
    record = run_one(scene, "1", "nan_test", 0, 1.0, None, 1.0, "experiment-hash", "test")
    assert record["status"] == "invalid"
    assert isinstance(record["path_sha256"], str)


def test_append_and_snapshot_preserve_bytes(tmp_path: Path) -> None:
    """JSONL 追加不覆盖旧行，快照文件内容哈希与文件名保持一致。"""
    record_path = tmp_path / "records.jsonl"
    append_jsonl(record_path, {"run": 1})
    append_jsonl(record_path, {"run": 2})
    assert [json.loads(line)["run"] for line in record_path.read_text(encoding="utf-8").splitlines()] == [1, 2]

    config_bytes = b'{"b": 2, "a": 1}\n'
    digest = hashlib.sha256(config_bytes).hexdigest()
    snapshot = save_config_snapshot(tmp_path / "snapshots", config_bytes, digest)
    assert snapshot.read_bytes() == config_bytes
    assert snapshot.stem == f"base-{digest}"


def test_budget_summary_and_recommendation_use_only_real_rows() -> None:
    """两个样本中一个成功时成功率为 50%，不应伪造达到 80% 的预算结论。"""
    records = [
        {
            "scene": "A",
            "mission": "1",
            "algorithm": "rrt_star",
            "status": "success",
            "first_feasible_time_s": 2.0,
            "composite_cost": 10.0,
            "budget": {"run_kind": "budget_time", "time_budget_s": 10.0, "iteration_budget": 5000},
        },
        {
            "scene": "A",
            "mission": "1",
            "algorithm": "rrt_star",
            "status": "timeout_no_solution",
            "first_feasible_time_s": None,
            "composite_cost": None,
            "budget": {"run_kind": "budget_time", "time_budget_s": 10.0, "iteration_budget": 5000},
        },
    ]
    rows = _rows_from_records(records)
    assert rows[0]["runs"] == 2
    assert rows[0]["solutions"] == 1
    assert rows[0]["success_rate"] == pytest.approx(0.5)
    assert _recommend_budget(rows, "time_budget_s") == 10.0
