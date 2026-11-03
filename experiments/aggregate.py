"""读取正式原始 JSONL，生成可行性、时间、风险、路径质量和综合代价汇总。"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import argparse
import csv
import json
import math
import statistics

import numpy as np

from experiments.run import _resolve_project_path
from src.experiments.config import FormalConfig, load_config
from src.experiments.route_generator import RouteSpec, load_route_manifest


STRICT_SUCCESS = "success"
LEGAL_PATH_STATUSES = {"success", "timeout_with_solution"}


@dataclass(frozen=True, slots=True)
class AggregationResult:
    """正式汇总表、复杂度分层、winner 和覆盖审计。"""

    summary_rows: tuple[dict[str, object], ...]
    complexity_rows: tuple[dict[str, object], ...]
    winner_rows: tuple[dict[str, object], ...]
    coverage: Mapping[str, object]


def load_jsonl_records(raw_root: Path) -> list[dict[str, Any]]:
    """读取目录下全部 JSONL；损坏记录立即报错。"""
    records: list[dict[str, Any]] = []
    for path in sorted(raw_root.rglob("*.jsonl")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path} 第 {line_number} 行不是合法 JSON") from error
            if not isinstance(record, dict):
                raise ValueError(f"{path} 第 {line_number} 行必须是 JSON 对象")
            record["_source_file"] = str(path)
            records.append(record)
    return records


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    return float(np.percentile(values, percentile)) if values else None


def _record_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """计算一组原始记录的状态和严格成功路径指标。"""
    status_counts = Counter(str(record.get("status")) for record in records)
    run_count = len(records)
    strict_records = [
        record
        for record in records
        if record.get("status") == STRICT_SUCCESS
    ]
    legal_records = [
        record
        for record in records
        if record.get("status") in LEGAL_PATH_STATUSES
    ]
    runtimes = [
        float(record["runtime_s"])
        for record in records
        if record.get("runtime_s") is not None
    ]
    first_times = [
        float(record["first_feasible_time_s"])
        for record in records
        if record.get("first_feasible_time_s") is not None
    ]
    costs = [
        float(record["composite_cost"])
        for record in strict_records
        if record.get("composite_cost") is not None
    ]
    lengths = [
        float(record["length_m"])
        for record in strict_records
        if record.get("length_m") is not None
    ]
    risks = [
        float(record["risk_expected"])
        for record in strict_records
        if record.get("risk_expected") is not None
    ]
    risk_per_distance = [
        float(record["risk_expected"]) / float(record["length_m"])
        for record in strict_records
        if record.get("risk_expected") is not None
        and record.get("length_m") not in {None, 0}
    ]
    detour_ratios = [
        float(record["length_m"]) / float(record["distance_m"])
        for record in strict_records
        if record.get("length_m") is not None and record.get("distance_m") not in {None, 0}
    ]
    expansions = [
        float(record["iterations_or_expansions"])
        for record in records
        if record.get("iterations_or_expansions") is not None
    ]
    strict_rate = len(strict_records) / run_count if run_count else 0.0
    legal_rate = len(legal_records) / run_count if run_count else 0.0
    return {
        "runs": run_count,
        "strict_success_count": len(strict_records),
        "legal_path_count": len(legal_records),
        "strict_success_rate": strict_rate,
        "legal_path_discovery_rate": legal_rate,
        "meets_80_percent_threshold": strict_rate >= 0.8,
        "not_ranked": strict_rate < 0.8,
        "status_success": status_counts["success"],
        "status_timeout_with_solution": status_counts["timeout_with_solution"],
        "status_timeout_no_solution": status_counts["timeout_no_solution"],
        "status_no_path": status_counts["no_path"],
        "status_invalid": status_counts["invalid"],
        "runtime_median_s": _median(runtimes),
        "runtime_p90_s": _percentile(runtimes, 90),
        "first_feasible_time_median_s": _median(first_times),
        "composite_cost_median": _median(costs),
        "composite_cost_p25": _percentile(costs, 25),
        "composite_cost_p75": _percentile(costs, 75),
        "length_median_m": _median(lengths),
        "risk_median": _median(risks),
        "risk_per_distance_median": _median(risk_per_distance),
        "detour_ratio_median": _median(detour_ratios),
        "iterations_or_expansions_median": _median(expansions),
    }


def _aggregate_rows(
    records: Sequence[Mapping[str, Any]],
    *,
    include_complexity: bool,
) -> list[dict[str, object]]:
    grouped: dict[tuple[object, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        key: tuple[object, ...] = (
            record.get("scene"),
            record.get("group"),
            record.get("algorithm"),
        )
        if include_complexity:
            key += (record.get("complexity_band"),)
        grouped[key].append(record)

    rows: list[dict[str, object]] = []
    for key, group_records in sorted(grouped.items(), key=lambda item: tuple(map(str, item[0]))):
        scene, group, algorithm = key[:3]
        row: dict[str, object] = {
            "scene": scene,
            "group": group,
            "algorithm": algorithm,
        }
        if include_complexity:
            row["complexity_band"] = key[3]
        row.update(_record_metrics(group_records))
        rows.append(row)
    return rows


def _winner_rows(summary_rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """每个 scene/group 仅从达到成功率门槛的算法中按综合代价中位数选 winner。"""
    grouped: dict[tuple[object, object], list[Mapping[str, object]]] = defaultdict(list)
    for row in summary_rows:
        grouped[(row["scene"], row["group"])].append(row)
    winners: list[dict[str, object]] = []
    for (scene, group), rows in sorted(grouped.items(), key=lambda item: tuple(map(str, item[0]))):
        eligible = [
            row
            for row in rows
            if not bool(row["not_ranked"]) and row.get("composite_cost_median") is not None
        ]
        winner = min(
            eligible,
            key=lambda row: float(row["composite_cost_median"]),
        ) if eligible else None
        winners.append(
            {
                "scene": scene,
                "group": group,
                "eligible_algorithm_count": len(eligible),
                "winner_algorithm": None if winner is None else winner["algorithm"],
                "winner_composite_cost_median": (
                    None if winner is None else winner["composite_cost_median"]
                ),
                "winner_strict_success_rate": (
                    None if winner is None else winner["strict_success_rate"]
                ),
                "ranking_criterion": "composite_cost_median",
                "status": "ranked" if winner is not None else "no_algorithm_meets_80_percent",
            }
        )
    return winners


def expected_task_keys(
    config: FormalConfig,
    routes: Sequence[RouteSpec],
) -> set[tuple[object, ...]]:
    """按冻结清单和算法 seed 规则计算完整任务键。"""
    deterministic = set(config.algorithms.deterministic)
    expected: set[tuple[object, ...]] = set()
    for route in routes:
        for algorithm in config.algorithms.all_algorithms:
            seeds = (
                (config.seeds.deterministic,)
                if algorithm in deterministic
                else config.seeds.sampling
            )
            for seed in seeds:
                expected.add(
                    (
                        route.scene,
                        route.route_group,
                        route.route_id,
                        algorithm,
                        seed,
                    )
                )
    return expected


def coverage_audit(
    config: FormalConfig,
    routes: Sequence[RouteSpec],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """核对缺失、重复、未知键和基础字段。"""
    expected = expected_task_keys(config, routes)
    actual_keys: list[tuple[object, ...]] = []
    missing_fields: list[dict[str, object]] = []
    for record in records:
        required = {"scene", "group", "route_id", "algorithm", "seed", "status"}
        absent = sorted(required.difference(record))
        if absent:
            missing_fields.append(
                {
                    "source_file": record.get("_source_file"),
                    "missing_fields": absent,
                }
            )
            continue
        actual_keys.append(
            (
                record["scene"],
                record["group"],
                record["route_id"],
                record["algorithm"],
                record["seed"],
            )
        )
    actual_counter = Counter(actual_keys)
    duplicates = [
        {"key": list(key), "count": count}
        for key, count in actual_counter.items()
        if count > 1
    ]
    actual_set = set(actual_keys)
    return {
        "expected_count": len(expected),
        "actual_record_count": len(records),
        "unique_key_count": len(actual_set),
        "missing_count": len(expected.difference(actual_set)),
        "unknown_count": len(actual_set.difference(expected)),
        "duplicate_key_count": len(duplicates),
        "records_with_missing_fields": missing_fields,
        "missing_keys": [list(key) for key in sorted(expected.difference(actual_set), key=str)],
        "unknown_keys": [list(key) for key in sorted(actual_set.difference(expected), key=str)],
        "duplicates": duplicates,
        "complete": not duplicates and not missing_fields and actual_set == expected,
    }


def aggregate_runs(
    records: Sequence[Mapping[str, Any]],
    config: FormalConfig,
    routes: Sequence[RouteSpec],
) -> AggregationResult:
    """生成正式条件表、复杂度分层、winner 和覆盖审计。"""
    summary_rows = _aggregate_rows(records, include_complexity=False)
    complexity_rows = _aggregate_rows(records, include_complexity=True)
    winners = _winner_rows(summary_rows)
    coverage = coverage_audit(config, routes, records)
    return AggregationResult(
        summary_rows=tuple(summary_rows),
        complexity_rows=tuple(complexity_rows),
        winner_rows=tuple(winners),
        coverage=coverage,
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_aggregation(result: AggregationResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "summary_by_condition.csv", result.summary_rows)
    _write_csv(output_dir / "complexity_summary.csv", result.complexity_rows)
    _write_csv(output_dir / "winners.csv", result.winner_rows)
    (output_dir / "coverage_audit.json").write_text(
        json.dumps(result.coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "aggregate.json").write_text(
        json.dumps(
            {
                "summary_rows": list(result.summary_rows),
                "complexity_rows": list(result.complexity_rows),
                "winner_rows": list(result.winner_rows),
                "coverage": dict(result.coverage),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="汇总正式 S/M/L 原始实验记录")
    parser.add_argument("--config", type=Path, default=Path("experiments/configs/formal.toml"))
    parser.add_argument("--input", type=Path, help="原始 JSONL 根目录；默认读取正式配置")
    parser.add_argument("--output", type=Path, help="汇总输出目录；默认读取正式配置")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    loaded = load_config(args.config)
    if not isinstance(loaded.config, FormalConfig):
        raise TypeError("aggregate 需要 formal 配置。")
    config = loaded.config
    raw_root = args.input or _resolve_project_path(config.output.raw_root, "raw_root")
    output_dir = args.output or _resolve_project_path(config.output.tables_root, "tables_root")
    routes = load_route_manifest(
        _resolve_project_path(config.route_manifest, "route_manifest")
    )
    records = load_jsonl_records(raw_root)
    result = aggregate_runs(records, config, routes)
    write_aggregation(result, output_dir)
    print(f"原始记录：{len(records)}")
    print(f"覆盖完整：{bool(result.coverage['complete'])}")
    print(f"输出目录：{output_dir}")
    return 0 if bool(result.coverage["complete"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
