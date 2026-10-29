"""规划请求、结果和算法接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from src.io.scene import SceneData


Point3D = tuple[float, float, float]
PlanStatus = Literal["success", "no_path", "timeout", "invalid"]


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """一次规划调用的公共输入；预算留空表示由调用方决定是否限时。"""

    scene_data: SceneData
    mission: str
    start: Point3D
    goal: Point3D
    seed: int | None = None
    time_budget_s: float | None = None
    iteration_budget: int | None = None


@dataclass(frozen=True, slots=True)
class PathResult:
    """规划器原始结果和公共评估器指标的统一载体。"""

    status: PlanStatus
    algorithm: str
    scene: str
    mission: str
    seed: int | None
    waypoints: tuple[Point3D, ...]
    path_points: int
    length_m: float
    risk_expected: float
    composite_cost: float
    runtime_s: float
    iterations_or_expansions: int
    samples: int | None
    failure_reason: str | None
    config_hash: str


class PlannerBase(ABC):
    """五种规划算法共用的最小抽象接口。"""

    @abstractmethod
    def plan(self, req: PlanRequest) -> PathResult:
        """基于请求搜索路径；评估指标由公共 evaluator 统一生成。"""
        raise NotImplementedError


PLANNERS: dict[str, type[PlannerBase]] = {}
