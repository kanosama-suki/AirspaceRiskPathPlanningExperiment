"""采用理论近邻半径和重连的三维 RRT* 规划器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import product
from time import perf_counter
from typing import Any
import math

import numpy as np

from src.core.collision import edge_in_collision, node_in_collision
from src.core.coords import Point3D, index_to_world, world_to_continuous_index, world_to_index
from src.core.grid import turn_is_allowed
from src.core.metrics import evaluate_path, path_length
from src.core.types import PLANNERS, PathResult, PlanRequest, PlannerBase, PlanStatus


@dataclass(frozen=True, slots=True)
class RRTStarResult(PathResult):
    """公共路径结果及 RRT* 搜索诊断信息。"""

    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class _TreeNode:
    """树中一个体素中心位置、父子关系和累计代价。"""

    point: Point3D
    parent: int | None
    cost: float
    children: set[int] = field(default_factory=set)


class _SpatialBuckets:
    """以最大近邻半径为桶宽的空间索引，支持动态插入和半径查询。"""

    def __init__(self, cell_size: float) -> None:
        if not math.isfinite(cell_size) or cell_size <= 0:
            raise ValueError("空间桶宽度必须是有限正数。")
        self.cell_size = float(cell_size)
        self._buckets: dict[tuple[int, int, int], list[int]] = {}
        self._coordinates = np.empty((16, 3), dtype=np.float64)
        self._count = 0

    def _key(self, point: Sequence[float]) -> tuple[int, int, int]:
        return tuple(math.floor(float(value) / self.cell_size) for value in point)  # type: ignore[return-value]

    def insert(self, index: int, point: Sequence[float]) -> None:
        """将树节点登记到对应空间桶。"""
        self._buckets.setdefault(self._key(point), []).append(index)
        if self._count == len(self._coordinates):
            expanded = np.empty((len(self._coordinates) * 2, 3), dtype=np.float64)
            expanded[: self._count] = self._coordinates
            self._coordinates = expanded
        self._coordinates[self._count] = point
        self._count += 1

    def within(
        self,
        target: Sequence[float],
        radius: float,
        nodes: Sequence[_TreeNode],
    ) -> list[int]:
        """只扫描覆盖查询半径的空间桶，再用欧氏距离精确筛选。"""
        center = self._key(target)
        shell = math.ceil(radius / self.cell_size)
        candidates: list[int] = []
        for offset in product(range(-shell, shell + 1), repeat=3):
            key = tuple(center[axis] + offset[axis] for axis in range(3))
            candidates.extend(self._buckets.get(key, ()))
        return [
            index
            for index in candidates
            if math.dist(nodes[index].point, target) <= radius
        ]

    def nearest(self, target: Sequence[float], nodes: Sequence[_TreeNode]) -> int:
        """用向量化精确距离扫描找到全局欧氏最近树节点。"""
        if not nodes:
            raise ValueError("空树没有最近节点。")
        if self._count != len(nodes):
            raise ValueError("空间索引与 RRT* 树节点数量不一致。")
        delta = self._coordinates[: self._count] - np.asarray(target, dtype=np.float64)
        squared_distances = np.einsum("ij,ij->i", delta, delta)
        return int(np.argmin(squared_distances))


def rrt_star_radius(n: int, gamma: float, eta: float) -> float:
    """计算三维 RRT* 理论半径 `min(gamma*(log(n)/n)^(1/3), eta)`。"""
    if n <= 1:
        return 0.0
    if not math.isfinite(gamma) or gamma < 0 or not math.isfinite(eta) or eta <= 0:
        raise ValueError("gamma 必须非负，eta 必须是有限正数。")
    return min(float(gamma) * (math.log(n) / n) ** (1.0 / 3.0), float(eta))


def theoretical_gamma(free_volume: float, dimension: int = 3) -> float:
    """按 Karaman & Frazzoli 2011 下界估算渐近最优半径系数。"""
    if not math.isfinite(free_volume) or free_volume <= 0:
        raise ValueError("自由空间体积必须是有限正数。")
    if dimension < 1:
        raise ValueError("空间维度必须为正数。")
    unit_ball_volume = math.pi ** (dimension / 2.0) / math.gamma(dimension / 2.0 + 1.0)
    gamma_threshold = 2.0 * (1.0 + 1.0 / dimension) ** (1.0 / dimension) * (
        free_volume / unit_ball_volume
    ) ** (1.0 / dimension)
    # Karaman-Frazzoli 条件要求严格大于阈值；向上取一个 binary64 间隔。
    return math.nextafter(gamma_threshold, math.inf)


class RRTStarPlanner(PlannerBase):
    """在三维体素中心上均匀采样并按公共综合代价执行 RRT*。"""

    name = "rrt_star"

    def __init__(self) -> None:
        self._rng = np.random.default_rng()
        self.best_length = math.inf

    def sample(self, req: PlanRequest) -> Point3D:
        """在配置指定的三维飞行空间体素中心上均匀采样。"""
        config = req.scene_data.config
        table = config["table2"]
        origin = config["coords"]["origin"]
        low_index = world_to_continuous_index(
            (float(origin[0]), float(origin[1]), req.scene_data.h_low), config
        )[2]
        high_index = world_to_continuous_index(
            (float(origin[0]), float(origin[1]), req.scene_data.h_high), config
        )[2]
        h_min = max(0, math.ceil(low_index))
        h_max = min(int(table["N_H"]) - 1, math.floor(high_index))
        if h_min > h_max:
            raise ValueError("配置高度范围内没有风险数据层。")
        while True:
            index = (
                int(self._rng.integers(0, int(table["N_I"]))),
                int(self._rng.integers(0, int(table["N_J"]))),
                int(self._rng.integers(h_min, h_max + 1)),
            )
            point = index_to_world(index, config)
            if not node_in_collision(req.scene_data.building_mask, point, config):
                return point

    @staticmethod
    def nearest(
        nodes: Sequence[_TreeNode],
        target: Sequence[float],
        spatial_index: _SpatialBuckets | None = None,
    ) -> int:
        """返回离采样点最近的树节点下标。"""
        if spatial_index is not None:
            return spatial_index.nearest(target, nodes)
        if not nodes:
            raise ValueError("空树没有最近节点。")
        return min(range(len(nodes)), key=lambda index: math.dist(nodes[index].point, target))

    @staticmethod
    def steer(
        nearest: Sequence[float],
        target: Sequence[float],
        max_distance: float,
        resolution: float = 1.0,
    ) -> Point3D:
        """沿采样方向前进并对齐到风险体素中心，保证离散距离不超步长。"""
        if max_distance <= 0 or resolution <= 0:
            raise ValueError("步长和数据分辨率必须大于零。")
        start = np.asarray(nearest, dtype=np.float64)
        end = np.asarray(target, dtype=np.float64)
        if start.shape != (3,) or end.shape != (3,):
            raise ValueError("RRT* 节点和采样点必须是三维坐标。")
        delta = end - start
        distance = float(np.linalg.norm(delta))
        if distance <= max_distance:
            return tuple(float(value) for value in end)  # type: ignore[return-value]

        step_units = math.floor(max_distance / resolution)
        if step_units < 1:
            return tuple(float(value) for value in start)  # type: ignore[return-value]
        offset_units = np.rint(delta / distance * step_units).astype(np.int64)
        max_units_squared = (max_distance / resolution) ** 2
        # 分辨率取整可能令斜向步长略超限；每次向内缩一个体素，直到合法。
        while float(np.dot(offset_units, offset_units)) > max_units_squared + 1e-12:
            axis = int(np.argmax(np.abs(offset_units)))
            offset_units[axis] -= int(np.sign(offset_units[axis]))
        result = start + offset_units.astype(np.float64) * resolution
        return tuple(float(value) for value in result)  # type: ignore[return-value]

    @staticmethod
    def near(
        nodes: Sequence[_TreeNode],
        target: Sequence[float],
        n: int,
        gamma: float,
        eta: float,
        spatial_index: _SpatialBuckets | None = None,
    ) -> list[int]:
        """按理论半径查找近邻集合。"""
        radius = rrt_star_radius(n, gamma, eta)
        if radius <= 0:
            return []
        if spatial_index is not None:
            return spatial_index.within(target, radius, nodes)
        return [index for index, node in enumerate(nodes) if math.dist(node.point, target) <= radius]

    def choose_parent(
        self,
        req: PlanRequest,
        new_point: Point3D,
        near_indices: Sequence[int],
        nodes: Sequence[_TreeNode],
        nearest_index: int,
        deadline: float | None = None,
    ) -> tuple[int, float] | None:
        """在近邻及可行的最近节点中选累计公共代价最低的父节点。"""
        candidates = set(near_indices)
        candidates.add(nearest_index)
        best: tuple[int, float] | None = None
        for parent_index in candidates:
            if deadline is not None and perf_counter() >= deadline:
                return None
            edge_cost = self._valid_edge_cost(req, nodes, parent_index, new_point, deadline)
            if edge_cost is None:
                continue
            candidate_cost = nodes[parent_index].cost + edge_cost
            if best is None or candidate_cost < best[1]:
                best = (parent_index, candidate_cost)
        return best

    def rewire(
        self,
        req: PlanRequest,
        new_index: int,
        near_indices: Sequence[int],
        nodes: list[_TreeNode],
        deadline: float | None = None,
    ) -> int:
        """尝试把近邻节点改接到新节点，并递归更新后代代价。"""
        rewired = 0
        for target_index in near_indices:
            if deadline is not None and perf_counter() >= deadline:
                break
            if target_index == new_index or nodes[target_index].parent is None:
                continue
            if self._is_ancestor(nodes, target_index, new_index):
                continue
            edge_cost = self._valid_edge_cost(
                req, nodes, new_index, nodes[target_index].point, deadline
            )
            if deadline is not None and perf_counter() >= deadline:
                break
            if edge_cost is None:
                continue
            proposed_cost = nodes[new_index].cost + edge_cost
            if proposed_cost >= nodes[target_index].cost:
                continue
            if not self._children_keep_turns(
                req,
                nodes,
                nodes[target_index].point,
                nodes[new_index].point,
                nodes[target_index].children,
            ):
                continue
            self._replace_parent(nodes, target_index, new_index, proposed_cost)
            rewired += 1
        return rewired

    def plan(self, req: PlanRequest) -> PathResult:
        """搜索并在预算结束时返回当前到达目标的最优树路径。"""
        started_at = perf_counter()
        self.best_length = math.inf
        scene = req.scene_data
        config = scene.config
        mask = scene.building_mask
        step = float(config["table2"]["STEP"])
        resolution = float(config["coords"]["resolution"])
        eta = step

        if req.time_budget_s is not None and (
            not math.isfinite(req.time_budget_s) or req.time_budget_s < 0
        ):
            return self._result(req, "invalid", started_at, failure_reason="invalid_time_budget")
        if req.iteration_budget is not None and req.iteration_budget < 0:
            return self._result(req, "invalid", started_at, failure_reason="invalid_iteration_budget")
        if req.time_budget_s is None and req.iteration_budget is None:
            return self._result(req, "invalid", started_at, failure_reason="missing_search_budget")

        try:
            start_index = world_to_index(req.start, config)
            goal_index = world_to_index(req.goal, config)
        except ValueError:
            return self._result(req, "invalid", started_at, failure_reason="endpoint_off_grid")

        start = index_to_world(start_index, config)
        goal = index_to_world(goal_index, config)
        if node_in_collision(mask, start, config):
            return self._result(req, "invalid", started_at, failure_reason="start_in_obstacle")
        if node_in_collision(mask, goal, config):
            return self._result(req, "invalid", started_at, failure_reason="goal_in_obstacle")
        if start == goal:
            self.best_length = 0.0
            try:
                metrics = evaluate_path((start,), scene.R, config, r_norm=scene.r_norm)
            except ValueError:
                return self._result(req, "invalid", started_at, failure_reason="invalid_start_risk")
            return self._result(
                req,
                "success",
                started_at,
                waypoints=(start,),
                length_m=metrics["length_m"],
                risk_expected=metrics["risk_expected"],
                composite=metrics["composite_cost"],
            )

        free_volume = self._free_volume(scene.building_mask, config, scene.h_low, scene.h_high)
        gamma = theoretical_gamma(free_volume)
        nodes = [_TreeNode(start, None, 0.0)]
        spatial = _SpatialBuckets(eta)
        spatial.insert(0, start)
        goal_index_in_tree: int | None = None
        first_feasible_time: float | None = None
        sample_count = 0
        iteration_count = 0
        rewire_count = 0
        timed_out = False
        self._rng = np.random.default_rng(req.seed)
        max_iterations = req.iteration_budget if req.iteration_budget is not None else math.inf
        deadline = None if req.time_budget_s is None else started_at + req.time_budget_s

        while iteration_count < max_iterations:
            if self._timed_out(started_at, req.time_budget_s):
                timed_out = True
                break
            sample = self.sample(req)
            sample_count += 1
            iteration_count += 1
            nearest_index = self.nearest(nodes, sample, spatial)
            new_point = self.steer(nodes[nearest_index].point, sample, step, resolution)
            if new_point == nodes[nearest_index].point:
                continue
            if node_in_collision(mask, new_point, config):
                continue
            if edge_in_collision(mask, nodes[nearest_index].point, new_point, config):
                continue

            near_indices = self.near(
                nodes,
                new_point,
                len(nodes),
                gamma,
                eta,
                spatial,
            )
            chosen = self.choose_parent(
                req,
                new_point,
                near_indices,
                nodes,
                nearest_index,
                deadline,
            )
            if self._timed_out(started_at, req.time_budget_s):
                timed_out = True
                break
            if chosen is None:
                continue

            parent_index, new_cost = chosen
            new_index = len(nodes)
            nodes.append(_TreeNode(new_point, parent_index, new_cost))
            nodes[parent_index].children.add(new_index)
            spatial.insert(new_index, new_point)
            rewires_before = rewire_count
            rewire_count += self.rewire(
                req, new_index, near_indices, nodes, deadline
            )
            if goal_index_in_tree is not None and rewire_count > rewires_before:
                current_goal_path = self._reconstruct(nodes, goal_index_in_tree)
                self.best_length = min(self.best_length, path_length(current_goal_path))
            if self._timed_out(started_at, req.time_budget_s):
                timed_out = True
                break

            if math.dist(new_point, goal) <= step:
                goal_edge_cost = self._valid_edge_cost(req, nodes, new_index, goal)
                if goal_edge_cost is not None:
                    candidate_path = self._reconstruct(nodes, new_index) + (goal,)
                    self.best_length = min(
                        self.best_length,
                        path_length(candidate_path),
                    )
                    if goal_index_in_tree is None:
                        goal_index_in_tree = len(nodes)
                        goal_cost = nodes[new_index].cost + goal_edge_cost
                        nodes.append(_TreeNode(goal, new_index, goal_cost))
                        nodes[new_index].children.add(goal_index_in_tree)
                        spatial.insert(goal_index_in_tree, goal)
                        first_feasible_time = perf_counter() - started_at
                    else:
                        rewired = self._rewire_node(
                            req,
                            nodes,
                            new_index,
                            goal_index_in_tree,
                            goal_edge_cost,
                        )
                        rewire_count += int(rewired)
                        if rewired:
                            # 目标节点重连后，祖先路径可能变短；采样子类读取该最新长度。
                            self.best_length = min(
                                self.best_length,
                                path_length(self._reconstruct(nodes, goal_index_in_tree)),
                            )

        if self._timed_out(started_at, req.time_budget_s):
            timed_out = True
        if timed_out:
            incumbent = self._metrics_for_goal(req, nodes, goal_index_in_tree)
            incumbent_path = (
                ()
                if goal_index_in_tree is None
                else self._reconstruct(nodes, goal_index_in_tree)
            )
            return self._result(
                req,
                "timeout",
                started_at,
                waypoints=incumbent_path,
                length_m=math.nan if incumbent is None else incumbent["length_m"],
                risk_expected=math.nan if incumbent is None else incumbent["risk_expected"],
                composite=math.nan if incumbent is None else incumbent["composite_cost"],
                expansions=iteration_count,
                samples=sample_count,
                failure_reason="timeout",
                metadata=self._metadata(
                    nodes,
                    sample_count,
                    rewire_count,
                    gamma,
                    eta,
                    first_feasible_time,
                    incumbent,
                ),
            )
        if goal_index_in_tree is None:
            return self._result(
                req,
                "no_path",
                started_at,
                expansions=iteration_count,
                samples=sample_count,
                failure_reason="iteration_budget_exhausted" if req.iteration_budget is not None else "no_goal_connection",
                metadata=self._metadata(nodes, sample_count, rewire_count, gamma, eta, first_feasible_time, None),
            )

        path = self._reconstruct(nodes, goal_index_in_tree)
        try:
            metrics = evaluate_path(path, scene.R, config, r_norm=scene.r_norm)
        except ValueError:
            return self._result(
                req,
                "invalid",
                started_at,
                expansions=iteration_count,
                samples=sample_count,
                failure_reason="invalid_risk_path",
                metadata=self._metadata(nodes, sample_count, rewire_count, gamma, eta, first_feasible_time, None),
            )
        return self._result(
            req,
            "success",
            started_at,
            waypoints=path,
            length_m=metrics["length_m"],
            risk_expected=metrics["risk_expected"],
            composite=metrics["composite_cost"],
            expansions=iteration_count,
            samples=sample_count,
            metadata=self._metadata(nodes, sample_count, rewire_count, gamma, eta, first_feasible_time, metrics),
        )

    def edge_cost(self, req: PlanRequest, start: Point3D, end: Point3D) -> float:
        """调用公共评估器计算局部边的距离与风险综合代价。"""
        metrics = evaluate_path(
            (start, end),
            req.scene_data.R,
            req.scene_data.config,
            r_norm=req.scene_data.r_norm,
        )
        return float(metrics["composite_cost"])

    def _valid_edge_cost(
        self,
        req: PlanRequest,
        nodes: Sequence[_TreeNode],
        parent_index: int,
        child: Point3D,
        deadline: float | None = None,
    ) -> float | None:
        """检查步长、边碰撞、端点碰撞和父节点处转角后返回局部代价。"""
        parent = nodes[parent_index].point
        config = req.scene_data.config
        if deadline is not None and perf_counter() >= deadline:
            return None
        step = float(config["table2"]["STEP"])
        if math.dist(parent, child) == 0.0 or math.dist(parent, child) > step + 1e-9:
            return None
        if node_in_collision(req.scene_data.building_mask, child, config):
            return None
        if edge_in_collision(req.scene_data.building_mask, parent, child, config):
            return None
        previous = nodes[nodes[parent_index].parent].point if nodes[parent_index].parent is not None else None
        if not turn_is_allowed(previous, parent, child, config):
            return None
        if deadline is not None and perf_counter() >= deadline:
            return None
        try:
            return self.edge_cost(req, parent, child)
        except ValueError:
            return None

    def _rewire_node(
        self,
        req: PlanRequest,
        nodes: list[_TreeNode],
        new_parent_index: int,
        target_index: int,
        edge_cost: float,
    ) -> bool:
        """为目标树节点尝试更优父节点，保留其现有子边的转角合法性。"""
        if nodes[target_index].parent is None:
            return False
        if self._is_ancestor(nodes, target_index, new_parent_index):
            return False
        proposed_cost = nodes[new_parent_index].cost + edge_cost
        if proposed_cost >= nodes[target_index].cost:
            return False
        if not self._children_keep_turns(
            req,
            nodes,
            nodes[target_index].point,
            nodes[new_parent_index].point,
            nodes[target_index].children,
        ):
            return False
        self._replace_parent(nodes, target_index, new_parent_index, proposed_cost)
        return True

    @staticmethod
    def _children_keep_turns(
        req: PlanRequest,
        nodes: Sequence[_TreeNode],
        target: Point3D,
        previous: Point3D,
        children: Sequence[int] | set[int],
    ) -> bool:
        """确保改换目标节点入边后，其所有现存出边仍满足转角限制。"""
        for child_index in children:
            if not turn_is_allowed(previous, target, nodes[child_index].point, req.scene_data.config):
                return False
        return True

    @staticmethod
    def _replace_parent(
        nodes: list[_TreeNode],
        child_index: int,
        parent_index: int,
        new_cost: float,
    ) -> None:
        """更新父子关系并把累计代价差传播至整棵后代子树。"""
        old_parent = nodes[child_index].parent
        if old_parent is None:
            raise ValueError("不能重连根节点。")
        nodes[old_parent].children.remove(child_index)
        nodes[parent_index].children.add(child_index)
        cost_delta = new_cost - nodes[child_index].cost
        nodes[child_index].parent = parent_index
        nodes[child_index].cost = new_cost
        pending = list(nodes[child_index].children)
        while pending:
            descendant = pending.pop()
            nodes[descendant].cost += cost_delta
            pending.extend(nodes[descendant].children)

    @staticmethod
    def _is_ancestor(
        nodes: Sequence[_TreeNode],
        candidate: int,
        node_index: int | None,
    ) -> bool:
        """判断 candidate 是否位于 node_index 的父链上。"""
        current = node_index
        while current is not None:
            if current == candidate:
                return True
            current = nodes[current].parent
        return False

    @staticmethod
    def _reconstruct(nodes: Sequence[_TreeNode], goal_index: int) -> tuple[Point3D, ...]:
        """从目标节点沿父索引回溯并反转成起点至终点路径。"""
        reverse_path: list[Point3D] = []
        current: int | None = goal_index
        while current is not None:
            reverse_path.append(nodes[current].point)
            current = nodes[current].parent
        reverse_path.reverse()
        return tuple(reverse_path)

    @staticmethod
    def _free_volume(
        mask: np.ndarray,
        config: Mapping[str, Any],
        h_low: float,
        h_high: float,
    ) -> float:
        """按可飞高度内的空闲体素数估算三维自由空间体积。"""
        origin = config["coords"]["origin"]
        low_index = world_to_continuous_index((origin[0], origin[1], h_low), config)[2]
        high_index = world_to_continuous_index((origin[0], origin[1], h_high), config)[2]
        first = max(0, math.ceil(low_index))
        last = min(mask.shape[2] - 1, math.floor(high_index))
        if first > last:
            return 0.0
        mask_window = mask[:, :, first : last + 1]
        free_voxels = mask_window.size - int(np.count_nonzero(mask_window))
        resolution = float(config["coords"]["resolution"])
        return free_voxels * resolution**3

    @staticmethod
    def _metrics_for_goal(
        req: PlanRequest,
        nodes: Sequence[_TreeNode],
        goal_index: int | None,
    ) -> Mapping[str, float] | None:
        """为超时诊断提取当前可行树路径的公共指标。"""
        if goal_index is None:
            return None
        return evaluate_path(
            RRTStarPlanner._reconstruct(nodes, goal_index),
            req.scene_data.R,
            req.scene_data.config,
            r_norm=req.scene_data.r_norm,
        )

    @staticmethod
    def _metadata(
        nodes: Sequence[_TreeNode],
        samples: int,
        rewires: int,
        gamma: float,
        eta: float,
        first_feasible_time: float | None,
        metrics: Mapping[str, float] | None,
    ) -> Mapping[str, object]:
        """汇总要求的 RRT* 参数、搜索计数和最终路径指标。"""
        return {
            "tree_nodes": len(nodes),
            "samples": samples,
            "rewires": rewires,
            "gamma": gamma,
            "eta": eta,
            "first_feasible_time_s": first_feasible_time,
            "final_length_m": None if metrics is None else metrics["length_m"],
            "final_risk_expected": None if metrics is None else metrics["risk_expected"],
            "final_composite_cost": None if metrics is None else metrics["composite_cost"],
        }

    @staticmethod
    def _timed_out(started_at: float, budget: float | None) -> bool:
        """判断调用方提供的时间预算是否耗尽。"""
        return budget is not None and perf_counter() - started_at >= budget

    def _result(
        self,
        req: PlanRequest,
        status: PlanStatus,
        started_at: float,
        *,
        waypoints: tuple[Point3D, ...] = (),
        length_m: float = math.nan,
        risk_expected: float = math.nan,
        composite: float = math.nan,
        expansions: int = 0,
        samples: int = 0,
        failure_reason: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> RRTStarResult:
        """创建标准路径结果，并显式保留 RRT* 运行信息。"""
        return RRTStarResult(
            status=status,
            algorithm=self.name,
            scene=req.scene_data.scene_name,
            mission=req.mission,
            seed=req.seed,
            waypoints=waypoints,
            path_points=len(waypoints),
            length_m=length_m,
            risk_expected=risk_expected,
            composite_cost=composite,
            runtime_s=perf_counter() - started_at,
            iterations_or_expansions=expansions,
            samples=samples,
            failure_reason=failure_reason,
            config_hash=req.scene_data.config_hash,
            metadata={} if metadata is None else metadata,
        )


PLANNERS[RRTStarPlanner.name] = RRTStarPlanner

