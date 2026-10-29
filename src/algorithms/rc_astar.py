"""距离/风险加权 RC-A* 规划器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from time import perf_counter
from typing import Any, TypeAlias
import math

import numpy as np

from src.core.collision import edge_in_collision, node_in_collision
from src.core.coords import Index3D, Point3D, index_to_world, world_to_index
from src.core.grid import is_search_node, neighbors_26, turn_is_allowed
from src.core.metrics import evaluate_path
from src.core.types import PLANNERS, PathResult, PlanRequest, PlannerBase, PlanStatus


Direction2D: TypeAlias = tuple[int, int]
SearchState: TypeAlias = tuple[Index3D, Direction2D | None]
OpenEntry: TypeAlias = tuple[float, int, SearchState, float]
BoxKey: TypeAlias = tuple[int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class RCParameters:
    """从场景配置和 SceneData 读取的 RC-A* 代价参数。"""

    alpha1: float
    alpha2: float
    cruise_speed_m_s: float
    r_norm: float

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        r_norm: float,
    ) -> RCParameters:
        """读取权重、巡航速度和 SceneData 提供的精确风险归一化量。"""
        table1 = config["table1"]
        table2 = config["table2"]
        parameters = cls(
            alpha1=float(table2["ALPHA1"]),
            alpha2=float(table2["ALPHA2"]),
            cruise_speed_m_s=float(table1["V_CRUISE"]),
            r_norm=float(r_norm),
        )
        if not all(
            math.isfinite(value)
            for value in (
                parameters.alpha1,
                parameters.alpha2,
                parameters.cruise_speed_m_s,
                parameters.r_norm,
            )
        ):
            raise ValueError("RC-A* 参数必须是有限数。")
        if parameters.alpha1 < 0 or parameters.alpha2 < 0:
            raise ValueError("ALPHA1 和 ALPHA2 不能为负数。")
        if parameters.cruise_speed_m_s <= 0 or parameters.r_norm <= 0:
            raise ValueError("V_CRUISE 和 R_norm 必须大于零。")
        return parameters


def rc_edge_cost(
    r_prev: float,
    r_next: float,
    distance_m: float,
    parameters: RCParameters,
) -> float:
    """按论文 A 式 (17)(18) 计算距离/归一化风险加权边代价。"""
    if not math.isfinite(r_prev) or not math.isfinite(r_next):
        raise ValueError("边端点风险必须是有限值。")
    if not math.isfinite(distance_m) or distance_m < 0:
        raise ValueError("边长必须是有限非负数。")

    r_segment = (float(r_prev) + float(r_next)) / 2.0
    t_hour = float(distance_m) / (parameters.cruise_speed_m_s * 3600.0)
    normalized_risk = (r_segment / parameters.r_norm) * t_hour
    return parameters.alpha1 * float(distance_m) + parameters.alpha2 * normalized_risk


def rc_heuristic(
    current: Point3D,
    goal: Point3D,
    predicted_risk: float,
    parameters: RCParameters,
) -> float:
    """按论文 A 式 (20)–(22)(27) 计算距离和风险组合启发式。"""
    if not math.isfinite(predicted_risk) or predicted_risk < 0:
        raise ValueError("包围盒风险估值必须是有限非负数。")
    distance_m = math.dist(current, goal)
    t_pred_hour = distance_m / (parameters.cruise_speed_m_s * 3600.0)
    normalized_risk = (predicted_risk / parameters.r_norm) * t_pred_hour
    return parameters.alpha1 * distance_m + parameters.alpha2 * normalized_risk


class BoundingBoxRiskEstimator:
    """使用二维前缀和与缓存统计三维轴对齐包围盒风险。

    小包围盒保留精确中位数；大包围盒使用确定性的三维等距采样，避免在
    1200×1200×61 风险场上为每个搜索状态复制数千万个元素。均值始终由
    前缀和精确计算，采样策略只影响启发式中的中位数估值。
    """

    MEDIAN_MAX_SAMPLES = 200_000

    def __init__(self, risk_field: np.ndarray) -> None:
        """保存只读风险场，并初始化高度范围及包围盒缓存。"""
        if risk_field.ndim != 3:
            raise ValueError("风险场必须是三维 [i,j,h_idx] 数组。")
        self._risk_field = risk_field
        self._shape = risk_field.shape
        self._prefix_by_height: dict[
            tuple[int, int], tuple[np.ndarray, np.ndarray]
        ] = {}
        self._stats_cache: dict[BoxKey, tuple[float, float]] = {}
        self.median_query_count = 0

    @property
    def median_method(self) -> str:
        """返回本估值器采用的中位数计算口径，供冒烟日志记录。"""
        return "小盒精确 nanmedian；大盒三维等距采样；按包围盒缓存"

    def stats(
        self,
        current_index: Index3D,
        goal_index: Index3D,
    ) -> tuple[float, float]:
        """返回当前节点与目标节点包围盒内有限风险的均值和中位数。"""
        i0, i1 = sorted((current_index[0], goal_index[0]))
        j0, j1 = sorted((current_index[1], goal_index[1]))
        h0, h1 = sorted((current_index[2], goal_index[2]))
        if any(
            low < 0 or high >= size
            for low, high, size in (
                (i0, i1, self._shape[0]),
                (j0, j1, self._shape[1]),
                (h0, h1, self._shape[2]),
            )
        ):
            raise ValueError("风险包围盒索引超出数组范围。")

        key: BoxKey = (i0, i1, j0, j1, h0, h1)
        cached = self._stats_cache.get(key)
        if cached is not None:
            return cached

        sum_prefix, count_prefix = self._summed_area_for_heights(h0, h1)
        i_end = i1 + 1
        j_end = j1 + 1
        risk_sum = (
            sum_prefix[i_end, j_end]
            - sum_prefix[i0, j_end]
            - sum_prefix[i_end, j0]
            + sum_prefix[i0, j0]
        )
        finite_count = int(
            count_prefix[i_end, j_end]
            - count_prefix[i0, j_end]
            - count_prefix[i_end, j0]
            + count_prefix[i0, j0]
        )
        if finite_count == 0:
            raise ValueError("当前节点到目标的风险包围盒内没有有限风险值。")

        risk_box = self._risk_field[i0:i_end, j0:j_end, h0 : h1 + 1]
        risk_median = self._median(risk_box)
        result = (float(risk_sum) / finite_count, risk_median)
        self._stats_cache[key] = result
        self.median_query_count += 1
        return result

    @classmethod
    def _median(cls, risk_box: np.ndarray) -> float:
        """计算包围盒中位数；大盒按三维等距网格确定性降采样。"""
        sample_count = int(np.prod(risk_box.shape, dtype=np.int64))
        if sample_count <= cls.MEDIAN_MAX_SAMPLES:
            return float(np.nanmedian(risk_box))
        stride = max(
            1,
            int(
                math.ceil(
                    (sample_count / float(cls.MEDIAN_MAX_SAMPLES)) ** (1.0 / 3.0)
                )
            ),
        )
        sampled = risk_box[::stride, ::stride, ::stride]
        return float(np.nanmedian(sampled))

    def _summed_area_for_heights(
        self,
        h0: int,
        h1: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """按需为高度闭区间构建 XY 风险和/有限计数前缀表。"""
        height_key = (h0, h1)
        cached = self._prefix_by_height.get(height_key)
        if cached is not None:
            return cached

        risk_sum = np.zeros(self._shape[:2], dtype=np.float64)
        finite_count = np.zeros(self._shape[:2], dtype=np.int64)
        for h_idx in range(h0, h1 + 1):
            layer = self._risk_field[:, :, h_idx]
            finite = np.isfinite(layer)
            np.add(risk_sum, layer, out=risk_sum, where=finite)
            finite_count += finite

        sum_prefix = np.zeros(
            (self._shape[0] + 1, self._shape[1] + 1), dtype=np.float64
        )
        count_prefix = np.zeros_like(sum_prefix, dtype=np.int64)
        sum_prefix[1:, 1:] = np.cumsum(
            np.cumsum(risk_sum, axis=0, dtype=np.float64),
            axis=1,
            dtype=np.float64,
        )
        count_prefix[1:, 1:] = np.cumsum(
            np.cumsum(finite_count, axis=0, dtype=np.int64),
            axis=1,
            dtype=np.int64,
        )
        self._prefix_by_height[height_key] = (sum_prefix, count_prefix)
        return sum_prefix, count_prefix


@dataclass(slots=True)
class _SearchRecord:
    """保存一个位置与进入方向状态的最优累计代价和父状态。"""

    g_score: float
    parent: SearchState | None


class RCAStarPlanner(PlannerBase):
    """采用动态包围盒风险启发式的 RC-A* 规划器。"""

    name = "rc_astar"

    def plan(self, req: PlanRequest) -> PathResult:
        """在三维 26 邻域中按距离/风险加权代价搜索路径。"""
        started_at = perf_counter()
        scene = req.scene_data
        config: Mapping[str, Any] = scene.config
        risk_field = scene.R
        building_mask = scene.building_mask

        if req.time_budget_s is not None and (
            not math.isfinite(req.time_budget_s) or req.time_budget_s < 0
        ):
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="invalid_time_budget",
            )
        if risk_field.ndim != 3 or risk_field.shape != building_mask.shape:
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="scene_array_shape_mismatch",
            )
        try:
            parameters = RCParameters.from_config(config, scene.r_norm)
        except (KeyError, TypeError, ValueError):
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="invalid_cost_parameters",
            )

        if not is_search_node(req.start, config):
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="start_not_search_node",
            )
        if not is_search_node(req.goal, config):
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="goal_not_search_node",
            )

        start_index = world_to_index(req.start, config)
        goal_index = world_to_index(req.goal, config)
        start = index_to_world(start_index, config)
        goal = index_to_world(goal_index, config)
        if node_in_collision(building_mask, start, config):
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="start_in_obstacle",
            )
        if node_in_collision(building_mask, goal, config):
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="goal_in_obstacle",
            )
        if start_index == goal_index:
            return self._successful_result(req, (start,), started_at, 0)

        estimator = BoundingBoxRiskEstimator(risk_field)
        heuristic_cache: dict[Index3D, float] = {}

        def heuristic_at(point: Point3D, index: Index3D) -> float:
            """缓存给定空间位置的动态包围盒启发值。"""
            cached = heuristic_cache.get(index)
            if cached is not None:
                return cached
            r_avg, r_median = estimator.stats(index, goal_index)
            value = rc_heuristic(
                point,
                goal,
                min(r_avg, r_median),
                parameters,
            )
            heuristic_cache[index] = value
            return value

        start_state: SearchState = (start_index, None)
        records: dict[SearchState, _SearchRecord] = {
            start_state: _SearchRecord(g_score=0.0, parent=None)
        }
        closed: set[SearchState] = set()
        tie_breaker = count()
        open_list: list[OpenEntry] = [
            (heuristic_at(start, start_index), next(tie_breaker), start_state, 0.0)
        ]
        expansions = 0
        node_collision_cache: dict[Index3D, bool] = {
            start_index: False,
            goal_index: False,
        }
        edge_collision_cache: dict[tuple[Index3D, Index3D], bool] = {}
        neighbor_cache: dict[Index3D, tuple[tuple[Point3D, Index3D], ...]] = {}

        while open_list:
            if self._timed_out(started_at, req.time_budget_s):
                return self._result(
                    req,
                    "timeout",
                    started_at,
                    expansions=expansions,
                    failure_reason="timeout",
                )

            _, _, current_state, queued_g = heappop(open_list)
            current_record = records[current_state]
            if queued_g != current_record.g_score or current_state in closed:
                continue
            closed.add(current_state)

            current_index, incoming_direction = current_state
            current = index_to_world(current_index, config)
            if current_index == goal_index:
                states = self._reconstruct(current_state, records)
                path = tuple(index_to_world(state[0], config) for state in states)
                return self._successful_result(req, path, started_at, expansions)

            expansions += 1
            previous = self._previous_world(
                current_index,
                incoming_direction,
                config,
            )
            cached_neighbors = neighbor_cache.get(current_index)
            if cached_neighbors is None:
                cached_neighbors = tuple(
                    (neighbor, world_to_index(neighbor, config))
                    for neighbor in neighbors_26(current, config)
                )
                neighbor_cache[current_index] = cached_neighbors

            for neighbor, neighbor_index in self._turn_filtered_neighbors(
                current,
                previous,
                config,
                cached_neighbors,
            ):
                if self._timed_out(started_at, req.time_budget_s):
                    return self._result(
                        req,
                        "timeout",
                        started_at,
                        expansions=expansions,
                        failure_reason="timeout",
                    )

                node_collision = node_collision_cache.get(neighbor_index)
                if node_collision is None:
                    node_collision = node_in_collision(
                        building_mask,
                        neighbor,
                        config,
                    )
                    node_collision_cache[neighbor_index] = node_collision
                if node_collision:
                    continue

                edge_key = (
                    (current_index, neighbor_index)
                    if current_index <= neighbor_index
                    else (neighbor_index, current_index)
                )
                edge_collision = edge_collision_cache.get(edge_key)
                if edge_collision is None:
                    edge_collision = edge_in_collision(
                        building_mask,
                        current,
                        neighbor,
                        config,
                    )
                    edge_collision_cache[edge_key] = edge_collision
                if edge_collision:
                    continue

                outgoing_direction: Direction2D = (
                    neighbor_index[0] - current_index[0],
                    neighbor_index[1] - current_index[1],
                )
                next_direction: Direction2D | None = (
                    outgoing_direction if outgoing_direction != (0, 0) else None
                )
                next_state: SearchState = (neighbor_index, next_direction)
                previous_risk = float(risk_field[current_index])
                next_risk = float(risk_field[neighbor_index])
                if not math.isfinite(previous_risk) or not math.isfinite(next_risk):
                    continue
                edge_distance = math.dist(current, neighbor)
                tentative_g = current_record.g_score + rc_edge_cost(
                    previous_risk,
                    next_risk,
                    edge_distance,
                    parameters,
                )
                previous_record = records.get(next_state)
                if previous_record is not None and tentative_g >= previous_record.g_score:
                    continue

                records[next_state] = _SearchRecord(
                    g_score=tentative_g,
                    parent=current_state,
                )
                closed.discard(next_state)
                next_h = heuristic_at(neighbor, neighbor_index)
                heappush(
                    open_list,
                    (
                        tentative_g + next_h,
                        next(tie_breaker),
                        next_state,
                        tentative_g,
                    ),
                )

        return self._result(
            req,
            "no_path",
            started_at,
            expansions=expansions,
            failure_reason="open_empty",
        )

    @staticmethod
    def _turn_filtered_neighbors(
        current: Point3D,
        previous: Point3D | None,
        config: Mapping[str, Any],
        candidates: Sequence[tuple[Point3D, Index3D]] | None = None,
    ) -> tuple[tuple[Point3D, Index3D], ...]:
        """保留通过公共水平转角检查的 26 邻域候选节点。"""
        candidate_nodes = (
            tuple((point, world_to_index(point, config)) for point in neighbors_26(current, config))
            if candidates is None
            else candidates
        )
        return tuple(
            (point, index)
            for point, index in candidate_nodes
            if turn_is_allowed(previous, current, point, config)
        )

    @staticmethod
    def _previous_world(
        current_index: Index3D,
        incoming_direction: Direction2D | None,
        config: Mapping[str, Any],
    ) -> Point3D | None:
        """根据进入时的水平航向还原上一节点供公共转角函数使用。"""
        if incoming_direction is None:
            return None
        previous_index: Index3D = (
            current_index[0] - incoming_direction[0],
            current_index[1] - incoming_direction[1],
            current_index[2],
        )
        return index_to_world(previous_index, config)

    @staticmethod
    def _reconstruct(
        goal_state: SearchState,
        records: Mapping[SearchState, _SearchRecord],
    ) -> tuple[SearchState, ...]:
        """沿父状态回溯起点至终点。"""
        reverse_states: list[SearchState] = []
        current_state: SearchState | None = goal_state
        while current_state is not None:
            reverse_states.append(current_state)
            current_state = records[current_state].parent
        reverse_states.reverse()
        return tuple(reverse_states)

    @staticmethod
    def _timed_out(started_at: float, time_budget_s: float | None) -> bool:
        """判断调用方提供的秒制预算是否耗尽。"""
        return time_budget_s is not None and perf_counter() - started_at >= time_budget_s

    def _successful_result(
        self,
        req: PlanRequest,
        path: tuple[Point3D, ...],
        started_at: float,
        expansions: int,
    ) -> PathResult:
        """使用公共评估器填充长度、路径风险和综合代价。"""
        try:
            metrics = evaluate_path(
                path,
                req.scene_data.R,
                req.scene_data.config,
                r_norm=req.scene_data.r_norm,
            )
        except ValueError:
            return self._result(
                req,
                "invalid",
                started_at,
                expansions=expansions,
                failure_reason="invalid_risk_path",
            )
        return self._result(
            req,
            "success",
            started_at,
            waypoints=path,
            length_m=metrics["length_m"],
            risk_expected=metrics["risk_expected"],
            composite_cost=metrics["composite_cost"],
            expansions=expansions,
        )

    def _result(
        self,
        req: PlanRequest,
        status: PlanStatus,
        started_at: float,
        *,
        waypoints: tuple[Point3D, ...] = (),
        length_m: float = math.nan,
        risk_expected: float = math.nan,
        composite_cost: float = math.nan,
        expansions: int = 0,
        failure_reason: str | None = None,
    ) -> PathResult:
        """组装公共规划结果；失败时未计算的指标保留为 NaN。"""
        return PathResult(
            status=status,
            algorithm=self.name,
            scene=req.scene_data.scene_name,
            mission=req.mission,
            seed=req.seed,
            waypoints=waypoints,
            path_points=len(waypoints),
            length_m=length_m,
            risk_expected=risk_expected,
            composite_cost=composite_cost,
            runtime_s=perf_counter() - started_at,
            iterations_or_expansions=expansions,
            samples=None,
            failure_reason=failure_reason,
            config_hash=req.scene_data.config_hash,
        )


PLANNERS[RCAStarPlanner.name] = RCAStarPlanner
