"""Progress and measured manual lens result on the device display."""

from PiFinder.types.positioning import CancelLensMeasurement
from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.distortion_calibration import (
    ACTIVE_STATES,
    UIDistortionCalibration,
    distortion_progress_values,
)

REASONS = {
    "no_pattern_match": "Waiting for stars",
    "low_quality": "Need clearer stars",
    "measurement_timeout": "No stable measurement",
    "camera_or_lens_changed": "Lens settings changed",
    "saved": "Manual lens applied",
}


class UILensMeasurement(UIDistortionCalibration):
    __title__ = "AUTO LENS"

    def _status(self):
        try:
            raw = self.shared_state.lens_measurement_status()
        except (AttributeError, BrokenPipeError, ConnectionResetError):
            raw = {"state": "error", "last_reason": "status_unavailable"}
        status = distortion_progress_values(raw, self.request_id)
        status["reason"] = REASONS.get(raw.get("last_reason"), status["reason"])
        status["focal_length_mm"] = raw.get("focal_length_mm")
        status["fov_deg"] = raw.get("fov_deg")
        return status

    def _completed_detail(self, status):
        return f"FOV {status['fov_deg']:.2f} deg"

    def _result_text(self, status):
        return f"Manual {status['focal_length_mm']:.2f} mm"

    def _cancel_if_active(self):
        if self._cancel_sent or self._status()["state"] not in ACTIVE_STATES:
            return
        command_queue = self.command_queues.get("align_command")
        if command_queue is not None:
            command_queue.put(CancelLensMeasurement(request_id=self.request_id))
        self.shared_state.set_lens_measurement_status(
            {
                "state": "cancelled",
                "request_id": self.request_id,
                "last_reason": "cancelled",
                "accepted_frames": 0,
                "required_frames": 5,
            }
        )
        self._cancel_sent = True


class UILensMenu(UITextMenu):
    def active(self):
        super().active()
        self._selected_values = [self.config_object.get_option("camera_lens")]
        for i, item in enumerate(self.item_definition["items"]):
            if item.get("value") == self._selected_values[0]:
                self._current_item_index = i
                break
