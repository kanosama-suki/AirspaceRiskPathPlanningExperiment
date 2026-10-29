"""场景加载器的路径、缓存和数组契约测试。"""

from hashlib import sha256
from pathlib import Path
import json

import numpy as np
import pytest

from src.io.scene import load_scene


def _write_scene_inputs(root: Path) -> tuple[Path, Path, np.ndarray, np.ndarray, np.ndarray]:
    scene_dir = root / "scene_a"
    scene_dir.mkdir()
    config_path = root / "config.json"
    config = {
        "paths": {
            "scene_A": "scene_a",
            "scene_B": "scene_b",
            "city_npz": "<scene>/city.npz",
        },
        "table2": {
            "N_I": 3,
            "N_J": 4,
            "N_H": 2,
            "H_LOW": 30,
            "H_HIGH": 31,
            "STEP": 10,
            "START1": [0, 10, 30],
            "GOAL1": [20, 30, 31],
            "START2": [10, 20, 30],
            "GOAL2": [0, 0, 31],
        },
    }
    config_bytes = json.dumps(config).encode("utf-8")
    config_path.write_bytes(config_bytes)

    building_mask = np.zeros((3, 4, 2), dtype=bool)
    building_mask[1, 2, 0] = True
    pop_density = np.ones((3, 4), dtype=np.float32)
    footprint = np.zeros((3, 4), dtype=bool)
    np.savez(scene_dir / "city.npz", building_mask=building_mask, pop_density=pop_density, building_footprint=footprint)

    risk_field = np.ones((3, 4, 2), dtype=np.float64)
    risk_field[building_mask] = np.nan
    cache_path = root / "risk.npy"
    np.save(cache_path, risk_field)
    return config_path, cache_path, building_mask, pop_density, risk_field


def test_load_scene_uses_config_relative_paths_and_validates_cache(tmp_path: Path) -> None:
    config_path, cache_path, building_mask, pop_density, risk_field = _write_scene_inputs(tmp_path)

    scene = load_scene("A", config_path, cache_path)

    assert scene.scene_name == "A"
    assert scene.scene_dir == (tmp_path / "scene_a").resolve()
    assert scene.R.shape == (3, 4, 2)
    assert scene.building_mask.shape == building_mask.shape
    assert scene.pop_density.shape == pop_density.shape
    assert scene.missions["1"] == ((0.0, 10.0, 30.0), (20.0, 30.0, 31.0))
    assert scene.missions["2"] == ((10.0, 20.0, 30.0), (0.0, 0.0, 31.0))
    assert scene.config_hash == sha256(config_path.read_bytes()).hexdigest()
    assert scene.r_norm == 1.0
    assert np.array_equal(np.isnan(scene.R), np.isnan(risk_field))
    assert not scene.R.flags.writeable


def test_load_scene_calls_r_generator_when_cache_is_not_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, building_mask, _, risk_field = _write_scene_inputs(tmp_path)
    captured: dict[str, object] = {}

    def fake_compute_r(
        building_footprint: np.ndarray,
        pop_density: np.ndarray,
        input_mask: np.ndarray,
        config: dict[str, object],
    ) -> np.ndarray:
        captured["footprint"] = building_footprint
        captured["mask"] = input_mask
        captured["config"] = config
        return risk_field.copy()

    monkeypatch.setattr("src.io.scene.compute_r_matrix", fake_compute_r)

    scene = load_scene("A", config_path)

    assert captured["mask"].shape == building_mask.shape  # type: ignore[union-attr]
    assert scene.R.shape == risk_field.shape
    assert scene.r_norm == 1.0


def test_load_scene_rejects_cache_with_wrong_nan_semantics(tmp_path: Path) -> None:
    config_path, cache_path, building_mask, _, _ = _write_scene_inputs(tmp_path)
    wrong_risk = np.ones((3, 4, 2), dtype=np.float64)
    np.save(cache_path, wrong_risk)

    with pytest.raises(ValueError, match="NaN 位置"):
        load_scene("A", config_path, cache_path)


def test_load_scene_reads_npz_cache_with_named_r_array(tmp_path: Path) -> None:
    config_path, _, building_mask, _, risk_field = _write_scene_inputs(tmp_path)
    cache_path = tmp_path / "risk_cache.npz"
    np.savez(cache_path, R=risk_field)

    scene = load_scene("A", config_path, cache_path)

    assert scene.R.shape == risk_field.shape
    assert np.array_equal(scene.building_mask, building_mask)
    assert np.array_equal(np.isnan(scene.R), np.isnan(risk_field))
