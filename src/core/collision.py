"""节点和线段碰撞检查；边检查沿线采样，不只检查端点。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import math

import numpy as np

from .coords import world_to_continuous_index, world_to_index


Config = Mapping[str, Any]


def node_in_collision(building_mask: np.ndarray, point: Sequence[float], config: Config) -> bool:
    """检查点所在体素；越界点视为碰撞，以阻止路径穿出地图。"""
    if building_mask.ndim != 3:
        raise ValueError("building_mask 必须是三维 [i, j, h_idx] 数组")
    expected_shape = (
        int(config["table2"]["N_I"]),
        int(config["table2"]["N_J"]),
        int(config["table2"]["N_H"]),
    )
    if building_mask.shape != expected_shape:
        raise ValueError(f"building_mask.shape={building_mask.shape}，配置期望 {expected_shape}")
    try:
        index = world_to_index(point, config)
    except ValueError:
        return True
    return bool(building_mask[index])


def edge_in_collision(
    building_mask: np.ndarray,
    start: Sequence[float],
    end: Sequence[float],
    config: Config,
) -> bool:
    """沿线以不超过一个数据格的间隔采样，检查端点和所有经过的体素。"""
    if building_mask.ndim != 3:
        raise ValueError("building_mask 必须是三维 [i, j, h_idx] 数组")
    expected_shape = (
        int(config["table2"]["N_I"]),
        int(config["table2"]["N_J"]),
        int(config["table2"]["N_H"]),
    )
    if building_mask.shape != expected_shape:
        raise ValueError(f"building_mask.shape={building_mask.shape}，配置期望 {expected_shape}")

    start_point = np.asarray(start, dtype=float)
    end_point = np.asarray(end, dtype=float)
    if start_point.shape != (3,) or end_point.shape != (3,):
        raise ValueError("线段起点和终点都必须是三维坐标")
    if node_in_collision(building_mask, start_point, config) or node_in_collision(building_mask, end_point, config):
        return True

    distance = float(np.linalg.norm(end_point - start_point))
    resolution = float(config["coords"]["resolution"])
    sample_count = max(1, math.ceil(distance / resolution))
    for sample_index in range(1, sample_count):
        fraction = sample_index / sample_count
        sample = start_point + fraction * (end_point - start_point)
        continuous_index = world_to_continuous_index(sample, config)
        voxel_index = tuple(int(round(value)) for value in continuous_index)
        if any(value < 0 or value >= size for value, size in zip(voxel_index, building_mask.shape)):
            return True
        if bool(building_mask[voxel_index]):
            return True
    return False

