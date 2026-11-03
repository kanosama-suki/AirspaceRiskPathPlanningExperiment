"""单次路径结果的统一合法性和指标评估。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.core.collision import edge_in_collision, node_in_collision
from src.core.grid import turn_is_allowed
from src.core.metrics import evaluate_path
from src.core.types import Point3D


def evaluate_route_result(
    path: Sequence[Point3D],
    scene_data: Any,
    config: Mapping[str, Any],
) -> dict[str, object]:
    """统一检查节点、边、NaN 和转角，并调用公共 metrics。"""
    if not path:
        return {"valid": False, "failure_reason": "empty_path", "metrics": None}
    mask = scene_data.building_mask
    for point in path:
        if node_in_collision(mask, point, config):
            return {"valid": False, "failure_reason": "node_collision", "metrics": None}
    for previous, following in zip(path, path[1:]):
        if edge_in_collision(mask, previous, following, config):
            return {"valid": False, "failure_reason": "edge_collision", "metrics": None}
    for previous, following, next_point in zip(path, path[1:], path[2:]):
        if not turn_is_allowed(previous, following, next_point, config):
            return {"valid": False, "failure_reason": "turn_constraint", "metrics": None}
    try:
        metrics = evaluate_path(path, scene_data.R, config, scene_data.r_norm)
    except (ValueError, IndexError) as error:
        return {"valid": False, "failure_reason": f"risk_evaluation:{error}", "metrics": None}
    return {"valid": True, "failure_reason": None, "metrics": metrics}

