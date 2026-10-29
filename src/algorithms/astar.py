"""标准 A* 规划器。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from time import perf_counter
from typing import Any, TypeAlias
import math

from src.core.collision import edge_in_collision, node_in_collision
from src.core.coords import Index3D, Point3D, index_to_world, world_to_index
from src.core.grid import is_search_node, neighbors_26, turn_is_allowed
from src.core.types import PLANNERS, PathResult, PlanRequest, PlannerBase, PlanStatus


Direction3D: TypeAlias = tuple[int, int, int]
SearchState: TypeAlias = tuple[Index3D, Direction3D | None]
OpenEntry: TypeAlias = tuple[float, int, SearchState, float]


@dataclass(slots=True)
class _SearchRecord:
    """在搜索过程中保存最优代价和父状态。"""

    g_score: float
    parent: SearchState | None


class AStarPlanner(PlannerBase):
    """采用 26 邻域、转角约束和建筑碰撞检查的几何距离 A*。"""

    name = "astar"

    def plan(self, req: PlanRequest) -> PathResult:
        """搜索起点到终点的最短几何路径，不在规划器内计算风险指标。"""
        started_at = perf_counter()
        config: Mapping[str, Any] = req.scene_data.config
        mask = req.scene_data.building_mask

        if req.time_budget_s is not None:
            if not math.isfinite(req.time_budget_s) or req.time_budget_s < 0:
                return self._result(req, "invalid", started_at, failure_reason="invalid_time_budget")

        if not is_search_node(req.start, config):
            return self._result(req, "invalid", started_at, failure_reason="start_not_search_node")
        if not is_search_node(req.goal, config):
            return self._result(req, "invalid", started_at, failure_reason="goal_not_search_node")

        start_index = world_to_index(req.start, config)
        goal_index = world_to_index(req.goal, config)
        start_world = index_to_world(start_index, config)
        goal_world = index_to_world(goal_index, config)

        if node_in_collision(mask, start_world, config):
            return self._result(req, "invalid", started_at, failure_reason="start_in_obstacle")
        if node_in_collision(mask, goal_world, config):
            return self._result(req, "invalid", started_at, failure_reason="goal_in_obstacle")
        if start_index == goal_index:
            return self._result(
                req,
                "success",
                started_at,
                waypoints=(start_world,),
                length_m=0.0,
            )

        start_state: SearchState = (start_index, None)
        records: dict[SearchState, _SearchRecord] = {
            start_state: _SearchRecord(g_score=0.0, parent=None)
        }
        closed: set[SearchState] = set()
        tie_breaker = count()
        open_list: list[OpenEntry] = [
            (self._heuristic(start_world, goal_world), next(tie_breaker), start_state, 0.0)
        ]
        expansions = 0

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
            current_world = index_to_world(current_index, config)
            if current_index == goal_index:
                states = self._reconstruct(current_state, records)
                waypoints = tuple(index_to_world(state[0], config) for state in states)
                return self._result(
                    req,
                    "success",
                    started_at,
                    waypoints=waypoints,
                    length_m=current_record.g_score,
                    expansions=expansions,
                )

            expansions += 1
            previous_world = self._previous_world(
                current_index,
                incoming_direction,
                config,
            )

            for neighbor_world in neighbors_26(current_world, config):
                if self._timed_out(started_at, req.time_budget_s):
                    return self._result(
                        req,
                        "timeout",
                        started_at,
                        expansions=expansions,
                        failure_reason="timeout",
                    )

                neighbor_index = world_to_index(neighbor_world, config)
                if node_in_collision(mask, neighbor_world, config):
                    continue
                if not turn_is_allowed(previous_world, current_world, neighbor_world, config):
                    continue
                if edge_in_collision(mask, current_world, neighbor_world, config):
                    continue

                direction: Direction3D = (
                    neighbor_index[0] - current_index[0],
                    neighbor_index[1] - current_index[1],
                    neighbor_index[2] - current_index[2],
                )
                next_state: SearchState = (neighbor_index, direction)
                edge_length = math.dist(current_world, neighbor_world)
                tentative_g = current_record.g_score + edge_length
                previous_record = records.get(next_state)
                if previous_record is not None and tentative_g >= previous_record.g_score:
                    continue

                # 方向作为搜索状态的一部分，因为同一位置从不同航向到达时，
                # 后续可用邻居会因转角上限而不同；同一状态的更小 g 会覆盖旧父状态。
                records[next_state] = _SearchRecord(
                    g_score=tentative_g,
                    parent=current_state,
                )
                closed.discard(next_state)
                heuristic = self._heuristic(neighbor_world, goal_world)
                heappush(
                    open_list,
                    (
                        tentative_g + heuristic,
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
    def _heuristic(current: Point3D, goal: Point3D) -> float:
        """返回到终点的欧氏距离，单位 m；不包含风险项。"""
        return math.dist(current, goal)

    @staticmethod
    def _previous_world(
        current_index: Index3D,
        incoming_direction: Direction3D | None,
        config: Mapping[str, Any],
    ) -> Point3D | None:
        """由当前节点和进入方向恢复前一节点坐标。"""
        if incoming_direction is None:
            return None
        previous_index: Index3D = (
            current_index[0] - incoming_direction[0],
            current_index[1] - incoming_direction[1],
            current_index[2] - incoming_direction[2],
        )
        return index_to_world(previous_index, config)

    @staticmethod
    def _reconstruct(
        goal_state: SearchState,
        records: dict[SearchState, _SearchRecord],
    ) -> tuple[SearchState, ...]:
        """沿父状态回溯起点到目标的搜索状态序列。"""
        reverse_states: list[SearchState] = []
        current_state: SearchState | None = goal_state
        while current_state is not None:
            reverse_states.append(current_state)
            current_state = records[current_state].parent
        reverse_states.reverse()
        return tuple(reverse_states)

    @staticmethod
    def _timed_out(started_at: float, time_budget_s: float | None) -> bool:
        """判断可选时间预算是否耗尽。"""
        return time_budget_s is not None and perf_counter() - started_at >= time_budget_s

    def _result(
        self,
        req: PlanRequest,
        status: PlanStatus,
        started_at: float,
        *,
        waypoints: tuple[Point3D, ...] = (),
        length_m: float = math.nan,
        expansions: int = 0,
        failure_reason: str | None = None,
    ) -> PathResult:
        """组装公共结果；风险字段留待公共 evaluator 外置计算。"""
        # A* 只优化几何距离，因此未由外部 metrics 评估的风险字段使用 NaN，
        # 不用 0 冒充“已评估且风险为零”。
        return PathResult(
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
        )


PLANNERS[AStarPlanner.name] = AStarPlanner
