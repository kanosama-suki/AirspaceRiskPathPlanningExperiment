"""Informed RRT* 路径长度椭球采样器；树逻辑复用 RRT*。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import math

import numpy as np

from src.core.coords import Point3D, world_to_continuous_index
from src.core.types import PLANNERS, PlanRequest

from .rrt_star import RRTStarPlanner


ELLIPSOID_MAX_ATTEMPTS = 100
"""单次椭球采样最多尝试次数；失败后回退父类全空间采样。"""


def ellipsoid_parameters(
    start: Point3D,
    goal: Point3D,
    c_best: float,
) -> tuple[np.ndarray, float, float]:
    """返回椭球中心、半长轴和半短轴，长度单位为米。

    `c_best` 是当前最优路径长度，两个焦点为 `start` 和 `goal`。
    """
    start_array = np.asarray(start, dtype=np.float64)
    goal_array = np.asarray(goal, dtype=np.float64)
    if start_array.shape != (3,) or goal_array.shape != (3,):
        raise ValueError("起点和终点必须是三维坐标。")
    if not math.isfinite(c_best) or c_best <= 0:
        raise ValueError("c_best 必须是有限正数。")
    c_min = float(np.linalg.norm(goal_array - start_array))
    if c_best < c_min:
        raise ValueError("c_best 不能小于起终点直线距离。")
    return (
        (start_array + goal_array) / 2.0,
        c_best / 2.0,
        math.sqrt(max(0.0, c_best * c_best - c_min * c_min)) / 2.0,
    )


def _rotation_from_x_axis(direction: np.ndarray) -> np.ndarray:
    """构造把单位 x 轴旋到 `direction` 的三维旋转矩阵。"""
    x_axis = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    dot = float(np.clip(np.dot(x_axis, direction), -1.0, 1.0))
    if dot >= 1.0 - 1e-12:
        return np.eye(3, dtype=np.float64)
    if dot <= -1.0 + 1e-12:
        # 绕 y 轴旋转 π：x 轴变成 -x 轴，且矩阵仍保持正交。
        return np.diag([-1.0, 1.0, -1.0])

    cross = np.cross(x_axis, direction)
    cross_matrix = np.array(
        [
            [0.0, -cross[2], cross[1]],
            [cross[2], 0.0, -cross[0]],
            [-cross[1], cross[0], 0.0],
        ],
        dtype=np.float64,
    )
    scale = (1.0 - dot) / float(np.dot(cross, cross))
    return np.eye(3, dtype=np.float64) + cross_matrix + cross_matrix @ cross_matrix * scale


def _within_scene(
    point: Point3D,
    req: PlanRequest,
) -> bool:
    """检查椭球采样点是否在数组边界和可飞高度内。"""
    config = req.scene_data.config
    table = config["table2"]
    try:
        index = world_to_continuous_index(point, config)
    except ValueError:
        return False
    if any(
        index[axis] < -1e-9
        or index[axis] > int(table[key]) - 1 + 1e-9
        for axis, key in enumerate(("N_I", "N_J", "N_H"))
    ):
        return False
    z = float(point[2])
    return req.scene_data.h_low <= z <= req.scene_data.h_high


class InformedRRTStarPlanner(RRTStarPlanner):
    """继承 RRT* 树逻辑，仅将有解后的采样限制到路径长度椭球。"""

    name = "informed_rrt_star"
    ellipsoid_enabled_count: int = 0
    ellipsoid_sample_count: int = 0
    fallback_count: int = 0
    full_space_sample_count: int = 0
    _sampling_rng: object | None = None

    def sample(self, req: PlanRequest) -> Point3D:
        """按当前最优路径长度在椭球内均匀采样，失败时调用父类采样。"""
        if getattr(self, "_sampling_rng", None) is not self._rng:
            self._sampling_rng = self._rng
            self.ellipsoid_enabled_count = 0
            self.ellipsoid_sample_count = 0
            self.fallback_count = 0
            self.full_space_sample_count = 0

        c_best = float(self.best_length)
        if not math.isfinite(c_best):
            self.full_space_sample_count += 1
            return super().sample(req)

        start = np.asarray(req.start, dtype=np.float64)
        goal = np.asarray(req.goal, dtype=np.float64)
        focus_vector = goal - start
        c_min = float(np.linalg.norm(focus_vector))
        if c_min <= 1e-12 or c_best <= c_min + 1e-12:
            self.fallback_count += 1
            self.full_space_sample_count += 1
            return super().sample(req)

        self.ellipsoid_enabled_count += 1
        center, semi_major, semi_minor = ellipsoid_parameters(
            req.start,
            req.goal,
            c_best,
        )
        rotation = _rotation_from_x_axis(focus_vector / c_min)
        axes = np.array([semi_major, semi_minor, semi_minor], dtype=np.float64)
        config: Mapping[str, Any] = req.scene_data.config

        for _ in range(ELLIPSOID_MAX_ATTEMPTS):
            direction = self._rng.normal(size=3)
            direction_norm = float(np.linalg.norm(direction))
            if direction_norm <= 1e-15:
                continue
            radius = float(self._rng.random()) ** (1.0 / 3.0)
            unit_ball_point = direction / direction_norm * radius
            candidate = center + rotation @ (axes * unit_ball_point)
            point = tuple(float(value) for value in candidate)
            if not _within_scene(point, req):
                continue
            if math.dist(req.start, point) + math.dist(point, req.goal) > c_best + 1e-9:
                continue
            self.ellipsoid_sample_count += 1
            return point

        self.fallback_count += 1
        self.full_space_sample_count += 1
        return super().sample(req)


PLANNERS[InformedRRTStarPlanner.name] = InformedRRTStarPlanner

