"""只读加载场景数据和任务配置。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
import json

import numpy as np

from src.core.metrics import risk_normalizer
from src.risk.risk_matrix import compute_r_matrix


Point3D = tuple[float, float, float]
MissionEndpoints = tuple[Point3D, Point3D]


@dataclass(frozen=True, slots=True)
class SceneData:
    """已加载场景数据；风险数组按 `[i, j, h_idx]` 排列。"""

    scene_name: str
    scene_dir: Path
    R: np.ndarray
    building_mask: np.ndarray
    pop_density: np.ndarray
    h_low: float
    h_high: float
    step: float
    missions: Mapping[str, MissionEndpoints]
    config: Mapping[str, Any]
    config_hash: str
    r_norm: float


def _load_r_cache(cache_path: Path) -> np.ndarray:
    """读取调用者明确提供的 `.npy` 或带 `R` 键的 `.npz` 缓存。"""
    if cache_path.suffix.lower() == ".npy":
        return np.load(cache_path, mmap_mode="r", allow_pickle=False)
    if cache_path.suffix.lower() == ".npz":
        with np.load(cache_path, allow_pickle=False) as archive:
            if "R" not in archive.files:
                raise KeyError(f"R 缓存 {cache_path} 中缺少 `R` 键。")
            return np.array(archive["R"], copy=True)
    raise ValueError("R 缓存只支持 `.npy` 或含 `R` 键的 `.npz` 文件。")


def _validate_scene_arrays(
    risk_field: np.ndarray,
    building_mask: np.ndarray,
    pop_density: np.ndarray,
    expected_shape: tuple[int, int, int],
) -> None:
    """核对数组维度、数据类型和建筑格 NaN 语义。"""
    plane_shape = expected_shape[:2]
    if risk_field.shape != expected_shape or risk_field.ndim != 3:
        raise ValueError(f"R.shape={risk_field.shape}，配置期望 {expected_shape}。")
    if not np.issubdtype(risk_field.dtype, np.number):
        raise TypeError("R 必须是数值数组。")
    if building_mask.shape != expected_shape or building_mask.dtype != np.bool_:
        raise ValueError(
            f"building_mask 必须是 bool 数组且形状为 {expected_shape}，"
            f"实际为 {building_mask.shape}/{building_mask.dtype}。"
        )
    if pop_density.shape != plane_shape or not np.issubdtype(pop_density.dtype, np.number):
        raise ValueError(
            f"pop_density 必须是形状为 {plane_shape} 的数值数组，"
            f"实际为 {pop_density.shape}/{pop_density.dtype}。"
        )
    if not np.isfinite(pop_density).all() or np.any(pop_density < 0):
        raise ValueError("pop_density 必须全部为有限非负数。")

    mismatch_count = 0
    # 按行块检查 NaN/建筑语义，避免为整张 700 MB 风险矩阵复制大型布尔掩码。
    for row_start in range(0, expected_shape[0], 32):
        row_end = min(row_start + 32, expected_shape[0])
        risk_block = risk_field[row_start:row_end]
        mask_block = building_mask[row_start:row_end]
        mismatch_count += int(np.count_nonzero(np.isnan(risk_block) != mask_block))
        if not np.isfinite(risk_block[~mask_block]).all():
            raise ValueError("非建筑体素的 R 必须全部为有限值。")
    if mismatch_count:
        raise ValueError(f"R 的 NaN 位置必须与 building_mask 一致，差异格数：{mismatch_count}。")


def load_scene(
    scene_name: str,
    config_path: Path,
    r_cache_path: Path | None = None,
) -> SceneData:
    """加载 A/B 场景并生成或读取真实 R。

    场景目录和全部参数均从 `config_path` 解析。未传 R 缓存时，读取
    `city.npz` 的 footprint、人口密度和建筑掩码，并调用现有
    `compute_r_matrix` 在内存中生成完整风险矩阵；本函数不会写入缓存。
    """
    if scene_name not in {"A", "B"}:
        raise ValueError("scene_name 只能是 `A` 或 `B`。")

    resolved_config_path = Path(config_path).expanduser().resolve()
    if not resolved_config_path.is_file():
        raise FileNotFoundError(f"找不到配置文件：{resolved_config_path}")
    config_bytes = resolved_config_path.read_bytes()
    config = json.loads(config_bytes.decode("utf-8-sig"))
    config_root = resolved_config_path.parent

    paths = config["paths"]
    scene_key = "scene_A" if scene_name == "A" else "scene_B"
    scene_dir_name = str(paths[scene_key])
    scene_dir = (config_root / scene_dir_name).resolve()
    city_relative_path = str(paths["city_npz"]).replace("<scene>", scene_dir_name)
    city_path = (config_root / city_relative_path).resolve()

    table2 = config["table2"]
    expected_shape = (int(table2["N_I"]), int(table2["N_J"]), int(table2["N_H"]))
    with np.load(city_path, allow_pickle=False) as archive:
        required_keys = {"building_mask", "pop_density", "building_footprint"}
        missing_keys = required_keys.difference(archive.files)
        if missing_keys:
            raise KeyError(f"{city_path} 缺少场景数组：{sorted(missing_keys)}")
        building_mask = np.array(archive["building_mask"], copy=True)
        pop_density = np.array(archive["pop_density"], copy=True)
        building_footprint = np.array(archive["building_footprint"], copy=True)

    if r_cache_path is None:
        risk_field = compute_r_matrix(
            building_footprint,
            pop_density,
            building_mask,
            config,
        )
    else:
        resolved_cache_path = Path(r_cache_path).expanduser()
        if not resolved_cache_path.is_absolute():
            resolved_cache_path = config_root / resolved_cache_path
        resolved_cache_path = resolved_cache_path.resolve()
        if not resolved_cache_path.is_file():
            raise FileNotFoundError(f"找不到指定的 R 缓存：{resolved_cache_path}")
        risk_field = _load_r_cache(resolved_cache_path)

    _validate_scene_arrays(risk_field, building_mask, pop_density, expected_shape)
    for array in (risk_field, building_mask, pop_density):
        array.setflags(write=False)

    missions: dict[str, MissionEndpoints] = {}
    for mission_id in ("1", "2"):
        start = tuple(float(value) for value in table2[f"START{mission_id}"])
        goal = tuple(float(value) for value in table2[f"GOAL{mission_id}"])
        if len(start) != 3 or len(goal) != 3:
            raise ValueError(f"任务 {mission_id} 的起点和终点必须各有三个坐标。")
        missions[mission_id] = (start, goal)  # type: ignore[assignment]

    return SceneData(
        scene_name=scene_name,
        scene_dir=scene_dir,
        R=risk_field,
        building_mask=building_mask,
        pop_density=pop_density,
        h_low=float(table2["H_LOW"]),
        h_high=float(table2["H_HIGH"]),
        step=float(table2["STEP"]),
        missions=missions,
        config=config,
        config_hash=sha256(config_bytes).hexdigest(),
        r_norm=risk_normalizer(risk_field),
    )
