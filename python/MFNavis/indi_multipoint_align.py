#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Shared state machine for INDI multi-point alignment."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from PiFinder.indi_align import BRIGHT_ALIGN_STARS, clamp_align_points


ALIGN_MODE_MANUAL = "manual"
ALIGN_MODE_AUTO = "auto"
ALIGN_MODES = {ALIGN_MODE_MANUAL, ALIGN_MODE_AUTO}

STATE_PREPARING = "preparing"
STATE_WAITING = "waiting"
STATE_MOVING = "moving"
STATE_ADJUST = "adjust"
STATE_COMPLETE = "complete"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"
STATE_IDLE = "idle"


class MultiPointAlignController:
    """Own the common multi-point alignment session lifecycle.

    UI layers and SkySafari should only choose when to call into the session.
    MountControlIndi remains responsible for hardware I/O.
    """

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self.session: Optional[dict[str, Any]] = None

    def _now(self) -> float:
        return float(self._clock())

    def _touch(self) -> None:
        if self.session is not None:
            self.session["updated"] = self._now()

    def start(self, mode: str, points: Any) -> dict[str, Any]:
        mode = (mode or ALIGN_MODE_MANUAL).strip().lower()
        if mode not in ALIGN_MODES:
            mode = ALIGN_MODE_MANUAL
        total_points = clamp_align_points(points)
        now = self._now()
        self.session = {
            "active": True,
            "mode": mode,
            "total_points": total_points,
            "completed_points": 0,
            "completed": [],
            "current_star": None,
            "available_stars": [star["name"] for star in BRIGHT_ALIGN_STARS],
            "state": STATE_WAITING,
            "message": "Select an alignment star",
            "started_at": now,
            "updated": now,
        }
        return self.session

    def status(self) -> Optional[dict[str, Any]]:
        return self.session

    def active_session(self) -> Optional[dict[str, Any]]:
        if not self.session or not self.session.get("active"):
            return None
        return self.session

    def set_status(self, state: str, message: str) -> None:
        if self.session is not None:
            self.session["state"] = state
            self.session["message"] = message
            self.session["updated"] = self._now()

    def set_location_time_synced(self) -> None:
        if self.session is not None:
            self.session["location_time_synced"] = True
            self._touch()

    def record_pifinder_sync(
        self,
        source: str,
        ra_deg: float,
        dec_deg: float,
        separation_arcmin: Optional[float],
    ) -> None:
        if self.session is None:
            return
        self.session["pifinder_sync_source"] = source
        self.session["pifinder_sync_ra"] = ra_deg
        self.session["pifinder_sync_dec"] = dec_deg
        self.session["pifinder_mount_separation_arcmin"] = separation_arcmin
        self._touch()

    def record_mount_sync_verified(
        self,
        verified: bool,
        phase: str,
        tolerance_arcmin: float,
        mount_position: Optional[tuple[float, float]] = None,
        separation_arcmin: Optional[float] = None,
    ) -> None:
        if self.session is None:
            return
        self.session["pifinder_mount_verified"] = verified
        self.session["pifinder_mount_verify_phase"] = phase
        self.session["pifinder_mount_verify_tolerance_arcmin"] = tolerance_arcmin
        if mount_position is not None:
            self.session["pifinder_mount_verify_ra"] = mount_position[0]
            self.session["pifinder_mount_verify_dec"] = mount_position[1]
        if separation_arcmin is not None:
            self.session["pifinder_mount_verify_separation_arcmin"] = separation_arcmin
        self._touch()

    def mark_mount_synced(self) -> None:
        if self.session is not None:
            self.session["pifinder_mount_synced"] = True
            self._touch()

    def record_native_alignment_started(self, started: bool) -> None:
        if self.session is None:
            return
        self.session["mount_align_started"] = started
        self.session["mount_align_message"] = (
            "Mount native alignment session started"
            if started
            else "Mount native alignment session unavailable"
        )
        self._touch()

    def set_auto_reference(self, ra_deg: float, dec_deg: float) -> None:
        if self.session is not None:
            self.session["auto_reference"] = {
                "ra": ra_deg % 360.0,
                "dec": dec_deg,
            }
            self._touch()

    def set_current_target(self, star: dict[str, Any]) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("No active multi-point alignment session")
        current_star = {
            "name": str(star.get("name") or "SkySafari Target"),
            "ra": float(star["ra"]) % 360.0,
            "dec": float(star["dec"]),
            "mag": star.get("mag"),
            "target_sent": False,
        }
        self.session["current_star"] = current_star
        self._touch()
        return current_star

    def clear_current_target(self) -> None:
        if self.session is not None:
            self.session["current_star"] = None
            self._touch()

    def mark_current_target_sent(self) -> None:
        if self.session is not None and self.session.get("current_star"):
            self.session["current_star"]["target_sent"] = True
            self._touch()

    def current_target(self) -> Optional[dict[str, Any]]:
        if self.session is None:
            return None
        target = self.session.get("current_star")
        return target if isinstance(target, dict) else None

    def record_current_point(
        self, source: str, mount_align_command: str
    ) -> dict[str, Any]:
        current_star = self.current_target()
        if self.session is None or current_star is None:
            raise RuntimeError("No current alignment target")
        completed = list(self.session.get("completed", []))
        point = {
            "name": current_star["name"],
            "ra": float(current_star["ra"]) % 360.0,
            "dec": float(current_star["dec"]),
            "source": source,
            "mount_align_started": bool(self.session.get("mount_align_started")),
            "mount_align_command": mount_align_command,
            "confirmed_at": self._now(),
        }
        completed.append(point)
        self.session["completed"] = completed
        self.session["completed_points"] = len(completed)
        self.session["current_star"] = None
        self._touch()
        return point

    def complete(self, message: str) -> None:
        if self.session is not None:
            self.session["active"] = False
            self.set_status(STATE_COMPLETE, message)

    def fail(self, message: str) -> None:
        if self.session is not None:
            self.session["active"] = False
            self.set_status(STATE_FAILED, message)

    def cancel(self, message: str = "Multi-point alignment cancelled") -> None:
        if self.session is not None:
            self.session["active"] = False
            self.set_status(STATE_CANCELLED, message)
