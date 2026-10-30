"""路径长度、风险和综合代价评估；所有算法共用小时制指标。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import math

import numpy as np

from .coords import world_to_index


Config = Mapping[str, Any]
Point3D = Sequence[float]


def path_length(path: Sequence[Point3D]) -> float:
    """累计路径中相邻航点之间的三维欧氏长度，单位为米。"""
    if len(path) < 2:
        return 0.0
    return sum(
        math.dist(tuple(float(value) for value in previous), tuple(float(value) for value in following))
        for previous, following in zip(path, path[1:])
    )


def flight_time_hours(distance_m: float, config: Config) -> float:
    """按配置的巡航速度把距离换算为小时。"""
    speed = float(config["table1"]["V_CRUISE"])
    if speed <= 0:
        raise ValueError("V_CRUISE 必须大于 0")
    return float(distance_m) / (speed * 3600.0)


def risk_normalizer(risk_field: np.ndarray) -> float:
    """排除非有限格后，取风险场均值和中位数中的较小者。"""
    finite_values = np.asarray(risk_field, dtype=float)
    finite_values = finite_values[np.isfinite(finite_values)]
    if finite_values.size == 0:
        raise ValueError("风险场没有有限值，无法计算 R_norm")
    normalizer = min(float(finite_values.mean()), float(np.median(finite_values)))
    if normalizer <= 0:
        raise ValueError("R_norm 必须大于 0，才能计算归一化风险代价")
    return normalizer


def sample_risk(risk_field: np.ndarray, point: Point3D, config: Config) -> float | None:
    """读取航点所在栅格的风险；NaN/无穷值以 None 标记为无效。"""
    try:
        index = world_to_index(point, config)
    except ValueError as error:
        raise ValueError(f"风险查询坐标无效：{tuple(point)}") from error
    if risk_field.ndim != 3:
        raise ValueError("风险场必须是三维 [i, j, h_idx] 数组")
    value = float(risk_field[index])
    return value if math.isfinite(value) else None


def normalized_risk_cost(
    path: Sequence[Point3D],
    risk_field: np.ndarray,
    config: Config,
    r_norm: float | None = None,
) -> tuple[float, float]:
    """用端点梯形近似积分 R/R_norm × t_hour，返回代价和 R_norm。"""
    normalizer = risk_normalizer(risk_field) if r_norm is None else float(r_norm)
    if not math.isfinite(normalizer) or normalizer <= 0:
        raise ValueError("R_norm 必须是有限正数。")
    total_cost = 0.0
    for previous, following in zip(path, path[1:]):
        previous_risk = sample_risk(risk_field, previous, config)
        following_risk = sample_risk(risk_field, following, config)
        if previous_risk is None or following_risk is None:
            raise ValueError("路径航点落在 NaN/非有限风险格，路径风险无效")
        segment_distance = math.dist(
            tuple(float(value) for value in previous),
            tuple(float(value) for value in following),
        )
        segment_time = flight_time_hours(segment_distance, config)
        segment_risk_mean = (previous_risk + following_risk) / 2.0
        total_cost += (segment_risk_mean / normalizer) * segment_time
    return total_cost, normalizer


def composite_cost(distance_cost: float, normalized_risk: float, config: Config) -> float:
    """根据配置的 ALPHA1/ALPHA2 合成距离代价和归一化风险代价。"""
    table_config = config["table2"]
    alpha1 = float(table_config["ALPHA1"])
    alpha2 = float(table_config["ALPHA2"])
    return alpha1 * float(distance_cost) + alpha2 * float(normalized_risk)


def evaluate_path(
    path: Sequence[Point3D],
    risk_field: np.ndarray,
    config: Config,
    r_norm: float | None = None,
) -> dict[str, float]:
    """计算统一指标；距离代价按数据栅格数表达，风险项为小时制归一化积分。"""
    length_m = path_length(path)
    grid_size = float(config["table2"]["GRID_SIZE"])
    if grid_size <= 0:
        raise ValueError("GRID_SIZE 必须大于 0")
    distance_cost = length_m / grid_size
    normalized_cost, normalizer = normalized_risk_cost(path, risk_field, config, r_norm)
    return {
        "length_m": length_m,
        "t_hour": flight_time_hours(length_m, config),
        "risk_norm": normalizer,
        "distance_cost": distance_cost,
        "risk_expected": normalized_cost * normalizer,
        "normalized_risk_cost": normalized_cost,
        "composite_cost": composite_cost(distance_cost, normalized_cost, config),
    }

