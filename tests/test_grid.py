"""搜索网格边界、邻域和转角的手算验证。"""

import math

import pytest

from src.core.grid import neighbors_26, turn_is_allowed


@pytest.fixture
def toy_config() -> dict[str, object]:
    return {
        "coords": {"axes_order": "i,j,h_idx", "origin": [0, 0, 30], "resolution": 10},
        "table1": {"V_CRUISE": 20},
        "table2": {
            "N_I": 5,
            "N_J": 5,
            "N_H": 3,
            "H_LOW": 30,
            "H_HIGH": 50,
            "STEP": 10,
            "THETA_MAX": math.pi / 3,
        },
    }


def test_neighbors_filter_horizontal_and_height_boundaries(toy_config: dict[str, object]) -> None:
    # 手算：在 x=40 的右边界、z=30 的最低层，只能向 -x/0/+y 组合及 +z；共 11 个邻居。
    neighbors = neighbors_26((40, 20, 30), toy_config)
    assert len(neighbors) == 11
    assert all(point[0] <= 40 for point in neighbors)
    assert all(point[2] >= 30 for point in neighbors)


def test_center_node_has_all_26_neighbors(toy_config: dict[str, object]) -> None:
    # 手算：内部节点在三个轴各有 -10、0、+10 三种选择，去掉自身后为 3³-1=26。
    neighbors = neighbors_26((20, 20, 40), toy_config)
    assert len(neighbors) == 26
    assert (20.0, 20.0, 40.0) not in neighbors


def test_turn_limit_accepts_45_degrees_and_rejects_90(toy_config: dict[str, object]) -> None:
    # 手算：东向转东北向是 45°，小于配置的 60°；东向转北向是 90°，超过上限。
    assert turn_is_allowed((10, 20, 30), (20, 20, 30), (30, 30, 30), toy_config)
    assert not turn_is_allowed((10, 20, 30), (20, 20, 30), (20, 30, 30), toy_config)


def test_first_segment_has_no_previous_heading(toy_config: dict[str, object]) -> None:
    # 手算：起点没有上一航段，因此第一段不受转角约束。
    assert turn_is_allowed(None, (0, 0, 30), (10, 0, 30), toy_config)

