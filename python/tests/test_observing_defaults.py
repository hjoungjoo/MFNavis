"""Fresh installs use the field tuning; saved user choices still win."""

import json

import pytest

from PiFinder import config
from PiFinder.livecam_config import settings_from_config
from PiFinder.solver_scheduling import SolverSchedulingPolicy

pytestmark = pytest.mark.unit


def test_fresh_install_activates_observing_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    cfg = config.Config()
    assert cfg.get_option("camera_exp") == "auto_star"
    assert cfg.get_option("camera_auto_star_framewise") is True
    assert settings_from_config(cfg)["solver_preprocess_enabled"] is True
    assert cfg.get_option("solver_optics_fov_gate") is True
    assert cfg.get_option("solver_optics_fullframe_fov") is True
    assert cfg.get_option("solver_preprocess_mode") == "auto"
    assert cfg.get_option("solver_preprocess_accelerator") == "cpu"
    assert cfg.get_option("solver_preprocess_reduction") == "auto"
    policy = SolverSchedulingPolicy(mode=cfg.get_option("solver_preprocess_mode"))
    assert [policy.choose(raw_solved=True) for _ in range(3)] == [
        "sync",
        "sync",
        "async",
    ]
    assert policy.choose(raw_solved=False) == "sync"
    # A fresh install must not inherit a field alignment or enable mount motion.
    assert cfg.get_option("target_pixel") == [256, 256]
    assert cfg.get_option("mount_control") is False


def test_saved_observing_choices_survive_new_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    saved = {
        "camera_exp": 0.5,
        "camera_auto_star_framewise": False,
        "livecam_solver_preprocess_enabled": False,
        "solver_preprocess_mode": "sync",
        "solver_preprocess_accelerator": "auto",
        "solver_preprocess_reduction": "numpy",
        "solver_optics_fov_gate": False,
        "solver_optics_fullframe_fov": False,
        "target_pixel": [250, 260],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(saved))
    cfg = config.Config()
    for key, value in saved.items():
        assert cfg.get_option(key) == value
    assert settings_from_config(cfg)["solver_preprocess_enabled"] is False
    assert json.loads(path.read_text()) == saved
