"""基于玩具建筑掩码的节点和边碰撞手算验证。"""

import numpy as np

from src.core.collision import edge_in_collision, node_in_collision


def toy_config() -> dict[str, object]:
    return {
        "coords": {"axes_order": "i,j,h_idx", "origin": [0, 0, 30], "resolution": 10},
        "table2": {"N_I": 5, "N_J": 5, "N_H": 3},
    }


def test_node_collision_checks_building_mask() -> None:
    building_mask = np.zeros((5, 5, 3), dtype=bool)
    building_mask[2, 2, 1] = True
    # 手算：世界点 (20,20,40) 映射到掩码索引 [2,2,1]，该格为建筑。
    assert node_in_collision(building_mask, (20, 20, 40), toy_config())
    assert not node_in_collision(building_mask, (10, 20, 40), toy_config())


def test_edge_collision_detects_building_between_endpoints() -> None:
    building_mask = np.zeros((5, 5, 3), dtype=bool)
    building_mask[2, 2, 0] = True
    # 手算：边从索引 [0,2,0] 到 [4,2,0]，两端为空，但中间索引 [2,2,0] 是建筑。
    assert edge_in_collision(building_mask, (0, 20, 30), (40, 20, 30), toy_config())
    building_mask[2, 2, 0] = False
    assert not edge_in_collision(building_mask, (0, 20, 30), (40, 20, 30), toy_config())

