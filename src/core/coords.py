"""坐标、体素索引和风险高度层映射。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import math


Config = Mapping[str, Any]
Index3D = tuple[int, int, int]
Point3D = tuple[float, float, float]


def _coordinate_spec(config: Config) -> tuple[tuple[float, float, float], float, tuple[int, int, int]]:
    """从场景配置读取索引顺序、原点、分辨率及数组尺寸。"""
    coordinate_config = config["coords"]
    table_config = config["table2"]
    axes_order = str(coordinate_config["axes_order"])
    if axes_order != "i,j,h_idx":
        raise ValueError(f"不支持的索引顺序：{axes_order}")

    origin = tuple(float(value) for value in coordinate_config["origin"])
    if len(origin) != 3:
        raise ValueError("coords.origin 必须包含三个坐标")

    resolution = float(coordinate_config["resolution"])
    if resolution <= 0:
        raise ValueError("coords.resolution 必须大于 0")

    shape = (
        int(table_config["N_I"]),
        int(table_config["N_J"]),
        int(table_config["N_H"]),
    )
    if any(size <= 0 for size in shape):
        raise ValueError("table2 中的 N_I、N_J、N_H 必须大于 0")
    return (origin[0], origin[1], origin[2]), resolution, shape


def index_to_world(index: Sequence[int], config: Config) -> Point3D:
    """将 `[i, j, h_idx]` 转为世界坐标 `(x, y, z)`。"""
    if len(index) != 3:
        raise ValueError("体素索引必须包含 i、j、h_idx 三个分量")
    origin, resolution, shape = _coordinate_spec(config)
    grid_index = tuple(int(value) for value in index)
    if any(float(value) != int(value) for value in index):
        raise ValueError("体素索引必须是整数")
    if any(value < 0 or value >= size for value, size in zip(grid_index, shape)):
        raise ValueError(f"体素索引 {grid_index} 超出数组范围 {shape}")
    return tuple(origin[axis] + grid_index[axis] * resolution for axis in range(3))  # type: ignore[return-value]


def world_to_continuous_index(point: Sequence[float], config: Config) -> tuple[float, float, float]:
    """把世界坐标换算为连续数组索引，供边线采样使用。"""
    if len(point) != 3:
        raise ValueError("世界坐标必须包含 x、y、z 三个分量")
    origin, resolution, _ = _coordinate_spec(config)
    return tuple((float(point[axis]) - origin[axis]) / resolution for axis in range(3))  # type: ignore[return-value]


def world_to_index(point: Sequence[float], config: Config) -> Index3D:
    """将落在体素中心位置的 `(x, y, z)` 转为整数索引。"""
    continuous_index = world_to_continuous_index(point, config)
    rounded = tuple(int(round(value)) for value in continuous_index)
    if any(not math.isclose(value, index, rel_tol=0.0, abs_tol=1e-9) for value, index in zip(continuous_index, rounded)):
        raise ValueError(f"世界坐标 {tuple(point)} 未落在数据栅格上")
    _, _, shape = _coordinate_spec(config)
    if any(value < 0 or value >= size for value, size in zip(rounded, shape)):
        raise ValueError(f"世界坐标 {tuple(point)} 对应索引 {rounded} 超出数组范围 {shape}")
    return rounded  # type: ignore[return-value]


def height_to_risk_index(z: float, config: Config) -> int:
    """把世界高度映射到一米（或配置分辨率）风险栅格的 `h_idx`。"""
    index = world_to_index((config["coords"]["origin"][0], config["coords"]["origin"][1], z), config)
    return index[2]

