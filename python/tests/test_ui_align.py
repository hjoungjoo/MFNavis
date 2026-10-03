from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import Mock

import PiFinder.i18n  # noqa: F401  (installs the built-in _ translator)
import pytest

from PiFinder.types.positioning import AlignCancel, AlignOnRaDec, AlignedResult
from PiFinder.ui import align


class _Config:
    def __init__(self) -> None:
        self.saved = None

    def set_option(self, name, value) -> None:
        self.saved = (name, value)


class _SharedState:
    def __init__(self) -> None:
        self.target_pixel = None

    def set_target_pixel(self, value) -> None:
        self.target_pixel = value


class _ResponseQueue:
    """Empty while stale replies are drained, then return the live reply."""

    def __init__(self, response=None) -> None:
        self.response = response
        self.calls = []

    def get(self, block=True, timeout=None):
        self.calls.append((block, timeout))
        if block is False or self.response is None:
            raise queue.Empty
        return self.response


def _queues(response_queue):
    return {
        "align_command": queue.Queue(),
        "align_response": response_queue,
        "console": queue.Queue(),
    }


def test_align_waits_for_solver_response_without_polling():
    response_queue = _ResponseQueue(AlignedResult(y_target=123.0, x_target=234.0))
    command_queues = _queues(response_queue)
    config = _Config()
    shared_state = _SharedState()

    assert align.align_on_radec(12.3, 45.6, command_queues, config, shared_state)

    assert response_queue.calls == [
        (False, None),
        (True, align.ALIGN_TIMEOUT_SECONDS),
    ]
    assert command_queues["align_command"].get_nowait() == AlignOnRaDec(
        ra=12.3, dec=45.6
    )
    assert command_queues["console"].get_nowait() == "Alignment Set"
    assert shared_state.target_pixel == (123.0, 234.0)
    assert config.saved == ("target_pixel", (123.0, 234.0))


def test_align_cancels_after_solver_timeout(monkeypatch):
    monkeypatch.setattr(align, "ALIGN_TIMEOUT_SECONDS", 0.25)
    response_queue = _ResponseQueue()
    command_queues = _queues(response_queue)
    config = _Config()
    shared_state = _SharedState()

    assert not align.align_on_radec(12.3, 45.6, command_queues, config, shared_state)

    assert response_queue.calls == [(False, None), (True, 0.25)]
    assert command_queues["align_command"].get_nowait() == AlignOnRaDec(
        ra=12.3, dec=45.6
    )
    assert command_queues["align_command"].get_nowait() == AlignCancel()
    assert command_queues["console"].get_nowait() == "Align Timeout"
    assert shared_state.target_pixel is None
    assert config.saved is None


@pytest.mark.parametrize("target", [(-1.0, -1.0), (-1.0, 25.0)])
def test_align_rejects_solver_failure_sentinel(target):
    response_queue = _ResponseQueue(
        AlignedResult(y_target=target[0], x_target=target[1])
    )
    command_queues = _queues(response_queue)
    config = _Config()
    shared_state = _SharedState()

    assert not align.align_on_radec(12.3, 45.6, command_queues, config, shared_state)
    assert shared_state.target_pixel is None
    assert config.saved is None


def test_lcd_alignment_is_saved_but_runtime_alignment_and_reset_are_not(
    monkeypatch, tmp_path
):
    from PiFinder import config, pos_server
    from PiFinder.state import SharedStateObj

    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(config.utils, "runtime_dir", tmp_path)
    cfg = config.Config()
    cfg.set_option("target_pixel", (200.0, 210.0))
    state = SharedStateObj()
    state.solution().last_solve_success = 1.0
    assert tuple(state.target_pixel()) == (200.0, 210.0)
    write = Mock(wraps=cfg.dump_config)
    monkeypatch.setattr(cfg, "dump_config", write)
    queues = _queues(_ResponseQueue(AlignedResult(y_target=123.0, x_target=234.0)))

    assert align.align_on_radec(12.3, 45.6, queues, cfg, state)
    write.assert_called_once()
    assert state.target_pixel() == (123.0, 234.0)
    saved = cfg.config_file_path.read_bytes()

    monkeypatch.setattr(pos_server, "pos_server_config", cfg)
    monkeypatch.setattr(pos_server, "mountcontrol_queue", None)
    monkeypatch.setattr(pos_server, "console_queue", None)
    monkeypatch.setattr(pos_server, "_mount_control_status", lambda: {})
    monkeypatch.setattr(
        pos_server, "cached_target_pixel", lambda *a, **kw: (321.0, 432.0)
    )
    monkeypatch.setattr(pos_server, "projection_context", lambda *_: ("optics",))
    assert pos_server._align_pifinder_if_enabled(state, 45.6, 12.3)
    assert state.target_pixel() == (321.0, 432.0)
    assert cfg.config_file_path.read_bytes() == saved
    write.assert_called_once()

    screen = object.__new__(align.UIAlign)
    screen.shared_state = state
    screen.config_object = cfg
    screen.display_class = SimpleNamespace(centerX=64, centerY=64)
    screen.align_mode = True
    screen.update = Mock()
    screen.key_number(1)
    assert state.target_pixel() == (256, 256)
    assert cfg.config_file_path.read_bytes() == saved
    write.assert_called_once()

    # Saving another setting must preserve the last successful LCD alignment,
    # and a new shared state must restore that saved point rather than RAM.
    cfg.set_option("display_flip", True)
    assert tuple(config.Config().get_option("target_pixel")) == (123.0, 234.0)
    assert tuple(SharedStateObj().target_pixel()) == (123.0, 234.0)
