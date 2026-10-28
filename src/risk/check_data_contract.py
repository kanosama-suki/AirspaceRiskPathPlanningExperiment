"""Read-only checks for the scene data contract.

The checker reads configuration, city containers, existing slice references,
probe schemas, and existing ``inspect_*.txt`` reports.  It does not calculate
``P_s`` and never builds or recalculates the full risk matrix ``R``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np


REQUIRED_CITY_KEYS: tuple[str, ...] = (
    "building_mask",
    "pop_density",
    "building_footprint",
    "meta",
)
EXPECTED_PROBE_COLUMNS: tuple[str, ...] = ("i", "j", "h_idx", "z", "kind", "R_expected")


def parse_args() -> argparse.Namespace:
    """Parse paths and scene selection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scenes", nargs="+", default=None)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    """Read a UTF-8 JSON document without modifying it."""
    return json.loads(path.read_text(encoding="utf-8"))


def json_value(value: Any) -> Any:
    """Convert NumPy scalars and paths into JSON-compatible values."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    return value


def make_check(name: str, status: str, detail: str) -> dict[str, str]:
    """Create one stable check record."""
    return {"name": name, "status": status, "detail": detail}


def resolve_scene_paths(config_path: Path, config: dict[str, Any], scene_key: str) -> dict[str, Path]:
    """Resolve all read-only artifacts for one configured scene."""
    scene_name = str(config["paths"][f"scene_{scene_key}"])
    root = config_path.parent
    city_path = root / Path(str(config["paths"]["city_npz"]).replace("<scene>", scene_name, 1))
    slices_dir = root / Path(str(config["paths"]["slices_dir"]).replace("<scene>", scene_name, 1))
    scene_dir = city_path.parent
    return {
        "scene_dir": scene_dir,
        "city": city_path,
        "slices": slices_dir,
        "index": slices_dir / "index.json",
        "probes": slices_dir / "probe_points.csv",
        "summary": slices_dir / "summary.json",
        "ps_check": scene_dir / "ps_check",
        "inspect": config_path.parents[2] / "experiments" / "raw" / f"inspect_{scene_key}.txt",
    }


def expected_shape(config: dict[str, Any]) -> list[int]:
    """Get the documented three-dimensional shape from config dimensions."""
    table2 = config["table2"]
    return [int(table2["N_I"]), int(table2["N_J"]), int(table2["N_H"])]


def close_sequence(actual: Any, expected: Any) -> bool:
    """Compare coordinate metadata without accepting shape changes."""
    try:
        actual_values = [float(item) for item in actual]
        expected_values = [float(item) for item in expected]
    except (TypeError, ValueError):
        return False
    return len(actual_values) == len(expected_values) and all(
        math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
        for left, right in zip(actual_values, expected_values)
    )


def read_city(path: Path) -> tuple[list[str], dict[str, np.ndarray]]:
    """Read existing city arrays into memory, retaining no writable input handle."""
    if not path.is_file():
        return [], {}
    with np.load(path, allow_pickle=False) as data:
        keys = list(data.files)
        arrays = {key: data[key] for key in keys}
    return keys, arrays


def check_city_keys(keys: list[str]) -> dict[str, str]:
    """Check only the required city container keys."""
    missing = [key for key in REQUIRED_CITY_KEYS if key not in keys]
    if missing:
        return make_check("city_npz_keys", "FAIL", f"missing required keys: {missing}; actual keys: {keys}")
    return make_check("city_npz_keys", "PASS", f"required keys present: {list(REQUIRED_CITY_KEYS)}")


def check_building_mask(arrays: dict[str, np.ndarray], shape: list[int]) -> dict[str, str]:
    """Check the building mask shape and boolean dtype."""
    array = arrays.get("building_mask")
    if array is None:
        return make_check("building_mask_contract", "FAIL", "city.npz key building_mask is absent")
    details = f"shape={list(array.shape)}, dtype={array.dtype}, expected_shape={shape}, expected_dtype=bool"
    if list(array.shape) != shape or array.dtype != np.dtype(bool):
        return make_check("building_mask_contract", "FAIL", details)
    return make_check("building_mask_contract", "PASS", details)


def check_pop_density(arrays: dict[str, np.ndarray], plane_shape: list[int]) -> dict[str, str]:
    """Check population density structure and finite values."""
    array = arrays.get("pop_density")
    expected_dtype = np.dtype(np.float32)
    if array is None:
        return make_check("pop_density_contract", "FAIL", "city.npz key pop_density is absent")
    finite_count = int(np.isfinite(array).sum()) if np.issubdtype(array.dtype, np.inexact) else 0
    details = (
        f"shape={list(array.shape)}, dtype={array.dtype}, finite_count={finite_count}, "
        f"expected_shape={plane_shape}, expected_dtype={expected_dtype}"
    )
    if list(array.shape) != plane_shape or array.dtype != expected_dtype or finite_count != array.size:
        return make_check("pop_density_contract", "FAIL", details)
    return make_check("pop_density_contract", "PASS", details)


def check_building_footprint(arrays: dict[str, np.ndarray], plane_shape: list[int]) -> dict[str, str]:
    """Check the ground footprint shape and boolean dtype."""
    array = arrays.get("building_footprint")
    if array is None:
        return make_check("building_footprint_contract", "FAIL", "city.npz key building_footprint is absent")
    details = f"shape={list(array.shape)}, dtype={array.dtype}, expected_shape={plane_shape}, expected_dtype=bool"
    if list(array.shape) != plane_shape or array.dtype != np.dtype(bool):
        return make_check("building_footprint_contract", "FAIL", details)
    return make_check("building_footprint_contract", "PASS", details)


def check_meta(arrays: dict[str, np.ndarray], config: dict[str, Any], shape: list[int]) -> dict[str, str]:
    """Check metadata JSON and its coordinate contract."""
    meta_array = arrays.get("meta")
    if meta_array is None:
        return make_check("meta_coordinate_contract", "FAIL", "city.npz key meta is absent")
    try:
        raw_meta = meta_array.item()
        meta = json.loads(str(raw_meta))
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as error:
        return make_check("meta_coordinate_contract", "FAIL", f"meta is not valid scalar JSON: {error}")
    coords = config["coords"]
    mismatches: list[str] = []
    if meta.get("shape") != shape:
        mismatches.append(f"shape={meta.get('shape')!r}, expected={shape!r}")
    if meta.get("axes_order") != coords["axes_order"]:
        mismatches.append(f"axes_order={meta.get('axes_order')!r}, expected={coords['axes_order']!r}")
    if not close_sequence(meta.get("origin"), coords["origin"]):
        mismatches.append(f"origin={meta.get('origin')!r}, expected={coords['origin']!r}")
    try:
        resolution_matches = math.isclose(
            float(meta.get("resolution")),
            float(coords["resolution"]),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    except (TypeError, ValueError):
        resolution_matches = False
    if not resolution_matches:
        mismatches.append(f"resolution={meta.get('resolution')!r}, expected={coords['resolution']!r}")
    detail = f"metadata keys={sorted(meta)}, checked shape/axes_order/origin/resolution"
    if mismatches:
        return make_check("meta_coordinate_contract", "FAIL", detail + f"; mismatches: {mismatches}")
    return make_check("meta_coordinate_contract", "PASS", detail)


def check_config_geometry(config: dict[str, Any], shape: list[int]) -> dict[str, str]:
    """Check internal geometry and mission endpoint consistency from config."""
    table2 = config["table2"]
    mismatches: list[str] = []
    if not close_sequence(table2["SCENE_SIZE"], [table2["N_I"] * table2["GRID_SIZE"], table2["N_J"] * table2["GRID_SIZE"]]):
        mismatches.append("SCENE_SIZE does not match N_I/N_J times GRID_SIZE")
    expected_h = (float(table2["H_HIGH"]) - float(table2["H_LOW"])) / float(table2["GRID_SIZE"]) + 1
    if not math.isclose(expected_h, float(table2["N_H"]), rel_tol=1e-9, abs_tol=1e-9):
        mismatches.append("N_H does not match H_LOW/H_HIGH/GRID_SIZE")
    if shape != [int(table2["N_I"]), int(table2["N_J"]), int(table2["N_H"])]:
        mismatches.append(f"config shape={shape!r} is inconsistent")
    for mission in ("START1", "GOAL1", "START2", "GOAL2"):
        point = table2.get(mission)
        if not isinstance(point, list) or len(point) != 3:
            mismatches.append(f"{mission} is not a 3D coordinate")
            continue
        if not (0 <= point[0] < table2["N_I"] * table2["GRID_SIZE"] and 0 <= point[1] < table2["N_J"] * table2["GRID_SIZE"]):
            mismatches.append(f"{mission} is outside the horizontal scene bounds")
        if not (table2["H_LOW"] <= point[2] <= table2["H_HIGH"]):
            mismatches.append(f"{mission} is outside the height bounds")
    detail = "checked scene dimensions, height layer count, array shape, and START/GOAL coordinates"
    if mismatches:
        return make_check("config_geometry_and_endpoints", "FAIL", detail + f"; mismatches: {mismatches}")
    return make_check("config_geometry_and_endpoints", "PASS", detail)


def inspect_r_absence_note(path: Path) -> str:
    """Return a short fact from an existing inspect report, if available."""
    if not path.is_file():
        return " Existing inspect report is unavailable."
    text = path.read_text(encoding="utf-8", errors="replace")
    if "R key absent from city.npz" in text:
        return f" Existing {path.name} also records R key absent from city.npz."
    return f" Existing {path.name} was read but does not explicitly record R key absence."


def check_r_shape(arrays: dict[str, np.ndarray], expected_shape: list[int], inspect_path: Path) -> dict[str, str]:
    """Check the actual full R array shape, never a summary or window shape."""
    array = arrays.get("R")
    if array is None:
        return make_check(
            "R_shape",
            "FAIL",
            "city.npz has no R key; cannot inspect actual R.shape and must not substitute summary.shape or R_win.shape."
            + inspect_r_absence_note(inspect_path),
        )
    detail = f"actual_R_shape={list(array.shape)}, expected_from_config={expected_shape}"
    if list(array.shape) != expected_shape:
        return make_check("R_shape", "FAIL", detail)
    return make_check("R_shape", "PASS", detail)


def check_nan_vs_building(arrays: dict[str, np.ndarray], inspect_path: Path) -> dict[str, str]:
    """Compare full-R NaN cells with building-mask cells only when R exists."""
    risk = arrays.get("R")
    building = arrays.get("building_mask")
    if risk is None:
        return make_check(
            "NaN_vs_building",
            "FAIL",
            "city.npz has no R key; NaN-vs-building comparison is unavailable and no summary/window substitute is allowed."
            + inspect_r_absence_note(inspect_path),
        )
    if building is None:
        return make_check("NaN_vs_building", "FAIL", "building_mask key is absent; cannot compare against R NaN cells")
    if risk.shape != building.shape:
        return make_check(
            "NaN_vs_building",
            "FAIL",
            f"R.shape={list(risk.shape)} and building_mask.shape={list(building.shape)} differ; masks not compared",
        )
    if not np.issubdtype(risk.dtype, np.inexact):
        return make_check("NaN_vs_building", "FAIL", f"R dtype={risk.dtype} is not floating; NaN mask is undefined")
    nan_mask = np.isnan(risk)
    building_mask = building.astype(bool, copy=False)
    nan_count = int(nan_mask.sum())
    building_count = int(building_mask.sum())
    equal = bool(np.array_equal(nan_mask, building_mask))
    detail = f"R_nan_count={nan_count}, building_true_count={building_count}, exact_mask_match={equal}"
    return make_check("NaN_vs_building", "PASS" if equal else "FAIL", detail)


def check_building_mask_shape_vs_r(arrays: dict[str, np.ndarray], inspect_path: Path) -> dict[str, str]:
    """Compare building-mask shape to the actual R shape only when R exists."""
    risk = arrays.get("R")
    building = arrays.get("building_mask")
    if risk is None:
        return make_check(
            "building_mask_shape_vs_R",
            "FAIL",
            "city.npz has no R key; building_mask.shape cannot be compared to actual R.shape."
            + inspect_r_absence_note(inspect_path),
        )
    if building is None:
        return make_check("building_mask_shape_vs_R", "FAIL", "building_mask key is absent")
    detail = f"building_mask.shape={list(building.shape)}, R.shape={list(risk.shape)}"
    return make_check("building_mask_shape_vs_R", "PASS" if building.shape == risk.shape else "FAIL", detail)


def check_pop_density_shape(arrays: dict[str, np.ndarray], plane_shape: list[int]) -> dict[str, str]:
    """Check population-density shape independently of full R availability."""
    array = arrays.get("pop_density")
    if array is None:
        return make_check("pop_density_shape", "FAIL", "city.npz key pop_density is absent")
    finite_count = int(np.isfinite(array).sum()) if np.issubdtype(array.dtype, np.inexact) else 0
    detail = f"pop_density.shape={list(array.shape)}, dtype={array.dtype}, expected_shape={plane_shape}, finite_count={finite_count}"
    status = array.shape == tuple(plane_shape) and array.dtype == np.dtype(np.float32) and finite_count == array.size
    return make_check("pop_density_shape", "PASS" if status else "FAIL", detail)


def read_index_windows(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Read index metadata without reading or calculating a full risk matrix."""
    if not path.is_file():
        return [], "slices/index.json is missing"
    try:
        document = load_json(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return [], f"cannot read slices/index.json: {error}"
    windows = document.get("windows") if isinstance(document, dict) else None
    if not isinstance(windows, list):
        return [], "index.json.windows is missing or not a list"
    return [window for window in windows if isinstance(window, dict)], None


def check_indexed_files_exist(paths: dict[str, Path]) -> dict[str, str]:
    """Check indexed windows and the slices probe file exist."""
    windows, error = read_index_windows(paths["index"])
    if error:
        return make_check("indexed_files_exist", "FAIL", error)
    problems: list[str] = []
    if not windows:
        problems.append("index.json.windows is empty")
    if not paths["probes"].is_file():
        problems.append(f"missing slices probe file: {paths['probes'].name}")
    for window in windows:
        name = str(window.get("file", ""))
        path = paths["slices"] / name
        if not name or not path.is_file():
            problems.append(f"missing indexed file {name!r}")
            continue
        try:
            with np.load(path, allow_pickle=False) as data:
                missing = [key for key in ("R_win", "meta") if key not in data.files]
            if missing:
                problems.append(f"{name} missing keys {missing}")
        except (OSError, ValueError) as error:
            problems.append(f"{name} unreadable: {error}")
    detail = (
        f"indexed_window_count={len(windows)}, probe_file={paths['probes'].name}, "
        f"probe_file_exists={paths['probes'].is_file()}, "
        "checked each indexed file, R_win/meta keys, and probe file existence"
    )
    return make_check("indexed_files_exist", "PASS" if not problems else "FAIL", detail + (f"; problems: {problems}" if problems else ""))


def check_summary_fields(paths: dict[str, Path]) -> dict[str, str]:
    """Check required summary fields without treating summary as the full R array."""
    required = (
        "scene",
        "r_units",
        "shape",
        "r_norm",
        "r_mean",
        "r_median",
        "r_min",
        "r_max",
        "n_finite_cells",
        "n_obstacle_cells",
        "finite_ratio",
        "layer_mean_h30",
        "layer_mean_h90",
        "layer_mean_monotonic_decreasing",
        "anchors",
        "city",
        "formulas",
        "simplifications",
    )
    if not paths["summary"].is_file():
        return make_check("summary_fields", "FAIL", "slices/summary.json is missing")
    try:
        summary = load_json(paths["summary"])
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return make_check("summary_fields", "FAIL", f"cannot read summary.json: {error}")
    missing = [field for field in required if field not in summary]
    detail = f"required_fields={list(required)}, present_count={len(required) - len(missing)}; summary is reference metadata only"
    if missing:
        return make_check("summary_fields", "FAIL", detail + f"; missing={missing}")
    return make_check("summary_fields", "PASS", detail)


def check_ps_check_classes(paths: dict[str, Path]) -> dict[str, str]:
    """Check global/window/probe reference artifacts without computing P_s."""
    ps_dir = paths["ps_check"]
    if not ps_dir.is_dir():
        return make_check("ps_check_classes", "FAIL", "ps_check directory is missing")
    files = {path.name for path in ps_dir.iterdir() if path.is_file()}
    classes = {
        "global": sorted(name for name in files if "summary" in name.lower()),
        "window": sorted(name for name in files if "window" in name.lower()),
        "probe": sorted(name for name in files if "probe" in name.lower()),
    }
    detail = f"classes={classes}; no P_s values were calculated"
    return make_check("ps_check_classes", "PASS" if all(classes.values()) else "FAIL", detail)


def check_window_indices_in_r_range(
    paths: dict[str, Path], arrays: dict[str, np.ndarray], h_low: float, inspect_path: Path
) -> dict[str, str]:
    """Check index.json windows against the actual R shape only when R exists."""
    risk = arrays.get("R")
    if risk is None:
        return make_check(
            "window_indices_in_R_range",
            "FAIL",
            "city.npz has no R key; window i0/j0/z cannot be checked against actual R.shape and summary.shape is not substituted."
            + inspect_r_absence_note(inspect_path),
        )
    windows, error = read_index_windows(paths["index"])
    if error:
        return make_check("window_indices_in_R_range", "FAIL", error)
    problems: list[str] = []
    for window in windows:
        name = str(window.get("file", ""))
        try:
            i0 = int(window["i0"])
            j0 = int(window["j0"])
            z = float(window["z"])
            h_idx = int(round(z - h_low))
        except (KeyError, TypeError, ValueError):
            problems.append(f"{name}: invalid i0/j0/z")
            continue
        if i0 < 0 or j0 < 0 or i0 + 64 > risk.shape[0] or j0 + 64 > risk.shape[1] or not 0 <= h_idx < risk.shape[2]:
            problems.append(f"{name}: i0={i0}, j0={j0}, z={z}, h_idx={h_idx}, R.shape={list(risk.shape)}")
    detail = f"checked {len(windows)} window index records against actual R.shape={list(risk.shape)}"
    return make_check("window_indices_in_R_range", "PASS" if not problems else "FAIL", detail + (f"; problems: {problems}" if problems else ""))


def check_probe_indices_in_r_range(paths: dict[str, Path], arrays: dict[str, np.ndarray], inspect_path: Path) -> dict[str, str]:
    """Check probe i/j/h_idx against the actual R shape only when R exists."""
    risk = arrays.get("R")
    if risk is None:
        return make_check(
            "probe_indices_in_R_range",
            "FAIL",
            "city.npz has no R key; probe indices cannot be checked against actual R.shape and summary.shape is not substituted."
            + inspect_r_absence_note(inspect_path),
        )
    if not paths["probes"].is_file():
        return make_check("probe_indices_in_R_range", "FAIL", "slices/probe_points.csv is missing")
    try:
        with paths["probes"].open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        return make_check("probe_indices_in_R_range", "FAIL", f"cannot read probe_points.csv: {error}")
    problems: list[str] = []
    for row_index, row in enumerate(rows, start=2):
        try:
            i = int(row["i"])
            j = int(row["j"])
            h_idx = int(row["h_idx"])
        except (KeyError, TypeError, ValueError) as error:
            problems.append(f"row {row_index}: invalid index ({error})")
            continue
        if not (0 <= i < risk.shape[0] and 0 <= j < risk.shape[1] and 0 <= h_idx < risk.shape[2]):
            problems.append(f"row {row_index}: {(i, j, h_idx)} outside R.shape={list(risk.shape)}")
    detail = f"checked {len(rows)} probe index records against actual R.shape={list(risk.shape)}"
    return make_check("probe_indices_in_R_range", "PASS" if not problems else "FAIL", detail + (f"; problems: {problems[:8]}" if problems else ""))


def check_slices(paths: dict[str, Path], shape: list[int]) -> dict[str, str]:
    """Check existing slice references and P_s artifact presence without calculating P_s."""
    index_path = paths["index"]
    summary_path = paths["summary"]
    ps_dir = paths["ps_check"]
    problems: list[str] = []
    window_count = 0
    if not index_path.is_file():
        problems.append("slices/index.json is missing")
    else:
        try:
            index = load_json(index_path)
            windows = index.get("windows", [])
            if not isinstance(windows, list) or not windows:
                problems.append("index.json.windows is empty or not a list")
                windows = []
            window_count = len(windows)
            for window in windows:
                if not isinstance(window, dict):
                    problems.append(f"index.json contains non-object window metadata: {window!r}")
                    continue
                file_name = str(window.get("file", ""))
                window_path = paths["slices"] / file_name
                if not file_name or not window_path.is_file():
                    problems.append(f"missing indexed window: {file_name!r}")
                    continue
                with np.load(window_path, allow_pickle=False) as data:
                    if "R_win" not in data.files or "meta" not in data.files:
                        problems.append(f"{file_name} lacks R_win/meta")
                    elif list(data["R_win"].shape) != [64, 64]:
                        problems.append(f"{file_name} R_win shape={list(data['R_win'].shape)}, expected=[64,64]")
                for field in ("i0", "j0", "z", "tag"):
                    if field not in window:
                        problems.append(f"{file_name} index metadata lacks {field}")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            problems.append(f"cannot read index.json: {error}")
    if not summary_path.is_file():
        problems.append("slices/summary.json is missing")
    else:
        try:
            summary = load_json(summary_path)
            if summary.get("shape") != shape:
                problems.append(f"summary shape={summary.get('shape')!r}, expected={shape!r}")
            for field in ("r_norm", "r_mean", "r_median", "r_min", "r_max", "n_finite_cells", "n_obstacle_cells"):
                if field not in summary:
                    problems.append(f"summary missing {field}")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            problems.append(f"cannot read summary.json: {error}")
    if not ps_dir.is_dir():
        problems.append("ps_check directory is missing")
    else:
        files = {path.name for path in ps_dir.iterdir() if path.is_file()}
        required = {"ps_summary.json", "ps_windows.npz", "ps_probes.csv"}
        missing = sorted(required - files)
        if missing:
            problems.append(f"ps_check missing reference artifacts: {missing}")
    detail = f"indexed_windows={window_count}; checked slices/index.json, R_win files, summary.json, and ps_check artifact presence without calculating P_s"
    if problems:
        return make_check("slices_and_ps_artifacts", "FAIL", detail + f"; problems: {problems}")
    return make_check("slices_and_ps_artifacts", "PASS", detail)


def check_probes(paths: dict[str, Path], shape: list[int], h_low: float) -> dict[str, str]:
    """Check probe schema, coordinate ranges, and declared kinds only."""
    probe_path = paths["probes"]
    if not probe_path.is_file():
        return make_check("probe_schema_and_ranges", "FAIL", "slices/probe_points.csv is missing")
    try:
        with probe_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        return make_check("probe_schema_and_ranges", "FAIL", f"cannot read probe_points.csv: {error}")
    problems: list[str] = []
    if columns != list(EXPECTED_PROBE_COLUMNS):
        problems.append(f"columns={columns!r}, expected={list(EXPECTED_PROBE_COLUMNS)!r}")
    for row_index, row in enumerate(rows, start=2):
        try:
            i = int(row["i"])
            j = int(row["j"])
            h_idx = int(row["h_idx"])
            z = float(row["z"])
        except (KeyError, TypeError, ValueError) as error:
            problems.append(f"row {row_index} coordinate parse failed: {error}")
            continue
        if not (0 <= i < shape[0] and 0 <= j < shape[1] and 0 <= h_idx < shape[2]):
            problems.append(f"row {row_index} index outside shape: {(i, j, h_idx)}")
        if not math.isclose(z, h_low + h_idx, rel_tol=1e-9, abs_tol=1e-9):
            problems.append(f"row {row_index} z does not match h_idx convention")
        if row.get("kind") not in {"open", "building"}:
            problems.append(f"row {row_index} kind is not open/building")
        if row.get("kind") == "building" and row.get("R_expected") != "NaN":
            problems.append(f"row {row_index} building probe R_expected is not NaN")
    detail = f"rows={len(rows)}, columns={columns!r}, checked index bounds, z convention, kind labels, and building NaN declarations"
    if problems:
        return make_check("probe_schema_and_ranges", "FAIL", detail + f"; problems: {problems[:8]}")
    return make_check("probe_schema_and_ranges", "PASS", detail)


def check_r_presence(paths: dict[str, Path], arrays: dict[str, np.ndarray], shape: list[int]) -> dict[str, str]:
    """Check whether the full R array is actually available; never substitute references."""
    if "R" not in arrays:
        inspect_note = ""
        if paths["inspect"].is_file():
            inspect_text = paths["inspect"].read_text(encoding="utf-8", errors="replace")
            if "R key absent from city.npz" in inspect_text:
                inspect_note = f" Existing inspect report {paths['inspect'].name} also records R key absent from city.npz."
            else:
                inspect_note = f" Existing inspect report {paths['inspect'].name} was read but does not state the R absence explicitly."
        return make_check(
            "full_R_contract",
            "FAIL",
            f"city.npz has no R key; full R shape/NaN/finite checks cannot be performed and no slice/summary is substituted.{inspect_note}",
        )
    array = arrays["R"]
    details = f"shape={list(array.shape)}, dtype={array.dtype}; expected_shape={shape}; inspected existing R only"
    if list(array.shape) != shape:
        return make_check("full_R_contract", "FAIL", details)
    if not np.issubdtype(array.dtype, np.floating):
        return make_check("full_R_contract", "FAIL", details + "; R dtype is not floating")
    return make_check("full_R_contract", "PASS", details)


def inspect_scene(config_path: Path, config: dict[str, Any], scene_key: str) -> dict[str, Any]:
    """Run the nine user-specified read-only contract checks for one scene."""
    paths = resolve_scene_paths(config_path, config, scene_key)
    shape = expected_shape(config)
    plane_shape = shape[:2]
    keys, arrays = read_city(paths["city"])
    checks = [
        check_r_shape(arrays, shape, paths["inspect"]),
        check_nan_vs_building(arrays, paths["inspect"]),
        check_building_mask_shape_vs_r(arrays, paths["inspect"]),
        check_pop_density_shape(arrays, plane_shape),
        check_indexed_files_exist(paths),
        check_summary_fields(paths),
        check_ps_check_classes(paths),
        check_window_indices_in_r_range(paths, arrays, float(config["table2"]["H_LOW"]), paths["inspect"]),
        check_probe_indices_in_r_range(paths, arrays, paths["inspect"]),
    ]
    passed = sum(check["status"] == "PASS" for check in checks)
    failed = len(checks) - passed
    return {
        "scene": scene_key,
        "source_paths": {key: str(value) for key, value in paths.items()},
        "checks": checks,
        "summary": {"pass": passed, "fail": failed, "status": "PASS" if failed == 0 else "FAIL"},
    }


def main() -> None:
    """Run contract checks, print a checklist, and write one JSON per scene."""
    args = parse_args()
    config_path = args.config.resolve()
    config = load_json(config_path)
    scene_keys: Iterable[str] = args.scenes or config["scenes"].keys()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for scene_key in scene_keys:
        result = inspect_scene(config_path, config, scene_key)
        output_path = args.output_dir / f"contract_{scene_key}.json"
        output_path.write_text(json.dumps(json_value(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"SCENE {scene_key}")
        for check in result["checks"]:
            print(f"{check['status']}: {check['name']} - {check['detail']}")
        print(f"SUMMARY: PASS={result['summary']['pass']} FAIL={result['summary']['fail']}")


if __name__ == "__main__":
    main()
