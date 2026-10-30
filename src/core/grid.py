"""搜索网格、26 邻域和转角检查；只负责候选邻居与几何约束。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import itertools
import math

from .coords import Index3D, Point3D, index_to_world, world_to_index


Config = Mapping[str, Any]


def _grid_parameters(config: Config) -> tuple[int, int, int, int]:
    """读取数组尺寸及算法步长，并验证步长可以映射到数据栅格。"""
    table_config = config["table2"]
    resolution = float(config["coords"]["resolution"])
    step = float(table_config["STEP"])
    if resolution <= 0 or step <= 0:
        raise ValueError("坐标分辨率和搜索步长必须大于 0")
    step_cells_float = step / resolution
    step_cells = round(step_cells_float)
    if not math.isclose(step_cells_float, step_cells, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("搜索步长必须是数据栅格分辨率的整数倍")
    return (
        int(table_config["N_I"]),
        int(table_config["N_J"]),
        int(table_config["N_H"]),
        int(step_cells),
    )


def is_search_node(point: Sequence[float], config: Config) -> bool:
    """判断世界坐标是否位于合法的算法离散节点上。"""
    try:
        index = world_to_index(point, config)
    except ValueError:
        return False
    n_i, n_j, n_h, stride = _grid_parameters(config)
    if index[0] >= n_i or index[1] >= n_j or index[2] >= n_h:
        return False
    h_low = float(config["table2"]["H_LOW"])
    h_high = float(config["table2"]["H_HIGH"])
    z = float(point[2])
    step = float(config["table2"]["STEP"])
    if z < h_low or z > h_high:
        return False
    if not math.isclose((z - h_low) / step, round((z - h_low) / step), rel_tol=0.0, abs_tol=1e-9):
        return False
    return index[0] % stride == 0 and index[1] % stride == 0


def neighbors_26(point: Sequence[float], config: Config) -> list[Point3D]:
    """返回经过数组边界和高度过滤的 26 邻域合法搜索节点。"""
    if not is_search_node(point, config):
        raise ValueError(f"输入点不是合法搜索节点：{tuple(point)}")
    current_index = world_to_index(point, config)
    n_i, n_j, n_h, stride = _grid_parameters(config)
    candidates: list[Point3D] = []
    for delta in itertools.product((-stride, 0, stride), repeat=3):
        if delta == (0, 0, 0):
            continue
        candidate_index: Index3D = tuple(current_index[axis] + delta[axis] for axis in range(3))  # type: ignore[assignment]
        if not (0 <= candidate_index[0] < n_i and 0 <= candidate_index[1] < n_j and 0 <= candidate_index[2] < n_h):
            continue
        candidate = index_to_world(candidate_index, config)
        if is_search_node(candidate, config):
            candidates.append(candidate)
    return candidates


def turn_is_allowed(
    previous: Sequence[float] | None,
    current: Sequence[float],
    following: Sequence[float],
    config: Config,
) -> bool:
    """检查相邻两段的水平航向夹角；首段和纯垂直段不施加航向限制。"""
    if previous is None:
        return True
    theta_max = float(config["table2"]["THETA_MAX"])
    incoming = (float(current[0]) - float(previous[0]), float(current[1]) - float(previous[1]))
    outgoing = (float(following[0]) - float(current[0]), float(following[1]) - float(current[1]))
    incoming_norm = math.hypot(*incoming)
    outgoing_norm = math.hypot(*outgoing)
    if incoming_norm == 0.0 or outgoing_norm == 0.0:
        return True
    cosine = (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / (incoming_norm * outgoing_norm)
    angle = math.acos(max(-1.0, min(1.0, cosine)))
    return angle <= theta_max

