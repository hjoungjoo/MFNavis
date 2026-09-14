"""Live LCD progress screen for on-sky lens-distortion measurement."""

from __future__ import annotations

from typing import Any, Mapping

from PiFinder.types.positioning import CancelDistortionCalibration
from PiFinder.ui.base import UIModule


ACTIVE_STATES = frozenset({"requested", "waiting_stars", "measuring", "collecting"})
TERMINAL_STATES = frozenset({"completed", "cancelled", "reset", "error"})

REASON_LABELS = {
    "requested": "Waiting for frame",
    "waiting_stars": "Waiting for stars",
    "not_enough_candidates": "Need more stars",
    "distortion_fit_failed": "No stable fit",
    "not_enough_field_coverage": "Need edge stars",
    "unsafe_distortion": "Fit outside range",
    "corrected_coordinate_mismatch": "Position mismatch",
    "no_rmse_improvement": "Trying next frame",
    "frame_moving": "Hold camera still",
    "waiting_full_frame": "Waiting for frame",
    "measuring_frame": "Solving full frame",
    "accepted": "Frame accepted",
    "saved": "Calibration saved",
    "internal_error": "Measurement error",
}


def distortion_progress_values(
    status: Mapping[str, Any] | None, request_id: int
) -> dict[str, Any]:
    """Normalise shared-process status into safe LCD display values."""

    value = dict(status or {})
    state = str(value.get("state") or "requested")
    status_request_id = value.get("request_id")
    if status_request_id not in {None, request_id}:
        state = "error"
        value["last_reason"] = "session_replaced"

    try:
        accepted = max(0, int(value.get("accepted_frames") or 0))
    except (TypeError, ValueError):
        accepted = 0
    try:
        required = max(1, int(value.get("required_frames") or 5))
    except (TypeError, ValueError):
        required = 5
    try:
        candidates = max(0, int(value.get("last_candidates") or 0))
    except (TypeError, ValueError):
        candidates = 0
    try:
        k1 = float(value["k1"]) if value.get("k1") is not None else None
    except (TypeError, ValueError):
        k1 = None

    reason_key = str(value.get("last_reason") or state)
    reason = REASON_LABELS.get(reason_key, reason_key.replace("_", " ").title())
    return {
        "state": state,
        "accepted": min(accepted, required),
        "required": required,
        "candidates": candidates,
        "k1": k1,
        "reason": reason,
    }


class UIDistortionCalibration(UIModule):
    """Keep the user on a live progress page until measurement finishes."""

    __title__ = "DISTORTION"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.request_id = int(self.item_definition["request_id"])
        self._cancel_sent = False

    def _status(self) -> dict[str, Any]:
        try:
            status = self.shared_state.distortion_calibration_status()
        except (AttributeError, BrokenPipeError, ConnectionResetError):
            status = {"state": "error", "last_reason": "status_unavailable"}
        return distortion_progress_values(status, self.request_id)

    def _draw_progress_bar(self, accepted: int, required: int, y: int) -> None:
        margin = round(self.display_class.resX * 10 / 128)
        width = self.display_class.resX - 2 * margin
        height = max(9, round(self.display_class.resY * 10 / 128))
        self.draw.rectangle(
            [margin, y, margin + width, y + height],
            outline=self.colors.get(96),
            fill=self.colors.get(0),
        )
        fill_width = int((width - 2) * min(accepted / required, 1.0))
        if fill_width > 0:
            self.draw.rectangle(
                [margin + 1, y + 1, margin + 1 + fill_width, y + height - 1],
                fill=self.colors.get(192),
            )

    def _completed_detail(self, status):
        return f"{status['accepted']} / {status['required']} frames"

    def _result_text(self, status):
        return (
            f"k1 {status['k1']:+.4f}"
            if status["k1"] is not None
            else "Calibration saved"
        )

    def update(self, force=False):
        self.clear_screen()
        status = self._status()
        state = status["state"]
        tb = self.display_class.titlebar_height

        if state == "completed":
            self.draw.text(
                (8, tb + 5),
                "MEASURED",
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (8, tb + 28),
                self._completed_detail(status),
                font=self.fonts.large.font,
                fill=self.colors.get(192),
            )
            result = self._result_text(status)
            self.draw.text(
                (8, tb + 55),
                result,
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            hint = f"{self._LEFT_ARROW} Done"
        elif state in ACTIVE_STATES:
            accepted = status["accepted"]
            required = status["required"]
            self.draw.text(
                (8, tb + 3),
                "MEASURE SKY",
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (8, tb + 21),
                f"{accepted} / {required}",
                font=self.fonts.large.font,
                fill=self.colors.get(192),
            )
            bar_y = tb + 47
            self._draw_progress_bar(accepted, required, bar_y)
            self.draw.text(
                (8, bar_y + 16),
                status["reason"],
                font=self.fonts.base.font,
                fill=self.colors.get(160),
            )
            candidate_text = (
                f"Stars {status['candidates']}" if status["candidates"] else "Stars --"
            )
            self.draw.text(
                (8, bar_y + 31),
                candidate_text,
                font=self.fonts.base.font,
                fill=self.colors.get(96),
            )
            hint = f"{self._LEFT_ARROW} Cancel"
        else:
            heading = "CANCELLED" if state in {"cancelled", "reset"} else "FAILED"
            self.draw.text(
                (8, tb + 8),
                heading,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (8, tb + 34),
                status["reason"],
                font=self.fonts.base.font,
                fill=self.colors.get(160),
            )
            hint = f"{self._LEFT_ARROW} Done"

        self.draw.text(
            (8, self.display_class.resY - self.fonts.base.height - 5),
            hint,
            font=self.fonts.base.font,
            fill=self.colors.get(96),
        )
        return self.screen_update(title_bar=True, button_hints=False)

    def _cancel_if_active(self) -> None:
        if self._cancel_sent or self._status()["state"] not in ACTIVE_STATES:
            return
        command_queue = self.command_queues.get("align_command")
        if command_queue is not None:
            command_queue.put(CancelDistortionCalibration(request_id=self.request_id))
        self.shared_state.set_distortion_calibration_status(
            {
                "state": "cancelled",
                "request_id": self.request_id,
                "accepted_frames": 0,
                "required_frames": 5,
                "last_reason": "cancelled",
            }
        )
        self._cancel_sent = True

    def inactive(self):
        self._cancel_if_active()
        super().inactive()

    def key_left(self) -> bool:
        self._cancel_if_active()
        return True

    def key_square(self):
        self._cancel_if_active()
        if self.remove_from_stack is not None:
            self.remove_from_stack()

    def key_number(self, number=None):
        if number == 0:
            self.key_square()
