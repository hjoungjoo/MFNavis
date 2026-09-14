"""Offline coverage for the passive Advanced > Lens declaration UI."""

import queue

import pytest

import PiFinder.i18n  # noqa: F401
from PiFinder.ui import callbacks, menu_structure
from PiFinder.ui.distortion_calibration import (
    UIDistortionCalibration,
    distortion_progress_values,
)
from PiFinder.mf_wide_calibration import CalibrationProfileStore
from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.types.positioning import (
    CancelDistortionCalibration,
    StartDistortionCalibration,
)

pytestmark = pytest.mark.unit


class _Config:
    def __init__(self, lens="", focal_length=None):
        self.lens = lens
        self.focal_length = focal_length
        self.saved = {}

    def get_option(self, option, default=None):
        if option in self.saved:
            return self.saved[option]
        if option == "camera_lens":
            return self.lens if self.lens is not None else default
        if option == "camera_lens_focal_length_mm":
            return self.focal_length if self.focal_length is not None else default
        if option == "wide_solver_calibration_store_v1":
            return default
        raise AssertionError(option)

    def set_option(self, option, value):
        self.saved[option] = value


class _State:
    def __init__(self):
        self.lens = None
        self.distortion_status = {"state": "idle"}

    def camera_type(self):
        return "imx462_color"

    def set_camera_lens(self, lens):
        self.lens = lens

    def set_camera_lens_focal_length_mm(self, focal_length):
        self.focal_length = focal_length

    def camera_lens(self):
        return self.lens

    def camera_lens_focal_length_mm(self):
        return getattr(self, "focal_length", None)

    def lens_measurement_status(self):
        return getattr(self, "lens_status", {})

    def set_lens_measurement_status(self, value):
        self.lens_status = dict(value)

    def distortion_calibration_status(self):
        return dict(self.distortion_status)

    def set_distortion_calibration_status(self, value):
        self.distortion_status = dict(value)


class _UI:
    def __init__(self, lens=""):
        self.config_object = _Config(lens)
        self.shared_state = _State()
        self.pushed = None
        self.messages = []
        self.command_queues = {"align_command": queue.SimpleQueue()}
        self.removed = False

    def add_to_stack(self, item):
        self.pushed = item

    def message(self, message, timeout):
        self.messages.append((message, timeout))

    def remove_from_stack(self):
        self.removed = True


def _lens_menu():
    def walk(node):
        if isinstance(node, dict):
            if node.get("name") == "Lens":
                return node
            for child in node.get("items", []):
                result = walk(child)
                if result:
                    return result
        return None

    result = walk(menu_structure.pifinder_menu)
    assert result is not None
    return result


def _named_menu(name):
    def walk(node):
        if isinstance(node, dict):
            if node.get("name") == name:
                return node
            for child in node.get("items", []):
                result = walk(child)
                if result:
                    return result
        return None

    result = walk(menu_structure.pifinder_menu)
    assert result is not None
    return result


def test_lens_menu_is_a_single_config_declaration():
    menu = _lens_menu()
    assert menu["config_option"] == "camera_lens"
    assert menu["post_callback"] is callbacks.set_camera_lens
    assert [item["value"] for item in menu["items"]] == [
        "",
        "4mm",
        "6mm",
        "8mm",
        "10mm",
        "12mm",
        "16mm",
        "25mm",
        "manual",
    ]
    manual_item = menu["items"][-1]
    assert manual_item["name"] == "Manual (mm)"
    assert manual_item["callback"] is callbacks.edit_manual_lens_focal_length
    assert (
        manual_item["name_suffix_callback"] is callbacks.manual_lens_focal_length_suffix
    )


def test_set_camera_lens_publishes_valid_lens_without_restart():
    ui = _UI("12mm")
    callbacks.set_camera_lens(ui)
    assert ui.shared_state.lens == "12mm"


def test_set_camera_lens_rejects_unrecognised_config_value():
    ui = _UI("bad-lens")
    callbacks.set_camera_lens(ui)
    assert ui.shared_state.lens == ""


def test_manual_lens_menu_opens_one_decimal_entry_and_publishes_value():
    ui = _UI()
    callbacks.edit_manual_lens_focal_length(ui)
    assert ui.pushed["max_length"] == 7
    assert ui.pushed["initial_text"] == ""

    ui.pushed["callback"]("7.64")
    assert ui.config_object.saved["camera_lens_focal_length_mm"] == 7.64
    assert ui.shared_state.focal_length == 7.64


def test_manual_lens_menu_displays_the_active_focal_length():
    ui = _UI()
    ui.config_object.focal_length = 7.6
    assert callbacks.manual_lens_focal_length_suffix(ui) == "  7.60"


def test_distortion_menu_exposes_status_measure_cancel_and_confirmed_reset():
    menu = _named_menu("Distortion")
    assert [item["name"] for item in menu["items"]] == [
        "Status",
        "Measure Sky",
        "Cancel Measurement",
        "Reset",
    ]
    assert menu["items"][-1]["items"][0]["callback"] is (
        callbacks.reset_distortion_calibration
    )


def test_measure_sky_queues_session_for_the_selected_lens():
    ui = _UI("6mm")
    ui.shared_state.lens = "6mm"

    callbacks.start_distortion_calibration(ui)

    command = ui.command_queues["align_command"].get_nowait()
    assert isinstance(command, StartDistortionCalibration)
    assert command.camera_type == "imx462_color"
    assert command.lens_key == "6mm"
    assert ui.shared_state.distortion_status["state"] == "requested"
    assert callbacks.distortion_status_suffix(ui) == "  0/5"
    assert ui.pushed["class"] is UIDistortionCalibration
    assert ui.pushed["request_id"] == command.request_id


def test_distortion_menu_keeps_showing_progress_while_worker_is_measuring():
    ui = _UI("6mm")
    ui.shared_state.distortion_status = {
        "state": "measuring",
        "accepted_frames": 2,
        "required_frames": 5,
        "last_reason": "measuring_frame",
    }

    assert callbacks.distortion_status_suffix(ui) == "  2/5"
    callbacks.show_distortion_status(ui)
    assert ui.messages[-1][0] == "Measuring 2/5\nSolving frame"


def test_distortion_progress_screen_normalises_live_measurement_status():
    values = distortion_progress_values(
        {
            "state": "measuring",
            "request_id": 99,
            "accepted_frames": 2,
            "required_frames": 5,
            "last_candidates": 156,
            "last_reason": "measuring_frame",
        },
        99,
    )

    assert values == {
        "state": "measuring",
        "accepted": 2,
        "required": 5,
        "candidates": 156,
        "k1": None,
        "reason": "Solving full frame",
    }


def test_leaving_active_distortion_progress_screen_cancels_its_session():
    ui = _UI("6mm")
    ui.shared_state.distortion_status = {
        "state": "measuring",
        "request_id": 99,
        "accepted_frames": 2,
        "required_frames": 5,
    }
    screen = object.__new__(UIDistortionCalibration)
    screen.request_id = 99
    screen._cancel_sent = False
    screen.shared_state = ui.shared_state
    screen.command_queues = ui.command_queues

    assert screen.key_left() is True
    command = ui.command_queues["align_command"].get_nowait()
    assert isinstance(command, CancelDistortionCalibration)
    assert command.request_id == 99
    assert ui.shared_state.distortion_status["state"] == "cancelled"


def test_distortion_status_reports_and_reset_clears_saved_sky_profile():
    ui = _UI("6mm")
    profile = get_camera_profile("imx462_color")
    CalibrationProfileStore(ui.config_object).save_auto_sky(
        "imx462_color", "6mm", profile, {"k1": -0.043}, {"frames": 5}
    )
    assert callbacks.distortion_status_suffix(ui) == "  Sky"

    callbacks.reset_distortion_calibration(ui)

    command = ui.command_queues["align_command"].get_nowait()
    assert isinstance(command, CancelDistortionCalibration)
    assert (
        CalibrationProfileStore(ui.config_object).load_active(
            "imx462_color", "6mm", profile
        )
        is None
    )
    assert ui.removed is True


def test_measure_sky_requires_a_named_lens():
    ui = _UI("")

    callbacks.start_distortion_calibration(ui)

    assert ui.command_queues["align_command"].empty()
    assert "Select a named lens" in ui.messages[-1][0]


def test_auto_opens_progress_without_clearing_current_optics():
    from PiFinder.ui.lens_measurement import UILensMeasurement
    from PiFinder.types.positioning import StartLensMeasurement

    ui = _UI("8mm")
    callbacks.start_lens_measurement(ui)
    assert ui.config_object.get_option("camera_lens") == "8mm"
    assert ui.pushed["class"] is UILensMeasurement
    assert ui.shared_state.lens_status["state"] == "requested"
    assert isinstance(
        ui.command_queues["align_command"].get_nowait(), StartLensMeasurement
    )


def test_manual_lens_allows_distortion_measurement_with_its_own_identity():
    ui = _UI("manual")
    ui.config_object.focal_length = 10.5234
    callbacks.start_distortion_calibration(ui)
    command = ui.command_queues["align_command"].get_nowait()
    assert command.lens_key == "manual-10.5234mm"
    assert ui.pushed["class"] is UIDistortionCalibration


def test_selecting_named_lens_clears_manual_override():
    ui = _UI("8mm")
    ui.config_object.focal_length = 10.5234
    callbacks.set_camera_lens(ui)
    assert ui.config_object.get_option("camera_lens_focal_length_mm") is None
    assert ui.shared_state.focal_length is None
