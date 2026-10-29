"""用真实 A 场景 R 切片验证公共指标的手算口径。"""

from pathlib import Path
import json

import pytest

from src.core.metrics import evaluate_path
from src.io.scene import load_scene


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "lib" / "03_场景" / "config.json"


def test_real_r_10_cube_short_path_matches_manual_composite_cost() -> None:
    """用 [0:10,0:10,0:10] 的真实 R 立方块手算一段两米路径。"""
    scene = load_scene("A", CONFIG_PATH)
    real_r_slice = scene.R[0:10, 0:10, 0:10]
    assert real_r_slice.shape == (10, 10, 10)

    # 该 10×10×10 块的三个路径体素为 [1,0,0]、[2,0,0]、[3,0,0]；
    # 输入场景的对应建筑掩码为 False，路径长度是两个数据格间隔。
    indices = ((1, 0, 0), (2, 0, 0), (3, 0, 0))
    assert not any(scene.building_mask[index] for index in indices)
    origin = scene.config["coords"]["origin"]
    resolution = float(scene.config["coords"]["resolution"])
    path = [
        (
            float(origin[0]) + i * resolution,
            float(origin[1]) + j * resolution,
            float(origin[2]) + h_idx * resolution,
        )
        for i, j, h_idx in indices
    ]
    risk_values = [float(real_r_slice[index]) for index in indices]

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    segment_time_hours = resolution / (float(config["table1"]["V_CRUISE"]) * 3600.0)
    manual_risk_expected = (
        (risk_values[0] + risk_values[1]) / 2.0
        + (risk_values[1] + risk_values[2]) / 2.0
    ) * segment_time_hours
    manual_normalized_risk = manual_risk_expected / scene.r_norm
    manual_distance_cost = 2.0 * resolution / float(config["table2"]["GRID_SIZE"])
    manual_composite = (
        float(config["table2"]["ALPHA1"]) * manual_distance_cost
        + float(config["table2"]["ALPHA2"]) * manual_normalized_risk
    )

    metrics = evaluate_path(path, scene.R, scene.config, r_norm=scene.r_norm)

    assert metrics["length_m"] == pytest.approx(2.0 * resolution)
    assert metrics["t_hour"] == pytest.approx(2.0 * segment_time_hours)
    assert metrics["risk_expected"] == pytest.approx(manual_risk_expected, rel=1e-12)
    assert metrics["normalized_risk_cost"] == pytest.approx(manual_normalized_risk, rel=1e-12)
    assert metrics["composite_cost"] == pytest.approx(manual_composite, rel=1e-12)
