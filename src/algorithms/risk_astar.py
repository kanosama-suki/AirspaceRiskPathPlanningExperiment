"""按纯风险积分目标实现 RiskA* 和论文 Algorithm 2 后优化。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from heapq import heappop, heappush
from itertools import count
from time import perf_counter
from typing import Any, TypeAlias
import math

import numpy as np

from src.core.collision import edge_in_collision, node_in_collision
from src.core.coords import Index3D, Point3D, index_to_world, world_to_continuous_index, world_to_index
from src.core.grid import is_search_node, neighbors_26, turn_is_allowed
from src.core.metrics import path_length
from src.core.types import PLANNERS, PathResult, PlanRequest, PlannerBase, PlanStatus


RISK_ASTAR_K = 0.75
RISK_ASTAR_EPS = float(np.finfo(np.float64).eps)

Direction2D: TypeAlias = tuple[int, int]
SearchState: TypeAlias = tuple[Index3D, Direction2D | None]
OpenEntry: TypeAlias = tuple[float, float, int, SearchState, float]


@dataclass(frozen=True, slots=True)
class RiskPathResult(PathResult):
    """保留公共结果字段，并附带 RiskA* 搜索与后优化记录。"""

    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class _SearchRecord:
    """搜索状态当前最优的风险积分及其父状态。"""

    g_score: float
    parent: SearchState | None


class _OptimizationTimeout(Exception):
    """LOS 后优化期间耗尽调用方的时间预算。"""


def risk_edge_cost(r_prev: float, r_next: float, distance: float) -> float:
    """按梯形积分计算一条边的风险代价；风险无量纲，距离为 m。"""
    if distance < 0:
        raise ValueError("边长不能为负数。")
    return ((float(r_prev) + float(r_next)) / 2.0) * float(distance)


def risk_heuristic(
    r_node: float,
    r_goal: float,
    distance: float,
    distance_min: float,
    risk_min: float,
) -> float:
    """按 Primatesta 2019 式 (11) 估计剩余风险积分；距离单位为 m。"""
    if distance < 0 or distance_min <= 0 or risk_min <= 0:
        raise ValueError("距离必须非负，最小步长和最小风险必须为正数。")
    return (
        ((float(r_node) + float(r_goal)) / 2.0) * float(distance_min)
        + (float(distance) - float(distance_min)) * float(risk_min)
    )


def _make_open_entry(
    f_score: float,
    node_risk: float,
    sequence: int,
    state: SearchState,
    g_score: float,
) -> OpenEntry:
    """构造按 f 优先、同 f 时按节点风险优先的开放列表项。"""
    return (float(f_score), float(node_risk), sequence, state, float(g_score))


def _risk_cost_at_index(
    risk_field: np.ndarray,
    building_mask: np.ndarray,
    index: Index3D,
    r_norm: float,
) -> float:
    """把一个风险体素映射到 `[eps, 1]`，建筑与 NaN 格代价为 1。"""
    value = float(risk_field[index])
    if bool(building_mask[index]) or not math.isfinite(value):
        return 1.0
    return float(np.clip(value / r_norm, RISK_ASTAR_EPS, 1.0))


def _build_risk_cost_field(
    risk_field: np.ndarray,
    building_mask: np.ndarray,
    r_norm: float,
) -> np.ndarray:
    """预构造只读风险代价场，避免扩展邻居时重复除法和 NaN 判断。"""
    risk_cost = np.ones(risk_field.shape, dtype=np.float64)
    open_cells = np.isfinite(risk_field) & ~building_mask
    risk_cost[open_cells] = np.clip(
        risk_field[open_cells] / r_norm,
        RISK_ASTAR_EPS,
        1.0,
    )
    risk_cost.setflags(write=False)
    return risk_cost


def _risk_cost_at_world(
    risk_field: np.ndarray,
    building_mask: np.ndarray,
    point: Sequence[float],
    config: Mapping[str, Any],
    r_norm: float,
) -> float | None:
    """用最近的风险体素读取连续 LOS 点；越界返回 None。"""
    continuous_index = world_to_continuous_index(point, config)
    index: Index3D = (
        int(round(continuous_index[0])),
        int(round(continuous_index[1])),
        int(round(continuous_index[2])),
    )
    if any(value < 0 or value >= size for value, size in zip(index, risk_field.shape)):
        return None
    if node_in_collision(building_mask, index_to_world(index, config), config):
        return 1.0
    return _risk_cost_at_index(risk_field, building_mask, index, r_norm)


def _path_risk_integral(
    path: Sequence[Point3D],
    risk_field: np.ndarray,
    building_mask: np.ndarray,
    config: Mapping[str, Any],
    r_norm: float,
) -> float:
    """累计离散路径各边的纯风险梯形积分。"""
    total = 0.0
    for previous, following in zip(path, path[1:]):
        previous_index = world_to_index(previous, config)
        following_index = world_to_index(following, config)
        total += risk_edge_cost(
            _risk_cost_at_index(risk_field, building_mask, previous_index, r_norm),
            _risk_cost_at_index(risk_field, building_mask, following_index, r_norm),
            math.dist(previous, following),
        )
    return total


def _line_of_sight_risk_cost(
    start: Point3D,
    end: Point3D,
    risk_field: np.ndarray,
    building_mask: np.ndarray,
    config: Mapping[str, Any],
    r_norm: float,
    deadline: float | None,
) -> float | None:
    """以风险栅格分辨率线性采样 LOS；碰撞或越界时返回 None。"""
    if edge_in_collision(building_mask, start, end, config):
        return None

    start_array = np.asarray(start, dtype=np.float64)
    end_array = np.asarray(end, dtype=np.float64)
    distance = float(np.linalg.norm(end_array - start_array))
    if distance == 0.0:
        return 0.0

    resolution = float(config["coords"]["resolution"])
    sample_count = max(1, math.ceil(distance / resolution))
    previous_risk = _risk_cost_at_world(
        risk_field, building_mask, start, config, r_norm
    )
    if previous_risk is None:
        return None

    total = 0.0
    segment_length = distance / sample_count
    for sample_number in range(1, sample_count + 1):
        if deadline is not None and perf_counter() >= deadline:
            raise _OptimizationTimeout
        fraction = sample_number / sample_count
        point = start_array + fraction * (end_array - start_array)
        current_risk = _risk_cost_at_world(
            risk_field, building_mask, point, config, r_norm
        )
        if current_risk is None:
            return None
        total += risk_edge_cost(previous_risk, current_risk, segment_length)
        previous_risk = current_risk
    return total


def _shortcut_preserves_turns(
    path: Sequence[Point3D],
    start_index: int,
    end_index: int,
    config: Mapping[str, Any],
) -> bool:
    """检查 LOS 替换后与保留航段相接处仍满足公共转角约束。"""
    if start_index > 0 and not turn_is_allowed(
        path[start_index - 1],
        path[start_index],
        path[end_index],
        config,
    ):
        return False
    if end_index + 1 < len(path) and not turn_is_allowed(
        path[start_index],
        path[end_index],
        path[end_index + 1],
        config,
    ):
        return False
    return True


def post_optimize_path(
    path: Sequence[Point3D],
    risk_field: np.ndarray,
    building_mask: np.ndarray,
    config: Mapping[str, Any],
    r_norm: float,
    deadline: float | None = None,
) -> tuple[Point3D, ...]:
    """按论文 Algorithm 2 尝试用不更高代价的有效 LOS 替换路径段。"""
    optimized = list(path)
    if len(optimized) < 3:
        return tuple(optimized)

    # 对每个 j 逐步尝试更远的 k；替换成功后从同一 j 重新检查新路径。
    j = 0
    while j < len(optimized) - 2:
        if deadline is not None and perf_counter() >= deadline:
            raise _OptimizationTimeout
        replaced = False
        for k in range(j + 2, len(optimized)):
            if deadline is not None and perf_counter() >= deadline:
                raise _OptimizationTimeout
            direct_cost = _line_of_sight_risk_cost(
                optimized[j],
                optimized[k],
                risk_field,
                building_mask,
                config,
                r_norm,
                deadline,
            )
            if direct_cost is None or not _shortcut_preserves_turns(
                optimized, j, k, config
            ):
                continue

            original_cost = _path_risk_integral(
                optimized[j : k + 1], risk_field, building_mask, config, r_norm
            )
            # LOS 采用 1 m 采样，而搜索/metadata 采用节点端点梯形积分。
            # 两种口径都必须不增加，才能保证“优化”不会抬高最终报告的风险。
            discrete_direct_cost = _path_risk_integral(
                (optimized[j], optimized[k]),
                risk_field,
                building_mask,
                config,
                r_norm,
            )
            if (
                direct_cost <= original_cost
                and discrete_direct_cost <= original_cost
            ):
                optimized = optimized[: j + 1] + optimized[k:]
                replaced = True
                break
        if not replaced:
            j += 1
    return tuple(optimized)


class RiskAStarPlanner(PlannerBase):
    """采用 `g + k*h` 排序、只累计归一化风险积分的 RiskA*。"""

    name = "risk_astar"

    def plan(self, req: PlanRequest) -> PathResult:
        """运行 3D 26 邻域 RiskA* 并执行纯风险 LOS 后优化。"""
        started_at = perf_counter()
        scene = req.scene_data
        config: Mapping[str, Any] = scene.config
        risk_field = scene.R
        building_mask = scene.building_mask
        r_norm = float(scene.r_norm)

        if req.time_budget_s is not None:
            if not math.isfinite(req.time_budget_s) or req.time_budget_s < 0:
                return self._result(
                    req,
                    "invalid",
                    started_at,
                    failure_reason="invalid_time_budget",
                )
        if not math.isfinite(r_norm) or r_norm <= 0:
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="invalid_r_norm",
            )
        if risk_field.shape != building_mask.shape or risk_field.ndim != 3:
            return self._result(
                req,
                "invalid",
                started_at,
                failure_reason="scene_array_shape_mismatch",
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
                req, "invalid", started_at, failure_reason="start_in_obstacle"
            )
        if node_in_collision(building_mask, goal, config):
            return self._result(
                req, "invalid", started_at, failure_reason="goal_in_obstacle"
            )

        risk_min = self._minimum_risk_cost(risk_field, building_mask, r_norm)
        risk_cost_field = _build_risk_cost_field(
            risk_field, building_mask, r_norm
        )
        if start_index == goal_index:
            discrete_path = (start,)
            return self._successful_result(
                req,
                discrete_path,
                discrete_path,
                risk_min,
                started_at,
                expansions=0,
            )

        start_state: SearchState = (start_index, None)
        records: dict[SearchState, _SearchRecord] = {
            start_state: _SearchRecord(g_score=0.0, parent=None)
        }
        closed: set[SearchState] = set()
        tie_breaker = count()
        start_risk = float(risk_cost_field[start_index])
        goal_risk = float(risk_cost_field[goal_index])
        distance_min = float(config["table2"]["STEP"])
        start_h = risk_heuristic(
            start_risk,
            goal_risk,
            math.dist(start, goal),
            distance_min,
            risk_min,
        )
        open_list: list[OpenEntry] = [
            _make_open_entry(
                RISK_ASTAR_K * start_h,
                start_risk,
                next(tie_breaker),
                start_state,
                0.0,
            )
        ]
        expansions = 0
        node_collision_cache: dict[Index3D, bool] = {
            start_index: False,
            goal_index: False,
        }
        edge_collision_cache: dict[tuple[Index3D, Index3D], bool] = {}
        neighbors_cache: dict[Index3D, tuple[tuple[Point3D, Index3D], ...]] = {}
        turn_cache: dict[tuple[Direction2D | None, Direction2D], bool] = {}
        edge_length_cache: dict[tuple[int, int, int], float] = {}
        heuristic_cache: dict[Index3D, float] = {start_index: start_h}

        while open_list:
            if self._timed_out(started_at, req.time_budget_s):
                return self._result(
                    req,
                    "timeout",
                    started_at,
                    expansions=expansions,
                    risk_min=risk_min,
                    failure_reason="timeout",
                )

            _, _, _, current_state, queued_g = heappop(open_list)
            current_record = records[current_state]
            if queued_g != current_record.g_score or current_state in closed:
                continue
            closed.add(current_state)

            current_index, incoming_direction = current_state
            current = index_to_world(current_index, config)
            if current_index == goal_index:
                search_states = self._reconstruct(current_state, records)
                discrete_path = tuple(
                    index_to_world(state[0], config) for state in search_states
                )
                deadline = (
                    None
                    if req.time_budget_s is None
                    else started_at + req.time_budget_s
                )
                try:
                    optimized_path = post_optimize_path(
                        discrete_path,
                        risk_field,
                        building_mask,
                        config,
                        r_norm,
                        deadline,
                    )
                except _OptimizationTimeout:
                    return self._result(
                        req,
                        "timeout",
                        started_at,
                        expansions=expansions,
                        risk_min=risk_min,
                        failure_reason="timeout",
                    )
                return self._successful_result(
                    req,
                    discrete_path,
                    optimized_path,
                    risk_min,
                    started_at,
                    expansions,
                )

            expansions += 1
            previous = self._previous_world(
                current_index, incoming_direction, config
            )
            current_risk = float(risk_cost_field[current_index])
            cached_neighbors = neighbors_cache.get(current_index)
            if cached_neighbors is None:
                cached_neighbors = tuple(
                    (neighbor, world_to_index(neighbor, config))
                    for neighbor in neighbors_26(current, config)
                )
                neighbors_cache[current_index] = cached_neighbors
            for neighbor, neighbor_index in cached_neighbors:
                if self._timed_out(started_at, req.time_budget_s):
                    return self._result(
                        req,
                        "timeout",
                        started_at,
                        expansions=expansions,
                        risk_min=risk_min,
                        failure_reason="timeout",
                    )
                neighbor_collision = node_collision_cache.get(neighbor_index)
                if neighbor_collision is None:
                    neighbor_collision = node_in_collision(
                        building_mask, neighbor, config
                    )
                    node_collision_cache[neighbor_index] = neighbor_collision
                if neighbor_collision:
                    continue
                outgoing_direction: Direction2D = (
                    neighbor_index[0] - current_index[0],
                    neighbor_index[1] - current_index[1],
                )
                turn_key = (incoming_direction, outgoing_direction)
                turn_allowed = turn_cache.get(turn_key)
                if turn_allowed is None:
                    turn_allowed = turn_is_allowed(
                        previous, current, neighbor, config
                    )
                    turn_cache[turn_key] = turn_allowed
                if not turn_allowed:
                    continue
                edge_key = (
                    (current_index, neighbor_index)
                    if current_index <= neighbor_index
                    else (neighbor_index, current_index)
                )
                edge_collision = edge_collision_cache.get(edge_key)
                if edge_collision is None:
                    edge_collision = edge_in_collision(
                        building_mask, current, neighbor, config
                    )
                    edge_collision_cache[edge_key] = edge_collision
                if edge_collision:
                    continue

                # 公共转角函数只检查水平航向；垂直分量不改变未来的转角合法性。
                direction: Direction2D | None = outgoing_direction
                if outgoing_direction == (0, 0):
                    direction = None
                next_state: SearchState = (neighbor_index, direction)
                neighbor_risk = float(risk_cost_field[neighbor_index])
                delta = (
                    neighbor_index[0] - current_index[0],
                    neighbor_index[1] - current_index[1],
                    neighbor_index[2] - current_index[2],
                )
                edge_length = edge_length_cache.get(delta)
                if edge_length is None:
                    edge_length = math.dist(current, neighbor)
                    edge_length_cache[delta] = edge_length
                tentative_g = current_record.g_score + risk_edge_cost(
                    current_risk,
                    neighbor_risk,
                    edge_length,
                )
                previous_record = records.get(next_state)
                if previous_record is not None and tentative_g >= previous_record.g_score:
                    continue

                records[next_state] = _SearchRecord(
                    g_score=tentative_g,
                    parent=current_state,
                )
                closed.discard(next_state)
                heuristic = heuristic_cache.get(neighbor_index)
                if heuristic is None:
                    heuristic = risk_heuristic(
                        neighbor_risk,
                        goal_risk,
                        math.dist(neighbor, goal),
                        distance_min,
                        risk_min,
                    )
                    heuristic_cache[neighbor_index] = heuristic
                heappush(
                    open_list,
                    _make_open_entry(
                        tentative_g + RISK_ASTAR_K * heuristic,
                        neighbor_risk,
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
            risk_min=risk_min,
            failure_reason="open_empty",
        )

    @staticmethod
    def _minimum_risk_cost(
        risk_field: np.ndarray,
        building_mask: np.ndarray,
        r_norm: float,
    ) -> float:
        """分行扫描全图有限空域并应用相同 `[eps,1]` 裁剪。"""
        minimum_value = math.inf
        for row_index in range(risk_field.shape[0]):
            row = risk_field[row_index]
            finite_values = row[np.isfinite(row) & ~building_mask[row_index]]
            if finite_values.size:
                minimum_value = min(minimum_value, float(finite_values.min()))
        if not math.isfinite(minimum_value):
            raise ValueError("风险场没有有限空域值，无法计算 r_cmin。")
        return float(np.clip(minimum_value / r_norm, RISK_ASTAR_EPS, 1.0))

    @staticmethod
    def _previous_world(
        current_index: Index3D,
        incoming_direction: Direction2D | None,
        config: Mapping[str, Any],
    ) -> Point3D | None:
        """由当前节点和进入方向恢复前一节点坐标。"""
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
        original_path: tuple[Point3D, ...],
        optimized_path: tuple[Point3D, ...],
        risk_min: float,
        started_at: float,
        expansions: int,
    ) -> RiskPathResult:
        """组装带有 LOS 前后路径与纯风险积分的成功结果。"""
        scene = req.scene_data
        original_risk = _path_risk_integral(
            original_path,
            scene.R,
            scene.building_mask,
            scene.config,
            float(scene.r_norm),
        )
        optimized_risk = _path_risk_integral(
            optimized_path,
            scene.R,
            scene.building_mask,
            scene.config,
            float(scene.r_norm),
        )
        return self._result(
            req,
            "success",
            started_at,
            waypoints=optimized_path,
            length_m=path_length(optimized_path),
            expansions=expansions,
            risk_min=risk_min,
            metadata={
                "k": RISK_ASTAR_K,
                "r_cmin": risk_min,
                "eps": RISK_ASTAR_EPS,
                "pre_optimization_path": original_path,
                "pre_optimization_path_points": len(original_path),
                "pre_optimization_length_m": path_length(original_path),
                "pre_optimization_risk_integral": original_risk,
                "post_optimization_path": optimized_path,
                "post_optimization_path_points": len(optimized_path),
                "post_optimization_length_m": path_length(optimized_path),
                "post_optimization_risk_integral": optimized_risk,
            },
        )

    def _result(
        self,
        req: PlanRequest,
        status: PlanStatus,
        started_at: float,
        *,
        waypoints: tuple[Point3D, ...] = (),
        length_m: float = math.nan,
        expansions: int = 0,
        risk_min: float = math.nan,
        failure_reason: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> RiskPathResult:
        """生成公共字段并附加 RiskA* 算法内信息。"""
        detail = dict(metadata) if metadata is not None else {}
        detail.setdefault("k", RISK_ASTAR_K)
        detail.setdefault("r_cmin", risk_min)
        detail.setdefault("eps", RISK_ASTAR_EPS)
        return RiskPathResult(
            status=status,
            algorithm=self.name,
            scene=req.scene_data.scene_name,
            mission=req.mission,
            seed=req.seed,
            waypoints=waypoints,
            path_points=len(waypoints),
            length_m=length_m,
            risk_expected=math.nan,
            composite_cost=math.nan,
            runtime_s=perf_counter() - started_at,
            iterations_or_expansions=expansions,
            samples=None,
            failure_reason=failure_reason,
            config_hash=req.scene_data.config_hash,
            metadata=detail,
        )


PLANNERS[RiskAStarPlanner.name] = RiskAStarPlanner
