"""实验配置模型的严格字段、分组和复现参数测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.experiments.config import (
    CalibrationConfig,
    FormalConfig,
    SmokeConfig,
    load_config,
)


ROOT = Path(__file__).resolve().parents[1]


def test_formal_config_is_route_driven_and_contains_new_seed_values() -> None:
    """正式配置只保留路线实验字段，两个指定 seed 均等于 114514。"""
    loaded = load_config(ROOT / "experiments/configs/formal.toml")
    assert isinstance(loaded.config, FormalConfig)
    assert loaded.config.route_pool.route_seed == 114514
    assert loaded.config.seeds.deterministic == 114514
    assert loaded.config.route_pool.candidate_routes_per_scene == 1000
    assert {
        name: group.routes_per_scene
        for name, group in loaded.config.route_groups.items()
    } == {"S": 40, "M": 10, "L": 5}
    assert loaded.config.route_groups["S"].percentile_min == 5
    assert loaded.config.route_groups["S"].target_percentile == 10
    assert loaded.config.route_groups["S"].percentile_max == 15


def test_smoke_and_calibration_configs_are_separate_typed_files() -> None:
    """冒烟和校准文件独立加载，不混入正式 route_groups。"""
    smoke = load_config(ROOT / "experiments/configs/smoke.toml")
    calibration = load_config(ROOT / "experiments/configs/calibration.toml")
    assert isinstance(smoke.config, SmokeConfig)
    assert isinstance(calibration.config, CalibrationConfig)
    assert smoke.config.route_manifest.endswith("smoke_routes.jsonl")
    assert calibration.config.worker_candidates == (6, 8)
    assert calibration.config.pilot_time_budgets_s == (60.0, 120.0, 240.0)


def test_toml_assignment_lines_have_inline_comments() -> None:
    """三份配置的赋值项保持同行中文注释，读取端仍使用标准 TOML。"""
    for name in ("formal.toml", "smoke.toml", "calibration.toml"):
        path = ROOT / "experiments/configs" / name
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("["):
                continue
            assert "=" in stripped, (path, line_number)
            assert "#" in stripped, (path, line_number)


def test_legacy_fields_are_unknown_and_rejected(tmp_path: Path) -> None:
    """schema_version 和 profile 等旧字段不能再悄悄进入正式配置。"""
    source = (ROOT / "experiments/configs/smoke.toml").read_text(encoding="utf-8")
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("schema_version = 1 # 旧字段\n" + source, encoding="utf-8")
    with pytest.raises(ValueError, match="未知键"):
        load_config(invalid)


def test_formal_route_group_percentiles_must_be_disjoint(tmp_path: Path) -> None:
    """S/M/L 分位区间重叠会让距离条件失去独立性，应在加载时失败。"""
    source = (ROOT / "experiments/configs/formal.toml").read_text(encoding="utf-8")
    invalid = tmp_path / "overlap.toml"
    invalid.write_text(
        source.replace(
            "percentile_min = 45 #",
            "percentile_min = 14 #",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="不能重叠"):
        load_config(invalid)
