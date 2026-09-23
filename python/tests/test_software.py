from unittest.mock import patch, MagicMock

import pytest
import requests

from PiFinder.ui.software import (
    update_needed,
    _strip_markdown,
    _fetch_migration_config,
    _UNLOCK_SEQUENCE,
)


_NIXOS_URL = "https://example.invalid/pifinder-nixos.tar.zst"


@pytest.mark.unit
@pytest.mark.parametrize("hardware", ("headless", "headless176", "headless320"))
@pytest.mark.parametrize("selection", ("Update", "Cancel"))
def test_update_action_text_and_cursor_share_bottom_anchored_rows(hardware, selection):
    import PiFinder.i18n  # noqa: F401

    from PiFinder.displays import (
        DisplayHeadless,
        DisplayHeadless176,
        DisplayHeadless320,
    )
    from PiFinder.ui.software import UISoftware

    module = object.__new__(UISoftware)
    module.display_class = {
        "headless": DisplayHeadless,
        "headless176": DisplayHeadless176,
        "headless320": DisplayHeadless320,
    }[hardware]()
    module.fonts = module.display_class.fonts
    module.colors = module.display_class.colors
    module.clear_screen = MagicMock()
    module.screen_update = MagicMock()
    module.draw = MagicMock()
    module._wifi_mode = "Client"
    module._software_version = "m2.6.0"
    module._release_version = "m2.6.1"
    module._option_select = selection

    module.update()

    pitch = module.fonts.large.height
    top = module.display_class.resY - 2 * pitch - 6
    calls = module.draw.text.call_args_list
    assert calls[-3].args[0] == (10, top)
    assert calls[-2].args[0] == (10, top + pitch)
    assert calls[-1].args[0] == (0, top if selection == "Update" else top + pitch)
    assert module._go_for_update


@pytest.mark.unit
class TestUpdateNeeded:
    def test_newer_version_available(self):
        assert update_needed("2.3.0", "2.4.0") is True

    def test_same_version(self):
        assert update_needed("2.4.0", "2.4.0") is False

    def test_older_version(self):
        assert update_needed("2.5.0", "2.4.0") is False

    def test_major_version_bump(self):
        assert update_needed("1.9.9", "2.0.0") is True

    def test_patch_bump(self):
        assert update_needed("2.4.0", "2.4.1") is True

    def test_garbage_input_returns_true(self):
        assert update_needed("garbage", "2.4.0") is True

    def test_empty_string_returns_true(self):
        assert update_needed("", "") is True

    def test_partial_version_returns_true(self):
        assert update_needed("2.4", "2.5.0") is True

    def test_unknown_returns_true(self):
        assert update_needed("2.4.0", "Unknown") is True

    # MF releases carry an "m" prefix in version.txt (m2.6.0). The prefix
    # must be transparent to the compare — most importantly, equal versions
    # must NOT report an update, or every device would show "Update Now"
    # forever after updating (int("m2") used to raise into the error bias).
    def test_mf_prefix_newer_available(self):
        assert update_needed("m2.6.0", "m2.6.1") is True

    def test_mf_prefix_same_version(self):
        assert update_needed("m2.6.1", "m2.6.1") is False

    def test_mf_prefix_older_release(self):
        assert update_needed("m2.6.1", "m2.6.0") is False

    def test_mf_prefix_mixed_with_plain(self):
        # A device still on a plain upstream-style version vs an m-release
        assert update_needed("2.6.0", "m2.6.1") is True


@pytest.mark.unit
class TestUnlockSequence:
    def test_sequence_length(self):
        assert len(_UNLOCK_SEQUENCE) == 7

    def test_sequence_content(self):
        assert _UNLOCK_SEQUENCE == ["square"] * 7


@pytest.mark.unit
class TestStripMarkdown:
    def test_removes_headings(self):
        assert _strip_markdown("# Hello") == "Hello"
        assert _strip_markdown("## Sub") == "Sub"

    def test_removes_bold(self):
        assert _strip_markdown("**bold**") == "bold"

    def test_removes_italic(self):
        assert _strip_markdown("*italic*") == "italic"

    def test_removes_links(self):
        assert _strip_markdown("[text](http://example.com)") == "text"

    def test_removes_backticks(self):
        assert _strip_markdown("`code`") == "code"

    def test_preserves_plain_text(self):
        assert _strip_markdown("Hello world") == "Hello world"

    def test_multiline(self):
        md = "# Title\n\nSome **bold** text.\n- item"
        result = _strip_markdown(md)
        assert "Title" in result
        assert "bold" in result
        assert "**" not in result


def _mock_json_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def _mock_invalid_json_response(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.side_effect = ValueError("not json")
    return resp


@pytest.mark.unit
class TestFetchMigrationConfig:
    @patch("PiFinder.ui.software.requests.get")
    def test_returns_dict_when_gate_open_and_url_set(self, mock_get):
        payload = {"nixos_for_everyone": True, "nixos_url": _NIXOS_URL}
        mock_get.return_value = _mock_json_response(payload)
        assert _fetch_migration_config() == payload

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_dict_when_gate_closed_but_url_set(self, mock_get):
        # Gate check is the caller's job; fetch only requires nixos_url.
        payload = {"nixos_for_everyone": False, "nixos_url": _NIXOS_URL}
        mock_get.return_value = _mock_json_response(payload)
        assert _fetch_migration_config() == payload

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_when_url_missing(self, mock_get):
        mock_get.return_value = _mock_json_response({"nixos_for_everyone": True})
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_when_url_empty(self, mock_get):
        mock_get.return_value = _mock_json_response(
            {"nixos_for_everyone": True, "nixos_url": ""}
        )
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_http_error(self, mock_get):
        mock_get.return_value = _mock_json_response(
            {"nixos_for_everyone": True, "nixos_url": _NIXOS_URL}, status_code=404
        )
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_malformed_json(self, mock_get):
        mock_get.return_value = _mock_invalid_json_response()
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_when_payload_is_not_object(self, mock_get):
        mock_get.return_value = _mock_json_response(["nixos_for_everyone"])
        assert _fetch_migration_config() is None


@pytest.mark.unit
class TestForkReleaseChannel:
    """MF: the device must watch this fork's releases, never brickbots'.

    A future upstream sync that re-points these URLs would silently turn the
    Software screen back into a monitor of a foreign project's releases (and
    hand upstream's migration gate remote-trigger power over a migration this
    fork excludes) -- these pins make that a test failure instead.
    """

    def test_migration_gate_url_points_at_the_fork(self):
        import PiFinder.ui.software as software

        assert "hjoungjoo/MFNavis" in software.MIGRATION_GATE_URL
        assert "brickbots" not in software.MIGRATION_GATE_URL

    def test_release_version_url_points_at_the_fork(self):
        import inspect

        from PiFinder.ui.software import UISoftware

        src = inspect.getsource(UISoftware.get_release_version)
        assert "hjoungjoo/MFNavis" in src
        assert "brickbots" not in src


@pytest.mark.unit
def test_unknown_release_offers_no_update(monkeypatch, tmp_path):
    """MF: a failed release fetch (network down, or no release branch cut yet)
    must not surface as "Update Now" -- update_needed()'s error bias would
    otherwise offer a doomed update against a release that doesn't exist."""
    from unittest.mock import MagicMock

    import PiFinder.i18n  # noqa: F401  installs the _() gettext builtin
    from PiFinder import utils
    from PiFinder.displays import get_display
    from PiFinder.ui.software import UISoftware

    # The display loads fonts and Config() reads default_config.json via
    # utils.pifinder_dir, so build the display before redirecting the dir and
    # give the redirected dir a copy of the defaults.
    display = get_display("headless")
    (tmp_path / "version.txt").write_text("m2.6.0")
    (tmp_path / "wifi_status.txt").write_text("Client")
    (tmp_path / "default_config.json").write_text(
        (utils.pifinder_dir / "default_config.json").read_text()
    )
    monkeypatch.setattr(utils, "pifinder_dir", tmp_path)

    shared_state = MagicMock()
    shared_state.ui_state.return_value.message_timeout.return_value = 0.0
    shared_state.sqm.return_value = None  # title bar info rotator
    shared_state.solve_state.return_value = False
    shared_state.location.return_value = None

    module = UISoftware(
        display,
        None,  # camera_image
        shared_state,
        {},  # command_queues
        MagicMock(),  # config_object
        MagicMock(),  # catalogs
        item_definition={},
        add_to_stack=MagicMock(),
        remove_from_stack=MagicMock(),
    )

    module._release_version = "Unknown"
    module.update(force=True)

    assert module._go_for_update is False


@pytest.mark.unit
def test_key_right_without_offered_update_is_inert(monkeypatch, tmp_path):
    """RIGHT on a screen that offered no update must not run the updater.

    Found live 2026-08-05: on the "Release info unavailable" state a single
    RIGHT ran pifinder_update.sh (git checkout release), which failed and
    unwound the UI main loop, killing the app.
    """
    import PiFinder.i18n  # noqa: F401
    from PiFinder import utils
    from PiFinder.displays import get_display
    from PiFinder.ui.software import UISoftware

    display = get_display("headless")
    (tmp_path / "version.txt").write_text("m2.6.0")
    (tmp_path / "wifi_status.txt").write_text("Client")
    (tmp_path / "default_config.json").write_text(
        (utils.pifinder_dir / "default_config.json").read_text()
    )
    monkeypatch.setattr(utils, "pifinder_dir", tmp_path)

    shared_state = MagicMock()
    shared_state.ui_state.return_value.message_timeout.return_value = 0.0
    shared_state.sqm.return_value = None
    shared_state.solve_state.return_value = False
    shared_state.location.return_value = None

    module = UISoftware(
        display,
        None,
        shared_state,
        {},
        MagicMock(),
        MagicMock(),
        item_definition={},
        add_to_stack=MagicMock(),
        remove_from_stack=MagicMock(),
    )
    ran = []
    monkeypatch.setattr(module, "update_software", lambda: ran.append(True))

    assert module._go_for_update is False
    module.key_right()  # default option is "Update", but nothing was offered
    assert ran == []

    module._go_for_update = True
    module.key_right()
    assert ran == [True]


@pytest.mark.unit
def test_update_software_failure_returns_false(monkeypatch):
    """A failing update script reports False instead of raising through the
    UI main loop (which killed the whole app)."""
    from PiFinder import sys_utils

    def _boom(*a, **k):
        raise RuntimeError("git checkout release failed")

    monkeypatch.setattr(sys_utils.sh, "bash", _boom)
    assert sys_utils.update_software() is False


@pytest.mark.unit
def test_fake_imu_monitor_accepts_the_command_queue():
    """main.py passes 4 args (incl. the compass-calibration command queue);
    the fake must bind them or every -fh run loses its IMU process."""
    import inspect

    from PiFinder import imu_fake

    sig = inspect.signature(imu_fake.imu_monitor)
    sig.bind("shared_state", "console_queue", "log_queue", "command_queue")
