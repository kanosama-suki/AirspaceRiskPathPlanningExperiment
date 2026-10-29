"""校验 P_s 及 reflect 边界口径。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import argparse
import csv
import json
import math
import re

import numpy as np

from .ps import REFLECT_MODE, compute_ps


REFLECT_CANDIDATES: tuple[str, ...] = ("edge_center", "edge_axis", "symmetric")
GLOBAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("ps_min", "min"),
    ("ps_max", "max"),
    ("ps_mean", "mean"),
    ("ps_median", "median"),
    ("n_cells_full_shielding", "full_shielding_count"),
)


def parse_args() -> argparse.Namespace:
    """解析配置、数据契约说明和输出目录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("lib/03_场景/config.json"))
    parser.add_argument("--readme", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="P_s 校验日志目录；默认写入仓库 experiments/validation/。",
    )
    parser.add_argument("--scenes", nargs="+", default=None)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    """读取 UTF-8 JSON，不修改源文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


def tolerance_from_readme(readme_path: Path) -> tuple[float, str]:
    """优先读取 README 中明示的 P_s 绝对容差。"""
    if readme_path.is_file():
        content = readme_path.read_text(encoding="utf-8")
        match = re.search(r"容差\s*：?\s*绝对误差\s*[≤<=]+\s*([0-9.eE+-]+)", content)
        if match is not None:
            return float(match.group(1)), f"README.md §2.8：绝对误差 ≤ {match.group(1)}"
    return 1e-6, "默认，待确认"


def scene_paths(config_path: Path, config: dict[str, Any], scene_key: str) -> dict[str, Path]:
    """按配置中的场景名和路径模板定位只读输入。"""
    root = config_path.parent
    scene_name = str(config["paths"][f"scene_{scene_key}"])
    city_template = str(config["paths"]["city_npz"])
    city_path = root / Path(city_template.replace("<scene>", scene_name, 1))
    scene_dir = city_path.parent
    return {
        "city": city_path,
        "scene": scene_dir,
        "ps_check": scene_dir / "ps_check",
        "summary": scene_dir / "ps_check" / "ps_summary.json",
        "windows": scene_dir / "ps_check" / "ps_windows.npz",
        "probes": scene_dir / "ps_check" / "ps_probes.csv",
    }


def reflect_index(idx: int, n: int, mode: str) -> int:
    """将越界索引按三个候选 reflect 约定独立映射回有效范围。"""
    if n <= 0:
        raise ValueError("反射轴长度 n 必须为正数。")
    if mode not in REFLECT_CANDIDATES:
        raise ValueError(f"不支持的 reflect 候选模式：{mode}")
    if n == 1:
        return 0

    if mode == "edge_center":
        # 例：[-1] -> [0]、[n] -> [n-1]，边缘格本身为镜像中心。
        period = 2 * n
        folded = idx % period
        return folded if folded < n else period - 1 - folded

    # 按任务给定的零起始示例，edge_axis 与 symmetric 都满足
    # [-k] -> [k]、[n-1+k] -> [n-1-k]，两者因此是相同索引映射。
    period = 2 * (n - 1)
    folded = idx % period
    return folded if folded < n else period - folded


def _window_mean_candidate(field: np.ndarray, window: int, mode: str) -> np.ndarray:
    """使用 reflect_index 构造候选边界，再通过积分图求窗口均值。"""
    if field.ndim != 2:
        raise ValueError("P_s 输入必须是二维平面数组。")
    if window <= 0 or window % 2 == 0:
        raise ValueError("P_S_WINDOW 必须是正奇数。")
    padding = window // 2
    rows = np.fromiter(
        (reflect_index(index, field.shape[0], mode) for index in range(-padding, field.shape[0] + padding)),
        dtype=np.intp,
        count=field.shape[0] + 2 * padding,
    )
    columns = np.fromiter(
        (reflect_index(index, field.shape[1], mode) for index in range(-padding, field.shape[1] + padding)),
        dtype=np.intp,
        count=field.shape[1] + 2 * padding,
    )
    padded = field[np.ix_(rows, columns)]

    # 积分图让每个中心格的窗口和可以用四个前缀值常数时间计算。
    cumulative = padded.cumsum(axis=0, dtype=np.float64).cumsum(axis=1, dtype=np.float64)
    prefix = np.pad(cumulative, ((1, 0), (1, 0)), mode="constant")
    window_sums = (
        prefix[window:, window:]
        - prefix[:-window, window:]
        - prefix[window:, :-window]
        + prefix[:-window, :-window]
    )
    return window_sums / (window * window)


def compute_ps_candidate(
    building_footprint: np.ndarray,
    pop_density: np.ndarray,
    config: dict[str, Any],
    mode: str,
) -> np.ndarray:
    """独立计算一个 reflect 候选下的 P_s，供基准反推使用。"""
    footprint = np.asarray(building_footprint)
    density = np.asarray(pop_density)
    if footprint.ndim != 2:
        raise ValueError("building_footprint 必须是二维平面数组。")
    if density.ndim != 2 or density.shape != footprint.shape:
        raise ValueError("pop_density 必须与 building_footprint 具有相同形状。")
    supplementary = config["supplementary"]
    window = int(supplementary["P_S_WINDOW"])
    scale = float(supplementary["P_S_SCALE"])
    coverage_reference = float(supplementary["P_S_C_REF"])
    if coverage_reference <= 0:
        raise ValueError("P_S_C_REF 必须大于 0。")
    coverage = _window_mean_candidate(footprint.astype(bool, copy=False), window, mode)
    return scale * np.minimum(1.0, coverage / coverage_reference)


def relative_error(actual: float, expected: float) -> float:
    """计算相对误差；基准为零且实测非零时返回无穷大。"""
    difference = abs(actual - expected)
    if expected == 0.0:
        return 0.0 if difference == 0.0 else math.inf
    return difference / abs(expected)


def array_error(actual: np.ndarray, expected: np.ndarray) -> dict[str, float | str]:
    """汇总数组的最大绝对/相对误差及基于绝对容差的状态。"""
    differences = np.abs(np.asarray(actual, dtype=np.float64) - np.asarray(expected, dtype=np.float64))
    expected_values = np.abs(np.asarray(expected, dtype=np.float64))
    relative = np.zeros_like(differences, dtype=np.float64)
    nonzero = expected_values != 0
    relative[nonzero] = differences[nonzero] / expected_values[nonzero]
    relative[(~nonzero) & (differences != 0)] = math.inf
    return {
        "max_abs": float(np.max(differences)) if differences.size else 0.0,
        "max_rel": float(np.max(relative)) if relative.size else 0.0,
        "sum_abs": float(np.sum(differences, dtype=np.float64)),
    }


def compare_scalar(actual: float, expected: float, tolerance: float) -> dict[str, float | str]:
    """按绝对容差比较一个标量基准。"""
    absolute = abs(actual - expected)
    return {
        "status": "MATCH" if absolute <= tolerance else "MISMATCH",
        "max_abs": absolute,
        "max_rel": relative_error(actual, expected),
        "sum_abs": absolute,
    }


def load_windows(path: Path) -> list[dict[str, Any]]:
    """读取窗口基准块和它们在二维 P_s 场中的起始索引。"""
    if not path.is_file():
        return []
    with np.load(path, allow_pickle=False) as data:
        required = ("blocks", "files", "i0", "j0")
        missing = [key for key in required if key not in data.files]
        if missing:
            raise KeyError(f"ps_windows.npz 字段不存在：{missing}")
        return [
            {
                "name": str(data["files"][index]),
                "i0": int(data["i0"][index]),
                "j0": int(data["j0"][index]),
                "block": data["blocks"][index],
            }
            for index in range(len(data["files"]))
        ]


def load_probes(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """读取探针 CSV 的原始列名和值，不补造缺失字段。"""
    if not path.is_file():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        columns = list(reader.fieldnames or [])
        return columns, list(reader)


def is_boundary_window(window: dict[str, Any], shape: tuple[int, int], padding: int) -> bool:
    """判断窗口块中是否含有会触及二维平面边界的 P_s 中心格。"""
    block = window["block"]
    i0 = window["i0"]
    j0 = window["j0"]
    return (
        i0 < padding
        or j0 < padding
        or i0 + block.shape[0] > shape[0] - padding
        or j0 + block.shape[1] > shape[1] - padding
    )


def is_boundary_probe(row: dict[str, str], shape: tuple[int, int], padding: int) -> bool:
    """判断某个探针的居中方窗是否需要边界填充。"""
    i = int(row["i"])
    j = int(row["j"])
    return i < padding or j < padding or i >= shape[0] - padding or j >= shape[1] - padding


def global_values(ps: np.ndarray, scale: float) -> dict[str, float | int]:
    """计算 ps_summary.json 中的全局统计口径。"""
    return {
        "min": float(ps.min()),
        "max": float(ps.max()),
        "mean": float(np.mean(ps, dtype=np.float64)),
        "median": float(np.median(ps)),
        "full_shielding_count": int(np.count_nonzero(ps >= scale)),
    }


def compare_global(
    lines: list[str],
    summary: dict[str, Any],
    ps: np.ndarray,
    scale: float,
    tolerance: float,
    mode: str,
) -> list[dict[str, Any]]:
    """输出指定模式下所有存在的全局字段对比。"""
    results: list[dict[str, Any]] = []
    actual_values = global_values(ps, scale)
    for source_key, actual_key in GLOBAL_FIELDS:
        if source_key not in summary:
            lines.append(f"{mode} / {source_key}: 字段不存在，不能比较。")
            results.append({"name": source_key, "status": "MISMATCH", "missing": True})
            continue
        actual = float(actual_values[actual_key])
        expected = float(summary[source_key])
        result = compare_scalar(actual, expected, tolerance)
        lines.append(
            f"{mode} / {source_key}: {result['status']}; 重算值={actual:.12g}; "
            f"基准值={expected:.12g}; 绝对误差={result['max_abs']:.12g}; "
            f"相对误差={result['max_rel']:.12g}"
        )
        results.append({"name": source_key, "actual": actual, "expected": expected, **result})
    return results


def compare_window(ps: np.ndarray, item: dict[str, Any], tolerance: float) -> dict[str, Any]:
    """比较一个切片窗口并定位最大绝对误差点。"""
    block = item["block"]
    i0 = item["i0"]
    j0 = item["j0"]
    actual = ps[i0 : i0 + block.shape[0], j0 : j0 + block.shape[1]]
    if actual.shape != block.shape:
        return {"status": "MISMATCH", "shape_mismatch": True, "max_abs": math.inf, "max_rel": math.inf}
    result = array_error(actual, block)
    result["status"] = "MATCH" if float(result["max_abs"]) <= tolerance else "MISMATCH"
    difference = np.abs(actual - block)
    worst = np.unravel_index(int(np.argmax(difference)), difference.shape)
    result["worst_index"] = (i0 + int(worst[0]), j0 + int(worst[1]))
    result["worst_actual"] = float(actual[worst])
    result["worst_expected"] = float(block[worst])
    return result


def compare_probe(ps: np.ndarray, row: dict[str, str], tolerance: float) -> dict[str, Any]:
    """比较一个探针；字段缺失或索引非法均作为失败记录。"""
    try:
        i = int(row["i"])
        j = int(row["j"])
        expected = float(row["Ps_expected"])
    except (KeyError, TypeError, ValueError) as error:
        return {"status": "MISMATCH", "error": f"probe fields unavailable: {error}"}
    if not (0 <= i < ps.shape[0] and 0 <= j < ps.shape[1]):
        return {"status": "MISMATCH", "error": f"probe index outside P_s.shape: ({i},{j})"}
    actual = float(ps[i, j])
    return {"i": i, "j": j, "actual": actual, "expected": expected, **compare_scalar(actual, expected, tolerance)}


def mode_edge_checks(
    mode: str,
    ps: np.ndarray,
    boundary_windows: list[dict[str, Any]],
    boundary_probes: list[tuple[int, dict[str, str]]],
    tolerance: float,
) -> dict[str, Any]:
    """比较一个候选模式的全部边界窗口与边界探针。"""
    window_results: list[dict[str, Any]] = []
    probe_results: list[dict[str, Any]] = []
    for item in boundary_windows:
        window_results.append({"name": item["name"], **compare_window(ps, item, tolerance)})
    for row_number, row in boundary_probes:
        probe_results.append({"row_number": row_number, **compare_probe(ps, row, tolerance)})

    all_results = window_results + probe_results
    max_abs = max((float(item.get("max_abs", math.inf)) for item in all_results), default=0.0)
    max_rel = max((float(item.get("max_rel", math.inf)) for item in all_results), default=0.0)
    sum_abs = sum((float(item.get("sum_abs", math.inf)) for item in all_results), 0.0)
    all_match = all(item.get("status") == "MATCH" for item in all_results)
    return {
        "window_results": window_results,
        "probe_results": probe_results,
        "all_match": all_match,
        "max_abs": max_abs,
        "max_rel": max_rel,
        "sum_abs": sum_abs,
        "mismatch_count": sum(item.get("status") != "MATCH" for item in all_results),
    }


def format_global_results(results: list[dict[str, Any]], lines: list[str], prefix: str) -> list[str]:
    """按选定模式重新列出全局检查并收集失败项。"""
    failures: list[str] = []
    for result in results:
        if result.get("status") != "MATCH":
            failures.append(f"global.{result['name']}")
    lines.append(f"{prefix} 全局检查失败项：{failures if failures else '无'}")
    return failures


def verify_scene(
    config_path: Path,
    config: dict[str, Any],
    scene_key: str,
    tolerance: float,
    tolerance_source: str,
) -> tuple[str, str, bool]:
    """为场景反推边界模式，返回日志、最终模式和是否存在边界全匹配候选。"""
    paths = scene_paths(config_path, config, scene_key)
    lines = [
        f"# 场景 {scene_key} P_s reflect 口径校验",
        f"容差来源：{tolerance_source}",
        f"绝对容差：{tolerance:.12g}",
        f"city.npz：{paths['city']}",
        f"ps_check：{paths['ps_check']}",
        "P_s 覆盖率输入：building_footprint；pop_density 仅核对二维形状。",
        "building_mask 未读取，未做高度投影。",
        "reflect 候选定义：edge_center(-1→0,n→n-1)；edge_axis(-1→1,n→n-2)；",
        "symmetric 按任务给定的 [-k]→[k]、[n-1+k]→[n-1-k] 实现，与 edge_axis 映射相同。",
        "",
        "## 1. 全局基准与 footprint 输入核验",
    ]

    with np.load(paths["city"], allow_pickle=False) as city:
        missing = [key for key in ("building_footprint", "pop_density") if key not in city.files]
        if missing:
            lines.append(f"city.npz 字段不存在：{missing}")
            lines.extend(["", "## 最终结论", "FAIL: 输入字段缺失。"])
            return "\n".join(lines) + "\n", REFLECT_MODE, False
        footprint = city["building_footprint"]
        pop_density = city["pop_density"]

    summary = load_json(paths["summary"]) if paths["summary"].is_file() else {}
    if not paths["summary"].is_file():
        lines.append(f"全局基准文件不存在：{paths['summary']}")
    supplementary = config["supplementary"]
    scale = float(supplementary["P_S_SCALE"])
    window = int(supplementary["P_S_WINDOW"])
    padding = window // 2

    candidates: dict[str, np.ndarray] = {}
    global_results: dict[str, list[dict[str, Any]]] = {}
    for mode in REFLECT_CANDIDATES:
        candidate = compute_ps_candidate(footprint, pop_density, config, mode)
        candidates[mode] = candidate
        lines.append(f"候选 {mode}: P_s.shape={candidate.shape}; dtype={candidate.dtype}")
        global_results[mode] = compare_global(lines, summary, candidate, scale, tolerance, mode)

    windows = load_windows(paths["windows"])
    window_baseline_missing = not paths["windows"].is_file()
    if window_baseline_missing:
        lines.append(f"窗口基准文件不存在：{paths['windows']}")
    columns, probe_rows = load_probes(paths["probes"])
    required_probe_columns = ("i", "j", "Ps_expected")
    missing_probe_columns = [name for name in required_probe_columns if name not in columns]
    lines.append(f"窗口基准数：{len(windows)}；探针列名：{columns}；探针行数：{len(probe_rows)}")

    boundary_windows = [
        item for item in windows if is_boundary_window(item, footprint.shape, padding)
    ]
    non_boundary_windows = [
        item for item in windows if not is_boundary_window(item, footprint.shape, padding)
    ]
    boundary_probes: list[tuple[int, dict[str, str]]] = []
    non_boundary_probes: list[tuple[int, dict[str, str]]] = []
    if not missing_probe_columns:
        for row_number, row in enumerate(probe_rows, start=2):
            target = boundary_probes if is_boundary_probe(row, footprint.shape, padding) else non_boundary_probes
            target.append((row_number, row))
    lines.append(
        f"边界分类：窗口 {len(boundary_windows)} 个，非边界窗口 {len(non_boundary_windows)} 个；"
        f"边界探针 {len(boundary_probes)} 个，非边界探针 {len(non_boundary_probes)} 个。"
    )

    lines.extend(["", "## 2. 非边界窗口校验（边界模式不影响这些中心格）"])
    non_boundary_failures: list[str] = []
    # 非边界窗口各候选结果相同；仅列一次，使用任务最终模式常量对应候选。
    for item in non_boundary_windows:
        result = compare_window(candidates["edge_center"], item, tolerance)
        lines.append(
            f"{item['name']}: {result['status']}; 最大绝对误差={float(result['max_abs']):.12g}; "
            f"最大相对误差={float(result['max_rel']):.12g}; "
            f"最大误差点={result.get('worst_index')}; "
            f"实测={result.get('worst_actual')}; 基准={result.get('worst_expected')}"
        )
        if result["status"] != "MATCH":
            non_boundary_failures.append(f"window.{item['name']}")

    lines.extend(["", "## 3. 边界窗口与边界探针的三种 reflect 候选"])
    candidate_edge_results: dict[str, dict[str, Any]] = {}
    if missing_probe_columns:
        lines.append(f"探针字段不存在：{missing_probe_columns}")

    for mode in REFLECT_CANDIDATES:
        candidate_edge_results[mode] = mode_edge_checks(
            mode,
            candidates[mode],
            boundary_windows,
            boundary_probes,
            tolerance,
        )
        result = candidate_edge_results[mode]
        lines.append(
            f"### 模式 {mode}: {'MATCH' if result['all_match'] else 'MISMATCH'}; "
            f"最大绝对误差={result['max_abs']:.12g}; 最大相对误差={result['max_rel']:.12g}; "
            f"不匹配基准项数={result['mismatch_count']}"
        )
        for item in result["window_results"]:
            lines.append(
                f"窗口 {item['name']}: {item['status']}; 最大绝对误差={float(item['max_abs']):.12g}; "
                f"最大相对误差={float(item['max_rel']):.12g}; "
                f"最大误差点={item.get('worst_index')}; 实测={item.get('worst_actual')}; "
                f"基准={item.get('worst_expected')}"
            )
        for item in result["probe_results"]:
            lines.append(
                f"探针 CSV 行 {item['row_number']} ({item.get('i')},{item.get('j')}): "
                f"{item['status']}; 实测={item.get('actual')}; 基准={item.get('expected')}; "
                f"绝对误差={item.get('max_abs')}; 相对误差={item.get('max_rel')}"
            )

    passing_modes = [
        mode for mode, result in candidate_edge_results.items() if result["all_match"]
    ]
    if passing_modes:
        selected_mode = passing_modes[0]
        selected_basis = f"全部边界项 MATCH 的候选模式={passing_modes}"
    else:
        selected_mode = min(
            candidate_edge_results,
            key=lambda mode: (
                candidate_edge_results[mode]["max_abs"],
                candidate_edge_results[mode]["sum_abs"],
            ),
        )
        selected_basis = (
            "所有候选均未全通过；按边界项最大绝对误差、再按绝对误差总和最小选择"
        )

    # 最终产物通过 ps.py 公共实现再算一次，确认和反推候选映射一致。
    module_mode_mismatch = REFLECT_MODE != selected_mode
    final_ps = compute_ps(
        footprint,
        pop_density,
        config,
        reflect_mode=selected_mode if module_mode_mismatch else None,
    )
    lines.extend(
        [
            "",
            "## 4. 最终模式及完整基准复核",
            f"reflect 模式：{selected_mode}，依据：边界基准反推（{selected_basis}）。",
            f"ps.py 模块级 REFLECT_MODE={REFLECT_MODE}；反推模式={selected_mode}；"
            f"{'MATCH' if not module_mode_mismatch else 'MISMATCH'}。",
            f"P_s.shape={final_ps.shape}; dtype={final_ps.dtype}; P_s 无高度维。",
        ]
    )
    final_failures: list[str] = list(non_boundary_failures)
    if module_mode_mismatch:
        final_failures.append("ps.REFLECT_MODE_mismatch")
    if window_baseline_missing:
        final_failures.append("window.baseline_file_missing")
    selected_global_results = compare_global(
        lines, summary, final_ps, scale, tolerance, f"最终模式 {selected_mode}"
    )
    final_failures.extend(
        f"global.{item['name']}" for item in selected_global_results if item.get("status") != "MATCH"
    )

    final_window_passes = 0
    for item in windows:
        result = compare_window(final_ps, item, tolerance)
        lines.append(
            f"最终窗口 {item['name']}: {result['status']}; "
            f"最大绝对误差={float(result['max_abs']):.12g}; "
            f"最大相对误差={float(result['max_rel']):.12g}"
        )
        if result["status"] != "MATCH":
            final_failures.append(f"window.{item['name']}")
        else:
            final_window_passes += 1

    probes_all_failed: list[tuple[int, int, int, dict[str, str]]] = []
    final_probe_passes = 0
    if missing_probe_columns:
        final_failures.extend(f"probe.missing_{name}" for name in missing_probe_columns)
    else:
        for row_number, row in enumerate(probe_rows, start=2):
            result = compare_probe(final_ps, row, tolerance)
            lines.append(
                f"最终探针 CSV 行 {row_number} ({result.get('i')},{result.get('j')}): "
                f"{result['status']}; 实测={result.get('actual')}; 基准={result.get('expected')}; "
                f"绝对误差={result.get('max_abs')}; 相对误差={result.get('max_rel')}"
            )
            if result["status"] != "MATCH":
                final_failures.append(f"probe.row_{row_number}")
            else:
                final_probe_passes += 1

            if is_boundary_probe(row, footprint.shape, padding):
                per_mode = [
                    candidate_edge_results[mode]["probe_results"][
                        next(
                            index
                            for index, (candidate_row_number, _) in enumerate(boundary_probes)
                            if candidate_row_number == row_number
                        )
                    ]
                    for mode in REFLECT_CANDIDATES
                ]
                if all(item.get("status") != "MATCH" for item in per_mode):
                    probes_all_failed.append(
                        (row_number, int(row["i"]), int(row["j"]), row)
                    )

    if probes_all_failed:
        lines.extend(["", "三种模式均未通过的边界探针："])
        for row_number, i, j, row in probes_all_failed:
            expected = row.get("Ps_expected", "字段不存在")
            lines.append(
                f"探针行 {row_number} (i={i},j={j})，基准={expected}；"
                "需人工确认镜像约定或窗口中心定义。"
            )
    else:
        lines.extend(["", "三种模式均未通过的边界探针：无。"])

    # 汇总所有候选下的逐项结果，让失败项能直接显示三种模式的对照。
    candidate_failure_records: list[tuple[str, str, dict[str, dict[str, Any]]]] = []
    for source_key, _ in GLOBAL_FIELDS:
        by_mode = {
            mode: next(
                (item for item in global_results[mode] if item["name"] == source_key),
                {"name": source_key, "status": "MISMATCH", "missing": True},
            )
            for mode in REFLECT_CANDIDATES
        }
        if any(item.get("status") != "MATCH" for item in by_mode.values()):
            candidate_failure_records.append((f"全局 {source_key}", "global", by_mode))

    for window_item in windows:
        by_mode = {
            mode: compare_window(candidates[mode], window_item, tolerance)
            for mode in REFLECT_CANDIDATES
        }
        if any(item.get("status") != "MATCH" for item in by_mode.values()):
            candidate_failure_records.append(
                (f"窗口 {window_item['name']}", "window", by_mode)
            )

    if not missing_probe_columns:
        for row_number, row in enumerate(probe_rows, start=2):
            by_mode = {
                mode: compare_probe(candidates[mode], row, tolerance)
                for mode in REFLECT_CANDIDATES
            }
            if any(item.get("status") != "MATCH" for item in by_mode.values()):
                candidate_failure_records.append(
                    (f"探针 CSV 行 {row_number} ({row.get('i')},{row.get('j')})", "probe", by_mode)
                )

    lines.extend(["", "## 最终结论"])
    if not passing_modes:
        lines.append("仍有歧义，写入 assumptions；没有 reflect 候选能使全部边界基准 MATCH。")
    if final_failures:
        lines.append("MISMATCH: " + ", ".join(final_failures))
    else:
        lines.append("ALL PASS")

    lines.extend(["", "### 1. 通过项"])
    if final_failures:
        lines.append(f"最终模式 {selected_mode} 有失败项，见下节和上文逐项数值。")
    else:
        lines.append(
            f"场景 {scene_key}：最终模式 {selected_mode} 的全局统计 "
            f"{sum(item.get('status') == 'MATCH' for item in selected_global_results)} 项、"
            f"非边界窗口 {len(non_boundary_windows)} 项、全部窗口 {final_window_passes} 项、"
            f"探针 {final_probe_passes} 项均 MATCH。"
        )

    lines.append("### 2. 失败项")
    if candidate_failure_records:
        lines.append("以下列出未选候选或候选分歧产生的 MISMATCH；最终模式是否仍有失败见逐场景结论。")
        for label, kind, by_mode in candidate_failure_records:
            primary = by_mode.get(selected_mode, {})
            if primary.get("status") == "MATCH":
                primary = next(
                    item for item in by_mode.values() if item.get("status") != "MATCH"
                )
            if kind == "window":
                measured = (
                    f"最大绝对误差点实测={primary.get('worst_actual')}; "
                    f"基准={primary.get('worst_expected')}; "
                    f"最大绝对误差={primary.get('max_abs')}"
                )
            else:
                measured = (
                    f"实测={primary.get('actual', '字段不存在')}; "
                    f"基准={primary.get('expected', '字段不存在')}"
                )
            mode_statuses = "; ".join(
                f"{mode}={result.get('status', 'MISMATCH')}"
                f"(最大相对误差={result.get('max_rel', '字段不存在')})"
                for mode, result in by_mode.items()
            )
            if any(result.get("status") == "MATCH" for result in by_mode.values()):
                suspected_cause = (
                    "边界镜像映射差异；通过候选下窗口大小、缩放和单位与基准相符。"
                )
            else:
                suspected_cause = (
                    "三种镜像候选均未解释基准，需核对窗口大小、边界、缩放、单位及输入口径。"
                )
            lines.append(
                f"- 场景 {scene_key}，{label}：{measured}；"
                f"相对误差={primary.get('max_rel', '字段不存在')}；"
                f"三种 reflect 模式：{mode_statuses}；怀疑原因：{suspected_cause}"
            )
    else:
        lines.append("无候选 MISMATCH。")
    if final_failures:
        lines.append(f"最终模式 {selected_mode} 的剩余阻断项：{', '.join(final_failures)}。")
    else:
        lines.append(f"最终模式 {selected_mode} 无剩余失败项。")

    lines.append("### 3. 下一步建议")
    if not passing_modes:
        blocker_text = ", ".join(final_failures) if final_failures else "没有候选通过全部边界基准"
        lines.append(
            f"P_s 未 ALL PASS；阻断项：{blocker_text}；当前还存在 reflect 歧义，"
            "需人工确认镜像约定或窗口中心定义。"
        )
    elif final_failures:
        lines.append(
            f"P_s 未 ALL PASS；阻断项：{', '.join(final_failures)}；边界候选已有通过模式，"
            "需先补齐或核实上述基准项，不存在待人工拍板的 reflect 窗口中心歧义。"
        )
    else:
        lines.append(
            f"P_s 为 ALL PASS；采用 {selected_mode}（题面定义下 edge_axis 与 symmetric 映射相同），"
            "边界基准已确认窗口中心口径，无需人工拍板。"
        )
    return "\n".join(lines) + "\n", selected_mode, bool(passing_modes)


def main() -> None:
    """逐场景完成边界模式反推并写入 P_s 校验日志。"""
    args = parse_args()
    config_path = args.config.resolve()
    config = load_json(config_path)
    readme_path = args.readme.resolve() if args.readme else config_path.parent / "README.md"
    tolerance, tolerance_source = tolerance_from_readme(readme_path)
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else config_path.parents[2] / "experiments" / "validation"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_keys: Iterable[str] = config["scenes"].keys() if args.scenes is None else args.scenes
    for scene_key in scene_keys:
        report, selected_mode, edge_all_pass = verify_scene(
            config_path, config, scene_key, tolerance, tolerance_source
        )
        output_path = output_dir / f"ps_check_{scene_key}.txt"
        output_path.write_text(report, encoding="utf-8")
        print(f"{scene_key}: reflect={selected_mode}; edge_all_pass={edge_all_pass}; log={output_path}")


if __name__ == "__main__":
    main()
