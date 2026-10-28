"""Read-only alignment inspection for scene validation artifacts.

This module inspects existing arrays and metadata only.  It never builds a
risk matrix, computes a shielding factor, or compares a window array with a
slice of the full risk array.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np


INDEX_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "i": ("i", "i_idx", "x_idx"),
    "j": ("j", "j_idx", "y_idx"),
    "h_idx": ("h_idx", "height_idx", "z_idx", "h"),
}
BASELINE_VALUE_COLUMNS: tuple[str, ...] = (
    "R_expected",
    "risk_expected",
    "value",
    "R",
)


def parse_args() -> argparse.Namespace:
    """Parse config, output, and requested scene paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scenes", nargs="+", default=None)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    """Read a JSON document without changing it."""
    return json.loads(path.read_text(encoding="utf-8"))


def compact(value: Any) -> str:
    """Render a value compactly for a text log."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def line(lines: list[str], text: str = "") -> None:
    """Append one text line."""
    lines.append(text)


def scene_paths(config_path: Path, config: dict[str, Any], scene_key: str) -> dict[str, Path]:
    """Resolve a scene from config path templates and scene names."""
    scene_name = str(config["paths"][f"scene_{scene_key}"])
    root = config_path.parent
    city_path = root / Path(str(config["paths"]["city_npz"]).replace("<scene>", scene_name, 1))
    slices_path = root / Path(str(config["paths"]["slices_dir"]).replace("<scene>", scene_name, 1))
    scene_path = city_path.parent
    return {
        "scene": scene_path,
        "city": city_path,
        "slices": slices_path,
        "summary": slices_path / "summary.json",
        "index": slices_path / "index.json",
        "probes": slices_path / "probe_points.csv",
        "ps_check": scene_path / "ps_check",
    }


def numeric_summary(array: np.ndarray) -> dict[str, Any]:
    """Collect facts from an existing numeric array."""
    result: dict[str, Any] = {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "nan_count": "unavailable",
        "finite_count": "unavailable",
        "min": "unavailable",
        "max": "unavailable",
        "mean": "unavailable",
        "median": "unavailable",
    }
    if not np.issubdtype(array.dtype, np.number):
        return result
    nan_count = int(np.isnan(array).sum()) if np.issubdtype(array.dtype, np.inexact) else 0
    finite_mask = np.isfinite(array) if np.issubdtype(array.dtype, np.inexact) else np.ones(array.shape, dtype=bool)
    finite = array[finite_mask]
    result["nan_count"] = nan_count
    result["finite_count"] = int(finite.size)
    if finite.size:
        result["min"] = float(finite.min())
        result["max"] = float(finite.max())
        result["mean"] = float(finite.mean())
        result["median"] = float(np.median(finite))
    return result


def format_stat(value: Any) -> str:
    """Format a statistic without introducing a replacement value."""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def values_match(expected: Any, actual: Any) -> bool:
    """Compare scalar or shape values for an alignment report."""
    if isinstance(expected, list):
        return list(actual) == expected if isinstance(actual, (list, tuple)) else False
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(expected), float(actual), rel_tol=1e-5, abs_tol=1e-12)
    return expected == actual


def expected_window_shape(readme_path: Path) -> list[int] | None:
    """Read the documented R_win shape from README rather than defining it here."""
    if not readme_path.is_file():
        return None
    text = readme_path.read_text(encoding="utf-8")
    match = re.search(r'R_win"?\s+shape\s*=\s*\((\d+)\s*,\s*(\d+)\)', text)
    if match is None:
        return None
    return [int(match.group(1)), int(match.group(2))]


def load_city(path: Path) -> tuple[list[str], dict[str, np.ndarray]]:
    """Read the existing city.npz arrays, retaining no writable input handle."""
    if not path.is_file():
        return [], {}
    with np.load(path, allow_pickle=False) as data:
        keys = list(data.files)
        arrays = {key: data[key] for key in keys}
    return keys, arrays


def compare_summary_to_r(summary: dict[str, Any], arrays: dict[str, np.ndarray], lines: list[str]) -> list[str]:
    """Compare documented summary statistics with an existing R array only."""
    expected_fields = {
        "shape": summary.get("shape"),
        "nan_count": summary.get("n_obstacle_cells"),
        "finite_count": summary.get("n_finite_cells"),
        "min": summary.get("r_min"),
        "max": summary.get("r_max"),
        "mean": summary.get("r_mean"),
        "median": summary.get("r_median"),
        "r_norm": summary.get("r_norm"),
    }
    if "R" not in arrays:
        line(lines, "R array: unavailable (city.npz has no R key)")
        for name, expected in expected_fields.items():
            display_name = {
                "shape": "R.shape",
                "nan_count": "R.nan_count",
                "finite_count": "R.finite_count",
                "min": "R.r_min",
                "max": "R.r_max",
                "mean": "R.r_mean",
                "median": "R.r_median",
                "r_norm": "R.r_norm",
            }[name]
            summary_name = {
                "shape": "shape",
                "nan_count": "n_obstacle_cells",
                "finite_count": "n_finite_cells",
                "min": "r_min",
                "max": "r_max",
                "mean": "r_mean",
                "median": "r_median",
                "r_norm": "r_norm",
            }[name]
            line(lines, f"{display_name}: MISMATCH (summary.{summary_name}={format_stat(expected)}, R=unavailable)")
        return [f"{name}: R key absent" for name in expected_fields]

    r_stats = numeric_summary(arrays["R"])
    mismatches: list[str] = []
    for name, expected in expected_fields.items():
        if expected is None:
            line(lines, f"{name}: MISMATCH (summary field absent, R={format_stat(r_stats.get(name))})")
            mismatches.append(f"{name}: summary field absent")
            continue
        actual = min(r_stats["mean"], r_stats["median"]) if name == "r_norm" else r_stats.get(name)
        status = "MATCH" if values_match(expected, actual) else "MISMATCH"
        display_name = {
            "shape": "R.shape",
            "nan_count": "R.nan_count",
            "finite_count": "R.finite_count",
            "min": "R.r_min",
            "max": "R.r_max",
            "mean": "R.r_mean",
            "median": "R.r_median",
            "r_norm": "R.r_norm",
        }[name]
        summary_name = {
            "shape": "shape",
            "nan_count": "n_obstacle_cells",
            "finite_count": "n_finite_cells",
            "min": "r_min",
            "max": "r_max",
            "mean": "r_mean",
            "median": "r_median",
            "r_norm": "r_norm",
        }[name]
        line(lines, f"{display_name}: {status} (summary.{summary_name}={format_stat(expected)}, R={format_stat(actual)})")
        if status == "MISMATCH":
            mismatches.append(f"{name}: summary={format_stat(expected)}, R={format_stat(actual)}")
    return mismatches


def inspect_window(
    window_path: Path,
    window: dict[str, Any],
    lines: list[str],
) -> tuple[bool, str]:
    """Print facts from one R_win file without comparing it to R."""
    file_name = str(window.get("file", ""))
    if not window_path.is_file():
        line(lines, f"{file_name}: MISSING")
        return False, file_name
    with np.load(window_path, allow_pickle=False) as data:
        if "R_win" not in data.files:
            line(lines, f"{file_name}: R_win field missing; keys={compact(list(data.files))}")
            return False, file_name
        array = data["R_win"]
    stats = numeric_summary(array)
    line(lines, f"{file_name}: shape={compact(stats['shape'])}, dtype={stats['dtype']}")
    line(
        lines,
        f"{file_name}: nan_count={stats['nan_count']}, finite_count={stats['finite_count']}, "
        f"min={format_stat(stats['min'])}, max={format_stat(stats['max'])}",
    )
    if array.ndim >= 2 and array.shape[0] and array.shape[1]:
        positions = {
            "top_left": (0, 0),
            "bottom_right": (array.shape[0] - 1, array.shape[1] - 1),
            "center": (array.shape[0] // 2, array.shape[1] // 2),
        }
        for label, (row, column) in positions.items():
            line(lines, f"{file_name}: {label}_index=({row},{column}), value={format_stat(array[row, column])}")
    else:
        line(lines, f"{file_name}: corner/center values unavailable for array ndim={array.ndim}")
    return True, ""


def inspect_slices(
    paths: dict[str, Path],
    summary: dict[str, Any],
    lines: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Inspect index, windows, and probes, returning alignment facts."""
    missing_files: list[str] = []
    window_names: list[str] = []
    window_shape_failures: list[str] = []
    probe_index_failures: list[str] = []
    index_path = paths["index"]
    index_exists = index_path.is_file()
    line(lines, f"index.json.exists: {index_exists}")
    index: dict[str, Any] = {}
    if index_exists:
        index = load_json(index_path)
        windows = index.get("windows", [])
        line(lines, f"index.json.windows_count: {len(windows)}")
        for window in windows:
            file_name = str(window.get("file", ""))
            window_names.append(file_name)
            window_path = paths["slices"] / file_name
            line(lines, f"window.file={file_name}; exists={window_path.is_file()}; metadata={compact(window)}")
            if not window_path.is_file():
                missing_files.append(file_name)
            else:
                with np.load(window_path, allow_pickle=False) as data:
                    array_shape = list(data["R_win"].shape) if "R_win" in data.files else None
                    array_dtype = str(data["R_win"].dtype) if "R_win" in data.files else "unavailable"
                line(lines, f"window.file={file_name}; R_win_shape={compact(array_shape)}; dtype={array_dtype}")
    else:
        line(lines, "index.json.windows_count: unavailable")
    probe_path = paths["probes"]
    line(lines, f"probe_points.csv.exists: {probe_path.is_file()}")
    if not probe_path.is_file():
        missing_files.append(probe_path.name)

    expected_shape = expected_window_shape(paths["scene"].parent / "README.md")
    line(lines, f"README R_win expected shape: {compact(expected_shape) if expected_shape else 'unavailable'}")
    for file_name in window_names:
        window_path = paths["slices"] / file_name
        if not window_path.is_file():
            continue
        with np.load(window_path, allow_pickle=False) as data:
            actual_shape = list(data["R_win"].shape) if "R_win" in data.files else None
        if expected_shape is None or actual_shape != expected_shape:
            window_shape_failures.append(f"{file_name}: actual={compact(actual_shape)}, expected={compact(expected_shape)}")

    if probe_path.is_file():
        with probe_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            rows = list(reader)
        line(lines, f"probe_points.csv.columns: {compact(columns)}")
        line(lines, f"probe_points.csv.row_count: {len(rows)}")
        if rows:
            line(lines, "probe_points.csv.first_5_rows:")
            for row in rows[:5]:
                line(lines, f"  {compact(row)}")
        recognized: dict[str, str | None] = {}
        for role, aliases in INDEX_COLUMN_ALIASES.items():
            recognized[role] = next((column for column in columns if column in aliases), None)
        baseline_column = next((column for column in columns if column in BASELINE_VALUE_COLUMNS), None)
        line(lines, f"probe_points.csv.index_columns: {compact(recognized)}")
        line(lines, f"probe_points.csv.baseline_value_column: {baseline_column or 'missing'}")
        missing_roles = [role for role, column in recognized.items() if column is None]
        if missing_roles:
            probe_index_failures.extend(missing_roles)
        if baseline_column is None:
            probe_index_failures.append("baseline_value")
        for row in rows[:5]:
            indices = {role: row.get(column) if column else None for role, column in recognized.items()}
            baseline = row.get(baseline_column) if baseline_column else None
            line(lines, f"probe.first5 indices={compact(indices)}, baseline={format_stat(baseline)}")
    else:
        line(lines, "probe_points.csv.columns: unavailable")
        line(lines, "probe_points.csv.row_count: unavailable")
        probe_index_failures.extend(["i", "j", "h_idx", "baseline_value"])
    return missing_files, window_shape_failures, probe_index_failures, window_names


def inspect_ps_check(paths: dict[str, Path], lines: list[str]) -> None:
    """List ps_check files and readable shapes or sizes without calculating P_s."""
    ps_path = paths["ps_check"]
    line(lines, f"ps_check.exists: {ps_path.is_dir()}")
    if not ps_path.is_dir():
        line(lines, "ps_check.files: unavailable")
        return
    files = sorted(path for path in ps_path.iterdir() if path.is_file())
    line(lines, f"ps_check.files: {compact([path.name for path in files])}")
    for path in files:
        description = f"size_bytes={path.stat().st_size}"
        if path.suffix.lower() == ".npz":
            with np.load(path, allow_pickle=False) as data:
                arrays = {key: {"shape": list(data[key].shape), "dtype": str(data[key].dtype)} for key in data.files}
            description += f", arrays={compact(arrays)}"
        line(lines, f"ps_check.file={path.name}: {description}")


def inspect_scene(config_path: Path, config: dict[str, Any], scene_key: str) -> str:
    """Produce one alignment log for a scene."""
    paths = scene_paths(config_path, config, scene_key)
    lines = [f"# 场景 {scene_key} 对齐检查", "", "## 1. R 与 summary.json"]
    summary: dict[str, Any] = {}
    if paths["summary"].is_file():
        summary = load_json(paths["summary"])
        line(lines, f"summary.json.top_level_keys: {compact(list(summary.keys()))}")
        if "anchors" in summary:
            for key, value in summary["anchors"].items():
                line(lines, f"summary.anchors.{key}: {compact(value)}")
    else:
        line(lines, "summary.json: missing")
    keys, arrays = load_city(paths["city"])
    line(lines, f"city.npz.keys: {compact(keys)}")
    summary_mismatches = compare_summary_to_r(summary, arrays, lines)

    lines.extend(["", "## 2. index.json 文件清单"])
    lines.extend([f"index.json.path: {paths['index']}", f"slices_dir: {paths['slices']}"])
    missing_files, window_shape_failures, probe_index_failures, window_names = inspect_slices(paths, summary, lines)

    lines.extend(["", "## 3. win_*.npz 概览"])
    for window_name in window_names:
        window_path = paths["slices"] / window_name
        if window_path.is_file():
            inspect_window(window_path, {"file": window_name}, lines)
        else:
            line(lines, f"{window_name}: MISSING")

    lines.extend(["", "## 4. probe_points.csv 概览"])
    line(lines, f"probe_points.csv.path: {paths['probes']}")
    line(lines, f"probe_points.csv.exists: {paths['probes'].is_file()}")
    if paths["probes"].is_file():
        with paths["probes"].open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            probe_columns = list(reader.fieldnames or [])
            probe_rows = list(reader)
        line(lines, f"probe_points.csv.columns: {compact(probe_columns)}")
        line(lines, f"probe_points.csv.row_count: {len(probe_rows)}")
        line(lines, "probe_points.csv.first_5_rows:")
        for row in probe_rows[:5]:
            line(lines, f"  {compact(row)}")
    else:
        line(lines, "probe_points.csv: missing")

    lines.extend(["", "## 5. ps_check 文件清单"])
    inspect_ps_check(paths, lines)

    lines.extend(["", "## 6. 对齐结论"])
    summary_status = "MATCH" if not summary_mismatches else "MISMATCH"
    line(lines, f"- summary vs R: {summary_status}")
    if summary_mismatches:
        lines.extend(f"  - {item}" for item in summary_mismatches)
    index_status = "齐全" if not missing_files else f"缺 {len(missing_files)} 个"
    line(lines, f"- index 列出的文件: {index_status}")
    if missing_files:
        line(lines, f"  - 缺失文件: {compact(missing_files)}")
    line(lines, "- probe 索引列: 存在" if not probe_index_failures else f"- probe 索引列: 缺失（{compact(probe_index_failures)}）")
    line(
        lines,
        "- win 数组形状: 与 README 契约一致"
        if not window_shape_failures
        else f"- win 数组形状: 不一致（{compact(window_shape_failures)}）",
    )

    lines.extend(["", "### 1. 可对齐项"])
    alignable: list[str] = []
    if paths["index"].is_file():
        alignable.append("index.json 可读取，窗口元数据可枚举。")
    if not missing_files:
        alignable.append("index.json 列出的窗口文件与 probe_points.csv 均存在。")
    if not probe_index_failures:
        alignable.append("probe_points.csv 具备索引列和基准值列，前五行可读取。")
    if not window_shape_failures:
        alignable.append("窗口 R_win 形状与 README 契约一致。")
    if "R" in arrays and not summary_mismatches:
        alignable.append("summary 统计项与 city.npz 的 R 实测项一致。")
    if not alignable:
        alignable.append("无可确认的完整 summary-to-R 对齐项。")
    lines.extend(f"- {item}" for item in alignable)

    lines.extend(["", "### 2. 不能对齐项"])
    blockers: list[str] = []
    if "R" not in arrays:
        blockers.append("city.npz 缺少 R；summary 无法与实测 R 对比，影响第 1 节和最终对齐结论。")
    blockers.extend(f"{item}；影响 summary 与 R 的逐项对比。" for item in summary_mismatches if "R key absent" not in item)
    if missing_files:
        blockers.append(f"缺少文件 {compact(missing_files)}；影响第 2 节文件清单和后续逐点核对。")
    if probe_index_failures:
        blockers.append(f"probe 列缺失 {compact(probe_index_failures)}；影响第 4 节索引/基准值读取。")
    if window_shape_failures:
        blockers.append(f"窗口形状异常 {compact(window_shape_failures)}；影响第 3 节契约对齐。")
    if not blockers:
        blockers.append("未发现不能对齐项。")
    lines.extend(f"- {item}" for item in blockers)

    lines.extend(["", "### 3. 下一步建议"])
    if "R" in arrays and not summary_mismatches and not missing_files and not probe_index_failures and not window_shape_failures:
        line(lines, "- 可以进入下一版 verify.py：重算一个窗口和若干探针，并与基准逐点比较。")
    else:
        line(lines, "- 不可以进入下一版 verify.py；阻断项：" + "；".join(blockers))
    return "\n".join(lines) + "\n"


def main() -> None:
    """Run the read-only alignment inspection for requested scenes."""
    args = parse_args()
    config_path = args.config.resolve()
    config = load_json(config_path)
    scene_keys: Iterable[str] = args.scenes or config["scenes"].keys()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for scene_key in scene_keys:
        output_path = args.output_dir / f"align_{scene_key}.txt"
        output_path.write_text(inspect_scene(config_path, config, scene_key), encoding="utf-8")


if __name__ == "__main__":
    main()
