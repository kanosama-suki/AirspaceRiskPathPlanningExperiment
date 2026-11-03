"""基于冻结 S/M/L 路线的预算与进程并行校准器。"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any
import argparse
import csv
import gc
import json
import statistics

import numpy as np

from experiments.run import (
    MatrixTask,
    _execute_scene_tasks,
    _resolve_project_path,
    raw_record_path,
    save_config_snapshot,
)
from src.experiments.config import (
    CalibrationConfig,
    FormalConfig,
    LoadedConfig,
    load_config,
)
from src.experiments.route_generator import RouteSpec, load_route_manifest
from src.io.scene import load_scene


SOLUTION_STATUSES = {"success", "timeout_with_solution"}


def _load_inputs(
    calibration_loaded: LoadedConfig,
) -> tuple[CalibrationConfig, FormalConfig, LoadedConfig, tuple[RouteSpec, ...]]:
    calibration = calibration_loaded.config
    if not isinstance(calibration, CalibrationConfig):
        raise TypeError("calibrate 需要 calibration 配置。")
    formal_path = _resolve_project_path(calibration.formal_config, "formal_config")
    formal_loaded = load_config(formal_path)
    if not isinstance(formal_loaded.config, FormalConfig):
        raise TypeError("calibration.formal_config 必须指向 formal 配置。")
    routes = load_route_manifest(
        _resolve_project_path(formal_loaded.config.route_manifest, "route_manifest")
    )
    return calibration, formal_loaded.config, formal_loaded, routes


def select_calibration_routes(
    routes: Sequence[RouteSpec],
    routes_per_scene_group: int,
) -> tuple[RouteSpec, ...]:
    """在每个 scene/group 内按复杂度层均匀选取校准路线。"""
    selected: list[RouteSpec] = []
    buckets: dict[tuple[str, str], list[RouteSpec]] = defaultdict(list)
    for route in routes:
        buckets[(route.scene, route.route_group)].append(route)
    bands = ("low", "medium", "high")
    if routes_per_scene_group == 1:
        allocation = {"low": 0, "medium": 1, "high": 0}
    elif routes_per_scene_group == 2:
        allocation = {"low": 1, "medium": 0, "high": 1}
    else:
        base, remainder = divmod(routes_per_scene_group, len(bands))
        allocation = {band: base for band in bands}
        for band in bands[:remainder]:
            allocation[band] += 1
    for condition in sorted(buckets):
        bucket = sorted(buckets[condition], key=lambda route: route.route_id)
        for band in bands:
            candidates = [route for route in bucket if route.complexity_band == band]
            quota = allocation[band]
            if len(candidates) < quota:
                raise RuntimeError(
                    f"{condition[0]}/{condition[1]}/{band} 只有 {len(candidates)} 条校准候选，"
                    f"不足 {quota} 条。"
                )
            if quota == 1:
                positions = [len(candidates) // 2]
            else:
                positions = [
                    round(index * (len(candidates) - 1) / (quota - 1))
                    for index in range(quota)
                ]
            selected.extend(candidates[position] for position in positions)
    return tuple(selected)


def _calibration_tasks(
    calibration: CalibrationConfig,
    formal: FormalConfig,
    routes: Sequence[RouteSpec],
    scene_hashes: Mapping[str, str],
    config_hash: str,
    *,
    time_budgets_s: Sequence[float],
    graph_time_budgets_s: Mapping[str, float],
    sampling_seed_count: int,
    workers: int,
    executor_kind: str,
    run_scope: str,
) -> list[MatrixTask]:
    """展开图搜索单次运行和采样算法预算档任务。"""
    raw_root = _resolve_project_path(calibration.raw_root, "raw_root")
    deterministic = set(formal.algorithms.deterministic)
    sampling_seeds = formal.seeds.sampling[:sampling_seed_count]
    tasks: list[MatrixTask] = []
    for route in routes:
        for algorithm in formal.algorithms.all_algorithms:
            if algorithm in deterministic:
                record_path = raw_record_path(
                    raw_root / "graph",
                    "{scene}/{group}/{algorithm}/{route_id}.jsonl",
                    route,
                    algorithm,
                    formal.seeds.deterministic,
                )
                tasks.append(
                    MatrixTask(
                        route=route,
                        algorithm=algorithm,
                        seed=formal.seeds.deterministic,
                        seed_kind="deterministic",
                        time_budget_s=graph_time_budgets_s[route.route_group],
                        iteration_budget=None,
                        spacing_m=formal.validation.path_resample_spacing_m,
                        experiment_config_hash=config_hash,
                        scene_config_hash=scene_hashes[route.scene],
                        run_kind="calibration_graph",
                        run_id=run_scope,
                        record_path=record_path,
                        workers=workers,
                        executor_kind=executor_kind,
                    )
                )
                continue

            for seed in sampling_seeds:
                for time_budget_s in time_budgets_s:
                    budget_label = f"{time_budget_s:g}".replace(".", "p")
                    record_path = raw_record_path(
                        raw_root,
                        f"sampling/{budget_label}s/{{scene}}/{{group}}/{{algorithm}}/"
                        "{route_id}_seed_{seed}.jsonl",
                        route,
                        algorithm,
                        seed,
                    )
                    tasks.append(
                        MatrixTask(
                            route=route,
                            algorithm=algorithm,
                            seed=seed,
                            seed_kind="sampling",
                            time_budget_s=time_budget_s,
                            iteration_budget=calibration.max_iterations,
                            spacing_m=formal.validation.path_resample_spacing_m,
                            experiment_config_hash=config_hash,
                            scene_config_hash=scene_hashes[route.scene],
                            run_kind="calibration_time",
                            run_id=run_scope,
                            record_path=record_path,
                            workers=workers,
                            executor_kind=executor_kind,
                        )
                    )
    return tasks


def _worker_benchmark_routes(routes: Sequence[RouteSpec]) -> list[RouteSpec]:
    """从每个场景短距离组复制足够多的确定性任务用于吞吐测试。"""
    source_routes = [
        route
        for route in routes
        if route.route_group == "S" and route.complexity_band == "low"
    ][:2]
    if not source_routes:
        source_routes = list(routes[:2])
    return [
        replace(
            source_routes[index % len(source_routes)],
            route_group="worker_bench",
            route_id=f"worker_bench_{index:03d}",
        )
        for index in range(28)
    ]


def _worker_benchmark(
    calibration: CalibrationConfig,
    formal: FormalConfig,
    source_routes: Sequence[RouteSpec],
    scene_hashes: Mapping[str, str],
    config_hash: str,
) -> list[dict[str, object]]:
    """用固定 A* 任务集测量不同 worker 数的端到端吞吐。"""
    benchmark_routes = _worker_benchmark_routes(source_routes)

    results: list[dict[str, object]] = []
    for worker_count in calibration.worker_candidates:
        started = perf_counter()
        total = 0
        for scene_name in sorted({route.scene for route in benchmark_routes}):
            scene_config_path = _resolve_project_path(formal.scene_config, "scene_config")
            scene = load_scene(scene_name, scene_config_path)
            scene_tasks = [
                MatrixTask(
                    route=route,
                    algorithm="astar",
                    seed=formal.seeds.deterministic,
                    seed_kind="deterministic",
                    time_budget_s=formal.route_groups["S"].time_budget_s,
                    iteration_budget=None,
                    spacing_m=formal.validation.path_resample_spacing_m,
                    experiment_config_hash=config_hash,
                    scene_config_hash=scene_hashes[route.scene],
                    run_kind="worker_benchmark",
                    run_id="worker-benchmark",
                    record_path=raw_record_path(
                        _resolve_project_path(calibration.raw_root, "raw_root")
                        / "workers"
                        / f"workers_{worker_count}",
                        "{scene}/{route_id}.jsonl",
                        route,
                        "astar",
                        formal.seeds.deterministic,
                    ),
                    workers=worker_count,
                    executor_kind="process",
                )
                for route in benchmark_routes
                if route.scene == scene_name
            ]
            executed, _ = _execute_scene_tasks(scene, scene_tasks, scene_config_path)
            total += executed
            del scene
            gc.collect()
        elapsed = perf_counter() - started
        results.append(
            {
                "workers": worker_count,
                "task_count": total,
                "wall_time_s": elapsed,
                "tasks_per_second": total / elapsed if elapsed > 0 else None,
            }
        )
    return results


def _read_records(
    raw_root: Path,
    config_hash: str,
    run_scope: str,
) -> list[dict[str, Any]]:
    """只读取当前配置和当前 scope 的记录，避免旧批次混入预算推荐。"""
    records: list[dict[str, Any]] = []
    if not raw_root.exists():
        return records
    for path in sorted(raw_root.rglob("*.jsonl")):
        if "workers" in path.parts:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                execution = record.get("execution", {})
                if not isinstance(execution, Mapping):
                    execution = {}
                if (
                    record.get("experiment_config_hash") == config_hash
                    and execution.get("run_id") == run_scope
                ):
                    records.append(record)
    return records


def summarize_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, object]]:
    """按条件汇总严格成功率、路径发现率、时间和综合代价。"""
    grouped: dict[tuple[object, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        budget = record.get("budget", {})
        if not isinstance(budget, Mapping):
            budget = {}
        key = (
            record.get("scene"),
            record.get("group"),
            record.get("algorithm"),
            budget.get("time_budget_s"),
            budget.get("iteration_budget"),
            budget.get("run_kind"),
        )
        grouped[key].append(record)

    rows: list[dict[str, object]] = []
    for key, group_records in sorted(grouped.items(), key=lambda item: str(item[0])):
        status_counts = Counter(str(row.get("status")) for row in group_records)
        strict_successes = status_counts["success"]
        legal_paths = sum(status_counts[status] for status in SOLUTION_STATUSES)
        runtimes = [
            float(row["runtime_s"])
            for row in group_records
            if row.get("runtime_s") is not None
        ]
        first_times = [
            float(row["first_feasible_time_s"])
            for row in group_records
            if row.get("first_feasible_time_s") is not None
        ]
        costs = [
            float(row["composite_cost"])
            for row in group_records
            if row.get("status") in SOLUTION_STATUSES
            and row.get("composite_cost") is not None
        ]
        scene, group, algorithm, time_budget_s, iteration_budget, run_kind = key
        runs = len(group_records)
        rows.append(
            {
                "run_kind": run_kind,
                "scene": scene,
                "group": group,
                "algorithm": algorithm,
                "time_budget_s": time_budget_s,
                "iteration_budget": iteration_budget,
                "runs": runs,
                "strict_success_count": strict_successes,
                "legal_path_count": legal_paths,
                "strict_success_rate": strict_successes / runs,
                "legal_path_discovery_rate": legal_paths / runs,
                "median_runtime_s": statistics.median(runtimes) if runtimes else None,
                "p90_runtime_s": (
                    float(np.percentile(runtimes, 90)) if runtimes else None
                ),
                "median_first_feasible_time_s": (
                    statistics.median(first_times) if first_times else None
                ),
                "median_composite_cost": statistics.median(costs) if costs else None,
            }
        )
    return rows


def recommend_budgets(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """按组选择达到 80% 严格成功率的最小采样时间预算。"""
    sampling_rows = [
        row
        for row in rows
        if row.get("run_kind") == "calibration_time"
    ]
    recommendations: dict[str, object] = {}
    for scene in sorted({str(row["scene"]) for row in sampling_rows}):
        for group in ("S", "M", "L"):
            candidates = [
                row
                for row in sampling_rows
                if row["scene"] == scene and row["group"] == group
            ]
            budgets = sorted({float(row["time_budget_s"]) for row in candidates})
            chosen = None
            for budget in budgets:
                at_budget = [row for row in candidates if float(row["time_budget_s"]) == budget]
                if at_budget and all(float(row["strict_success_rate"]) >= 0.8 for row in at_budget):
                    chosen = budget
                    break
            recommendations[f"{scene}/{group}"] = chosen
    return {
        "minimum_budget_for_80_percent_strict_success": recommendations,
        "note": (
            "示例路线校准只用于确定预算；未达到 80% 时返回 null，"
            "不能通过复制或事后删除失败样本补齐。"
        ),
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校准冻结 S/M/L 路线的预算和并行度")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("experiments/configs/calibration.toml"),
    )
    parser.add_argument(
        "--scope",
        choices=("quick", "pilot", "full", "workers"),
        default="quick",
    )
    parser.add_argument("--workers", type=int, help="预算扫描使用的并行 worker 数")
    parser.add_argument("--executor", choices=("process", "thread"), default="process")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    calibration_loaded = load_config(args.config)
    calibration, formal, formal_loaded, routes = _load_inputs(calibration_loaded)
    selected_routes = select_calibration_routes(
        routes,
        1 if args.scope in {"quick", "pilot", "workers"} else calibration.routes_per_scene_group,
    )
    config_hash = sha256(calibration_loaded.raw_bytes + formal_loaded.raw_bytes).hexdigest()
    scene_config_path = _resolve_project_path(formal.scene_config, "scene_config")
    scene_hashes: dict[str, str] = {}
    for scene_name in sorted({route.scene for route in selected_routes}):
        scene = load_scene(scene_name, scene_config_path)
        scene_hashes[scene_name] = scene.config_hash
        del scene
        gc.collect()

    raw_root = _resolve_project_path(calibration.raw_root, "raw_root")
    save_config_snapshot(
        raw_root / "config_snapshots",
        calibration_loaded.raw_bytes,
        calibration_loaded.sha256,
        source_suffix=".toml",
    )
    save_config_snapshot(
        raw_root / "config_snapshots",
        formal_loaded.raw_bytes,
        formal_loaded.sha256,
        source_suffix=".toml",
    )

    if args.scope == "quick":
        time_budgets = calibration.time_budgets_s[:1]
        sampling_seed_count = 1
    elif args.scope == "pilot":
        time_budgets = calibration.pilot_time_budgets_s
        sampling_seed_count = min(3, len(formal.seeds.sampling))
    else:
        time_budgets = calibration.time_budgets_s
        sampling_seed_count = min(
            calibration.sampling_seed_count,
            len(formal.seeds.sampling),
        )
    workers = args.workers or (8 if args.scope != "full" else min(calibration.worker_candidates))
    if args.scope != "workers":
        graph_time_budgets_s = {
            group_name: (
                group.time_budget_s
                if args.scope in {"pilot", "full"}
                else calibration.graph_timeout_s
            )
            for group_name, group in formal.route_groups.items()
        }
        tasks = _calibration_tasks(
            calibration,
            formal,
            selected_routes,
            scene_hashes,
            config_hash,
            time_budgets_s=time_budgets,
            graph_time_budgets_s=graph_time_budgets_s,
            sampling_seed_count=sampling_seed_count,
            workers=workers,
            executor_kind=args.executor,
            run_scope=args.scope,
        )
        sampling_tasks = [task for task in tasks if task.iteration_budget is not None]
        sampling_cpu_hours = sum(task.time_budget_s for task in sampling_tasks) / 3600
        graph_cpu_hours = sum(
            task.time_budget_s for task in tasks if task.iteration_budget is None
        ) / 3600
        print(
            f"校准任务：总计 {len(tasks)}；采样 {len(sampling_tasks)}；"
            f"图搜索时间预算上限合计 {graph_cpu_hours:.1f} CPU 小时；"
            f"采样时间预算上限合计 {sampling_cpu_hours:.1f} CPU 小时"
        )
        for scene_name in sorted(scene_hashes):
            scene = load_scene(scene_name, scene_config_path)
            scene_tasks = [task for task in tasks if task.route.scene == scene_name]
            _execute_scene_tasks(scene, scene_tasks, scene_config_path)
            del scene
            gc.collect()

    worker_rows = (
        _worker_benchmark(
            calibration,
            formal,
            selected_routes,
            scene_hashes,
            config_hash,
        )
        if args.scope == "full"
        else []
    )
    records = _read_records(raw_root, config_hash, args.scope)
    summary_rows = summarize_records(records)
    summary_path = _resolve_project_path(calibration.summary_csv, "summary_csv")
    _write_csv(summary_path, summary_rows)
    if worker_rows:
        _write_csv(summary_path.with_name("worker_throughput.csv"), worker_rows)
    recommendation = recommend_budgets(summary_rows)
    recommendation_path = summary_path.with_suffix(".recommendation.json")
    recommendation_path.write_text(
        json.dumps(
            {
                **recommendation,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "scope": args.scope,
                "selected_route_count": len(selected_routes),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"校准汇总：{summary_path}")
    print(f"预算建议：{recommendation_path}")
    print(json.dumps(recommendation, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
