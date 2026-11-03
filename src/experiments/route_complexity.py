"""路线级实验复杂度指标；不参与任何规划器的搜索代价。"""

from __future__ import annotations

from collections.abc import Sequence
import math

import numpy as np

from src.core.coords import index_to_world, world_to_continuous_index
from src.core.metrics import sample_risk
from src.core.types import Point3D


def _clip01(value: float) -> float:
    return float(np.clip(float(value), 0.0, 1.0))


def route_complexity(
    start: Point3D,
    goal: Point3D,
    building_mask: np.ndarray,
    risk_field: np.ndarray,
    config: dict,
    *,
    samples: int | None = None,
) -> dict[str, float | bool | str]:
    """计算路线诊断复杂度。

    分数为 `0.45*obstacle + 0.35*risk_variation + 0.20*altitude`。
    该指标只用于路线抽样和分层统计，不进入任何算法的 g/h/f。
    """
    required = ("GRID_SIZE", "H_LOW", "H_HIGH", "N_I", "N_J", "N_H")
    table = config.get("table2", {})
    missing = [key for key in required if key not in table]
    if missing:
        raise ValueError(f"路线复杂度评估需要完整 table2 配置，缺少：{missing}")
    start_array = np.asarray(start, dtype=float)
    goal_array = np.asarray(goal, dtype=float)
    distance = float(np.linalg.norm(goal_array - start_array))
    if distance <= 0:
        raise ValueError("路线起点和终点不能重合。")
    spacing = float(table["GRID_SIZE"])
    count = max(2, int(math.ceil(distance / spacing)) + 1) if samples is None else max(2, int(samples))
    points = []
    for point in np.linspace(start_array, goal_array, count):
        continuous = world_to_continuous_index(tuple(float(value) for value in point), config)
        index = tuple(int(round(value)) for value in continuous)
        points.append(index_to_world(index, config))
    voxel_indices: list[tuple[int, int, int]] = []
    for point in points:
        continuous_index = world_to_continuous_index(point, config)
        index = tuple(int(round(value)) for value in continuous_index)
        if any(value < 0 or value >= size for value, size in zip(index, building_mask.shape)):
            raise ValueError("路线复杂度采样点超出地图边界。")
        voxel_indices.append(index)

    # 每次以 1 个数据格间距采样；点位占用率用于路线复杂度分层。
    obstacle_hits = np.asarray(
        [bool(building_mask[index]) for index in voxel_indices],
        dtype=bool,
    )
    collision = bool(obstacle_hits.any())
    risks = [sample_risk(risk_field, point, config) for point in points]
    finite_risks = np.asarray([value for value in risks if value is not None], dtype=float)
    risk_mean = float(finite_risks.mean()) if finite_risks.size else math.nan
    risk_max = float(finite_risks.max()) if finite_risks.size else math.nan
    risk_std = float(finite_risks.std()) if finite_risks.size else math.nan
    obstacle_fraction = float(obstacle_hits.mean())
    if finite_risks.size:
        scale = max(abs(risk_mean), 1e-30)
        risk_variation = _clip01((0.5 * (risk_max - risk_mean) + risk_std) / scale)
    else:
        risk_variation = 1.0
    h_low = float(config["table2"]["H_LOW"])
    h_high = float(config["table2"]["H_HIGH"])
    altitude_score = _clip01(abs(float(goal[2]) - float(start[2])) / max(h_high - h_low, 1e-12))
    score = 0.45 * obstacle_fraction + 0.35 * risk_variation + 0.20 * altitude_score
    return {
        "obstacle_score": _clip01(obstacle_fraction),
        "risk_variation_score": risk_variation,
        "altitude_score": altitude_score,
        "complexity_score": _clip01(score),
        "straight_line_collision": collision,
        "straight_line_risk_mean": risk_mean,
        "straight_line_risk_max": risk_max,
        "straight_line_risk_std": risk_std,
    }

