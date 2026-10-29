"""用起终点直线检查真实场景的碰撞、风险查询和指标数据流。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import argparse
import gc
import math

import numpy as np

from src.core.collision import edge_in_collision, node_in_collision
from src.core.coords import index_to_world, world_to_continuous_index
from src.core.grid import turn_is_allowed
from src.core.metrics import evaluate_path, flight_time_hours, path_length, sample_risk
from src.io.scene import SceneData, load_scene


def _sample_line(
    start: Sequence[float],
    goal: Sequence[float],
    spacing: float,
    config: Mapping[str, Any],
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """按空间间隔采直线，并把每个采样映射到最近风险格心。"""
    start_array = np.asarray(start, dtype=np.float64)
    goal_array = np.asarray(goal, dtype=np.float64)
    distance = float(np.linalg.norm(goal_array - start_array))
    sample_count = max(1, math.ceil(distance / spacing))
    continuous_points = [
        tuple(float(value) for value in start_array + (goal_array - start_array) * (index / sample_count))
        for index in range(sample_count + 1)
    ]

    grid_points: list[tuple[float, float, float]] = []
    for point in continuous_points:
        continuous_index = world_to_continuous_index(point, config)
        snapped_index = tuple(int(round(value)) for value in continuous_index)
        grid_points.append(index_to_world(snapped_index, config))
    return continuous_points, grid_points


def _mission_report(scene: SceneData, mission_id: str) -> list[str]:
    """生成单个任务的直线数据流事实记录。"""
    start, goal = scene.missions[mission_id]
    spacing = float(scene.config["table2"]["GRID_SIZE"])
    continuous_points, grid_points = _sample_line(start, goal, spacing, scene.config)

    node_collision_samples = sum(
        node_in_collision(scene.building_mask, point, scene.config)
        for point in grid_points
    )
    edge_collision_segments = sum(
        edge_in_collision(scene.building_mask, previous, following, scene.config)
        for previous, following in zip(grid_points, grid_points[1:])
    )
    turn_checks = max(0, len(continuous_points) - 2)
    turn_violations = sum(
        not turn_is_allowed(
            continuous_points[index - 1],
            continuous_points[index],
            continuous_points[index + 1],
            scene.config,
        )
        for index in range(1, len(continuous_points) - 1)
    )

    sampled_risks = [sample_risk(scene.R, point, scene.config) for point in grid_points]
    nan_hits = sum(value is None for value in sampled_risks)
    straight_length = path_length([start, goal])
    straight_time_hours = flight_time_hours(straight_length, scene.config)
    path_valid = (
        node_collision_samples == 0
        and edge_collision_segments == 0
        and turn_violations == 0
        and nan_hits == 0
    )

    report = [
        f"任务 {mission_id}：START{mission_id} -> GOAL{mission_id}",
        f"起点：{start}",
        f"终点：{goal}",
        f"1 m 直线采样点数：{len(continuous_points)}",
        f"节点碰撞采样数：{node_collision_samples}",
        f"边碰撞线段数：{edge_collision_segments}",
        f"转角检查数 / 违规数：{turn_checks} / {turn_violations}",
        f"R 查询命中 NaN 数：{nan_hits}",
        f"直线长度：{straight_length:.12g} m",
        f"直线飞行时间：{straight_time_hours:.12g} h",
    ]

    if path_valid:
        metrics = evaluate_path(grid_points, scene.R, scene.config, r_norm=scene.r_norm)
        report.extend(
            [
                f"路径状态：VALID",
                f"路径长度（格心采样路径）：{metrics['length_m']:.12g} m",
                f"风险期望积分：{metrics['risk_expected']:.12g}",
                f"归一化风险代价：{metrics['normalized_risk_cost']:.12g}",
                f"综合代价：{metrics['composite_cost']:.12g}",
            ]
        )
    else:
        blockers = []
        if node_collision_samples:
            blockers.append("节点建筑碰撞")
        if edge_collision_segments:
            blockers.append("边穿越建筑")
        if turn_violations:
            blockers.append("转角约束违规")
        if nan_hits:
            blockers.append("R 查询命中 NaN")
        report.extend(
            [
                f"路径状态：INVALID（{', '.join(blockers)}）",
                "风险期望积分：INVALID（路径无效或含非有限风险，不以零替代）",
                "归一化风险代价：INVALID",
                "综合代价：INVALID",
            ]
        )
    return report


def _scene_report(scene: SceneData) -> str:
    """生成一个场景两个任务的冒烟报告。"""
    lines = [
        f"# 场景 {scene.scene_name} 真实 R 数据流冒烟",
        f"场景目录：{scene.scene_dir}",
        f"config SHA-256：{scene.config_hash}",
        f"R.shape：{scene.R.shape}",
        f"R dtype：{scene.R.dtype}",
        f"R NaN 数：{int(np.isnan(scene.R).sum())}",
        f"R finite 数：{int(np.isfinite(scene.R).sum())}",
        f"R_norm（精确有限值计算）：{scene.r_norm:.12g}",
        f"R finite min/max：{float(np.nanmin(scene.R)):.12g} / {float(np.nanmax(scene.R)):.12g}",
        f"建筑体素数：{int(scene.building_mask.sum())}",
        f"pop_density.shape：{scene.pop_density.shape}",
        f"高度范围 / 搜索步长：{scene.h_low:g}–{scene.h_high:g} m / {scene.step:g} m",
        "检查说明：直线按 GRID_SIZE 采样并映射到最近数据格心；结果只用于数据流冒烟，不代表算法表现。",
        "",
    ]
    for mission_id in ("1", "2"):
        lines.extend(_mission_report(scene, mission_id))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析场景、配置和可选 R 缓存路径。"""
    parser = argparse.ArgumentParser(description="A/B 真实 R 直线数据流冒烟检查")
    parser.add_argument("--scenes", nargs="+", choices=("A", "B"), default=("A", "B"))
    parser.add_argument("--config", type=Path, default=Path("lib/03_场景/config.json"))
    parser.add_argument("--cache-A", type=Path)
    parser.add_argument("--cache-B", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("experiments/raw"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """按场景顺序执行冒烟检查，释放前一个场景后再加载下一个。"""
    args = _parse_args(argv)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    for scene_name in args.scenes:
        cache_path = getattr(args, f"cache_{scene_name}")
        scene_data = load_scene(scene_name, args.config, cache_path)
        output_path = output_dir / f"smoke_dataline_{scene_name}.txt"
        output_text = _scene_report(scene_data)
        output_path.write_text(output_text, encoding="utf-8")
        print(output_text, end="")
        print(f"日志已写入：{output_path.resolve()}")
        del scene_data
        gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
