"""计算二维遮蔽系数 P_s。"""

from __future__ import annotations

from typing import Any

import numpy as np


# A、B 场景的边界基准均支持此映射；按题面索引定义，symmetric 与它相同。
REFLECT_MODE = "edge_axis"


def _reflect_index(index: int, size: int, mode: str) -> int:
    """按指定镜像约定把一个越界数组索引映射回有效范围。"""
    if size <= 0:
        raise ValueError("镜像数组长度必须为正数。")
    if mode not in {"edge_center", "edge_axis", "symmetric"}:
        raise ValueError(f"不支持的 reflect 模式：{mode}")
    if size == 1:
        return 0

    if mode == "edge_center":
        # 边缘格本身作为镜像中心：-1 -> 0，size -> size - 1。
        period = 2 * size
        folded = index % period
        return folded if folded < size else period - 1 - folded

    # 按任务给出的例子，edge_axis 与 symmetric 都是 -k -> k、
    # size-1+k -> size-1-k；两种标签在该零起始定义下映射相同。
    period = 2 * (size - 1)
    folded = index % period
    return folded if folded < size else period - folded


def _window_mean(field: np.ndarray, window: int, mode: str) -> np.ndarray:
    """用选定的 reflect 索引和积分图计算居中方窗均值。"""
    if window <= 0 or window % 2 == 0:
        raise ValueError("P_S_WINDOW 必须是正奇数。")
    if field.ndim != 2:
        raise ValueError("P_s 输入必须是二维平面场。")

    padding = window // 2
    row_indices = np.fromiter(
        (_reflect_index(index, field.shape[0], mode) for index in range(-padding, field.shape[0] + padding)),
        dtype=np.intp,
        count=field.shape[0] + 2 * padding,
    )
    column_indices = np.fromiter(
        (_reflect_index(index, field.shape[1], mode) for index in range(-padding, field.shape[1] + padding)),
        dtype=np.intp,
        count=field.shape[1] + 2 * padding,
    )
    padded = field[np.ix_(row_indices, column_indices)]

    # 积分图复用相邻方窗的累加值，避免逐格复制窗口。
    cumulative = padded.cumsum(axis=0, dtype=np.float64).cumsum(axis=1, dtype=np.float64)
    prefix = np.pad(cumulative, ((1, 0), (1, 0)), mode="constant")
    window_sums = (
        prefix[window:, window:]
        - prefix[:-window, window:]
        - prefix[window:, :-window]
        + prefix[:-window, :-window]
    )
    return window_sums / (window * window)


def compute_ps(
    building_footprint: np.ndarray,
    pop_density: np.ndarray,
    config: dict[str, Any],
    reflect_mode: str | None = None,
) -> np.ndarray:
    """根据二维 building_footprint 计算无高度维的遮蔽系数场。"""
    footprint = np.asarray(building_footprint)
    density = np.asarray(pop_density)
    if footprint.ndim != 2:
        raise ValueError("building_footprint 必须是二维平面数组。")
    if density.ndim != 2 or density.shape != footprint.shape:
        raise ValueError("pop_density 必须与 building_footprint 具有相同的二维形状。")

    supplementary = config["supplementary"]
    window = int(supplementary["P_S_WINDOW"])
    scale = float(supplementary["P_S_SCALE"])
    coverage_reference = float(supplementary["P_S_C_REF"])
    if coverage_reference <= 0:
        raise ValueError("P_S_C_REF 必须大于 0。")

    selected_mode = REFLECT_MODE if reflect_mode is None else reflect_mode
    coverage = _window_mean(footprint.astype(bool, copy=False), window, selected_mode)
    return scale * np.minimum(1.0, coverage / coverage_reference)


def compute_ps_window(
    ps: np.ndarray,
    i: int,
    j: int,
    window: int,
    reflect_mode: str | None = None,
) -> float:
    """返回二维场在指定中心、选定反射边界方窗内的均值。"""
    values = np.asarray(ps)
    if values.ndim != 2:
        raise ValueError("窗口输入必须是二维平面场。")
    if not (0 <= i < values.shape[0] and 0 <= j < values.shape[1]):
        raise IndexError("窗口中心索引超出平面场范围。")
    selected_mode = REFLECT_MODE if reflect_mode is None else reflect_mode
    return float(_window_mean(values, window, selected_mode)[i, j])
