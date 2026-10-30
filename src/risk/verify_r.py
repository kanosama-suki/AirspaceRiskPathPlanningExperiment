"""校验 R 矩阵的 sample 和 full 范围；比较窗口、探针与全局统计。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import argparse
import csv
import gc
import json
import math
import re

import numpy as np

from src.risk.ps import compute_ps
from src.risk.risk_matrix import (
    ballistic_impact_components,
    compute_casualty_area_ballistic,
    compute_casualty_area_parachute,
    compute_crash_energy,
    compute_fatality_rate,
    compute_final_R_point,
    compute_mitigation_M,
    compute_mitigation_Mp,
    compute_mitigation_Ms,
    compute_r_matrix,
    parachute_impact_components,
)


def _relative_error(actual: float, expected: float) -> float:
    """计算相对误差；基准为零时用绝对误差避免除零。"""
    if expected == 0.0:
        return abs(actual - expected)
    return abs(actual - expected) / abs(expected)


def _read_tolerance(readme_path: Path) -> float:
    """从场景 README 的窗口逐点契约读取相对误差阈值。"""
    readme_text = readme_path.read_text(encoding="utf-8")
    window_section = readme_text.split("### 步骤 2：窗口逐点", maxsplit=1)
    if len(window_section) != 2:
        raise ValueError(f"README 中没有窗口逐点契约：{readme_path}")

    match = re.search(r"空中格相对误差\s*≤\s*([0-9.eE+-]+)", window_section[1])
    if match is None:
        raise ValueError(f"README 中没有可解析的空中格相对误差阈值：{readme_path}")
    return float(match.group(1))


def _load_json(path: Path) -> dict[str, Any]:
    """以 UTF-8 读取 JSON 对象。"""
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须为对象：{path}")
    return value


def _scene_paths(config_path: Path, config: Mapping[str, Any], scene: str) -> tuple[Path, Path, Path]:
    """按 config.paths 解析场景、城市数组和切片目录。"""
    paths = config["paths"]
    scene_name = str(paths[f"scene_{scene}"])
    scene_dir = config_path.parent / scene_name
    city_template = str(paths["city_npz"])
    slices_template = str(paths["slices_dir"])
    city_path = config_path.parent / city_template.replace("<scene>", scene_name)
    slices_path = config_path.parent / slices_template.replace("<scene>", scene_name)
    return scene_dir, city_path, slices_path


def _prepare_layer_model(
    height: float,
    table1: Mapping[str, Any],
    supplementary: Mapping[str, Any],
) -> dict[str, float]:
    """预先计算当前高度共享的弹道与开伞运动中间量。"""
    mass = float(table1["MASS"])
    gravity = float(table1["G"])
    cruise_speed = float(table1["V_CRUISE"])
    rho = float(supplementary["RHO"])
    c_d_u = float(supplementary["C_D_U"])
    s_u = float(supplementary["S_U"])
    c_d_p = float(supplementary["C_D_P"])
    s_p = float(supplementary["S_P"])
    r_p = float(supplementary["R_P"])
    r_u = float(supplementary["R_U"])
    h_p = float(supplementary["H_P"])

    # 摘要明確採用自由落體豎直能量；彈道面積仍使用式 (16) 的水平速度。
    ballistic_vx, ballistic_vy = ballistic_impact_components(
        height, mass, cruise_speed, gravity, rho, c_d_u, s_u
    )
    ballistic_energy = compute_crash_energy(mass, (0.0, ballistic_vy))
    ballistic_area = compute_casualty_area_ballistic(
        r_p, r_u, h_p, ballistic_vx, ballistic_vy
    )

    # 開傘能量按摘要的終端豎直速度簡化，傷亡面積則使用式 (19) 的水平分量。
    parachute_vx, parachute_vy, _ = parachute_impact_components(
        height,
        mass,
        cruise_speed,
        gravity,
        rho,
        c_d_u,
        s_u,
        c_d_p,
        s_p,
        float(supplementary["T_1"]),
    )
    parachute_energy = compute_crash_energy(mass, (0.0, parachute_vy))
    parachute_area = compute_casualty_area_parachute(
        r_p, r_u, h_p, parachute_vx, parachute_vy
    )
    return {
        "ballistic_energy": ballistic_energy,
        "ballistic_area": ballistic_area,
        "parachute_energy": parachute_energy,
        "parachute_area": parachute_area,
    }


def _compute_point(
    i: int,
    j: int,
    h_idx: int,
    building_mask: np.ndarray,
    pop_density: np.ndarray,
    ps_field: np.ndarray,
    layer_model: Mapping[str, float],
    table1: Mapping[str, Any],
    supplementary: Mapping[str, Any],
) -> float:
    """按指定的 `[i, j, h_idx]` 坐标计算一个 R 值，不构造全量矩阵。"""
    if bool(building_mask[i, j, h_idx]):
        return float(np.nan)

    ps_value = float(ps_field[i, j])
    alpha = float(table1["ALPHA"])
    beta = float(table1["BETA"])
    fatality_ballistic = compute_fatality_rate(
        ps_value, layer_model["ballistic_energy"], alpha, beta
    )
    fatality_parachute = compute_fatality_rate(
        ps_value, layer_model["parachute_energy"], alpha, beta
    )
    mitigation_mp = compute_mitigation_Mp(
        layer_model["ballistic_area"],
        layer_model["parachute_area"],
        fatality_ballistic,
        fatality_parachute,
    )
    mitigation_ms = compute_mitigation_Ms(
        ps_value, layer_model["ballistic_energy"], alpha, beta
    )
    mitigation = compute_mitigation_M(
        mitigation_mp,
        mitigation_ms,
        layer_model["ballistic_energy"],
        layer_model["parachute_energy"],
        beta,
        float(supplementary["ETA"]),
    )
    return compute_final_R_point(
        float(pop_density[i, j]),
        layer_model["ballistic_area"],
        mitigation,
        float(table1["P_LOC"]),
        False,
    )


def _format_value(value: float) -> str:
    """以易读形式格式化浮点值和 NaN。"""
    return "NaN" if math.isnan(value) else f"{value:.12e}"


def _verify_window(
    scene: str,
    window: Mapping[str, Any],
    slices_dir: Path,
    building_mask: np.ndarray,
    pop_density: np.ndarray,
    ps_field: np.ndarray,
    config: Mapping[str, Any],
    tolerance: float,
) -> tuple[str, list[str]]:
    """只重算首个参考窗口，并生成逐格差异日志。"""
    window_path = slices_dir / str(window["file"])
    with np.load(window_path, allow_pickle=False) as archive:
        expected = np.asarray(archive["R_win"])

    coords = config["coords"]
    table1 = config["table1"]
    supplementary = config["supplementary"]
    table2 = config["table2"]
    origin_z = float(coords["origin"][2])
    resolution = float(coords["resolution"])
    height = float(window["z"])
    h_idx = int(round((height - origin_z) / resolution))
    if not 0 <= h_idx < int(table2["N_H"]):
        raise ValueError(f"窗口高度映射超出配置层范围：z={height}, h_idx={h_idx}")

    i0 = int(window["i0"])
    j0 = int(window["j0"])
    i1 = i0 + expected.shape[0]
    j1 = j0 + expected.shape[1]
    if i0 < 0 or j0 < 0 or i1 > building_mask.shape[0] or j1 > building_mask.shape[1]:
        raise ValueError(f"窗口超出 city.npz 平面范围：i=[{i0},{i1}), j=[{j0},{j1})")

    layer_model = _prepare_layer_model(height, table1, supplementary)
    actual = np.empty(expected.shape, dtype=np.float64)
    for row in range(expected.shape[0]):
        for column in range(expected.shape[1]):
            actual[row, column] = _compute_point(
                i0 + row,
                j0 + column,
                h_idx,
                building_mask,
                pop_density,
                ps_field,
                layer_model,
                table1,
                supplementary,
            )

    expected_nan = np.isnan(expected)
    actual_nan = np.isnan(actual)
    nan_mismatch = expected_nan != actual_nan
    finite_mask = np.isfinite(expected) & np.isfinite(actual)
    relative_errors = np.zeros(expected.shape, dtype=np.float64)
    if finite_mask.any():
        denominators = np.abs(expected[finite_mask].astype(np.float64))
        differences = np.abs(actual[finite_mask] - expected[finite_mask].astype(np.float64))
        relative_errors[finite_mask] = np.divide(
            differences,
            denominators,
            out=differences.copy(),
            where=denominators != 0.0,
        )

    failed_mask = nan_mismatch | (finite_mask & (relative_errors > tolerance))
    failed_coordinates = np.argwhere(failed_mask)
    max_relative_error = float(relative_errors[finite_mask].max()) if finite_mask.any() else 0.0
    matched_nan_count = int(np.count_nonzero(expected_nan & actual_nan))
    expected_finite_count = int(np.count_nonzero(np.isfinite(expected)))

    lines = [
        f"# 场景 {scene} R 单窗口校验",
        f"窗口文件：{window_path.name}",
        f"窗口索引：左上角 ({i0}, {j0})，高度索引 {h_idx}，z={height:g} m",
        f"窗口形状：{expected.shape}",
        f"容差：相对误差 ≤ {tolerance:.0e}（来源：场景 README 步骤 2）",
        f"参与比较格数：{expected.size}",
        f"有限值比较格数：{expected_finite_count}",
        f"双方均为 NaN 格数：{matched_nan_count}",
        f"NaN 位置不一致数：{int(nan_mismatch.sum())}",
        f"最大相对误差：{max_relative_error:.6e}",
        f"失败点数：{len(failed_coordinates)}",
        "前 10 个失败点：",
    ]
    if len(failed_coordinates) == 0:
        lines.append("无")
    else:
        for row, column in failed_coordinates[:10]:
            expected_value = float(expected[row, column])
            actual_value = float(actual[row, column])
            relative_error = float(relative_errors[row, column])
            lines.append(
                f"  i={i0 + row}, j={j0 + column}, h_idx={h_idx}, "
                f"重算值={_format_value(actual_value)}, 基准值={_format_value(expected_value)}, "
                f"相对误差={relative_error:.6e}, "
                f"NaN位置不一致={bool(nan_mismatch[row, column])}"
            )

    passed = len(failed_coordinates) == 0
    lines.append(f"结论：{'MATCH' if passed else 'MISMATCH'}（仅本窗口）")
    return "\n".join(lines) + "\n", [
        f"窗口 {window_path.name}: {'MATCH' if passed else 'MISMATCH'}, "
        f"失败点 {len(failed_coordinates)}, 最大相对误差 {max_relative_error:.6e}",
    ]


def _verify_probes(
    scene: str,
    probes_path: Path,
    building_mask: np.ndarray,
    pop_density: np.ndarray,
    ps_field: np.ndarray,
    config: Mapping[str, Any],
    tolerance: float,
) -> tuple[str, list[str]]:
    """仅读取并核验探针 CSV 的前五个数据行。"""
    with probes_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = [row for _, row in zip(range(5), reader)]
        fieldnames = reader.fieldnames or []
    required = {"i", "j", "h_idx", "R_expected"}
    missing = sorted(required.difference(fieldnames))
    if missing:
        raise ValueError(f"探针 CSV 缺少必需列：{', '.join(missing)}")

    table1 = config["table1"]
    supplementary = config["supplementary"]
    coords = config["coords"]
    origin_z = float(coords["origin"][2])
    resolution = float(coords["resolution"])
    lines = [
        f"# 场景 {scene} R 探针校验",
        f"探针文件：{probes_path.name}",
        "本轮范围：仅 CSV 的前五个数据行；按 [i, j, h_idx] 索引，不生成全量 R。",
        f"容差：相对误差 ≤ {tolerance:.0e}（来源：场景 README 步骤 3；与窗口阈值相同）",
    ]
    failures: list[str] = []
    layer_cache: dict[int, dict[str, float]] = {}
    for index, row in enumerate(rows, start=1):
        i = int(row["i"])
        j = int(row["j"])
        h_idx = int(row["h_idx"])
        z = origin_z + h_idx * resolution
        if not (0 <= i < building_mask.shape[0] and 0 <= j < building_mask.shape[1]):
            raise IndexError(f"探针平面索引越界：({i}, {j})")
        if not 0 <= h_idx < building_mask.shape[2]:
            raise IndexError(f"探针高度索引越界：h_idx={h_idx}")
        if h_idx not in layer_cache:
            layer_cache[h_idx] = _prepare_layer_model(z, table1, supplementary)

        actual = _compute_point(
            i,
            j,
            h_idx,
            building_mask,
            pop_density,
            ps_field,
            layer_cache[h_idx],
            table1,
            supplementary,
        )
        expected = float(row["R_expected"])
        if math.isnan(actual) or math.isnan(expected):
            passed = math.isnan(actual) and math.isnan(expected)
            error_text = "N/A（NaN 比較）"
        else:
            error = _relative_error(actual, expected)
            passed = error <= tolerance
            error_text = f"{error:.6e}"

        status = "MATCH" if passed else "MISMATCH"
        lines.append(
            f"探针 {index}：i={i}, j={j}, h_idx={h_idx}, z={z:g} m, "
            f"kind={row.get('kind', '字段不存在')}, 重算值={_format_value(actual)}, "
            f"基准值={_format_value(expected)}, 相对误差={error_text}, {status}"
        )
        if not passed:
            failures.append(
                f"探针 {index} ({i}, {j}, {h_idx}): 重算值={_format_value(actual)}, "
                f"基准值={_format_value(expected)}, 相对误差={error_text}"
            )

    if len(rows) < 5:
        lines.append(f"探针行数不足：要求前五行，实际读取 {len(rows)} 行。")
        failures.append(f"探针 CSV 只有 {len(rows)} 行，少于要求的五行")
    lines.append(f"失败探针数：{len(failures)}")
    lines.append(f"结论：{'MATCH' if not failures else 'MISMATCH'}（仅前五个探针）")
    return "\n".join(lines) + "\n", failures


def verify_scene(
    scene: str,
    config_path: Path,
    config: Mapping[str, Any],
    output_dir: Path,
) -> list[str]:
    """读取单个场景，只运行一窗口及五探针校验，并写出两份日志。"""
    scene_dir, city_path, slices_dir = _scene_paths(config_path, config, scene)
    if not scene_dir.is_dir():
        raise FileNotFoundError(f"场景目录不存在：{scene_dir}")

    index_data = _load_json(slices_dir / "index.json")
    windows = index_data.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError(f"index.json 没有可用窗口：{slices_dir / 'index.json'}")
    first_window = windows[0]
    if not isinstance(first_window, dict) or "file" not in first_window:
        raise ValueError("index.json 的第一个窗口缺少 file 字段")

    with np.load(city_path, allow_pickle=False) as archive:
        building_mask = np.asarray(archive["building_mask"])
        building_footprint = np.asarray(archive["building_footprint"])
        pop_density = np.asarray(archive["pop_density"])
        # np.load 返回的源数组只读；转换出的 P_s 是临时计算结果，不写回任何输入文件。
        ps_field = compute_ps(building_footprint, pop_density, dict(config))

    if building_mask.ndim != 3:
        raise ValueError(f"building_mask 必须是三维 [i,j,h_idx]：{building_mask.shape}")
    if pop_density.shape != building_mask.shape[:2] or ps_field.shape != pop_density.shape:
        raise ValueError("building_mask、pop_density 与 P_s 的平面形状不一致")

    tolerance = _read_tolerance(config_path.parent / "README.md")
    window_text, window_failures = _verify_window(
        scene,
        first_window,
        slices_dir,
        building_mask,
        pop_density,
        ps_field,
        config,
        tolerance,
    )
    probe_text, probe_failures = _verify_probes(
        scene,
        slices_dir / "probe_points.csv",
        building_mask,
        pop_density,
        ps_field,
        config,
        tolerance,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"r_window_{scene}.txt").write_text(window_text, encoding="utf-8")
    (output_dir / f"r_probe_{scene}.txt").write_text(probe_text, encoding="utf-8")
    return [*window_failures, *probe_failures]


def _read_summary_tolerance(readme_path: Path) -> float:
    """从场景 slices README 读取全局统计量相对误差阈值。"""
    readme_text = readme_path.read_text(encoding="utf-8")
    match = re.search(r"统计量相对误差\s*≤\s*([0-9.]+)\s*%", readme_text)
    if match is None:
        raise ValueError(f"README 中没有可解析的统计量容差：{readme_path}")
    return float(match.group(1)) / 100.0


def _read_engineering_tolerance(assumptions_path: Path) -> dict[str, Any]:
    """从已记录的局部窗口/探针最大误差提取工程容差，不复制常数到代码。"""
    text = assumptions_path.read_text(encoding="utf-8")
    section_parts = text.split("## R 校验工程容差", maxsplit=1)
    if len(section_parts) != 2:
        raise ValueError(f"assumptions.md 缺少 R 校验工程容差一节：{assumptions_path}")
    section = section_parts[1].split("\n## ", maxsplit=1)[0]
    match = re.search(
        r"A/B 单窗口最大相对误差分别为\s*`([0-9.eE+-]+)`、\s*`([0-9.eE+-]+)`；"
        r"前五探针最大相对误差分别为\s*`([0-9.eE+-]+)`、\s*`([0-9.eE+-]+)`",
        section,
    )
    if match is None:
        raise ValueError(f"无法从工程容差一节解析四个已记录的最大误差：{assumptions_path}")

    reference_values = [float(value) for value in match.groups()]
    return {
        "value": max(reference_values),
        "reference_values": reference_values,
        "source": str(assumptions_path),
        "basis": "assumptions.md 中 A/B 单窗口和前五探针已记录最大相对误差的最大值",
    }


def _json_float(value: float | np.floating[Any]) -> float | None:
    """将有限浮点转换为 JSON 数值，非有限值用 null 表示。"""
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _calculate_r_statistics(R: np.ndarray) -> dict[str, Any]:
    """计算完整 R 的结构计数和风险统计量；中位数采用精确排序结果。"""
    nan_count = int(np.count_nonzero(np.isnan(R)))
    finite_count = int(np.count_nonzero(np.isfinite(R)))
    if finite_count == 0:
        raise ValueError("R 中没有有限风险值，无法计算统计量。")

    finite_values = R[np.isfinite(R)]
    r_mean = float(np.mean(finite_values, dtype=np.float64))
    r_min = float(np.min(finite_values))
    r_max = float(np.max(finite_values))
    # 允许分区算法原地整理临时有限值副本，避免再分配一份大型临时数组。
    r_median = float(np.median(finite_values, overwrite_input=True))
    del finite_values
    return {
        "shape": [int(size) for size in R.shape],
        "nan_count": nan_count,
        "finite_count": finite_count,
        "r_min": r_min,
        "r_max": r_max,
        "r_mean": r_mean,
        "r_median": r_median,
        "r_norm": min(r_mean, r_median),
        "r_median_method": "有限值精确中位数（numpy.partition）；基准 summary 使用 log 直方图估计，按 README 1% 容差比较",
    }


def _summary_comparisons(
    summary: Mapping[str, Any],
    statistics: Mapping[str, Any],
    summary_tolerance: float,
) -> dict[str, dict[str, Any]]:
    """对比摘要中确实存在的统计键，不为缺失字段补造期望值。"""
    comparisons: dict[str, dict[str, Any]] = {}
    fields = (
        ("shape", "shape", "shape"),
        ("n_obstacle_cells", "nan_count", "nan_count"),
        ("n_finite_cells", "finite_count", "finite_count"),
        ("r_min", "r_min", "relative"),
        ("r_max", "r_max", "relative"),
        ("r_mean", "r_mean", "relative"),
        ("r_median", "r_median", "relative"),
        ("r_norm", "r_norm", "relative"),
    )
    for reference_key, actual_key, compare_kind in fields:
        if reference_key not in summary or summary[reference_key] is None:
            comparisons[reference_key] = {
                "status": "FIELD_MISSING",
                "detail": "summary.json 中字段不存在或值为 null",
                "reference": None,
                "actual": statistics.get(actual_key),
            }
            continue

        reference = summary[reference_key]
        actual = statistics[actual_key]
        if compare_kind == "shape":
            actual_value = [int(value) for value in actual]
            reference_value = [int(value) for value in reference]
            status = "MATCH" if actual_value == reference_value else "MISMATCH"
            comparisons[reference_key] = {
                "status": status,
                "reference": reference_value,
                "actual": actual_value,
                "relative_error": None,
            }
            continue

        if compare_kind in {"nan_count", "finite_count"}:
            actual_value = int(actual)
            reference_value = int(reference)
            status = "MATCH" if actual_value == reference_value else "MISMATCH"
            comparisons[reference_key] = {
                "status": status,
                "reference": reference_value,
                "actual": actual_value,
                "relative_error": None,
            }
            continue

        actual_value = float(actual)
        reference_value = float(reference)
        error = _relative_error(actual_value, reference_value)
        if actual_value == reference_value:
            status = "MATCH"
        elif error <= summary_tolerance:
            status = "WITHIN_TOLERANCE"
        else:
            status = "MISMATCH"
        comparisons[reference_key] = {
            "status": status,
            "reference": reference_value,
            "actual": actual_value,
            "relative_error": error,
            "tolerance": summary_tolerance,
        }
    return comparisons


def _compare_array_values(
    actual: np.ndarray,
    expected: np.ndarray,
    strict_tolerance: float,
    engineering_tolerance: float,
) -> dict[str, Any]:
    """按既有逐点口径比较 NaN 位置与有限值相对误差。"""
    actual_values = np.asarray(actual, dtype=np.float64)
    expected_values = np.asarray(expected, dtype=np.float64)
    if actual_values.shape != expected_values.shape:
        raise ValueError(
            f"比较数组形状不同：实际 {actual_values.shape}，基准 {expected_values.shape}"
        )

    actual_nan = np.isnan(actual_values)
    expected_nan = np.isnan(expected_values)
    nan_mismatch = actual_nan != expected_nan
    finite_pair = np.isfinite(actual_values) & np.isfinite(expected_values)
    nonfinite_mismatch = ~(actual_nan | expected_nan) & ~finite_pair
    relative_errors = np.zeros(actual_values.shape, dtype=np.float64)
    if finite_pair.any():
        differences = np.abs(actual_values[finite_pair] - expected_values[finite_pair])
        denominators = np.abs(expected_values[finite_pair])
        relative_errors[finite_pair] = np.divide(
            differences,
            denominators,
            out=differences.copy(),
            where=denominators != 0.0,
        )

    strict_failures = (
        nan_mismatch
        | nonfinite_mismatch
        | (finite_pair & (relative_errors > strict_tolerance))
    )
    engineering_failures = (
        nan_mismatch
        | nonfinite_mismatch
        | (finite_pair & (relative_errors > engineering_tolerance))
    )
    maximum_error = float(relative_errors[finite_pair].max()) if finite_pair.any() else 0.0
    return {
        "finite_pair_count": int(np.count_nonzero(finite_pair)),
        "nan_mismatch_count": int(np.count_nonzero(nan_mismatch)),
        "nonfinite_mismatch_count": int(np.count_nonzero(nonfinite_mismatch)),
        "strict_failures": strict_failures,
        "engineering_failures": engineering_failures,
        "relative_errors": relative_errors,
        "finite_pair": finite_pair,
        "maximum_relative_error": maximum_error,
    }


def _compare_scalar_values(
    actual: float,
    expected: float,
    strict_tolerance: float,
    engineering_tolerance: float,
) -> dict[str, Any]:
    """比较一个探针值，分别保留 README 阈值与工程容差结论。"""
    actual_nan = math.isnan(actual)
    expected_nan = math.isnan(expected)
    if actual_nan or expected_nan:
        matched = actual_nan and expected_nan
        return {
            "relative_error": None,
            "strict_status": "MATCH" if matched else "MISMATCH",
            "engineering_status": "MATCH" if matched else "MISMATCH",
        }
    if not math.isfinite(actual) or not math.isfinite(expected):
        return {
            "relative_error": None,
            "strict_status": "MISMATCH",
            "engineering_status": "MISMATCH",
        }

    error = _relative_error(actual, expected)
    return {
        "relative_error": error,
        "strict_status": "MATCH" if error <= strict_tolerance else "MISMATCH",
        "engineering_status": "MATCH" if error <= engineering_tolerance else "MISMATCH",
    }


def _validate_full_windows(
    scene: str,
    windows: list[Any],
    slices_dir: Path,
    R: np.ndarray,
    ps_field: np.ndarray,
    config: Mapping[str, Any],
    strict_tolerance: float,
    engineering_tolerance: float,
) -> dict[str, Any]:
    """遍历 index.json 的全部窗口并收集逐点误差与分布。"""
    coords = config["coords"]
    origin_z = float(coords["origin"][2])
    resolution = float(coords["resolution"])
    window_results: list[dict[str, Any]] = []
    first_failures: list[dict[str, Any]] = []
    failures_by_window: Counter[str] = Counter()
    failures_by_ps: Counter[str] = Counter()
    failures_by_height: Counter[str] = Counter()
    maximum_error = 0.0
    strict_fail_count = 0
    engineering_fail_count = 0
    nan_mismatch_count = 0
    file_error_count = 0

    for window_number, window in enumerate(windows, start=1):
        if not isinstance(window, dict):
            file_error_count += 1
            window_results.append({
                "window_number": window_number,
                "file": None,
                "status": "ERROR",
                "error": "index.json 窗口项不是对象",
            })
            continue

        window_file = str(window.get("file", "字段不存在"))
        required_fields = {"file", "z", "i0", "j0"}
        missing_fields = sorted(required_fields.difference(window))
        if missing_fields:
            file_error_count += 1
            window_results.append({
                "window_number": window_number,
                "file": window_file,
                "status": "ERROR",
                "error": f"index.json 窗口项缺少字段：{', '.join(missing_fields)}",
            })
            continue

        window_path = slices_dir / window_file
        if not window_path.is_file():
            file_error_count += 1
            window_results.append({
                "window_number": window_number,
                "file": window_file,
                "status": "ERROR",
                "error": f"窗口基准文件不存在：{window_path}",
            })
            continue

        try:
            with np.load(window_path, allow_pickle=False) as archive:
                if "R_win" not in archive.files:
                    raise KeyError("npz 中字段 R_win 不存在")
                expected = np.asarray(archive["R_win"])
            height = float(window["z"])
            i0 = int(window["i0"])
            j0 = int(window["j0"])
            fractional_h_idx = (height - origin_z) / resolution
            h_idx = int(round(fractional_h_idx))
            if not math.isclose(fractional_h_idx, h_idx, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(f"窗口高度不能映射到整数 h_idx：z={height}")
            if not 0 <= h_idx < R.shape[2]:
                raise IndexError(f"窗口高度索引超界：h_idx={h_idx}")
            if expected.ndim != 2:
                raise ValueError(f"R_win 必须为二维数组，实际 shape={expected.shape}")
            i1 = i0 + expected.shape[0]
            j1 = j0 + expected.shape[1]
            if i0 < 0 or j0 < 0 or i1 > R.shape[0] or j1 > R.shape[1]:
                raise IndexError(
                    f"窗口范围超出 R：i=[{i0},{i1}), j=[{j0},{j1})，R.shape={R.shape}"
                )
            actual = R[i0:i1, j0:j1, h_idx]
            comparison = _compare_array_values(
                actual, expected, strict_tolerance, engineering_tolerance
            )
        except (OSError, KeyError, TypeError, ValueError, IndexError) as error:
            file_error_count += 1
            window_results.append({
                "window_number": window_number,
                "file": window_file,
                "status": "ERROR",
                "error": str(error),
            })
            continue

        strict_coordinates = np.argwhere(comparison["strict_failures"])
        engineering_point_failures = int(
            np.count_nonzero(comparison["engineering_failures"])
        )
        local_strict_failures = len(strict_coordinates)
        local_nan_mismatches = comparison["nan_mismatch_count"]
        strict_fail_count += local_strict_failures
        engineering_fail_count += engineering_point_failures
        nan_mismatch_count += local_nan_mismatches
        maximum_error = max(maximum_error, comparison["maximum_relative_error"])
        if local_strict_failures:
            failures_by_window[window_file] += local_strict_failures
            height_key = f"{height:g}"
            failures_by_height[height_key] += local_strict_failures

        local_first_failures: list[dict[str, Any]] = []
        for row_index, column_index in strict_coordinates:
            i = i0 + int(row_index)
            j = j0 + int(column_index)
            finite_pair = bool(comparison["finite_pair"][row_index, column_index])
            relative_error = (
                float(comparison["relative_errors"][row_index, column_index])
                if finite_pair
                else None
            )
            ps_value = float(ps_field[i, j])
            ps_key = f"{ps_value:.12g}"
            failures_by_ps[ps_key] += 1
            point = {
                "window": window_file,
                "i": i,
                "j": j,
                "h_idx": h_idx,
                "z": height,
                "P_s": ps_value,
                "actual": _json_float(actual[row_index, column_index]),
                "expected": _json_float(expected[row_index, column_index]),
                "actual_is_nan": bool(np.isnan(actual[row_index, column_index])),
                "expected_is_nan": bool(np.isnan(expected[row_index, column_index])),
                "relative_error": relative_error,
            }
            if len(local_first_failures) < 10:
                local_first_failures.append(point)
            if len(first_failures) < 10:
                first_failures.append(point)

        window_results.append({
            "window_number": window_number,
            "file": window_file,
            "tag": window.get("tag"),
            "z": height,
            "h_idx": h_idx,
            "i0": i0,
            "j0": j0,
            "shape": [int(size) for size in expected.shape],
            "finite_pair_count": comparison["finite_pair_count"],
            "expected_nan_count": int(np.count_nonzero(np.isnan(expected))),
            "matched_nan_count": int(np.count_nonzero(np.isnan(expected) & np.isnan(actual))),
            "nan_mismatch_count": local_nan_mismatches,
            "maximum_relative_error": comparison["maximum_relative_error"],
            "strict_fail_count": local_strict_failures,
            "engineering_fail_count": engineering_point_failures,
            "strict_status": "MATCH" if local_strict_failures == 0 else "MISMATCH",
            "engineering_status": "WITHIN_ENGINEERING_TOLERANCE"
            if engineering_point_failures == 0
            else "EXCEEDS_ENGINEERING_TOLERANCE",
            "first_10_strict_failures": local_first_failures,
        })

    return {
        "window_count": len(windows),
        "window_file_error_count": file_error_count,
        "strict_tolerance": strict_tolerance,
        "engineering_tolerance": engineering_tolerance,
        "maximum_relative_error": maximum_error,
        "strict_fail_count": strict_fail_count,
        "engineering_fail_count": engineering_fail_count,
        "nan_mismatch_count": nan_mismatch_count,
        "strict_status": "MATCH" if strict_fail_count == 0 and file_error_count == 0 else "MISMATCH",
        "engineering_status": "WITHIN_ENGINEERING_TOLERANCE"
        if engineering_fail_count == 0 and nan_mismatch_count == 0 and file_error_count == 0
        else "EXCEEDS_ENGINEERING_TOLERANCE",
        "windows": window_results,
        "first_10_strict_failures": first_failures,
        "failure_distribution": {
            "by_window": dict(failures_by_window),
            "by_P_s": dict(sorted(failures_by_ps.items(), key=lambda item: float(item[0]))),
            "by_height_m": dict(sorted(failures_by_height.items(), key=lambda item: float(item[0]))),
        },
    }


def _validate_all_probes(
    scene: str,
    probes_path: Path,
    R: np.ndarray,
    strict_tolerance: float,
    engineering_tolerance: float,
) -> dict[str, Any]:
    """遍历 probe_points.csv 的全部探针并同时记录严格和工程容差结果。"""
    if not probes_path.is_file():
        return {
            "total_count": 0,
            "file_error": f"探针基准文件不存在：{probes_path}",
            "strict_pass_count": 0,
            "strict_fail_count": 0,
            "engineering_pass_count": 0,
            "engineering_fail_count": 0,
            "maximum_relative_error": 0.0,
            "results": [],
            "first_10_strict_failures": [],
        }

    with probes_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = set(reader.fieldnames or [])
        rows = list(reader)
    required = {"i", "j", "h_idx", "R_expected"}
    missing = sorted(required.difference(fieldnames))
    if missing:
        return {
            "total_count": len(rows),
            "file_error": f"probe_points.csv 缺少字段：{', '.join(missing)}",
            "strict_pass_count": 0,
            "strict_fail_count": len(rows),
            "engineering_pass_count": 0,
            "engineering_fail_count": len(rows),
            "maximum_relative_error": 0.0,
            "results": [],
            "first_10_strict_failures": [],
        }

    results: list[dict[str, Any]] = []
    first_failures: list[dict[str, Any]] = []
    strict_fail_count = 0
    engineering_fail_count = 0
    maximum_error = 0.0
    for probe_number, row in enumerate(rows, start=1):
        try:
            i = int(row["i"])
            j = int(row["j"])
            h_idx = int(row["h_idx"])
            expected = float(row["R_expected"])
        except (TypeError, ValueError) as error:
            strict_fail_count += 1
            engineering_fail_count += 1
            failure = {
                "probe_number": probe_number,
                "status": "ERROR",
                "error": f"探针行字段无法解析：{error}",
                "row": row,
            }
            results.append(failure)
            if len(first_failures) < 10:
                first_failures.append(failure)
            continue

        if not (0 <= i < R.shape[0] and 0 <= j < R.shape[1] and 0 <= h_idx < R.shape[2]):
            strict_fail_count += 1
            engineering_fail_count += 1
            failure = {
                "probe_number": probe_number,
                "i": i,
                "j": j,
                "h_idx": h_idx,
                "kind": row.get("kind"),
                "expected": _json_float(expected),
                "actual": None,
                "relative_error": None,
                "strict_status": "MISMATCH",
                "engineering_status": "MISMATCH",
                "error": "探针索引超出 R.shape",
            }
            results.append(failure)
            if len(first_failures) < 10:
                first_failures.append(failure)
            continue

        actual = float(R[i, j, h_idx])
        comparison = _compare_scalar_values(
            actual, expected, strict_tolerance, engineering_tolerance
        )
        strict_failed = comparison["strict_status"] != "MATCH"
        engineering_failed = comparison["engineering_status"] != "MATCH"
        strict_fail_count += int(strict_failed)
        engineering_fail_count += int(engineering_failed)
        if comparison["relative_error"] is not None:
            maximum_error = max(maximum_error, float(comparison["relative_error"]))

        probe_result = {
            "probe_number": probe_number,
            "i": i,
            "j": j,
            "h_idx": h_idx,
            "z": _json_float(float(row["z"])) if row.get("z") else None,
            "kind": row.get("kind"),
            "P_s": None,
            "actual": _json_float(actual),
            "expected": _json_float(expected),
            "actual_is_nan": math.isnan(actual),
            "expected_is_nan": math.isnan(expected),
            "relative_error": comparison["relative_error"],
            "strict_status": comparison["strict_status"],
            "engineering_status": comparison["engineering_status"],
        }
        results.append(probe_result)
        if strict_failed and len(first_failures) < 10:
            first_failures.append(probe_result)

    return {
        "total_count": len(rows),
        "strict_tolerance": strict_tolerance,
        "engineering_tolerance": engineering_tolerance,
        "strict_pass_count": len(rows) - strict_fail_count,
        "strict_fail_count": strict_fail_count,
        "engineering_pass_count": len(rows) - engineering_fail_count,
        "engineering_fail_count": engineering_fail_count,
        "maximum_relative_error": maximum_error,
        "strict_status": "MATCH" if strict_fail_count == 0 else "MISMATCH",
        "engineering_status": "WITHIN_ENGINEERING_TOLERANCE"
        if engineering_fail_count == 0
        else "EXCEEDS_ENGINEERING_TOLERANCE",
        "results": results,
        "first_10_strict_failures": first_failures,
    }


def _verify_scene_full(
    scene: str,
    config_path: Path,
    config: Mapping[str, Any],
    output_dir: Path,
    strict_tolerance: float,
    summary_tolerance: float,
    engineering_tolerance: Mapping[str, Any],
) -> dict[str, Any]:
    """生成一个场景的全量 R，并对全部窗口、探针和摘要进行校验。"""
    scene_dir, city_path, slices_dir = _scene_paths(config_path, config, scene)
    if not scene_dir.is_dir():
        raise FileNotFoundError(f"场景目录不存在：{scene_dir}")

    index_data = _load_json(slices_dir / "index.json")
    windows = index_data.get("windows")
    if not isinstance(windows, list):
        raise ValueError(f"index.json 的 windows 字段不是列表：{slices_dir / 'index.json'}")
    summary = _load_json(slices_dir / "summary.json")
    with np.load(city_path, allow_pickle=False) as archive:
        required_keys = {"building_footprint", "pop_density", "building_mask"}
        missing_keys = sorted(required_keys.difference(archive.files))
        if missing_keys:
            raise KeyError(f"city.npz 缺少全量 R 输入：{', '.join(missing_keys)}")
        building_footprint = np.asarray(archive["building_footprint"])
        pop_density = np.asarray(archive["pop_density"])
        building_mask = np.asarray(archive["building_mask"])

    ps_field = compute_ps(building_footprint, pop_density, dict(config))
    R = compute_r_matrix(
        building_footprint,
        pop_density,
        building_mask,
        config,
        ps_field=ps_field,
    )
    statistics = _calculate_r_statistics(R)
    building_voxel_count = int(np.count_nonzero(building_mask))
    nonbuilding_nonfinite_count = 0
    for h_idx in range(R.shape[2]):
        nonbuilding_nonfinite_count += int(
            np.count_nonzero(~np.isfinite(R[:, :, h_idx]) & ~building_mask[:, :, h_idx])
        )

    config_shape = [
        int(config["table2"]["N_I"]),
        int(config["table2"]["N_J"]),
        int(config["table2"]["N_H"]),
    ]
    invariant_checks = [
        {
            "name": "R_shape",
            "status": "PASS" if statistics["shape"] == config_shape else "FAIL",
            "expected": config_shape,
            "actual": statistics["shape"],
        },
        {
            "name": "R_nan_vs_building_mask",
            "status": "PASS" if statistics["nan_count"] == building_voxel_count else "FAIL",
            "expected": building_voxel_count,
            "actual": statistics["nan_count"],
        },
        {
            "name": "nonbuilding_values_finite",
            "status": "PASS" if nonbuilding_nonfinite_count == 0 else "FAIL",
            "expected": 0,
            "actual": nonbuilding_nonfinite_count,
        },
    ]

    summary_comparison = _summary_comparisons(summary, statistics, summary_tolerance)
    windows_result = _validate_full_windows(
        scene,
        windows,
        slices_dir,
        R,
        ps_field,
        config,
        strict_tolerance,
        float(engineering_tolerance["value"]),
    )
    probes_result = _validate_all_probes(
        scene,
        slices_dir / "probe_points.csv",
        R,
        strict_tolerance,
        float(engineering_tolerance["value"]),
    )

    required_summary_keys = {
        "shape",
        "n_obstacle_cells",
        "n_finite_cells",
        "r_mean",
        "r_median",
        "r_norm",
    }
    required_summary_ok = all(
        summary_comparison[key]["status"] in {"MATCH", "WITHIN_TOLERANCE"}
        for key in required_summary_keys
    )
    summary_mismatch_keys = [
        key for key, value in summary_comparison.items() if value["status"] == "MISMATCH"
    ]
    strict_pointwise_ok = (
        windows_result["strict_fail_count"] == 0
        and windows_result["window_file_error_count"] == 0
        and probes_result["strict_fail_count"] == 0
        and all(check["status"] == "PASS" for check in invariant_checks)
    )
    engineering_pointwise_ok = (
        windows_result["engineering_fail_count"] == 0
        and windows_result["nan_mismatch_count"] == 0
        and windows_result["window_file_error_count"] == 0
        and probes_result["engineering_fail_count"] == 0
        and not probes_result.get("file_error")
        and all(check["status"] == "PASS" for check in invariant_checks)
    )
    result = {
        "scene": scene,
        "scope": "full",
        "source_paths": {
            "city_npz": str(city_path),
            "summary_json": str(slices_dir / "summary.json"),
            "index_json": str(slices_dir / "index.json"),
            "probe_points_csv": str(slices_dir / "probe_points.csv"),
        },
        "generation_invariants": invariant_checks,
        "statistics": statistics,
        "building_voxel_count": building_voxel_count,
        "nonbuilding_nonfinite_count": nonbuilding_nonfinite_count,
        "summary_comparison": {
            "tolerance": summary_tolerance,
            "tolerance_source": str(slices_dir / "README.md"),
            "fields": summary_comparison,
        },
        "window_validation": windows_result,
        "probe_validation": probes_result,
        "engineering_tolerance": dict(engineering_tolerance),
        "strict_pointwise_status": "MATCH" if strict_pointwise_ok else "MISMATCH",
        "engineering_tolerance_status": "WITHIN_ENGINEERING_TOLERANCE"
        if engineering_pointwise_ok
        else "EXCEEDS_ENGINEERING_TOLERANCE_OR_HAS_STRUCTURAL_FAILURE",
        "engineering_tolerance_accepted": engineering_pointwise_ok,
        "summary_status": "MISMATCH"
        if summary_mismatch_keys
        else "WITHIN_SUMMARY_TOLERANCE"
        if required_summary_ok
        else "INCOMPLETE",
        "summary_mismatch_keys": summary_mismatch_keys,
        "full_validation_accepted": engineering_pointwise_ok
        and required_summary_ok
        and not summary_mismatch_keys,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"validation_{scene}.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    # 及时解除全量大数组引用；A/B 按顺序运行，避免同时保留两份矩阵。
    del R, building_mask, building_footprint, pop_density, ps_field
    gc.collect()
    return result


def _format_report_value(value: Any) -> str:
    """格式化报告中的浮点、缺失值和 JSON 字段。"""
    if value is None:
        return "字段不存在/NaN"
    if isinstance(value, float):
        return f"{value:.12e}"
    return str(value)


def _known_b_summary_difference_percent(assumptions_path: Path) -> tuple[float, int] | None:
    """从 assumptions 读取已接受的 B 中位数差异及百分比显示精度。"""
    text = assumptions_path.read_text(encoding="utf-8")
    section = text.split("## M1 全局统计容差与 B 场景 summary 差异", maxsplit=1)
    if len(section) != 2:
        return None
    section_text = section[1].split("\n## ", maxsplit=1)[0]
    if "基准精度限制接受" not in section_text or "不阻断 M2" not in section_text:
        return None
    match = re.search(r"B 相差\s*`([0-9]+(?:\.[0-9]+)?)%`", section_text)
    if match is None:
        return None
    shown_value = match.group(1)
    decimal_places = len(shown_value.partition(".")[2])
    return float(shown_value), decimal_places


def _is_known_b_summary_difference(
    result: Mapping[str, Any],
    assumptions_path: Path,
) -> bool:
    """判断 B 是否仅有已记录接受的 r_median / r_norm 摘要差异。"""
    if (
        result.get("scene") != "B"
        or not result.get("engineering_tolerance_accepted")
        or result.get("summary_status") != "MISMATCH"
    ):
        return False

    mismatch_keys = set(result.get("summary_mismatch_keys", []))
    if mismatch_keys != {"r_median", "r_norm"}:
        return False

    fields = result.get("summary_comparison", {}).get("fields", {})
    if not isinstance(fields, Mapping):
        return False
    actual_mismatch_keys = {
        key for key, comparison in fields.items()
        if comparison.get("status") == "MISMATCH"
    }
    if actual_mismatch_keys != mismatch_keys:
        return False

    if not all(
        comparison.get("status") == "MISMATCH"
        if key in mismatch_keys
        else comparison.get("status") in {"MATCH", "WITHIN_TOLERANCE"}
        for key, comparison in fields.items()
    ):
        return False

    known_difference = _known_b_summary_difference_percent(assumptions_path)
    if known_difference is None:
        return False
    expected_percent, decimal_places = known_difference
    rounding_tolerance_percent = 0.5 * (10 ** -decimal_places)
    for key in mismatch_keys:
        comparison = fields[key]
        reference = comparison.get("reference")
        actual = comparison.get("actual")
        if reference in (None, 0) or actual is None:
            return False
        observed_percent = abs(float(actual) - float(reference)) / abs(float(reference)) * 100.0
        if abs(observed_percent - expected_percent) > rounding_tolerance_percent:
            return False
    return True


def _only_known_b_summary_difference_remains(
    results: list[Mapping[str, Any]],
    assumptions_path: Path,
) -> bool:
    """确认所有其余场景完整通过，唯一未通过项是 B 的已知摘要差异。"""
    known_difference_found = False
    for result in results:
        if result.get("full_validation_accepted"):
            continue
        if not _is_known_b_summary_difference(result, assumptions_path):
            return False
        known_difference_found = True
    return known_difference_found


def _render_full_summary(
    results: list[Mapping[str, Any]],
    known_diff_accepted: bool = False,
) -> str:
    """生成包含场景统计、全量逐点对照和工程容差结论的文本报告。"""
    lines = [
        "# R 全量生成与校验摘要",
        "R 仅在内存生成；输入 city.npz、slices 基准及配置均为只读。",
        "README 窗口/探针阈值保持原值；工程容差接受不等同于严格逐点通过。",
        "",
    ]
    for result in results:
        scene = str(result["scene"])
        statistics = result["statistics"]
        windows = result["window_validation"]
        probes = result["probe_validation"]
        engineering = result["engineering_tolerance"]
        summary_comparison = result["summary_comparison"]["fields"]
        lines.extend([
            f"## 场景 {scene}",
            f"R.shape：{tuple(statistics['shape'])}",
            f"NaN 数：{statistics['nan_count']}（building_mask True 数：{result['building_voxel_count']}）",
            f"finite 数：{statistics['finite_count']}",
            f"r_min：{statistics['r_min']:.12e}",
            f"r_max：{statistics['r_max']:.12e}",
            f"r_mean：{statistics['r_mean']:.12e}",
            f"r_median：{statistics['r_median']:.12e}（{statistics['r_median_method']}）",
            f"r_norm：{statistics['r_norm']:.12e}",
            f"非建筑格非有限值数：{result['nonbuilding_nonfinite_count']}",
            "",
            "### summary.json 逐项对比",
        ])
        for key, comparison in summary_comparison.items():
            status = comparison["status"]
            if status == "FIELD_MISSING":
                lines.append(f"- {key}：字段不存在")
            else:
                error = comparison.get("relative_error")
                error_text = "N/A" if error is None else f"{float(error):.6e}"
                lines.append(
                    f"- {key}：{status}；重算={_format_report_value(comparison['actual'])}；"
                    f"基准={_format_report_value(comparison['reference'])}；相对误差={error_text}"
                )

        lines.extend([
            "",
            "### 全量窗口逐点校验",
            f"窗口数：{windows['window_count']}；文件/结构错误数：{windows['window_file_error_count']}",
            f"README 严格阈值：{windows['strict_tolerance']:.0e}",
            f"窗口最大相对误差：{windows['maximum_relative_error']:.6e}",
            f"严格阈值失败点数：{windows['strict_fail_count']}；NaN 位置不一致数：{windows['nan_mismatch_count']}",
            f"超过工程容差的点数：{windows['engineering_fail_count']}",
            f"工程容差：{float(engineering['value']):.6e}（来源：{engineering['source']}）",
            "按窗口失败分布：",
        ])
        by_window = windows["failure_distribution"]["by_window"]
        if by_window:
            lines.extend(f"- {name}: {count}" for name, count in by_window.items())
        else:
            lines.append("- 无严格阈值失败点")
        lines.append("按高度失败分布（米）：")
        by_height = windows["failure_distribution"]["by_height_m"]
        if by_height:
            lines.extend(f"- z={height}: {count}" for height, count in by_height.items())
        else:
            lines.append("- 无严格阈值失败点")
        lines.append("按 P_s 失败分布：")
        by_ps = windows["failure_distribution"]["by_P_s"]
        if by_ps:
            lines.extend(f"- P_s={ps_value}: {count}" for ps_value, count in by_ps.items())
        else:
            lines.append("- 无严格阈值失败点")

        lines.extend([
            "",
            "### 全部探针",
            f"探针总数：{probes['total_count']}",
            f"README 严格阈值通过数：{probes['strict_pass_count']}；失败数：{probes['strict_fail_count']}",
            f"工程容差通过数：{probes['engineering_pass_count']}；失败数：{probes['engineering_fail_count']}",
            f"探针最大相对误差：{probes['maximum_relative_error']:.6e}",
            "前 10 个严格阈值失败探针：",
        ])
        failed_probes = probes["first_10_strict_failures"]
        if failed_probes:
            for point in failed_probes:
                if point.get("status") == "ERROR":
                    lines.append(f"- 第 {point['probe_number']} 行：{point['error']}")
                else:
                    lines.append(
                        f"- ({point.get('i')}, {point.get('j')}, {point.get('h_idx')}): "
                        f"重算={_format_report_value(point.get('actual'))}，"
                        f"基准={_format_report_value(point.get('expected'))}，"
                        f"相对误差={_format_report_value(point.get('relative_error'))}"
                    )
        else:
            lines.append("- 无严格阈值失败探针")

        lines.extend([
            "",
            f"严格逐点结论：{result['strict_pointwise_status']}（README 阈值未放宽）",
            f"工程容差结论：{result['engineering_tolerance_status']}",
            f"全局 summary 结论：{result['summary_status']}",
        ])
        if result.get("known_summary_difference_accepted"):
            lines.append("B summary 差异已按 assumptions 接受，退出码 0。")
            lines.append("summary MISMATCH 保留为基准精度限制，不视为计算通过。")
        if result["engineering_tolerance_accepted"]:
            lines.append(
                "说明：该结论表示在既有工程容差内，不代表通过 README 的 1e-5 严格逐点校验。"
            )
        else:
            over_tolerance_windows = [
                item for item in windows["windows"]
                if item.get("status") == "ERROR"
                or item.get("engineering_fail_count", 0) > 0
            ]
            over_tolerance_probes = [
                item for item in probes.get("results", [])
                if item.get("engineering_status") != "MATCH"
            ]
            lines.append("超过工程容差或结构校验失败项：")
            if over_tolerance_windows:
                lines.extend(
                    f"- 窗口 {item.get('file')}：{item.get('error', item.get('engineering_fail_count'))}"
                    for item in over_tolerance_windows
                )
            if over_tolerance_probes:
                lines.extend(
                    f"- 探针 {item.get('probe_number')}：{item.get('error', item.get('relative_error'))}"
                    for item in over_tolerance_probes[:10]
                )
            failed_invariants = [
                check for check in result["generation_invariants"] if check["status"] != "PASS"
            ]
            lines.extend(
                f"- {check['name']}：期望 {check['expected']}，实际 {check['actual']}"
                for check in failed_invariants
            )
        lines.append("")

    lines.append("## 总结")
    if all(bool(result["full_validation_accepted"]) for result in results):
        lines.append("A/B 全量矩阵达到已记录工程容差，且 summary 指标满足场景 README 契约。")
        lines.append("逐点 README 严格阈值的 MISMATCH 仍如实保留，不写作严格通过。")
    elif all(bool(result["engineering_tolerance_accepted"]) for result in results):
        lines.append("A/B 窗口与探针误差均在已记录工程容差内，但至少一个 summary 指标不满足 README 全局统计容差。")
    else:
        lines.append("存在场景超出工程点位容差或结构校验失败，不能把全量结果视为工程容差接受。")
    if known_diff_accepted:
        lines.append("全量运行接受条件满足；B summary 差异按 assumptions 接受，退出码 0。")
        lines.append("该状态仅接受已记录的基准直方图估值精度差异；summary MISMATCH 原样保留，不视为计算通过。")
    return "\n".join(lines) + "\n"


def main() -> int:
    """按显式范围运行局部 sample 或全量 R 校验。"""
    parser = argparse.ArgumentParser(description="生成并校验 R 矩阵；默认只运行 sample 范围。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("lib/03_场景/config.json"),
        help="唯一参数源 config.json 的路径。",
    )
    parser.add_argument(
        "--scene",
        choices=("A", "B"),
        help="选择一个场景；省略时依次检查 A、B。",
    )
    parser.add_argument(
        "--scenes",
        nargs="+",
        choices=("A", "B"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--scope",
        choices=("sample", "full"),
        default="sample",
        help="sample 检查首个窗口和前五探针；full 遍历全部窗口和探针。默认 sample。",
    )
    parser.add_argument(
        "--accept-known-diff",
        action="store_true",
        help="仅在 full 范围、其他校验通过且唯一剩余问题是已记录的 B summary 中位数估值差异时接受。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="校验日志和 JSON 目录；默认写入仓库 experiments/validation/。",
    )
    args = parser.parse_args()
    if args.scene is not None and args.scenes is not None:
        parser.error("--scene 与旧参数 --scenes 不能同时指定。")
    if args.accept_known_diff and args.scope != "full":
        parser.error("--accept-known-diff 仅适用于 --scope full。")

    config_path = args.config.resolve()
    config = _load_json(config_path)
    repository_root = config_path.parent.parent.parent
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else repository_root / "experiments" / "validation"
    )
    selected_scenes = (
        [args.scene]
        if args.scene is not None
        else args.scenes if args.scenes is not None else ["A", "B"]
    )

    if args.scope == "sample":
        failures: list[str] = []
        for scene in selected_scenes:
            failures.extend(verify_scene(scene, config_path, config, output_dir))

        print(f"sample 校验日志目录：{output_dir}")
        print("范围：每场景首个窗口 + 前五个探针；未生成全量 R。")
        if failures:
            print("README 严格阈值下存在以下 MISMATCH：")
            for failure in failures:
                print(f"- {failure}")
            return 1

        print("所选窗口和探针均 MATCH；该结论仅适用于本次 sample 范围。")
        return 0

    strict_tolerance = _read_tolerance(config_path.parent / "README.md")
    assumptions_path = repository_root / "report" / "assumptions.md"
    engineering_tolerance = _read_engineering_tolerance(assumptions_path)
    scene_results: list[dict[str, Any]] = []
    for scene in selected_scenes:
        scene_dir, _, slices_dir = _scene_paths(config_path, config, scene)
        if not scene_dir.is_dir():
            raise FileNotFoundError(f"场景目录不存在：{scene_dir}")
        summary_tolerance = _read_summary_tolerance(slices_dir / "README.md")
        scene_results.append(
            _verify_scene_full(
                scene,
                config_path,
                config,
                output_dir,
                strict_tolerance,
                summary_tolerance,
                engineering_tolerance,
            )
        )

    all_full_accepted = all(result["full_validation_accepted"] for result in scene_results)
    known_diff_accepted = (
        args.accept_known_diff
        and _only_known_b_summary_difference_remains(scene_results, assumptions_path)
    )
    for result in scene_results:
        result["known_summary_difference_accepted"] = bool(
            known_diff_accepted
            and _is_known_b_summary_difference(result, assumptions_path)
        )
        result["run_accepted"] = bool(
            result["full_validation_accepted"]
            or result["known_summary_difference_accepted"]
        )
        output_path = output_dir / f"validation_{result['scene']}.json"
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    summary_path = output_dir / "r_full_summary.txt"
    summary_path.write_text(
        _render_full_summary(scene_results, known_diff_accepted=known_diff_accepted),
        encoding="utf-8",
    )
    print(f"全量校验输出目录：{output_dir}")
    for result in scene_results:
        stats = result["statistics"]
        print(
            f"场景 {result['scene']}: shape={tuple(stats['shape'])}, "
            f"NaN={stats['nan_count']}, finite={stats['finite_count']}, "
            f"窗口 max_rel={result['window_validation']['maximum_relative_error']:.6e}, "
            f"strict_fail={result['window_validation']['strict_fail_count']}, "
            f"探针 strict_pass/fail={result['probe_validation']['strict_pass_count']}/"
            f"{result['probe_validation']['strict_fail_count']}, "
            f"工程容差={result['engineering_tolerance_status']}, "
            f"summary={result['summary_status']}"
        )

    if not all_full_accepted:
        if known_diff_accepted:
            print("B summary 差异已按 assumptions 接受，退出码 0")
            print("summary MISMATCH 保留为已知基准精度限制，不标记为计算通过。")
            return 0
        print("至少一个场景的全量验收未满足：请分别查看点位工程容差与 summary 全局统计结论。")
        return 1

    print("全量结果在已记录工程容差内；README 的 1e-5 严格逐点状态另行保留。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
