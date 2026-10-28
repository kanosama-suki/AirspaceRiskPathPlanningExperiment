"""Read-only inspection of scene containers and validation artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np


def parse_args() -> argparse.Namespace:
    """Parse paths and scene identifiers supplied by the caller."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ps-check-dir-name", required=True)
    parser.add_argument("--scenes", nargs="+", default=None)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    """Read one UTF-8 JSON document without changing it."""
    return json.loads(path.read_text(encoding="utf-8"))


def format_value(value: Any) -> str:
    """Render JSON-compatible values compactly for the text report."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def resolve_scene_paths(
    config_path: Path,
    config: dict[str, Any],
    scene_key: str,
    ps_check_dir_name: str,
) -> dict[str, Path]:
    """Resolve paths from the scene entry and path templates in config.json."""
    scene_name = config["paths"][f"scene_{scene_key}"]
    city_template = str(config["paths"]["city_npz"])
    city_relative = Path(city_template.replace("<scene>", scene_name, 1))
    city_path = config_path.parent / city_relative
    scene_dir = city_path.parent
    slices_template = str(config["paths"]["slices_dir"])
    slices_relative = Path(slices_template.replace("<scene>", scene_name, 1))
    slices_dir = config_path.parent / slices_relative
    return {
        "scene_dir": scene_dir,
        "city_npz": city_path,
        "slices_dir": slices_dir,
        "summary": slices_dir / "summary.json",
        "index": slices_dir / "index.json",
        "probe_points": slices_dir / "probe_points.csv",
        "ps_check_dir": scene_dir / ps_check_dir_name,
    }


def array_stats(array: np.ndarray) -> str:
    """Return factual dtype and finite-value statistics for an existing array."""
    stats = [f"shape={array.shape}", f"dtype={array.dtype}"]
    if np.issubdtype(array.dtype, np.number):
        nan_count = int(np.isnan(array).sum()) if np.issubdtype(array.dtype, np.floating) else 0
        finite = np.isfinite(array) if np.issubdtype(array.dtype, np.inexact) else np.ones(array.shape, dtype=bool)
        finite_count = int(finite.sum())
        stats.extend([f"nan_count={nan_count}", f"finite_count={finite_count}"])
        if finite_count:
            finite_values = array[finite]
            stats.extend([f"min={finite_values.min()}", f"max={finite_values.max()}"])
        else:
            stats.extend(["min=unavailable", "max=unavailable"])
    else:
        stats.extend(["nan_count=not_applicable", "finite_count=not_applicable"])
    return ", ".join(stats)


def write_line(lines: list[str], key: str, value: Any) -> None:
    """Append one key/value fact to a report."""
    if isinstance(value, str):
        lines.append(f"{key}: {value}")
    else:
        lines.append(f"{key}: {format_value(value)}")


def inspect_city_npz(path: Path, lines: list[str]) -> dict[str, np.ndarray]:
    """Read and describe the existing city.npz arrays."""
    arrays: dict[str, np.ndarray] = {}
    write_line(lines, "city_npz.path", str(path))
    write_line(lines, "city_npz.exists", path.exists())
    if not path.exists():
        return arrays
    with np.load(path, allow_pickle=False) as data:
        keys = list(data.files)
        write_line(lines, "city_npz.keys", keys)
        write_line(lines, "city_npz.has_meta", "meta" in keys)
        for key in keys:
            array = data[key]
            arrays[key] = array
            write_line(lines, f"city_npz.{key}", array_stats(array))
    return arrays


def inspect_core_arrays(arrays: dict[str, np.ndarray], lines: list[str]) -> None:
    """Describe required city arrays and report the absence of a full R array."""
    for key in ("building_mask", "pop_density"):
        if key not in arrays:
            write_line(lines, f"{key}.present", False)
            continue
        array = arrays[key]
        write_line(lines, f"{key}.shape", array.shape)
        write_line(lines, f"{key}.dtype", str(array.dtype))
        if key == "building_mask":
            true_count = int(np.count_nonzero(array))
            write_line(lines, "building_mask.true_count", true_count)
            write_line(lines, "building_mask.total_count", int(array.size))
            write_line(lines, "building_mask.true_ratio", true_count / array.size if array.size else "unavailable")
        else:
            write_line(lines, "pop_density.nan_count", int(np.isnan(array).sum()))
            write_line(lines, "pop_density.min", float(np.nanmin(array)) if np.isfinite(array).any() else "unavailable")
            write_line(lines, "pop_density.max", float(np.nanmax(array)) if np.isfinite(array).any() else "unavailable")
    if "R" in arrays:
        write_line(lines, "R.shape", arrays["R"].shape)
        write_line(lines, "R.dtype", str(arrays["R"].dtype))
        write_line(lines, "R.nan_count", int(np.isnan(arrays["R"]).sum()))
        write_line(lines, "R.finite_count", int(np.isfinite(arrays["R"]).sum()))
        finite = arrays["R"][np.isfinite(arrays["R"])]
        write_line(lines, "R.min", float(finite.min()) if finite.size else "unavailable")
        write_line(lines, "R.max", float(finite.max()) if finite.size else "unavailable")
    else:
        write_line(lines, "R.shape", "unavailable: R key absent from city.npz")
        write_line(lines, "R.dtype", "unavailable: R key absent from city.npz")
        write_line(lines, "R.nan_count", "unavailable: R key absent from city.npz")
        write_line(lines, "R.finite_count", "unavailable: R key absent from city.npz")
        write_line(lines, "R.min", "unavailable: R key absent from city.npz")
        write_line(lines, "R.max", "unavailable: R key absent from city.npz")


def inspect_slices(paths: dict[str, Path], lines: list[str]) -> None:
    """Describe slice index, referenced files, probes, summary, and R_win facts."""
    slices_dir = paths["slices_dir"]
    write_line(lines, "slices_dir", str(slices_dir))
    write_line(lines, "slices_dir.exists", slices_dir.is_dir())

    index_path = paths["index"]
    write_line(lines, "index_json.exists", index_path.is_file())
    windows: list[dict[str, Any]] = []
    if index_path.is_file():
        index = load_json(index_path)
        windows = list(index.get("windows", []))
        write_line(lines, "index_json.windows", windows)
        for window in windows:
            file_name = str(window.get("file", ""))
            window_path = slices_dir / file_name
            write_line(lines, f"window.{file_name}.exists", window_path.is_file())
            if window_path.is_file():
                with np.load(window_path, allow_pickle=False) as data:
                    write_line(lines, f"window.{file_name}.keys", list(data.files))
                    if "R_win" in data.files:
                        write_line(lines, f"window.{file_name}.R_win", array_stats(data["R_win"]))
    else:
        write_line(lines, "index_json.windows", "unavailable")

    probe_path = paths["probe_points"]
    write_line(lines, "probe_points.csv.exists", probe_path.is_file())
    if probe_path.is_file():
        probe_lines = probe_path.read_text(encoding="utf-8").splitlines()
        write_line(lines, "probe_points.csv.header", probe_lines[0] if probe_lines else "unavailable")
        write_line(lines, "probe_points.csv.data_line_count", max(len(probe_lines) - 1, 0))
        with probe_path.open(encoding="utf-8", newline="") as probe_file:
            probes = list(csv.DictReader(probe_file))
        lines.append("probe_points.csv.probes:")
        lines.extend(f"  {format_value(probe)}" for probe in probes)

    summary_path = paths["summary"]
    write_line(lines, "summary_json.exists", summary_path.is_file())
    if summary_path.is_file():
        summary = load_json(summary_path)
        write_line(lines, "summary_json.top_level_keys", list(summary.keys()))
        for key in ("r_mean", "r_median", "r_norm"):
            write_line(lines, f"summary_json.{key}.present", key in summary)
        write_line(lines, "R.reference_shape", summary.get("shape", "unavailable"))
        write_line(lines, "R.reference_dtype", "unavailable: full R array is not stored in allowed inputs")
        write_line(lines, "R.reference_nan_count", summary.get("n_obstacle_cells", "unavailable"))
        write_line(lines, "R.reference_finite_count", summary.get("n_finite_cells", "unavailable"))
        write_line(lines, "R.reference_min", summary.get("r_min", "unavailable"))
        write_line(lines, "R.reference_max", summary.get("r_max", "unavailable"))


def inspect_ps_check(paths: dict[str, Path], lines: list[str]) -> None:
    """List ps_check artifacts and report the three artifact classes by filename."""
    ps_dir = paths["ps_check_dir"]
    write_line(lines, "ps_check_dir", str(ps_dir))
    write_line(lines, "ps_check_dir.exists", ps_dir.is_dir())
    if not ps_dir.is_dir():
        write_line(lines, "ps_check.files", [])
        write_line(lines, "ps_check.global_window_probe_files", {"global": [], "window": [], "probe": []})
        return
    files = sorted(path.name for path in ps_dir.iterdir() if path.is_file())
    write_line(lines, "ps_check.files", files)
    classifications = {
        "global": [name for name in files if "summary" in name.lower()],
        "window": [name for name in files if "window" in name.lower()],
        "probe": [name for name in files if "probe" in name.lower()],
    }
    write_line(lines, "ps_check.global_window_probe_files", classifications)
    write_line(
        lines,
        "ps_check.all_three_classes_present",
        all(classifications[name] for name in ("global", "window", "probe")),
    )


def inspect_scene(
    config_path: Path,
    config: dict[str, Any],
    scene_key: str,
    ps_check_dir_name: str,
) -> str:
    """Build one fact-only report for a configured scene."""
    paths = resolve_scene_paths(config_path, config, scene_key, ps_check_dir_name)
    lines = [f"SCENE: {scene_key}", "", "SECTION 1: city.npz"]
    arrays = inspect_city_npz(paths["city_npz"], lines)
    lines.extend(["", "SECTION 2: building_mask / pop_density / R"])
    inspect_core_arrays(arrays, lines)
    lines.extend(["", "SECTION 3: slices"])
    inspect_slices(paths, lines)
    lines.extend(["", "SECTION 4: ps_check"])
    inspect_ps_check(paths, lines)
    lines.extend(["", "SECTION 5: missing or abnormal"])
    missing: list[str] = []
    if "building_mask" not in arrays:
        missing.append("city.npz key building_mask")
    if "pop_density" not in arrays:
        missing.append("city.npz key pop_density")
    if "R" not in arrays:
        missing.append("city.npz key R (full risk matrix is not stored in city.npz)")
    for path_key in ("index", "summary", "probe_points"):
        if not paths[path_key].is_file():
            missing.append(str(paths[path_key]))
    if not paths["ps_check_dir"].is_dir():
        missing.append(str(paths["ps_check_dir"]))
    if missing:
        lines.extend(f"missing_or_abnormal: {item}" for item in missing)
    else:
        lines.append("missing_or_abnormal: none observed by this read-only inspection")
    return "\n".join(lines) + "\n"


def main() -> None:
    """Inspect all requested scenes and write one report per scene."""
    args = parse_args()
    config_path = args.config.resolve()
    config = load_json(config_path)
    scene_keys: Iterable[str] = args.scenes or config["scenes"].keys()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for scene_key in scene_keys:
        report = inspect_scene(config_path, config, scene_key, args.ps_check_dir_name)
        output_path = args.output_dir / f"inspect_{scene_key}.txt"
        output_path.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
