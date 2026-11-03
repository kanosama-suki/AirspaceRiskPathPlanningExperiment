"""冻结路线审计的配额、端点和栅格检查测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import numpy as np

from src.experiments.config import load_config
from src.experiments.route_generator import RouteSpec
from src.validation.audit_route_manifest import audit_routes
from src.io.scene import SceneData


def test_route_audit_accepts_two_scene_quota(tmp_path: Path, monkeypatch) -> None:
    """每个场景各一条合法路线时审计通过，场景由配置派生。"""
    import src.validation.audit_route_manifest as auditor

    config = {
        "coords": {
            "axes_order": "i,j,h_idx",
            "origin": [0.0, 0.0, 0.0],
            "resolution": 1.0,
        },
        "table2": {
            "N_I": 5,
            "N_J": 5,
            "N_H": 1,
            "GRID_SIZE": 1.0,
            "STEP": 1,
            "H_LOW": 0.0,
            "H_HIGH": 0.0,
        },
    }
    mask = np.zeros((5, 5, 1), dtype=bool)
    risk = np.full(mask.shape, 2.0, dtype=np.float64)
    route = RouteSpec(
        scene="A",
        route_group="S",
        route_id="A_S_001",
        route_seed=114514,
        start=(0.0, 0.0, 0.0),
        goal=(2.0, 0.0, 0.0),
        distance_m=2.0,
        height_delta_m=0.0,
        complexity_score=0.1,
        complexity_band="low",
        diagnostics={},
    )
    route_b = RouteSpec(
        **{
            **route.to_dict(),
            "scene": "B",
            "route_id": "B_S_001",
        }
    )
    scene = SceneData(
        scene_name="A",
        scene_dir=tmp_path,
        R=risk,
        building_mask=mask,
        pop_density=np.ones((5, 5), dtype=np.float64),
        h_low=0.0,
        h_high=0.0,
        step=1.0,
        missions={},
        config=config,
        config_hash="hash",
        r_norm=2.0,
    )
    scene_config_path = tmp_path / "scene.json"
    scene_config_path.write_text(json.dumps({"scenes": {"A": {}, "B": {}}}), encoding="utf-8")
    monkeypatch.setattr(
        auditor,
        "load_scene",
        lambda scene_name, path: scene if scene_name == "A" else replace(scene, scene_name="B"),
    )

    formal = load_config(Path("experiments/configs/formal.toml")).config
    formal = replace(
        formal,
        route_groups={
            "S": replace(formal.route_groups["S"], routes_per_scene=1),
            "M": replace(formal.route_groups["M"], routes_per_scene=0),
            "L": replace(formal.route_groups["L"], routes_per_scene=0),
        },
    )
    report = audit_routes(formal, (route, route_b), scene_config_path)
    assert report["all_pass"]
