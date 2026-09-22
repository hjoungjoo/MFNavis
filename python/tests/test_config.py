#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Tests for the shared config file's cross-process write behaviour.

config.json is written by several processes (main/UI, camera, web), each
holding its own long-lived ``Config`` instance. A write therefore has to merge
onto the current file instead of dumping a snapshot taken at process start --
otherwise saving one setting silently reverts every setting another process
changed in the meantime (the camera process saving ``camera_exp`` used to undo
the LiveCam settings the web UI had just written).
"""

import json
from pathlib import Path

import pytest

from PiFinder import config


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Point Config at a throwaway data dir with an empty user config."""
    data_dir = tmp_path / "PiFinder_data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text("{}")
    monkeypatch.setattr(config.utils, "data_dir", data_dir)
    return data_dir


def _on_disk(config_dir: Path) -> dict:
    return json.loads((config_dir / "config.json").read_text())


@pytest.mark.unit
def test_retired_tile_settings_removed_without_losing_lens_calibration(config_dir):
    calibration = {"profiles": {"imx462:6mm": {"coefficients": {"k1": -0.11}}}}
    retained = {
        "wide_solver_calibration_store_v1": calibration,
        "camera_exp": 123000,
        "target_pixel": [220, 240],
    }
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                **retained,
                "wide_solver_enabled": True,
                "mf_wide_excluded_tiles_by_optics": {"imx462:6mm": ["C"]},
            }
        )
    )

    cfg = config.Config()
    assert _on_disk(config_dir) == retained
    assert cfg.get_option("wide_solver_enabled") is None
    assert cfg.get_option("mf_wide_excluded_tiles_by_optics") is None
    assert cfg.get_option("wide_solver_calibration_store_v1") == calibration
    # Loading again must not rewrite an already migrated configuration.
    stamp = (config_dir / "config.json").stat().st_mtime_ns
    config.Config()
    assert (config_dir / "config.json").stat().st_mtime_ns == stamp


@pytest.mark.unit
def test_set_option_persists(config_dir):
    cfg = config.Config()
    cfg.set_option("camera_exp", 400000)
    assert _on_disk(config_dir)["camera_exp"] == 400000
    assert cfg.get_option("camera_exp") == 400000


@pytest.mark.unit
def test_set_options_persists_batch_without_losing_other_changes(config_dir):
    stale = config.Config()
    config.Config().set_option("camera_exp", 123000)

    stale.set_options(
        {
            "onstep_connection_type": "usb",
            "onstep_serial_port": "/dev/serial/by-id/test",
            "onstep_serial_baud": 115200,
        }
    )

    saved = _on_disk(config_dir)
    assert saved["camera_exp"] == 123000
    assert saved["onstep_connection_type"] == "usb"
    assert saved["onstep_serial_port"] == "/dev/serial/by-id/test"
    assert saved["onstep_serial_baud"] == 115200


@pytest.mark.unit
def test_set_options_rejects_special_namespaces(config_dir):
    cfg = config.Config()
    with pytest.raises(ValueError, match="plain persistent options"):
        cfg.set_options({"session.test": True})


@pytest.mark.unit
def test_get_stored_option_does_not_use_default_config(config_dir):
    cfg = config.Config()
    assert cfg.get_option("camera_exp") == "auto_star"
    assert cfg.get_stored_option("camera_exp") is None


@pytest.mark.unit
def test_goto_method_defaults_to_pifinder(config_dir):
    """New and legacy configs without the key use PiFinder GoTo."""
    cfg = config.Config()
    assert cfg.get_stored_option("indi_goto_method") is None
    assert cfg.get_option("indi_goto_method") == "pifinder"


@pytest.mark.unit
def test_write_keeps_another_process_changes(config_dir):
    """The camera process saving an exposure must not revert LiveCam settings."""
    camera_cfg = config.Config()  # loaded at camera start

    web_cfg = config.Config()  # a later web request
    web_cfg.set_option("livecam_low_percentile", 33.0)

    camera_cfg.set_option("camera_exp", 200000)

    saved = _on_disk(config_dir)
    assert saved["camera_exp"] == 200000
    assert saved["livecam_low_percentile"] == 33.0


@pytest.mark.unit
def test_write_keeps_own_earlier_changes(config_dir):
    """Merging in the file's state must not drop what this process wrote."""
    cfg = config.Config()
    cfg.set_option("camera_exp", 100000)
    cfg.set_option("camera_gain", 4.0)

    saved = _on_disk(config_dir)
    assert saved["camera_exp"] == 100000
    assert saved["camera_gain"] == 4.0


@pytest.mark.unit
def test_reset_filters_keeps_another_process_changes(config_dir):
    seed = config.Config()
    seed.set_option("filter.magnitude", 12)
    seed.set_option("camera_exp", 50000)

    stale = config.Config()
    config.Config().set_option("livecam_high_percentile", 98.0)

    stale.reset_filters()

    saved = _on_disk(config_dir)
    assert "filter.magnitude" not in saved
    assert saved["camera_exp"] == 50000
    assert saved["livecam_high_percentile"] == 98.0


@pytest.mark.unit
def test_dump_is_atomic(config_dir):
    """A reader never sees a partial file, and no temp files are left behind."""
    cfg = config.Config()
    cfg.set_option("camera_exp", 25000)

    assert json.loads((config_dir / "config.json").read_text())
    leftovers = [p.name for p in config_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


@pytest.mark.unit
def test_unreadable_file_does_not_wipe_settings(config_dir, caplog):
    """A corrupt config.json must not turn a single write into a full reset."""
    cfg = config.Config()
    cfg.set_option("camera_exp", 800000)
    (config_dir / "config.json").write_text("{ this is not json")

    cfg.set_option("camera_gain", 8.0)

    saved = _on_disk(config_dir)
    assert saved["camera_gain"] == 8.0
    assert saved["camera_exp"] == 800000


@pytest.mark.unit
def test_read_picks_up_another_process_write(config_dir, monkeypatch):
    """The UI must see an exposure the web/camera process just saved."""
    monkeypatch.setattr(config, "REFRESH_INTERVAL", 0)
    ui_cfg = config.Config()  # loaded when the main process started
    assert ui_cfg.get_option("camera_exp") == "auto_star"  # default_config value

    config.Config().set_option("camera_exp", "auto")

    assert ui_cfg.get_option("camera_exp") == "auto"


@pytest.mark.unit
def test_read_is_not_rechecked_within_the_interval(config_dir, monkeypatch):
    """get_option() runs in draw loops, so it must not stat on every call."""
    monkeypatch.setattr(config, "REFRESH_INTERVAL", 3600)
    ui_cfg = config.Config()
    ui_cfg.get_option("camera_exp")

    config.Config().set_option("camera_exp", 25000)

    # Still the value from our last read: the file is only re-checked once
    # the interval has passed.
    assert ui_cfg.get_option("camera_exp") == "auto_star"


@pytest.mark.unit
def test_own_write_is_visible_immediately(config_dir, monkeypatch):
    """A process always sees its own write, whatever the recheck interval."""
    monkeypatch.setattr(config, "REFRESH_INTERVAL", 3600)
    cfg = config.Config()
    cfg.set_option("camera_exp", 50000)
    assert cfg.get_option("camera_exp") == 50000


@pytest.mark.unit
def test_session_options_are_not_persisted(config_dir):
    cfg = config.Config()
    cfg.set_option("session.foo", "bar")
    assert cfg.get_option("session.foo") == "bar"
    assert "session.foo" not in _on_disk(config_dir)
