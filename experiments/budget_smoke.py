"""预算冒烟工具：扫描预算并汇总结果。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median
from typing import Any
import argparse
import csv
import gc
import json

from .run import (
    PROJECT_ROOT,
    _resolve_project_path,
    append_jsonl,
    load_experiment_config,
    run_one,
    save_config_snapshot,
)
from src.io.scene import SceneData, load_scene


SOLUTION_STATUSES = {"success", "timeout_with_solution"}
CSV_FIELDS = (
    "mode",
    "scene",
    "mission",
    "algorithm",
    "time_budget_s",
    "iteration_budget",
    "runs",
    "solutions",
    "success_rate",
    "runtime_median_s",
    "first_feasible_time_median_s",
    "final_composite_cost_median",
    "statuses",
)

BudgetTask = tuple[
    SceneData,
    str,
    str,
    int,
    float | None,
    int | None,
    float,
    str,
    str,
    Path,
]
ProcessBudgetTask = tuple[
    str,
    str,
    int,
    float | None,
    int | None,
    float,
    str,
    str,
    Path,
]

_PROCESS_SCENE: SceneData | None = None


def _condition_name(mode: str, time_budget_s: float | None, iteration_budget: int | None) -> str:
    """为 raw 条件目录生成稳定且适合文件名的标识。"""
    time_part = "none" if time_budget_s is None else f"{time_budget_s:g}".replace(".", "p")
    iteration_part = "none" if iteration_budget is None else str(iteration_budget)
    return f"{mode}_t-{time_part}_i-{iteration_part}"


def _budget_record_path(
    raw_root: Path,
    scene: str,
    mission: str,
    algorithm: str,
    mode: str,
    time_budget_s: float | None,
    iteration_budget: int | None,
    seed: int,
) -> Path:
    """返回该次预算试验的 JSONL 路径，重复运行采用追加方式保留。"""
    condition = _condition_name(mode, time_budget_s, iteration_budget)
    path = (
        raw_root
        / "budget_smoke"
        / scene
        / mission
        / algorithm
        / condition
        / f"seed_{seed}.jsonl"
    ).resolve()
    if not path.is_relative_to(raw_root.resolve()):
        raise ValueError(f"预算冒烟 raw 路径越出 raw 根目录：{path}")
    return path


def _record_one(
    scene_data: SceneData,
    mission: str,
    algorithm: str,
    seed: int,
    time_budget_s: float | None,
    iteration_budget: int | None,
    spacing_m: float,
    config_hash: str,
    mode: str,
    raw_root: Path,
) -> dict[str, object]:
    """运行单项预算条件并把原始记录追加写入 raw。"""
    record = run_one(
        scene_data,
        mission,
        algorithm,
        seed,
        time_budget_s,
        iteration_budget,
        spacing_m,
        config_hash,
        mode,
    )
    record_path = _budget_record_path(
        raw_root,
        scene_data.scene_name,
        mission,
        algorithm,
        mode,
        time_budget_s,
        iteration_budget,
        seed,
    )
    append_jsonl(record_path, record)
    print(
        json.dumps(
            {
                "mode": mode,
                "scene": scene_data.scene_name,
                "mission": mission,
                "algorithm": algorithm,
                "seed": seed,
                "status": record["status"],
                "runtime_s": record["runtime_s"],
                "failure_reason": record["failure_reason"],
                "raw": str(record_path.relative_to(PROJECT_ROOT)),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return record


def _initialize_process_scene(scene_name: str, scene_config_path: Path) -> None:
    """在每个工作进程中加载一份只读场景，避免通过进程队列复制 R。"""
    global _PROCESS_SCENE
    _PROCESS_SCENE = load_scene(scene_name, scene_config_path)


def _record_process_task(task: ProcessBudgetTask) -> dict[str, object]:
    """用工作进程预加载的场景执行一项预算任务。"""
    if _PROCESS_SCENE is None:
        raise RuntimeError("预算工作进程没有初始化场景。")
    return _record_one(_PROCESS_SCENE, *task)


def _run_tasks(
    tasks: Sequence[BudgetTask],
    workers: int,
    executor_kind: str = "thread",
    scene_config_path: Path | None = None,
) -> list[Mapping[str, object]]:
    """执行预算任务；进程模式适合 CPU 密集规划，线程模式共享场景内存。"""
    if workers < 1:
        raise ValueError("workers 必须是正整数。")
    if executor_kind not in {"thread", "process"}:
        raise ValueError("executor_kind 只能是 `thread` 或 `process`。")
    if not tasks:
        return []
    if workers == 1:
        return [_record_one(*task) for task in tasks]

    if executor_kind == "process":
        if scene_config_path is None:
            raise ValueError("进程并发需要 scene_config_path。")
        scene_name = tasks[0][0].scene_name
        process_tasks: list[ProcessBudgetTask] = [task[1:] for task in tasks]
        records: list[Mapping[str, object]] = []
        with ProcessPoolExecutor(
            max_workers=min(workers, len(tasks)),
            initializer=_initialize_process_scene,
            initargs=(scene_name, scene_config_path),
        ) as executor:
            futures = [executor.submit(_record_process_task, task) for task in process_tasks]
            for future in as_completed(futures):
                records.append(future.result())
        return records

    records: list[Mapping[str, object]] = []
    with ThreadPoolExecutor(
        max_workers=min(workers, len(tasks)),
        thread_name_prefix="budget-smoke",
    ) as executor:
        futures = [executor.submit(_record_one, *task) for task in tasks]
        for future in as_completed(futures):
            records.append(future.result())
    return records


def _summarize_records(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """按预算条件计算成功率及有解记录的中位数。"""
    solutions = [record for record in records if record["status"] in SOLUTION_STATUSES]
    first_feasible = [
        float(record["first_feasible_time_s"])
        for record in solutions
        if record.get("first_feasible_time_s") is not None
    ]
    composite_costs = [
        float(record["composite_cost"])
        for record in solutions
        if record.get("composite_cost") is not None
    ]
    runtimes = [
        float(record["runtime_s"])
        for record in records
        if record.get("runtime_s") is not None
    ]
    status_counts: dict[str, int] = defaultdict(int)
    for record in records:
        status_counts[str(record["status"])] += 1
    return {
        "runs": len(records),
        "solutions": len(solutions),
        "success_rate": len(solutions) / len(records) if records else 0.0,
        "runtime_median_s": median(runtimes) if runtimes else None,
        "first_feasible_time_median_s": median(first_feasible) if first_feasible else None,
        "final_composite_cost_median": median(composite_costs) if composite_costs else None,
        "statuses": json.dumps(dict(sorted(status_counts.items())), ensure_ascii=False, separators=(",", ":")),
    }


def _rows_from_records(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """将原始运行按场景、任务、算法和预算档位聚合成 CSV 行。"""
    grouped: dict[tuple[object, ...], list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        budget = record["budget"]
        if not isinstance(budget, Mapping):
            raise TypeError("运行记录的 budget 必须是 JSON 对象。")
        key = (
            str(budget["run_kind"]),
            str(record["scene"]),
            str(record["mission"]),
            str(record["algorithm"]),
            budget.get("time_budget_s"),
            budget.get("iteration_budget"),
        )
        grouped[key].append(record)

    rows: list[dict[str, object]] = []
    for key, condition_records in sorted(grouped.items(), key=lambda item: tuple(str(part) for part in item[0])):
        summary = _summarize_records(condition_records)
        rows.append(
            {
                "mode": key[0],
                "scene": key[1],
                "mission": key[2],
                "algorithm": key[3],
                "time_budget_s": key[4],
                "iteration_budget": key[5],
                **summary,
            }
        )
    return rows


def _write_summary(rows: Sequence[Mapping[str, object]], output_path: Path) -> None:
    """写出可由 Excel、pandas 或标准库 CSV 读取的预算摘要。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _recommend_budget(rows: Sequence[Mapping[str, object]], budget_key: str) -> int | float | None:
    """从所有采样算法条件中选出成功率达到 80% 的最小预算档位。"""
    rates: dict[int | float, list[tuple[int, int]]] = defaultdict(list)
    for row in rows:
        mode = str(row["mode"])
        allowed_modes = {"quick", "budget_time"} if budget_key == "time_budget_s" else {"quick", "budget_iterations"}
        if mode not in allowed_modes:
            continue
        value = row["time_budget_s"] if budget_key == "time_budget_s" else row["iteration_budget"]
        if value is None:
            continue
        budget_value = float(value) if budget_key == "time_budget_s" else int(value)
        rates[budget_value].append((int(row["solutions"]), int(row["runs"])))
    if not rates:
        return None

    performance = {
        budget: (sum(successes for successes, _ in counts), sum(runs for _, runs in counts))
        for budget, counts in rates.items()
    }
    qualified = [
        budget
        for budget, (successes, runs) in performance.items()
        if runs and successes / runs >= 0.8
    ]
    if qualified:
        return min(qualified)
    return max(
        performance,
        key=lambda budget: (
            performance[budget][0] / performance[budget][1],
            -float(budget),
        ),
    )


def run_quick(
    config: Mapping[str, Any],
    config_hash: str,
    raw_root: Path,
    workers: int = 1,
    executor_kind: str = "thread",
) -> list[Mapping[str, object]]:
    """运行配置指定的一项短预算自测，不推断跨场景的正式预算。"""
    settings = config["budget_smoke"]["quick"]
    scene_config_path = _resolve_project_path(str(config["scene_config"]), "scene_config")
    scene = load_scene(str(settings["scene"]), scene_config_path)
    records = _run_tasks(
        [
            (
                scene,
                str(settings["mission"]),
                str(settings["algorithm"]),
                int(settings["seed"]),
                float(settings["time_budget_s"]),
                int(settings["max_iterations"]),
                float(config["validation"]["path_resample_spacing_m"]),
                config_hash,
                "quick",
                raw_root,
            )
        ],
        workers,
        executor_kind,
        scene_config_path,
    )
    del scene
    gc.collect()
    return records


def run_full_scan(
    config: Mapping[str, Any],
    config_hash: str,
    raw_root: Path,
    workers: int = 1,
    executor_kind: str = "thread",
) -> list[Mapping[str, object]]:
    """执行完整预算梯度和图搜索单次计时；该模式可能运行较长时间。"""
    settings = config["budget_smoke"]
    scene_config_path = _resolve_project_path(str(config["scene_config"]), "scene_config")
    sampling_algorithms = [str(item) for item in config["algorithm_groups"]["sampling"]]
    deterministic_algorithms = [str(item) for item in config["algorithm_groups"]["deterministic"]]
    seeds = [int(item) for item in settings["seeds"]]
    time_budgets = [float(item) for item in settings["time_budgets_s"]]
    iteration_budgets = [int(item) for item in settings["iteration_budgets"]]
    fixed_time = max(time_budgets)
    fixed_iterations = max(iteration_budgets)
    spacing_m = float(config["validation"]["path_resample_spacing_m"])
    records: list[Mapping[str, object]] = []

    for scene_name in settings["scenes"]:
        scene = load_scene(str(scene_name), scene_config_path)
        tasks: list[BudgetTask] = []
        for mission in settings["missions"]:
            mission_id = str(mission)
            for algorithm in sampling_algorithms:
                for time_budget in time_budgets:
                    for seed in seeds:
                        tasks.append(
                            (
                                scene,
                                mission_id,
                                algorithm,
                                seed,
                                time_budget,
                                fixed_iterations,
                                spacing_m,
                                config_hash,
                                "budget_time",
                                raw_root,
                            )
                        )
                for iteration_budget in iteration_budgets:
                    for seed in seeds:
                        tasks.append(
                            (
                                scene,
                                mission_id,
                                algorithm,
                                seed,
                                fixed_time,
                                iteration_budget,
                                spacing_m,
                                config_hash,
                                "budget_iterations",
                                raw_root,
                            )
                        )
            for algorithm in deterministic_algorithms:
                time_budget = float(config["budgets"]["deterministic"]["timeout_s"])
                tasks.append(
                    (
                        scene,
                        mission_id,
                        algorithm,
                        0,
                        time_budget,
                        None,
                        spacing_m,
                        config_hash,
                        "graph_timing",
                        raw_root,
                    )
                )
        records.extend(_run_tasks(tasks, workers, executor_kind, scene_config_path))
        del scene
        gc.collect()
    return records


def run_targeted_scan(
    config: Mapping[str, Any],
    config_hash: str,
    raw_root: Path,
    *,
    workers: int,
    executor_kind: str,
    time_budget_s: float,
    iteration_budget: int,
    seeds: Sequence[int],
) -> list[Mapping[str, object]]:
    """运行候选预算的小规模采样确认，不修改正式配置或执行图搜索。"""
    if time_budget_s <= 0 or not isinstance(time_budget_s, (int, float)):
        raise ValueError("定向时间预算必须是正数。")
    if iteration_budget <= 0:
        raise ValueError("定向迭代预算必须是正整数。")
    if not seeds:
        raise ValueError("定向测试至少需要一个 seed。")

    settings = config["budget_smoke"]
    scene_config_path = _resolve_project_path(str(config["scene_config"]), "scene_config")
    sampling_algorithms = [str(item) for item in config["algorithm_groups"]["sampling"]]
    spacing_m = float(config["validation"]["path_resample_spacing_m"])
    records: list[Mapping[str, object]] = []

    for scene_name in settings["scenes"]:
        scene = load_scene(str(scene_name), scene_config_path)
        tasks: list[BudgetTask] = []
        for mission in settings["missions"]:
            for algorithm in sampling_algorithms:
                for seed in seeds:
                    tasks.append(
                        (
                            scene,
                            str(mission),
                            algorithm,
                            int(seed),
                            float(time_budget_s),
                            int(iteration_budget),
                            spacing_m,
                            config_hash,
                            "targeted_budget",
                            raw_root,
                        )
                    )
        records.extend(_run_tasks(tasks, workers, executor_kind, scene_config_path))
        del scene
        gc.collect()
    return records


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析快速自测或完整预算扫描选项。"""
    parser = argparse.ArgumentParser(description="采样算法预算冒烟与预算梯度汇总")
    parser.add_argument("--config", type=Path, default=Path("experiments/configs/base.json"))
    parser.add_argument(
        "--full",
        action="store_true",
        help="执行完整预算梯度和图搜索计时，可能运行很久；默认只做 quick 自测",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="只运行配置中的一项 quick 自测（默认行为）",
    )
    parser.add_argument(
        "--targeted",
        action="store_true",
        help="运行候选采样预算的小规模确认，不执行图搜索计时",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="并发预算任务数；默认 1，显式设置才启用并行",
    )
    parser.add_argument(
        "--executor",
        choices=("thread", "process"),
        default="thread",
        help="并发方式；CPU 密集预算测试建议用 process，多进程会各自加载场景",
    )
    parser.add_argument(
        "--targeted-time-budget",
        type=float,
        default=600.0,
        help="--targeted 的单次时间预算，单位秒",
    )
    parser.add_argument(
        "--targeted-iterations",
        type=int,
        default=500000,
        help="--targeted 的单次迭代预算",
    )
    parser.add_argument(
        "--targeted-seeds",
        nargs="+",
        type=int,
        default=[0],
        help="--targeted 使用的 seed 列表，默认只跑 seed 0",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """运行预算自测/扫描、追加 raw 记录并生成 CSV 汇总。"""
    args = _parse_args(argv)
    modes = sum(bool(value) for value in (args.full, args.quick, args.targeted))
    if modes > 1:
        raise ValueError("--full、--quick 和 --targeted 只能选择一个。")
    if args.workers < 1:
        raise ValueError("--workers 必须是正整数。")
    config, config_bytes, config_hash = load_experiment_config(args.config)
    raw_root = _resolve_project_path(str(config["output"]["raw_root"]), "raw_root")
    tables_root = _resolve_project_path(str(config["output"]["tables_root"]), "tables_root")
    snapshot_dir = _resolve_project_path(str(config["output"]["snapshot_dir"]), "snapshot_dir")
    snapshot = save_config_snapshot(snapshot_dir, config_bytes, config_hash)
    if args.full:
        records = run_full_scan(config, config_hash, raw_root, args.workers, args.executor)
    elif args.targeted:
        records = run_targeted_scan(
            config,
            config_hash,
            raw_root,
            workers=args.workers,
            executor_kind=args.executor,
            time_budget_s=args.targeted_time_budget,
            iteration_budget=args.targeted_iterations,
            seeds=args.targeted_seeds,
        )
    else:
        records = run_quick(config, config_hash, raw_root, args.workers, args.executor)
    rows = _rows_from_records(records)
    summary_path = tables_root / (
        "budget_targeted_summary.csv" if args.targeted else "budget_smoke_summary.csv"
    )
    _write_summary(rows, summary_path)
    time_recommendation = _recommend_budget(rows, "time_budget_s") if not args.targeted else None
    iteration_recommendation = _recommend_budget(rows, "iteration_budget") if not args.targeted else None
    if args.full:
        scope = "完整预算扫描"
    elif args.targeted:
        scope = "定向候选预算确认"
    else:
        scope = "quick 自测，样本不足"
    print(f"预算扫描模式：{scope}")
    if args.targeted:
        print(
            "定向测试不自动修改或推荐 base.json；请结合成功率和运行时间人工确认候选预算。"
        )
    else:
        print(f"根据数据，建议 base.json 的采样时间预算设为 {time_recommendation} 秒，迭代预算设为 {iteration_recommendation}。")
    if not args.full and not args.targeted:
        print("quick 自测仅用于验证运行与落盘链路，不能作为正式预算决策或算法结论。")
    print(f"预算摘要 CSV：{summary_path.relative_to(PROJECT_ROOT)}")
    print(f"配置快照：{snapshot.relative_to(PROJECT_ROOT)}")
    print(f"本次预算运行数：{len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
