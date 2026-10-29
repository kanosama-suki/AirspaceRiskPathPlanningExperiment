"""路径长度、小时制、风险积分和综合代价的手算验证。"""

import numpy as np

from src.core.metrics import evaluate_path, flight_time_hours, path_length


def toy_config() -> dict[str, object]:
    return {
        "coords": {"axes_order": "i,j,h_idx", "origin": [0, 0, 30], "resolution": 10},
        "table1": {"V_CRUISE": 20},
        "table2": {
            "N_I": 5,
            "N_J": 5,
            "N_H": 3,
            "GRID_SIZE": 10,
            "ALPHA1": 0.4,
            "ALPHA2": 0.6,
        },
    }


def test_straight_path_length_and_flight_time() -> None:
    path = [(0, 0, 30), (30, 40, 30)]
    # 手算：长度为 √(30²+40²)=50 m，时间为 50/(20×3600) 小时。
    assert path_length(path) == 50.0
    assert flight_time_hours(50, toy_config()) == 50 / (20 * 3600)


def test_toy_risk_field_composite_cost() -> None:
    risk_field = np.full((5, 5, 3), 2.0, dtype=float)
    path = [(0, 0, 30), (20, 0, 30)]
    # 手算：R_norm=2；两端风险均为 2，归一化段风险是 1×(20/(20×3600))=1/3600 h。
    # 距离代价是 20/10=2 个配置栅格单位，综合代价为 0.4×2+0.6×(1/3600)。
    result = evaluate_path(path, risk_field, toy_config())
    assert result["length_m"] == 20.0
    assert result["risk_norm"] == 2.0
    assert result["normalized_risk_cost"] == 1 / 3600
    assert result["composite_cost"] == 0.4 * 2 + 0.6 / 3600


def test_evaluate_path_uses_precomputed_normalizer_and_reports_risk_integral() -> None:
    risk_field = np.full((5, 5, 3), 100.0, dtype=float)
    risk_field[0, 0, 0] = 2.0
    risk_field[2, 0, 0] = 6.0
    path = [(0, 0, 30), (20, 0, 30)]

    # 手算：端点风险均值为 4，飞行时间为 20/(20×3600) 小时，
    # 未归一化风险积分为 4×20/(20×3600)=1/900；给定 R_norm=4 后归一化代价为 1/3600。
    result = evaluate_path(path, risk_field, toy_config(), r_norm=4.0)

    assert result["risk_norm"] == 4.0
    assert result["risk_expected"] == 1 / 900
    assert result["normalized_risk_cost"] == 1 / 3600
    assert result["composite_cost"] == 0.4 * 2 + 0.6 / 3600

