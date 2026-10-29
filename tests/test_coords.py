"""坐标转换的手算验证。"""

import pytest

from src.core.coords import height_to_risk_index, index_to_world, world_to_index


@pytest.fixture
def toy_config() -> dict[str, object]:
    return {
        "coords": {"axes_order": "i,j,h_idx", "origin": [0, 0, 30], "resolution": 10},
        "table2": {"N_I": 5, "N_J": 5, "N_H": 3, "H_LOW": 30, "H_HIGH": 50},
    }


def test_index_to_world_manual_example(toy_config: dict[str, object]) -> None:
    # 手算：i=2、j=3、h_idx=1，每格 10 m，原点高度为 30 m，因此坐标为 (20, 30, 40)。
    assert index_to_world((2, 3, 1), toy_config) == (20.0, 30.0, 40.0)


def test_world_to_index_and_height_mapping_manual_example(toy_config: dict[str, object]) -> None:
    # 手算：(40, 0, 50) 相对原点的索引偏移是 (4, 0, 2)，z=50 对应 h_idx=2。
    assert world_to_index((40, 0, 50), toy_config) == (4, 0, 2)
    assert height_to_risk_index(50, toy_config) == 2

