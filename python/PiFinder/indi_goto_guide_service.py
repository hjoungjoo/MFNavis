#!/usr/bin/python
# -*- coding:utf-8 -*-
"""INDI GoTo/Guide orchestration service.

This service is intentionally separate from ``mountcontrol_indi``.  The mount
control process remains the low-level INDI command executor, while this process
owns the higher-level GoTo/Guide policy and state machine.

Responsibilities:

- ``indi_goto_method = off``: reject GoTo requests (Stop/Abort still works).
- ``indi_goto_method = indi_mount``: forward accepted GoTo/abort requests
  straight to the mount-control executor. The mount only ever moves on
  user-issued commands and its own tracking: the tracking guide (pulses,
  disturbance recovery, auto sync) is entirely inactive in this mode (B4,
  docs/mf_report/mf_field_test_20260724_analysis_ko.md).
- ``indi_goto_method = pifinder``: sync the mount to the current
  ``PointingCoordinateService`` coordinate, GoTo the target, and repeat sync +
  GoTo (bounded by ``indi_pifinder_goto_max_gotos``) until within the near
  threshold, then pulse-guide to the final accuracy and do a final sync.
- Tracking Guide (pifinder mode only): when enabled, hold a target with
  pulse-guide correction, and recover from an external disturbance by settling
  first, then either pulse-guiding (small error) or sync + GoTo re-acquisition
  (large error, gated by ``indi_tracking_guide_goto_recovery_enabled``).

All mount motion is issued as small primitive commands on the mount-control
queue; Stop/Abort takes priority in every phase.
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import time
import uuid
from multiprocessing import Queue
from typing import Any, Optional

from PiFinder import config, utils
from PiFinder.calc_utils import sf_utils, pointing_axis_errors
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.operation_errors import ErrorNotifier


logger = logging.getLogger("IndiGotoGuideService")

STATUS_FILE = utils.runtime_dir / "indi_goto_guide_status.json"
MOUNT_STATUS_FILE = utils.runtime_dir / "mount_control_status.json"
POINTING_STATUS_FILE = utils.runtime_dir / "pointing_coordinate_status.json"

HEARTBEAT_SECONDS = 1.0
# Status-file writes go to the tmpfs runtime dir; the web UI polls it ~every 1s,
# so match that cadence (the service loop is also 1s, so writing faster is
# pointless). Cheap on tmpfs -- no SD wear.
STATUS_WRITE_SECONDS = 1.0
# How fast a config change (LCD/Web setting) reaches this service. The service
# does not handle an explicit reload command, so this auto-reload is the only
# path. load_config only READS config.json (no write), so a shorter cadence
# costs a cheap re-parse, not SD wear. Lowered 5.0 -> 2.0 for snappier settings.
CONFIG_RELOAD_SECONDS = 2.0
POINTING_STATUS_MAX_AGE_SECONDS = 5.0
# A GoTo is "complete" once the mount reports no motion continuously for this
# long, and only after the same minimum settle since the command was sent. This
# keeps a brief mid-slew idle -- or an OnStepX near-move/fine-adjust pause --
# from being misread as arrival. Shared by the PiFinder sync + GoTo waits and the
# tracking-guide recovery GoTo wait.
#
# Tuned to 1.0 s from a 6-slew OnStepX field test (12-56 deg slews, 2026-07-18):
# zero mid-slew idle/bounce was observed, and mount-control only clears its
# motion flags after its own GOTO_COMPLETE_STABLE_SECONDS (4 s) window, so by the
# time this service sees no-motion the mount has already been physically stopped
# ~4-5 s. 1.0 s therefore just absorbs command-pickup latency and single-sample
# glitches while trimming per-iteration latency versus the old 2.0 s.
PIFINDER_FINAL_GOTO_SETTLE_SECONDS = 1.0
# Fallback cap on sync + GoTo iterations when indi_pifinder_goto_max_gotos is
# missing from config.
PIFINDER_DEFAULT_MAX_GOTOS = 10
# A sync + GoTo step must cut the error by at least this much versus the previous
# step, otherwise the loop stops rather than slewing without converging.
PIFINDER_MIN_ERROR_IMPROVEMENT_ARCMIN = 1.0
# A 1x sidereal, 2.5 s capped guide pulse moves at most about 0.625 arcmin per
# axis.  With a 3 s fresh-solve cadence and the 90 s pulse-align timeout, an
# initial error above 15 arcmin cannot reliably reach the 6 arcmin target.
# Keep larger errors in the sync+GoTo loop instead of handing an impossible
# correction to the fine pulse stage.
PIFINDER_PULSE_ALIGN_MAX_ERROR_ARCMIN = 15.0
# Give the pulse-guide fine-alignment stage this long to reach the final accuracy
# before giving up (mount-control pulses every 3 s off a fresh solve).
PIFINDER_PULSE_ALIGN_TIMEOUT_SECONDS = 90.0
# After a GoTo settles, wait up to this long for a high-quality plate-solve
# coordinate before measuring the arrival error. IMU estimates right after a
# slew can be degrees off, which poisons both the error measurement and the
# next sync anchor (observed 2026-08-02: attempt error 127' -> 400' off a
# medium-quality estimate). A timeout must not authorize an estimated anchor.
PIFINDER_SOLVE_ANCHOR_WAIT_SECONDS = 12.0
# Status-file freshness does not bound the age of the underlying exposure.
PIFINDER_SOLVE_ANCHOR_MAX_AGE_SECONDS = 12.0
TRACKING_GUIDE_MAX_RECOVERY_GOTOS = 5
# Once the tracking target sinks below this altitude the guide must never move
# the mount toward it (overnight targets set below the horizon; a recovery slew
# would drive the scope into the ground). Overridable via config.
TRACKING_TARGET_MIN_ALT_DEFAULT_DEG = 10.0
# Target altitude changes at sidereal rate, so a cached value stays valid for
# a while; recompute this often (or immediately when the target changes).
TRACKING_TARGET_ALT_CACHE_SECONDS = 10.0
# The BNO055 "moving" flag is far more sensitive than the coordinate-motion
# threshold (quaternion-delta hysteresis around 0.0003) and can stay set for
# tens of seconds of micro-sway after the scope is released. Without a bound it
# resets the settle window every tick and delays recovery indefinitely. Once
# the fused coordinate has been still for this many settle windows, the IMU
# flag alone no longer holds off recovery (2x the 1 s settle default = 2 s cap).
TRACKING_IMU_QUIET_OVERRIDE_MULTIPLE = 2.0


class IndiGotoGuideService:
    """State-machine host for future INDI GoTo/Guide behavior."""

    def __init__(
        self,
        service_queue: Queue,
        mountcontrol_queue: Optional[Queue],
        shared_state: Any,
        alert_queue: Optional[Queue] = None,
    ):
        self.service_queue = service_queue
        self.mountcontrol_queue = mountcontrol_queue
        self.shared_state = shared_state
        self.error_notifier = ErrorNotifier(alert_queue, "GoTo / Guide")
        self.started_at = time.time()
        self.updated_at = 0.0
        self.last_config_load = 0.0
        self.config_values: dict[str, Any] = {}
        # Keypad/keyboard/Web-Remote type changes are deliberately runtime
        # only, avoiding repeated config.json writes to the SD card.
        self.runtime_goto_method: Optional[str] = None
        self.last_command: Optional[str] = None
        self.sync_goto_request_id: Optional[str] = None
        self.service_state = "starting"
        self.phase = "idle"
        self.wait_reason = ""
        self.active_target_ra: Optional[float] = None
        self.active_target_dec: Optional[float] = None
        self.current_ra: Optional[float] = None
        self.current_dec: Optional[float] = None
        self.last_error_arcmin: Optional[float] = None
        self.alignment_target_pixel = None
        self.goto_plan: Optional[dict[str, Any]] = None
        self.final_goto_sent_at = 0.0
        self.final_goto_idle_since = 0.0
        # Total sync + GoTo iterations issued for the active target (initial
        # GoTo is attempt 1), compared against indi_pifinder_goto_max_gotos.
        self.correction_count = 0
        self.previous_goto_error_arcmin: Optional[float] = None
        self.final_sync_sent = False
        self.pulse_align_sent = False
        self.pulse_align_started_at = 0.0
        self.tracking_target_ra: Optional[float] = None
        self.tracking_target_dec: Optional[float] = None
        self.tracking_guide_active_sent = False
        self.tracking_guide_state = "off"
        self.tracking_guide_last_action = ""
        self.tracking_guide_error_arcmin: Optional[float] = None
        self.tracking_guide_accuracy_arcmin: Optional[float] = None
        self.tracking_guide_recovery_mode = "none"
        self.tracking_guide_recovery_count = 0
        self.tracking_guide_settle_remaining: Optional[float] = None
        self.tracking_motion_ra: Optional[float] = None
        self.tracking_motion_dec: Optional[float] = None
        self.tracking_last_motion_at = 0.0
        self.tracking_last_imu_motion_at = 0.0
        self.tracking_imu_flag_overridden = False
        # Cached tracking-target altitude, keyed by target coordinates so a
        # fresh target is never judged by a stale altitude.
        self._target_alt_cache: Optional[dict[str, Any]] = None
        self.tracking_recovery_state = "idle"
        self.tracking_recovery_goto_sent_at = 0.0
        self.tracking_recovery_goto_idle_since = 0.0
        self.tracking_recovery_attempts = 0
        # Manual re-target: a user mount manual-move during tracking, once ended
        # and settled, adopts the stopped position as the new target.
        self.manual_retarget_pending = False
        self.manual_retarget_count = 0
        self.goto_started_wall = time.time()
        self.manual_motion_handled_wall = self.goto_started_wall
        self.manual_retarget_idle_since = 0.0
        self.manual_retarget_after_wall = 0.0
        self.manual_target_origin: Optional[tuple[float, float]] = None
        # User-requested pause of tracking guide + GoTo recovery. Runtime-only
        # (config checkboxes untouched); cleared by the next GoTo or once a
        # manual move ends and settles.
        self.tracking_guide_suspended = False
        # Monotonic timestamp of the first post-settle tick that found no
        # high-quality solve coordinate; bounds the solve-anchor wait.
        self.solve_anchor_wait_since = 0.0
        # A high-quality solve from before the mount became idle is stale for
        # arrival-error decisions even when PointingCoordinateService still
        # publishes it. This wall-clock boundary is set on the first idle tick.
        self.solve_anchor_required_after_wall = 0.0
        # Same bounded wait for the tracking-recovery goto's sync anchor.
        self.recovery_anchor_wait_since = 0.0
        self.initial_goto_deadline: Optional[float] = None
        self.last_action = "startup"
        self.pointing_status: dict[str, Any] = {"available": False}

    def run(self) -> None:
        logger.info("INDI GoTo/Guide service started")
        self.service_state = "idle"
        running = True
        while running:
            self._reload_config_if_needed()
            self._tick_state_machine()
            self._tick_tracking_guide()
            self._write_status()
            try:
                command = self.service_queue.get(timeout=self._loop_timeout())
            except queue.Empty:
                continue

            try:
                self._refresh_pointing_status()
                running = self.handle_command(command)
            except Exception:
                logger.exception("INDI GoTo/Guide command failed: %r", command)
                self.service_state = "error"
                self.phase = "error"
                self.wait_reason = "command failed"

        self.service_state = "stopped"
        self.phase = "stopped"
        self._write_status(force=True)
        logger.info("INDI GoTo/Guide service stopped")

    def _loop_timeout(self) -> float:
        # A queued command (e.g. Stop) interrupts the wait immediately, so the
        # single heartbeat cadence is enough for the sync + GoTo and pulse-align
        # waits (both driven by the mount, not by keepalives from here).
        return HEARTBEAT_SECONDS

    def handle_command(self, command: Any) -> bool:
        if not isinstance(command, dict):
            logger.warning("Ignoring INDI GoTo/Guide command: %r", command)
            return True

        command_type = str(command.get("type", "")).strip()
        if command_type in {
            "goto_target",
            "set_tracking_target",
            "resume_tracking_guide",
        }:
            self.error_notifier.reset()
        self.last_command = command_type or "unknown"

        if command_type in {
            "shutdown",
            "ping",
            "set_goto_method",
            "clear_tracking_target",
            "set_tracking_target",
            "suspend_tracking_guide",
            "stop_movement",
        }:
            self._cancel_initial_goto_wait("pending GoTo canceled by user command")

        if command_type == "shutdown":
            return False
        if command_type == "ping":
            self.service_state = "idle"
            self.phase = "idle"
            self.wait_reason = ""
            self.last_action = "ping"
            return True
        if command_type == "set_goto_method":
            goto_method = str(command.get("goto_method", "")).strip()
            if goto_method not in {"off", "indi_mount", "pifinder"}:
                logger.warning("Invalid runtime GoTo Type: %r", command)
                return True
            self.runtime_goto_method = goto_method
            self.config_values["indi_goto_method"] = goto_method
            self.last_action = f"runtime GoTo Type: {goto_method}"
            self._write_status(force=True)
            return True
        if command_type == "reload_config":
            # Settings-menu changes are persistent and intentionally replace a
            # transient keypad/keyboard/Web-Remote selection immediately.
            self.runtime_goto_method = None
            self.last_config_load = 0.0
            self._reload_config_if_needed()
            self.last_action = "config reloaded"
            self._write_status(force=True)
            return True
        if command_type == "goto_target":
            self._handle_goto_target(command)
            return True
        if command_type == "clear_tracking_target":
            # Drop the tracking target without any mount command. Sent by the
            # pointing reset: after a frame re-alignment the old target (often
            # hours stale, possibly below the horizon) must not drive a
            # recovery slew.
            self._disable_tracking_guide("tracking target cleared")
            self._reset_tracking_recovery()
            self.tracking_target_ra = None
            self.tracking_target_dec = None
            self.last_action = "tracking target cleared"
            logger.info("Tracking target cleared by request")
            return True
        if command_type == "set_tracking_target":
            # Re-arm the tracking-guide target for a GoTo issued outside this
            # service (fallback path when a UI sends goto_target straight to
            # mount control). Does not move the mount; it just lets the
            # tracking guide resume auto-correction.
            try:
                ra, dec = float(command["ra"]) % 360.0, float(command["dec"])
                if (
                    not math.isfinite(ra)
                    or not math.isfinite(dec)
                    or not -90 <= dec <= 90
                ):
                    raise ValueError("invalid tracking target")
                self._disable_tracking_guide("tracking target changed")
                self._disable_pulse_align()
                self.tracking_target_ra, self.tracking_target_dec = ra, dec
                self.active_target_ra, self.active_target_dec = ra, dec
                if not command.get("manual_retarget"):
                    self.manual_target_origin = None
                self.alignment_target_pixel = command.get("alignment_target_pixel")
                self.phase = "tracking"
                self.service_state = "idle"
                self.goto_plan = None
                self.last_error_arcmin = None
                self.final_sync_sent = False
                self.tracking_motion_ra = self.tracking_motion_dec = None
                self.tracking_last_motion_at = time.monotonic()
                self.tracking_last_imu_motion_at = 0.0
                self.tracking_guide_suspended = False
                self.manual_retarget_pending = False
                self._reset_tracking_recovery()
                self.last_action = "tracking target set"
                logger.info(
                    "Tracking target set: RA %.4f Dec %.4f",
                    self.tracking_target_ra,
                    self.tracking_target_dec,
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Invalid set_tracking_target command: %r", command)
            return True
        if command_type == "suspend_tracking_guide":
            self.tracking_guide_suspended = True
            self._disable_tracking_guide("suspended by user")
            self._reset_tracking_recovery()
            self.tracking_guide_state = "suspended"
            self.tracking_guide_last_action = "suspended until next GoTo or manual move"
            self.last_action = "tracking guide suspended"
            logger.info("Tracking guide suspended by user request")
            return True
        if command_type == "resume_tracking_guide":
            self.tracking_guide_suspended = False
            self.tracking_guide_last_action = "resumed by user"
            self.last_action = "tracking guide resumed"
            logger.info("Tracking guide resumed by user request")
            return True
        if command_type == "stop_movement":
            self._forward_to_mountcontrol({"type": "stop_movement"})
            self.active_target_ra = None
            self.active_target_dec = None
            self.current_ra = None
            self.current_dec = None
            self.last_error_arcmin = None
            self.goto_plan = None
            self.final_goto_sent_at = 0.0
            self.final_goto_idle_since = 0.0
            self.correction_count = 0
            self.previous_goto_error_arcmin = None
            self.final_sync_sent = False
            self._disable_pulse_align()
            self._disable_tracking_guide("stop command")
            self._reset_tracking_recovery()
            self.tracking_guide_suspended = False
            # Clear the tracking target so auto-correction stays off until the
            # next GoTo / tracking start re-arms it.
            self.tracking_target_ra = None
            self.tracking_target_dec = None
            self.service_state = "idle"
            self.phase = "idle"
            self.wait_reason = ""
            self.last_action = "stop_movement"
            return True

        logger.info(
            "Queued INDI GoTo/Guide command is not implemented yet: %s",
            command_type,
        )
        self.service_state = "idle"
        self.phase = "idle"
        self.wait_reason = f"command not implemented: {command_type or 'unknown'}"
        return True

    def _handle_goto_target(self, command: dict[str, Any]) -> None:
        self.manual_target_origin = None
        self.initial_goto_deadline = None
        self.alignment_target_pixel = None
        try:
            target_ra = float(command["ra"])
            target_dec = float(command["dec"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Invalid INDI GoTo target command: %r", command)
            self.service_state = "error"
            self.phase = "error"
            self.wait_reason = "invalid goto target"
            self.last_action = "goto rejected"
            return

        if self.config_values.get("indi_goto_method", "pifinder") == "off":
            self.service_state = "idle"
            self.phase = "idle"
            self.wait_reason = "goto disabled (GoTo Type off)"
            self.last_action = "goto rejected: GoTo Type off"
            logger.info(
                "INDI GoTo rejected; indi_goto_method is off (RA %.4f Dec %.4f)",
                target_ra,
                target_dec,
            )
            return

        if self.tracking_guide_suspended:
            self.tracking_guide_suspended = False
            logger.info("Tracking guide suspension cleared by new GoTo")

        self.active_target_ra = target_ra
        self.active_target_dec = target_dec

        # Reset per-GoTo state. Without this a second GoTo in the same session
        # (e.g. a fresh SkySafari GoTo after one already completed, or a
        # disturbance recovery) inherits a stale final_sync_sent=True, so
        # _send_final_sync_once() no-ops and the state machine never advances to
        # "complete". Stale correction_count / previous_goto_error_arcmin would
        # likewise mis-fire the GoTo limit and the "error did not improve" guard.
        self.correction_count = 0
        self.previous_goto_error_arcmin = None
        self.final_sync_sent = False
        self.final_goto_idle_since = 0.0
        self.final_goto_sent_at = 0.0
        self.manual_retarget_pending = False
        self.goto_started_wall = time.time()
        self._disable_pulse_align()

        goto_method = self.config_values.get("indi_goto_method", "pifinder")

        if goto_method == "indi_mount":
            # No refine_after_goto passthrough: post-GoTo refinement is this
            # service's job (indi_goto_method = pifinder), not mount-control's
            # legacy one-shot solve refine.
            forwarded = self._forward_to_mountcontrol(
                {
                    "type": "goto_target",
                    "ra": target_ra,
                    "dec": target_dec,
                }
            )
            if not forwarded:
                return

            # B4: no tracking target in indi_mount mode -- the tracking guide
            # never acts there, and a stale target must not spring to life on
            # a later switch to pifinder mode.
            self.service_state = "running"
            self.phase = "indi_mount_goto"
            self.wait_reason = ""
            self.last_action = "forwarded goto_target"
            logger.info(
                "Forwarded INDI Mount GoTo target: RA %.4f Dec %.4f",
                target_ra,
                target_dec,
            )
            return

        block_reason = self._pifinder_goto_block_reason()
        if block_reason:
            self.service_state = "waiting"
            self.phase = "pifinder_goto_blocked"
            self.wait_reason = block_reason
            self.last_action = "pifinder goto blocked"
            if block_reason == "PiFinder GoTo requires a recent plate solve":
                self._disable_tracking_guide("waiting for new GoTo solve anchor")
                self._reset_tracking_recovery()
                self.tracking_target_ra = self.tracking_target_dec = None
                self.initial_goto_deadline = (
                    time.monotonic() + PIFINDER_SOLVE_ANCHOR_WAIT_SECONDS
                )
                self.last_action = "waiting for initial solve anchor"
            logger.info("PiFinder GoTo blocked: %s", self.wait_reason)
            return

        self._begin_pifinder_goto(target_ra, target_dec)

    def _begin_pifinder_goto(self, target_ra: float, target_dec: float) -> None:
        """Use the same checked pointing snapshot when starting or resuming."""
        current = self.pointing_status.get("current") or {}
        self.current_ra = self._finite_float(current.get("ra"))
        self.current_dec = self._finite_float(current.get("dec"))
        self.last_error_arcmin = self._target_error_arcmin(
            self.current_ra,
            self.current_dec,
            target_ra,
            target_dec,
        )
        self.goto_plan = {
            "method": "pifinder",
            "target_ra": target_ra,
            "target_dec": target_dec,
            "current_ra": self.current_ra,
            "current_dec": self.current_dec,
            "error_arcmin": self.last_error_arcmin,
            "current_source": current.get("source"),
            "current_quality": current.get("quality"),
            "near_threshold_degrees": self._pulse_align_threshold_arcmin() / 60.0,
            "configured_near_threshold_degrees": self.config_values.get(
                "indi_pifinder_goto_near_threshold_deg", 1.0
            ),
            "max_gotos": self._max_gotos(),
            "stage": "pifinder_goto",
        }

        # Sync + GoTo loop, starting with the first iteration: sync the mount to
        # the current PiFinder coordinate (so the readback aligns to PiFinder,
        # current.source = mount, instead of the raw IMU fallback) and GoTo the
        # target. Completion and the error branch are handled in _tick_goto_wait.
        self._send_sync_and_goto(first=True)

    def _forward_to_mountcontrol(self, command: dict[str, Any]) -> bool:
        if self.mountcontrol_queue is None:
            logger.warning("Cannot forward INDI GoTo/Guide command; queue unavailable")
            self.service_state = "error"
            self.phase = "error"
            self.wait_reason = "mountcontrol queue unavailable"
            self.last_action = "forward failed"
            return False

        self.mountcontrol_queue.put(command)
        return True

    def _sync_context(
        self, origin: str, pointing_source: Optional[str] = None
    ) -> dict[str, Any]:
        """B5 visibility (docs/mf_report/mf_field_test_20260724_analysis_ko.md): tag a
        sync command with who requested it and which coordinate source fed
        the value, so mount-control can record it in ``coordinate_sync``."""
        pointing = (
            self.pointing_status if isinstance(self.pointing_status, dict) else {}
        )
        current = pointing.get("current") or {}
        solved = pointing.get("solved") or {}
        solve_age_seconds = None
        solved_timestamp = solved.get("timestamp")
        if solved.get("valid") and isinstance(solved_timestamp, (int, float)):
            solve_age_seconds = max(0.0, time.time() - float(solved_timestamp))
        context: dict[str, Any] = {
            "origin": origin,
            "pointing_source": pointing_source or current.get("source") or "unknown",
        }
        if solve_age_seconds is not None:
            context["solve_age_seconds"] = round(solve_age_seconds, 1)
        return context

    def _tick_state_machine(self) -> None:
        goto_active = self.phase in {
            "pifinder_goto_blocked",
            "pifinder_goto",
            "pifinder_pulse_align",
        }
        tracking_retarget = (
            self.config_values.get("indi_goto_method", "pifinder") == "pifinder"
            and self.config_values.get(
                "indi_tracking_guide_manual_retarget_enabled", True
            )
            and self.tracking_target_ra is not None
            and self.tracking_target_dec is not None
        )
        if goto_active or tracking_retarget or self.phase == "manual_retarget":
            status = self._mount_status_summary()
            user_started = self._finite_float(
                status.get("last_user_motion_started_wall")
            )
            new_user_motion = user_started is not None and user_started > max(
                self.goto_started_wall, self.manual_motion_handled_wall
            )
            if new_user_motion and user_started is not None:
                self.manual_motion_handled_wall = user_started
            if self.phase != "manual_retarget" and (
                self._mount_summary_reports_manual_motion(status) or new_user_motion
            ):
                # Also runs after GoTo completion and before recovery handling.
                # The persistent event catches key taps between service ticks.
                self._begin_manual_retarget()
        if self.phase == "manual_retarget":
            self._tick_manual_retarget()
            return
        if (
            self.phase == "pifinder_goto_blocked"
            and self.initial_goto_deadline is not None
        ):
            self._tick_initial_goto_wait()
            return
        if self.phase == "pifinder_goto":
            self._tick_goto_wait()
            return
        if self.phase == "pifinder_pulse_align":
            self._tick_pulse_align()
            return

    def _begin_manual_retarget(self) -> None:
        """User movement replaces the GoTo destination after release/settle."""
        if self.manual_target_origin is None:
            ra = (
                self.active_target_ra
                if self.active_target_ra is not None
                else self.tracking_target_ra
            )
            dec = (
                self.active_target_dec
                if self.active_target_dec is not None
                else self.tracking_target_dec
            )
            if ra is not None and dec is not None:
                self.manual_target_origin = (ra, dec)
        self._disable_pulse_align()
        self._disable_tracking_guide("manual target change")
        self._reset_tracking_recovery()
        self.sync_goto_request_id = None
        self.initial_goto_deadline = None
        self.manual_retarget_idle_since = 0.0
        self.manual_retarget_after_wall = 0.0
        self.phase = "manual_retarget"
        self.service_state = "running"
        self.last_action = "waiting for manual position"

    def _tick_manual_retarget(self) -> None:
        status = self._mount_status_summary()
        if not status.get("available") or self._mount_summary_reports_motion(status):
            self.manual_retarget_idle_since = 0.0
            return
        if self._mount_summary_reports_parked(status):
            return
        stopped_wall = float(status.get("last_user_motion_stopped_wall") or 0.0)
        now = time.monotonic()
        if (
            self.manual_retarget_idle_since == 0.0
            or stopped_wall > self.manual_retarget_after_wall
        ):
            self.manual_retarget_idle_since = now
            self.manual_retarget_after_wall = time.time()
        settle = float(
            self.config_values.get("indi_tracking_guide_settle_seconds", 1.0)
        )
        if now - self.manual_retarget_idle_since < settle:
            self.last_action = "waiting for manual position to settle"
            return
        pointing = self._refresh_pointing_status()
        current = pointing.get("current") or {}
        if (
            not pointing.get("usable_for_goto")
            or not self._is_recent_solve(current)
            or float(current.get("timestamp") or 0.0)
            < self.manual_retarget_after_wall + settle
        ):
            self.last_action = "waiting for solve at manual position"
            if (
                now - self.manual_retarget_idle_since
                >= PIFINDER_SOLVE_ANCHOR_WAIT_SECONDS
            ):
                self.error_notifier.emit(
                    "manual_target_waiting_solve",
                    "No fresh camera solve after manual movement. Correction is paused until a new solve is available.",
                )
            return
        ra, dec = (
            self._finite_float(current.get("ra")),
            self._finite_float(current.get("dec")),
        )
        if ra is None or dec is None:
            return
        self.handle_command(
            {
                "type": "set_tracking_target",
                "ra": ra,
                "dec": dec,
                "manual_retarget": True,
            }
        )
        self.manual_retarget_count += 1
        self.wait_reason = ""
        self.last_action = "target changed to manual position"
        logger.info("Target changed to manual position: RA %.4f Dec %.4f", ra, dec)

    def _cancel_initial_goto_wait(self, reason: str) -> None:
        if self.initial_goto_deadline is None:
            return
        self.initial_goto_deadline = None
        self.service_state = "error"
        self.wait_reason = reason
        self.last_action = "pending GoTo canceled"
        logger.info("PiFinder pending GoTo canceled: %s", reason)

    def _tick_initial_goto_wait(self) -> None:
        # A rejected click must not become an indefinitely armed future slew.
        # Expiry and cancellation win even if a solve arrives on that tick.
        deadline = self.initial_goto_deadline
        if deadline is None:
            return
        if time.monotonic() >= deadline:
            self._cancel_initial_goto_wait(
                "timed out waiting for a recent plate solve; request GoTo again"
            )
            return
        if self.config_values.get("indi_goto_method", "pifinder") != "pifinder":
            self._cancel_initial_goto_wait("GoTo method changed while waiting")
            return
        mount = self._mount_status_summary()
        if self._mount_summary_reports_parked(
            mount
        ) or self._mount_summary_reports_motion(mount):
            self._cancel_initial_goto_wait("mount parked or moved while waiting")
            return
        reason = self._pifinder_goto_block_reason()
        if reason:
            self.wait_reason = reason
            return
        self.initial_goto_deadline = None
        if self.active_target_ra is None or self.active_target_dec is None:
            return
        logger.info("PiFinder initial GoTo resumed with a recent plate solve")
        self._begin_pifinder_goto(self.active_target_ra, self.active_target_dec)

    def _stop_with_error(self, reason: str) -> None:
        self._forward_to_mountcontrol({"type": "stop_movement"})
        self._disable_pulse_align()
        self.service_state = "error"
        self.phase = "error"
        self.wait_reason = reason
        self.last_action = "pifinder goto stopped"
        self._update_goto_plan()
        logger.warning("PiFinder GoTo stopped: %s", reason)

    def _max_gotos(self) -> int:
        try:
            value = int(
                self.config_values.get(
                    "indi_pifinder_goto_max_gotos", PIFINDER_DEFAULT_MAX_GOTOS
                )
            )
        except (TypeError, ValueError):
            value = PIFINDER_DEFAULT_MAX_GOTOS
        return max(1, value)

    def _final_accuracy_arcmin(self) -> float:
        try:
            value = float(
                self.config_values.get("indi_goto_refine_accuracy_arcmin", 3.0)
            )
        except (TypeError, ValueError):
            value = 3.0
        return max(0.1, value)

    def _pulse_align_threshold_arcmin(self) -> float:
        """Return the configured near threshold capped to pulse capacity."""

        try:
            configured = (
                float(
                    self.config_values.get("indi_pifinder_goto_near_threshold_deg", 1.0)
                )
                * 60.0
            )
        except (TypeError, ValueError):
            configured = PIFINDER_PULSE_ALIGN_MAX_ERROR_ARCMIN
        return min(
            max(self._final_accuracy_arcmin(), configured),
            PIFINDER_PULSE_ALIGN_MAX_ERROR_ARCMIN,
        )

    def _is_recent_solve(self, current: dict[str, Any]) -> bool:
        """Require a camera solve with a recent, finite observation epoch."""
        timestamp = self._finite_float(current.get("timestamp"))
        return bool(
            current.get("source") == "solve"
            and current.get("quality") == "high"
            and timestamp is not None
            and 0.0 <= time.time() - timestamp <= PIFINDER_SOLVE_ANCHOR_MAX_AGE_SECONDS
        )

    def _is_fresh_arrival_solve(self, current: dict[str, Any]) -> bool:
        """Require a recent camera solve captured after the mount became idle."""

        timestamp = self._finite_float(current.get("timestamp"))
        return bool(
            self._is_recent_solve(current)
            and timestamp is not None
            and timestamp >= self.solve_anchor_required_after_wall
        )

    def _send_sync_and_goto(self, *, first: bool) -> None:
        """Sync the mount to the current PiFinder coordinate, then GoTo target.

        Used for both the initial iteration and every corrective one; the sync
        re-aligns the mount frame to PiFinder so each GoTo only closes the
        remaining error. Advances to the pifinder_goto wait phase.
        """
        if (
            self.current_ra is None
            or self.current_dec is None
            or self.active_target_ra is None
            or self.active_target_dec is None
        ):
            self._stop_with_error("pifinder GoTo coordinates unavailable")
            return

        self.sync_goto_request_id = uuid.uuid4().hex
        self._forward_to_mountcontrol(
            {
                "type": "sync_and_goto",
                "request_id": self.sync_goto_request_id,
                "sync_ra": self.current_ra,
                "sync_dec": self.current_dec,
                "ra": self.active_target_ra,
                "dec": self.active_target_dec,
                **self._sync_context("pifinder_goto"),
            }
        )
        self.correction_count = 1 if first else self.correction_count + 1
        self.previous_goto_error_arcmin = self.last_error_arcmin
        self.final_goto_sent_at = time.monotonic()
        self.final_goto_idle_since = 0.0
        self.solve_anchor_wait_since = 0.0
        self.solve_anchor_required_after_wall = 0.0
        self.service_state = "running"
        self.phase = "pifinder_goto"
        self.wait_reason = ""
        self.last_action = (
            "pifinder sync + goto sent"
            if first
            else f"pifinder sync + goto {self.correction_count}/{self._max_gotos()}"
        )
        self._update_goto_plan()
        if self.goto_plan is not None:
            self.goto_plan.update(
                {
                    "stage": "pifinder_goto",
                    "sync_ra": self.current_ra,
                    "sync_dec": self.current_dec,
                    "goto_ra": self.active_target_ra,
                    "goto_dec": self.active_target_dec,
                    "goto_attempt": self.correction_count,
                }
            )
        logger.info(
            "PiFinder sync + GoTo %s/%s: sync RA %.4f Dec %.4f -> target "
            "RA %.4f Dec %.4f (error %.2f arcmin)",
            self.correction_count,
            self._max_gotos(),
            self.current_ra,
            self.current_dec,
            self.active_target_ra,
            self.active_target_dec,
            self.last_error_arcmin if self.last_error_arcmin is not None else -1.0,
        )

    def _begin_pulse_align(self) -> None:
        """Hand off to manual approach plus pulse alignment near the target.

        OnStep Alt/Az uses bounded physical-axis moves outside the pulse band,
        then the existing timed-guide path for final accuracy. Each correction
        requires a post-motion solve. Tracking hold remains pulse-only.
        """
        if self.active_target_ra is None or self.active_target_dec is None:
            self._stop_with_error("pulse align target unavailable")
            return
        accuracy = self._final_accuracy_arcmin()
        self.tracking_target_ra = self.active_target_ra
        self.tracking_target_dec = self.active_target_dec
        self._forward_to_mountcontrol(
            {
                "type": "toggle_guide_correction",
                "enabled": True,
                "target_ra": self.active_target_ra,
                "target_dec": self.active_target_dec,
                "accuracy_arcmin": accuracy,
                "manual_approach": True,
            }
        )
        self.pulse_align_sent = True
        self.pulse_align_started_at = time.monotonic()
        self.service_state = "running"
        self.phase = "pifinder_pulse_align"
        self.wait_reason = ""
        self.last_action = "pifinder pulse align started"
        self._update_goto_plan()
        if self.goto_plan is not None:
            self.goto_plan.update(
                {
                    "stage": "pifinder_pulse_align",
                    "pulse_accuracy_arcmin": accuracy,
                }
            )
        logger.info(
            "PiFinder pulse align: target RA %.4f Dec %.4f accuracy %.2f arcmin "
            "(error %.2f arcmin)",
            self.active_target_ra,
            self.active_target_dec,
            accuracy,
            self.last_error_arcmin if self.last_error_arcmin is not None else -1.0,
        )

    def _tick_pulse_align(self) -> None:
        if self.active_target_ra is None or self.active_target_dec is None:
            self._stop_with_error("pulse align target unavailable")
            return

        mount_status = self._mount_status_summary()
        if not mount_status.get("available"):
            self._stop_with_error("mount status unavailable during pulse align")
            return
        if self._mount_summary_reports_parked(mount_status):
            self._stop_with_error("mount parked during pulse align")
            return
        if (
            str(mount_status.get("state", "")).strip().lower()
            == "guide_correction_failed"
            or mount_status.get("guide_correction_mode") == "failed"
        ):
            self._stop_with_error(
                str(mount_status.get("message") or "pulse align failed")
            )
            return

        if (
            time.monotonic() - self.pulse_align_started_at
            > PIFINDER_PULSE_ALIGN_TIMEOUT_SECONDS
        ):
            self._stop_with_error("pulse align did not converge")
            return
        if self._mount_summary_reports_motion(mount_status):
            if mount_status.get("manual_motion_origin") == "user":
                self._begin_manual_retarget()
                return
            self.last_action = "pifinder manual approach"
            return

        pointing = self._refresh_pointing_status()
        if not pointing.get("usable_for_goto"):
            if mount_status.get("guide_correction_mode") in {
                "manual_approach",
                "settling",
            }:
                self.last_action = "waiting for solve after manual approach"
                return
            self._stop_with_error(
                str(pointing.get("reason") or "pointing unavailable during pulse align")
            )
            return

        current = pointing.get("current") or {}
        self.current_ra = self._finite_float(current.get("ra"))
        self.current_dec = self._finite_float(current.get("dec"))
        self.last_error_arcmin = self._target_error_arcmin(
            self.current_ra,
            self.current_dec,
            self.active_target_ra,
            self.active_target_dec,
        )
        self._update_goto_plan()

        accuracy = self._final_accuracy_arcmin()
        pulse_end = float(mount_status.get("guide_pulse_until_wall") or 0.0)
        observation_after = max(
            pulse_end, float(mount_status.get("guide_observation_after_wall") or 0.0)
        )
        if (
            self.last_error_arcmin is not None
            and self.last_error_arcmin <= accuracy
            and self._is_recent_solve(current)
            and float(current.get("timestamp") or 0.0) >= observation_after
            and not self._mount_summary_reports_motion(mount_status)
        ):
            self._disable_pulse_align()
            self._send_final_sync_once()
            return

        self.last_action = (
            f"pifinder pulse align {self.last_error_arcmin:.1f} arcmin"
            if self.last_error_arcmin is not None
            else "pifinder pulse align"
        )

    def _disable_pulse_align(self) -> None:
        if self.pulse_align_sent:
            self._forward_to_mountcontrol(
                {"type": "toggle_guide_correction", "enabled": False}
            )
        self.pulse_align_sent = False
        self.pulse_align_started_at = 0.0

    def _tick_goto_wait(self) -> None:
        """Wait for the active sync + GoTo to finish, then branch on the error.

        Completion is decided by the mount motion flags plus a settle window
        (see _mount_summary_reports_motion): the GoTo is done once the mount
        reports no motion for PIFINDER_FINAL_GOTO_SETTLE_SECONDS, and only after
        the same minimum settle since the command was sent. The arrival error is
        then measured from PointingCoordinateService and drives the branch:
        below the final accuracy -> final sync; within the near threshold ->
        pulse-guide fine alignment; otherwise -> another sync + GoTo (bounded).
        """
        if self.active_target_ra is None or self.active_target_dec is None:
            self._stop_with_error("pifinder GoTo target unavailable")
            return

        mount_status = self._mount_status_summary()
        if not mount_status.get("available"):
            self._stop_with_error("mount status unavailable during GoTo")
            return
        if self._mount_summary_reports_parked(mount_status):
            self._stop_with_error("mount parked during GoTo")
            return

        if not self._verified_sync_goto_ready(mount_status, recovery=False):
            return

        now = time.monotonic()
        if now - self.final_goto_sent_at < PIFINDER_FINAL_GOTO_SETTLE_SECONDS:
            return

        if self._mount_summary_reports_motion(mount_status):
            self.final_goto_idle_since = 0.0
            self.last_action = "waiting for INDI GoTo"
            return
        if self.final_goto_idle_since == 0.0:
            self.final_goto_idle_since = now
            self.solve_anchor_required_after_wall = time.time()
            return
        if now - self.final_goto_idle_since < PIFINDER_FINAL_GOTO_SETTLE_SECONDS:
            return

        pointing = self._refresh_pointing_status()
        if not pointing.get("usable_for_goto"):
            self._stop_with_error(
                str(pointing.get("reason") or "pointing unavailable after GoTo")
            )
            return

        current = pointing.get("current") or {}
        if not self._is_fresh_arrival_solve(current):
            if self.solve_anchor_wait_since == 0.0:
                self.solve_anchor_wait_since = now
            if now - self.solve_anchor_wait_since < PIFINDER_SOLVE_ANCHOR_WAIT_SECONDS:
                self.last_action = "waiting for solve anchor"
                return
            logger.warning(
                "No post-idle solve anchor within %.0fs after GoTo; "
                "refusing %s/%s coordinate",
                PIFINDER_SOLVE_ANCHOR_WAIT_SECONDS,
                current.get("source"),
                current.get("quality"),
            )
            self._stop_with_error("No fresh plate solve after GoTo")
            return
        self.solve_anchor_wait_since = 0.0
        self.current_ra = self._finite_float(current.get("ra"))
        self.current_dec = self._finite_float(current.get("dec"))
        self.last_error_arcmin = self._target_error_arcmin(
            self.current_ra,
            self.current_dec,
            self.active_target_ra,
            self.active_target_dec,
        )
        if self.last_error_arcmin is None:
            self._stop_with_error("GoTo error unavailable")
            return

        self._update_goto_plan()
        near_threshold_arcmin = self._pulse_align_threshold_arcmin()
        final_accuracy_arcmin = self._final_accuracy_arcmin()

        if self.last_error_arcmin <= final_accuracy_arcmin:
            # Already at final accuracy straight off the slew: skip pulse guide.
            self._send_final_sync_once()
            return
        if self.last_error_arcmin <= near_threshold_arcmin:
            # Within the near threshold: hand off to pulse-guide fine alignment.
            self._begin_pulse_align()
            return

        # Still outside the near threshold: sync + GoTo again, bounded by the
        # attempt limit and the no-improvement guard.
        max_gotos = self._max_gotos()
        if self.correction_count >= max_gotos:
            self._stop_with_error(f"GoTo limit reached ({max_gotos})")
            return
        if (
            self.previous_goto_error_arcmin is not None
            and self.last_error_arcmin
            >= self.previous_goto_error_arcmin - PIFINDER_MIN_ERROR_IMPROVEMENT_ARCMIN
        ):
            self._stop_with_error("GoTo error did not improve")
            return

        self._send_sync_and_goto(first=False)

    def _send_final_sync_once(self) -> None:
        if self.final_sync_sent:
            return
        self._forward_to_mountcontrol(
            {
                "type": "sync",
                "ra": self.active_target_ra,
                "dec": self.active_target_dec,
                **self._sync_context(
                    "pifinder_final_sync", pointing_source="goto_target"
                ),
            }
        )
        self.final_sync_sent = True
        self.tracking_target_ra = self.active_target_ra
        self.tracking_target_dec = self.active_target_dec
        self.service_state = "idle"
        self.phase = "complete"
        self.wait_reason = ""
        self.last_action = "pifinder final sync complete"
        self._update_goto_plan()
        if self.goto_plan is not None:
            self.goto_plan.update(
                {
                    "stage": "complete",
                    "final_sync_ra": self.active_target_ra,
                    "final_sync_dec": self.active_target_dec,
                    "final_sync_sent": True,
                    "tracking_target_ra": self.tracking_target_ra,
                    "tracking_target_dec": self.tracking_target_dec,
                }
            )
        logger.info(
            "PiFinder GoTo complete; final sync target RA %.4f Dec %.4f "
            "error %.2f arcmin",
            self.active_target_ra,
            self.active_target_dec,
            self.last_error_arcmin if self.last_error_arcmin is not None else -1.0,
        )

    def _tick_tracking_guide(self) -> None:
        previous_state = self.tracking_guide_state
        self._tick_tracking_guide_states()
        if self.tracking_guide_state != previous_state:
            logger.info(
                "Tracking guide %s -> %s (%s)",
                previous_state,
                self.tracking_guide_state,
                self.tracking_guide_last_action,
            )

    def _tick_tracking_guide_states(self) -> None:
        # B4 mode gate (docs/mf_report/mf_field_test_20260724_analysis_ko.md): the
        # tracking guide is a pifinder-mode feature. In indi_mount (or off)
        # mode the mount moves only on user-issued GoTo/manual/sync commands
        # and its own tracking -- no pulses, no disturbance recovery, no
        # auto sync. The Tracking Guide setting only has effect in pifinder
        # mode.
        goto_method = str(self.config_values.get("indi_goto_method", "pifinder"))
        if goto_method != "pifinder":
            self._disable_tracking_guide(f"tracking guide inactive: {goto_method} mode")
            self._reset_tracking_recovery()
            self.tracking_target_ra = None
            self.tracking_target_dec = None
            self.manual_retarget_pending = False
            self.tracking_guide_state = "off"
            return

        enabled = bool(self.config_values.get("indi_tracking_guide_enabled", True))
        if not enabled:
            self._disable_tracking_guide("disabled in config")
            self._reset_tracking_recovery()
            self.tracking_guide_state = "off"
            return

        if self.tracking_target_ra is None or self.tracking_target_dec is None:
            self._disable_tracking_guide("no tracking target")
            self._reset_tracking_recovery()
            self.tracking_guide_state = "waiting_target"
            self.tracking_guide_last_action = "waiting for tracking target"
            return

        if self.alignment_target_pixel is not None:
            solution = self.shared_state.solution()
            plate = getattr(solution, "alignment_projection", None) or {}
            current = self._refresh_pointing_status().get("current") or {}
            published_pixel = (current.get("metadata") or {}).get("target_pixel")
            if tuple(plate.get("target_pixel") or ()) != tuple(
                self.alignment_target_pixel
            ) or tuple(published_pixel or ()) != tuple(self.alignment_target_pixel):
                self._disable_tracking_guide("waiting for aligned pointing")
                self.tracking_guide_state = "settling"
                self.tracking_guide_last_action = "waiting for aligned pointing"
                return
            self.alignment_target_pixel = None

        if self.phase in {"pifinder_goto", "pifinder_pulse_align", "manual_retarget"}:
            self._disable_tracking_guide(f"paused during {self.phase}")
            self._reset_tracking_recovery()
            self.tracking_guide_state = "paused"
            self.tracking_guide_last_action = f"paused during {self.phase}"
            return

        mount_status = self._mount_status_summary()
        if not mount_status.get("available"):
            self.tracking_guide_state = "waiting_mount"
            self.tracking_guide_last_action = "mount status unavailable"
            return
        if self._mount_summary_reports_parked(mount_status):
            self._disable_tracking_guide("mount parked")
            self._reset_tracking_recovery()
            self.tracking_guide_state = "paused"
            self.tracking_guide_last_action = "paused because mount is parked"
            return

        # Altitude guard: once the target has set below the minimum altitude,
        # abandon it — no pulse or recovery slew may ever chase a target near
        # or below the horizon (an overnight target set while unattended).
        target_alt = self._tracking_target_altitude_deg()
        min_alt = float(
            self.config_values.get(
                "indi_tracking_guide_min_target_alt_deg",
                TRACKING_TARGET_MIN_ALT_DEFAULT_DEG,
            )
        )
        if target_alt is not None and target_alt < min_alt:
            self._abandon_tracking_target(
                f"target altitude {target_alt:.1f} deg below limit {min_alt:.1f} deg"
            )
            return

        # Drive an in-progress sync + GoTo recovery to completion first, even
        # though the mount reports motion during its own recovery slew.
        if self.tracking_recovery_state == "goto_wait":
            self._tick_tracking_recovery_goto(mount_status)
            return

        if mount_status.get("tracking_enabled") is False:
            self._disable_tracking_guide("mount tracking off")
            self.tracking_guide_state = "paused"
            return

        # Any other slew/manual motion (not our recovery) suspends correction.
        if self._mount_summary_reports_motion(mount_status):
            # Low-level guide fallback pulses use the same INDI direction
            # primitive as user controls, but mount-control tags their origin.
            # Arm re-target for explicit USER commands regardless of whether
            # guide correction was already enabled; that enabled flag describes
            # the tracking policy, not who caused this particular movement.
            self._disable_tracking_guide("mount motion")
            self.tracking_motion_ra = None
            self.tracking_motion_dec = None
            self.tracking_last_motion_at = time.monotonic()
            if self._mount_summary_reports_manual_motion(mount_status):
                self.manual_retarget_pending = True
                self.tracking_guide_state = "manual_move"
                self.tracking_guide_last_action = "manual move in progress"
            else:
                self.tracking_guide_state = "paused"
                self.tracking_guide_last_action = "paused during mount motion"
            return

        # Coordinate and its usability are decided by PointingCoordinateService;
        # Tracking Guide trusts usable_for_goto and makes no solve/IMU judgment,
        # with one exception: the recovery goto's SYNC anchor requires a fresh
        # solve (see the goto_threshold branch below).
        pointing = self._refresh_pointing_status()
        current = pointing.get("current") or {}
        current_ra = self._finite_float(current.get("ra"))
        current_dec = self._finite_float(current.get("dec"))
        if (
            not pointing.get("usable_for_goto")
            or current_ra is None
            or current_dec is None
        ):
            self._disable_tracking_guide("pointing coordinate unavailable")
            self.tracking_guide_error_arcmin = None
            self.tracking_guide_state = "waiting_coordinate"
            self.tracking_guide_last_action = str(
                pointing.get("reason") or "pointing coordinate unavailable"
            )
            return

        self.tracking_guide_error_arcmin = self._target_error_arcmin(
            current_ra,
            current_dec,
            self.tracking_target_ra,
            self.tracking_target_dec,
        )

        # Disturbance detection: while the scope is being moved, suspend all
        # correction and wait for it to stop. We treat BOTH a jump in the fused
        # coordinate AND the IMU's own motion flag as "moving". A hand-push
        # frequently pauses for a moment (the fused-coordinate delta dips below
        # the arcmin threshold) while the scope is clearly still being handled;
        # keying the settle window off the IMU motion flag as well keeps the
        # recovery slew from firing mid-interaction -- it holds off until the
        # scope is genuinely still (the operator's original "correct only once
        # movement stops" intent). The IMU flag alone is bounded by
        # TRACKING_IMU_QUIET_OVERRIDE_MULTIPLE, so residual micro-sway cannot
        # postpone recovery indefinitely.
        imu_moving = bool(
            ((pointing.get("imu") or {}).get("metadata") or {}).get("moving")
        )
        coordinate_moving = self._tracking_coordinate_moving(current_ra, current_dec)
        now = time.monotonic()
        if imu_moving:
            self.tracking_last_imu_motion_at = now

        settle_seconds = float(
            self.config_values.get("indi_tracking_guide_settle_seconds", 1.0)
        )
        coord_quiet = (
            now - self.tracking_last_motion_at
            if self.tracking_last_motion_at
            else settle_seconds
        )
        imu_quiet = (
            now - self.tracking_last_imu_motion_at
            if self.tracking_last_imu_motion_at
            else settle_seconds
        )
        ignore_imu_flag = (
            not coordinate_moving
            and coord_quiet >= settle_seconds * TRACKING_IMU_QUIET_OVERRIDE_MULTIPLE
        )
        if imu_moving and ignore_imu_flag and not self.tracking_imu_flag_overridden:
            self.tracking_imu_flag_overridden = True
            logger.info(
                "Tracking guide: IMU moving flag still set %.1fs after the "
                "coordinate went quiet; proceeding without it",
                coord_quiet,
            )
        if not imu_moving:
            self.tracking_imu_flag_overridden = False

        if coordinate_moving or (imu_moving and not ignore_imu_flag):
            self._disable_tracking_guide("scope moving")
            self.tracking_recovery_attempts = 0
            self.tracking_guide_recovery_mode = "none"
            self.tracking_guide_state = "disturbed"
            self.tracking_guide_last_action = (
                "suspended: coordinate moving"
                if coordinate_moving
                else "suspended: IMU moving"
            )
            return

        # Settle wait: the scope must stay still before we correct again. The
        # window is short (1 s default) for fast recovery; a pause between
        # pushes is still covered because the IMU moving flag keeps re-arming
        # the window while the scope is being handled.
        stable_for = coord_quiet if ignore_imu_flag else min(coord_quiet, imu_quiet)
        self.tracking_guide_settle_remaining = max(0.0, settle_seconds - stable_for)
        if stable_for < settle_seconds:
            self.tracking_guide_state = "settling"
            self.tracking_guide_last_action = (
                f"settling {self.tracking_guide_settle_remaining:.1f}s"
            )
            return

        # Manual re-target: a USER manual move ended and the coordinate settled.
        # Adopt the current coordinate as the new tracking target and hold it,
        # instead of recovering to the old target. Gated by config; when off,
        # clear the flag and fall through to the disturbance recovery bands
        # (which return to the original target).
        if self.manual_retarget_pending:
            self.manual_retarget_pending = False
            if self.tracking_guide_suspended:
                self.tracking_guide_suspended = False
                logger.info("Tracking guide suspension cleared; manual move ended")
            manual_retarget_enabled = bool(
                self.config_values.get(
                    "indi_tracking_guide_manual_retarget_enabled", True
                )
            )
            if manual_retarget_enabled:
                self.manual_retarget_count += 1
                self.tracking_target_ra = current_ra
                self.tracking_target_dec = current_dec
                self.active_target_ra = current_ra
                self.active_target_dec = current_dec
                self.goto_plan = None
                self.last_action = "target changed to manual position"
                self.tracking_guide_error_arcmin = 0.0
                self.tracking_recovery_attempts = 0
                self.tracking_guide_recovery_mode = "none"
                # Re-arm mount-control guide correction on the NEW target (disable
                # first forces _enable_pulse_correction to re-send with it).
                self._disable_tracking_guide("manual re-target")
                accuracy = float(
                    self.config_values.get("indi_tracking_guide_threshold_arcmin", 3.0)
                )
                self._enable_pulse_correction(accuracy)
                self.tracking_guide_state = "enabled"
                self.tracking_guide_last_action = (
                    f"re-targeted to manual position (#{self.manual_retarget_count})"
                )
                logger.info(
                    "Tracking guide manual re-target #%s: new target RA %.4f Dec %.4f",
                    self.manual_retarget_count,
                    current_ra,
                    current_dec,
                )
                return

        if self.tracking_guide_error_arcmin is None:
            self.tracking_guide_state = "waiting_coordinate"
            self.tracking_guide_last_action = "tracking error unavailable"
            return

        # User pause gate: no pulse or recovery correction while suspended.
        # Sits after motion/settle handling so a user manual move still arms
        # manual_retarget_pending and its completion lifts the suspension.
        if self.tracking_guide_suspended:
            self._disable_tracking_guide("suspended by user")
            self.tracking_recovery_attempts = 0
            self.tracking_guide_recovery_mode = "none"
            self.tracking_guide_state = "suspended"
            self.tracking_guide_last_action = "suspended until next GoTo or manual move"
            return

        goto_threshold_arcmin = (
            float(
                self.config_values.get("indi_tracking_guide_goto_threshold_deg", 0.25)
            )
            * 60.0
        )
        goto_recovery_enabled = bool(
            self.config_values.get("indi_tracking_guide_goto_recovery_enabled", True)
        )

        # Large error with recovery enabled: sync mount to current, GoTo target.
        # The recovery starts with a mount SYNC, so the anchor must be a fresh
        # plate solve: an IMU estimate here can be degrees off and sends the
        # recovery slew far from the target (observed 2026-08-03: 13 deg misses
        # burning all 5 attempts). Same bounded wait as the pifinder GoTo loop.
        if (
            self.tracking_guide_error_arcmin > goto_threshold_arcmin
            and goto_recovery_enabled
        ):
            if not self._is_recent_solve(current):
                if self.recovery_anchor_wait_since == 0.0:
                    self.recovery_anchor_wait_since = now
                if (
                    now - self.recovery_anchor_wait_since
                    < PIFINDER_SOLVE_ANCHOR_WAIT_SECONDS
                ):
                    self.tracking_guide_state = "settling"
                    self._disable_tracking_guide("recovery waiting for solve anchor")
                    return
                wait_action = "recovery waiting: no fresh solve"
                if self.tracking_guide_last_action != wait_action:
                    logger.warning(
                        "No fresh solve anchor within %.0fs before recovery goto; "
                        "holding correction instead of using %s/%s coordinate",
                        PIFINDER_SOLVE_ANCHOR_WAIT_SECONDS,
                        current.get("source"),
                        current.get("quality"),
                    )
                self._disable_tracking_guide(wait_action)
                self.tracking_guide_state = "waiting_coordinate"
                self.error_notifier.emit(
                    "recovery_waiting_solve",
                    "Recovery is paused: no fresh camera solve is available.",
                )
                return
            self.recovery_anchor_wait_since = 0.0
            self._begin_tracking_recovery_goto(current_ra, current_dec)
            return
        self.recovery_anchor_wait_since = 0.0

        # Otherwise pulse-guide fine correction. Within the envelope this closes
        # the error; with recovery Off it is the only tool and pulses slowly
        # toward the target without any mount slew.
        accuracy = float(
            self.config_values.get("indi_tracking_guide_threshold_arcmin", 3.0)
        )
        self._enable_pulse_correction(accuracy)
        self.tracking_recovery_attempts = 0
        self.tracking_guide_recovery_mode = "pulse"

        mount_state = str(mount_status.get("state", "")).strip().lower()
        if mount_state == "guide_correction_failed":
            self.tracking_guide_state = "failed"
            self.tracking_guide_last_action = str(
                mount_status.get("message") or "guide correction failed"
            )
        else:
            self.tracking_guide_state = "enabled"
            if self.tracking_guide_error_arcmin > goto_threshold_arcmin:
                self.tracking_guide_last_action = (
                    "large error; goto recovery off, pulse only"
                )

    def _enable_pulse_correction(self, accuracy: float) -> None:
        target_changed = not self.tracking_guide_active_sent
        accuracy_changed = self.tracking_guide_accuracy_arcmin != accuracy
        if target_changed or accuracy_changed:
            self._forward_to_mountcontrol(
                {
                    "type": "toggle_guide_correction",
                    "enabled": True,
                    "target_ra": self.tracking_target_ra,
                    "target_dec": self.tracking_target_dec,
                    "accuracy_arcmin": accuracy,
                }
            )
            self.tracking_guide_active_sent = True
            self.tracking_guide_accuracy_arcmin = accuracy
            self.tracking_guide_last_action = "guide correction enabled"

    def _tracking_coordinate_moving(
        self, current_ra: float, current_dec: float
    ) -> bool:
        motion_arcmin = float(
            self.config_values.get("indi_tracking_guide_motion_arcmin", 15.0)
        )
        previous_ra = self.tracking_motion_ra
        previous_dec = self.tracking_motion_dec
        self.tracking_motion_ra = current_ra
        self.tracking_motion_dec = current_dec
        if previous_ra is None or previous_dec is None:
            # First sample after acquisition; require a fresh settle window.
            self.tracking_last_motion_at = time.monotonic()
            return False
        delta = self._angular_error_arcmin(
            previous_ra, previous_dec, current_ra, current_dec
        )
        if delta is not None and delta >= motion_arcmin:
            self.tracking_last_motion_at = time.monotonic()
            return True
        return False

    def _tracking_target_altitude_deg(self) -> Optional[float]:
        """Current altitude of the tracking target, or None if not computable.

        Needs the shared-state location and datetime; without them (e.g. no
        GPS fix yet) the guard is skipped rather than blocking the guide.
        The result is cached briefly and keyed by the target coordinates so a
        freshly set target is never judged by a stale altitude.
        """
        if (
            self.shared_state is None
            or self.tracking_target_ra is None
            or self.tracking_target_dec is None
        ):
            return None

        cache = self._target_alt_cache
        now = time.monotonic()
        if (
            cache is not None
            and cache["ra"] == self.tracking_target_ra
            and cache["dec"] == self.tracking_target_dec
            and now - cache["t"] < TRACKING_TARGET_ALT_CACHE_SECONDS
        ):
            return cache["alt"]

        try:
            location = self.shared_state.location()
            dt = self.shared_state.datetime()
        except Exception:
            logger.debug("Could not read location/datetime", exc_info=True)
            return None
        if location is None or dt is None:
            return None

        try:
            sf_utils.set_location(location.lat, location.lon, location.altitude)
            alt, _az = sf_utils.radec_to_altaz(
                self.tracking_target_ra, self.tracking_target_dec, dt
            )
        except Exception:
            logger.debug("Target altitude computation failed", exc_info=True)
            return None

        alt_value = self._finite_float(alt)
        self._target_alt_cache = {
            "ra": self.tracking_target_ra,
            "dec": self.tracking_target_dec,
            "alt": alt_value,
            "t": now,
        }
        return alt_value

    def _abandon_tracking_target(self, reason: str) -> None:
        """Drop the tracking target and halt any in-flight recovery slew.

        Used when correcting toward the target would be wrong no matter what:
        the target set below the altitude limit, or the measured error is too
        large to be a physical disturbance. stop_movement aborts motion only;
        sidereal tracking stays on.
        """
        self._forward_to_mountcontrol({"type": "stop_movement"})
        self._disable_tracking_guide(reason)
        self._reset_tracking_recovery()
        self.tracking_target_ra = None
        self.tracking_target_dec = None
        self._target_alt_cache = None
        self.tracking_guide_state = "failed"
        self.tracking_guide_last_action = reason
        logger.warning("Tracking guide target abandoned: %s", reason)

    def _begin_tracking_recovery_goto(
        self, current_ra: float, current_dec: float
    ) -> None:
        if self.tracking_recovery_attempts >= TRACKING_GUIDE_MAX_RECOVERY_GOTOS:
            self._disable_tracking_guide("goto recovery limit reached")
            self.tracking_recovery_state = "idle"
            self.tracking_guide_recovery_mode = "goto"
            self.tracking_guide_state = "failed"
            self.tracking_guide_last_action = "goto recovery limit reached"
            return

        self._disable_tracking_guide("starting goto recovery")
        self.sync_goto_request_id = uuid.uuid4().hex
        self._forward_to_mountcontrol(
            {
                "type": "sync_and_goto",
                "request_id": self.sync_goto_request_id,
                "sync_ra": current_ra,
                "sync_dec": current_dec,
                "ra": self.tracking_target_ra,
                "dec": self.tracking_target_dec,
                **self._sync_context("tracking_recovery"),
            }
        )
        self.tracking_recovery_attempts += 1
        self.tracking_guide_recovery_count += 1
        self.tracking_recovery_state = "goto_wait"
        self.tracking_recovery_goto_sent_at = time.monotonic()
        self.tracking_recovery_goto_idle_since = 0.0
        self.tracking_guide_recovery_mode = "goto"
        self.tracking_guide_state = "recovering_goto"
        self.tracking_guide_last_action = (
            f"goto recovery {self.tracking_recovery_attempts}"
            f"/{TRACKING_GUIDE_MAX_RECOVERY_GOTOS}: sync+goto sent"
        )
        logger.info(
            "Tracking guide recovery %s/%s: sync RA %.4f Dec %.4f then GoTo "
            "RA %.4f Dec %.4f (error %.2f arcmin)",
            self.tracking_recovery_attempts,
            TRACKING_GUIDE_MAX_RECOVERY_GOTOS,
            current_ra,
            current_dec,
            self.tracking_target_ra,
            self.tracking_target_dec,
            self.tracking_guide_error_arcmin
            if self.tracking_guide_error_arcmin is not None
            else -1.0,
        )

    def _tick_tracking_recovery_goto(self, mount_status: dict[str, Any]) -> None:
        self.tracking_guide_state = "recovering_goto"
        if not self._verified_sync_goto_ready(mount_status, recovery=True):
            return
        now = time.monotonic()
        if (
            now - self.tracking_recovery_goto_sent_at
            < PIFINDER_FINAL_GOTO_SETTLE_SECONDS
        ):
            self.tracking_guide_last_action = "recovery goto settling"
            return
        if self._mount_summary_reports_motion(mount_status):
            self.tracking_recovery_goto_idle_since = 0.0
            self.tracking_guide_last_action = "waiting for recovery goto"
            return
        if self.tracking_recovery_goto_idle_since == 0.0:
            self.tracking_recovery_goto_idle_since = now
            return
        if (
            now - self.tracking_recovery_goto_idle_since
            < PIFINDER_FINAL_GOTO_SETTLE_SECONDS
        ):
            return
        # Recovery GoTo finished; re-baseline and re-measure on the next tick.
        self.tracking_recovery_state = "idle"
        self.tracking_motion_ra = None
        self.tracking_motion_dec = None
        self.tracking_last_motion_at = now
        self.tracking_guide_last_action = "recovery goto complete"

    def _verified_sync_goto_ready(self, mount_status, *, recovery: bool) -> bool:
        if self.sync_goto_request_id is None:
            return True
        receipt = mount_status.get("sync_goto") or {}
        matches = receipt.get("request_id") == self.sync_goto_request_id
        state = receipt.get("state") if matches else None
        sent_at = (
            self.tracking_recovery_goto_sent_at if recovery else self.final_goto_sent_at
        )
        reason = str(receipt.get("reason") or "Mount sync verification failed")
        if state == "failed" or time.monotonic() - sent_at > 25.0:
            if state != "failed":
                reason = "No verified sync+GoTo acknowledgement"
            # A failed alignment must not lead to an automatic recovery retry
            # based on the same unconfirmed mount frame.
            self.tracking_guide_suspended = True
            self._disable_tracking_guide(reason)
            self._stop_with_error(reason)
            self.tracking_recovery_state = "idle"
            self.sync_goto_request_id = None
            return False
        if state != "goto_sent":
            self.last_action = "waiting for mount sync verification"
            self.tracking_guide_last_action = self.last_action
            return False
        actual_sent = self._finite_float(receipt.get("goto_sent_monotonic"))
        if actual_sent is None:
            return False
        if recovery:
            self.tracking_recovery_goto_sent_at = actual_sent
        else:
            self.final_goto_sent_at = actual_sent
        self.sync_goto_request_id = None
        return True

    def _reset_tracking_recovery(self) -> None:
        self.recovery_anchor_wait_since = 0.0
        self.tracking_motion_ra = None
        self.tracking_motion_dec = None
        self.tracking_last_motion_at = 0.0
        self.tracking_last_imu_motion_at = 0.0
        self.tracking_imu_flag_overridden = False
        self.tracking_recovery_state = "idle"
        self.tracking_recovery_goto_sent_at = 0.0
        self.tracking_recovery_goto_idle_since = 0.0
        self.tracking_recovery_attempts = 0
        self.tracking_guide_recovery_mode = "none"
        self.tracking_guide_recovery_count = 0
        self.tracking_guide_settle_remaining = None
        self.tracking_guide_error_arcmin = None
        self.manual_retarget_pending = False
        self.manual_retarget_count = 0

    def _disable_tracking_guide(self, reason: str) -> None:
        if self.tracking_guide_active_sent:
            self._forward_to_mountcontrol(
                {"type": "toggle_guide_correction", "enabled": False}
            )
        self.tracking_guide_active_sent = False
        self.tracking_guide_accuracy_arcmin = None
        self.tracking_guide_last_action = reason

    def _update_goto_plan(self) -> None:
        if self.goto_plan is None:
            return
        self.goto_plan.update(
            {
                "current_ra": self.current_ra,
                "current_dec": self.current_dec,
                "error_arcmin": self.last_error_arcmin,
                "correction_count": self.correction_count,
                "phase": self.phase,
            }
        )

    def _refresh_pointing_status(self) -> dict[str, Any]:
        self.pointing_status = self._load_pointing_status()
        return self.pointing_status

    def _pifinder_goto_block_reason(self) -> str:
        pointing = self._refresh_pointing_status()
        if not pointing.get("usable_for_goto"):
            return str(pointing.get("reason") or "pointing coordinate unavailable")

        mount_status = self._mount_status_summary()
        if not mount_status.get("available"):
            return "mount status unavailable"
        if self._mount_summary_reports_parked(mount_status):
            return "mount is parked"

        current = pointing.get("current") or {}
        if not self._is_recent_solve(current):
            return "PiFinder GoTo requires a recent plate solve"
        if self._finite_float(current.get("ra")) is None:
            return "current RA unavailable"
        if self._finite_float(current.get("dec")) is None:
            return "current Dec unavailable"

        return ""

    def _load_pointing_status(self) -> dict[str, Any]:
        try:
            with open(POINTING_STATUS_FILE, encoding="utf-8") as status_in:
                raw_status = json.load(status_in)
        except FileNotFoundError:
            return {
                "available": False,
                "fresh": False,
                "usable_for_goto": False,
                "reason": "pointing coordinate status file not found",
            }
        except (json.JSONDecodeError, OSError):
            logger.debug("Could not read pointing coordinate status", exc_info=True)
            return {
                "available": False,
                "fresh": False,
                "usable_for_goto": False,
                "reason": "pointing coordinate status unreadable",
            }

        updated = self._finite_float(raw_status.get("updated"))
        age_seconds = time.time() - updated if updated is not None else None
        fresh = (
            age_seconds is not None
            and age_seconds >= 0.0
            and age_seconds <= POINTING_STATUS_MAX_AGE_SECONDS
        )

        current = self._coordinate_sample_summary(raw_status.get("current"))
        solved = self._coordinate_sample_summary(raw_status.get("solved"))
        imu = self._coordinate_sample_summary(raw_status.get("imu"))
        mount = self._coordinate_sample_summary(raw_status.get("mount"))
        usable_for_goto = bool(
            fresh
            and current.get("valid")
            and current.get("ra") is not None
            and current.get("dec") is not None
            and not self._sample_reports_parked(current)
        )

        reason = ""
        if not fresh:
            reason = "pointing coordinate status is stale"
        elif not current.get("valid"):
            reason = str(current.get("reason") or "current coordinate invalid")
        elif self._sample_reports_parked(current):
            reason = "current coordinate comes from parked mount"

        return {
            "available": True,
            "fresh": fresh,
            "age_seconds": age_seconds,
            "usable_for_goto": usable_for_goto,
            "reason": reason,
            "selected_source": raw_status.get("selected_source"),
            "mode": raw_status.get("mode"),
            "weights": raw_status.get("weights") or {},
            "current": current,
            "solved": solved,
            "imu": imu,
            "mount": mount,
            "health": raw_status.get("health") or {},
            "updated": updated,
        }

    def _coordinate_sample_summary(self, sample: Any) -> dict[str, Any]:
        if not isinstance(sample, dict):
            return {"valid": False, "reason": "sample unavailable"}

        return {
            "valid": bool(sample.get("valid")),
            "source": sample.get("source"),
            "quality": sample.get("quality"),
            "ra": self._finite_float(sample.get("ra")),
            "dec": self._finite_float(sample.get("dec")),
            "alt": self._finite_float(sample.get("alt")),
            "az": self._finite_float(sample.get("az")),
            "reason": sample.get("reason") or "",
            "aligned": bool(sample.get("aligned")),
            "timestamp": self._finite_float(sample.get("timestamp")),
            "metadata": sample.get("metadata") or {},
        }

    def _sample_reports_parked(self, sample: dict[str, Any]) -> bool:
        metadata = sample.get("metadata")
        if not isinstance(metadata, dict):
            return False
        for key in ("park_state", "driver_mount_status"):
            raw = str(metadata.get(key, "")).strip().lower()
            if raw and "park" in raw and "unpark" not in raw:
                return True
        raw_mount_status = str(metadata.get("raw_mount_status", ""))
        return raw_mount_status.startswith("P")

    def _mount_summary_reports_parked(self, status: dict[str, Any]) -> bool:
        for key in ("park_state", "driver_mount_status"):
            raw = str(status.get(key, "")).strip().lower()
            if raw and "park" in raw and "unpark" not in raw:
                return True
        raw_mount_status = str(status.get("raw_mount_status", ""))
        return raw_mount_status.startswith("P")

    def _mount_summary_reports_motion(self, status: dict[str, Any]) -> bool:
        if bool(status.get("mount_motion_active")):
            return True
        if bool(status.get("goto_motion_active")):
            return True
        if status.get("manual_motion_direction"):
            return True
        state = str(status.get("state", "")).strip().lower()
        return any(token in state for token in ("slew", "goto", "moving", "motion"))

    def _mount_summary_reports_manual_motion(self, status: dict[str, Any]) -> bool:
        origin = str(status.get("manual_motion_origin", "")).strip().lower()
        if origin == "guide_correction":
            return False
        if origin == "user":
            return True
        # Backward compatibility for a mount-control process/status file from
        # before origin tagging: guide_correction is automatic; all other
        # explicit manual-direction reports came from user input.
        if str(status.get("state", "")).strip().lower() == "guide_correction":
            return False
        if status.get("manual_motion_direction"):
            return True
        return "manual_motion" in str(status.get("state", "")).strip().lower()

    def _target_error_arcmin(self, ra, dec, target_ra, target_dec):
        separation = self._angular_error_arcmin(ra, dec, target_ra, target_dec)
        if separation is None or self.shared_state is None:
            return separation
        # Arrival/hold must also satisfy the actual LCD axes. Use its raw
        # aligned estimate rather than allowing the moving average to hide
        # a residual that the observer can still see on the push screen.
        solution = self.shared_state.solution()
        if not solution or not solution.has_pointing():
            return separation
        aligned = solution.pointing.aligned.estimate
        errors = pointing_axis_errors(
            aligned.RA,
            aligned.Dec,
            target_ra,
            target_dec,
            self.config_values.get("mount_type", "Alt/Az"),
            self.shared_state.location(),
            self.shared_state.datetime(),
        )
        if errors is None:
            return None
        return max(separation, *(abs(value) * 60.0 for value in errors))

    def _angular_error_arcmin(
        self,
        current_ra: Optional[float],
        current_dec: Optional[float],
        target_ra: Optional[float],
        target_dec: Optional[float],
    ) -> Optional[float]:
        if (
            current_ra is None
            or current_dec is None
            or target_ra is None
            or target_dec is None
        ):
            return None

        ra_a = math.radians(current_ra)
        dec_a = math.radians(current_dec)
        ra_b = math.radians(target_ra)
        dec_b = math.radians(target_dec)
        cos_sep = math.sin(dec_a) * math.sin(dec_b) + math.cos(dec_a) * math.cos(
            dec_b
        ) * math.cos(ra_a - ra_b)
        sep_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))
        return sep_deg * 60.0

    def _finite_float(self, value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _reload_config_if_needed(self) -> None:
        now = time.monotonic()
        if now - self.last_config_load < CONFIG_RELOAD_SECONDS:
            return

        cfg = config.Config()
        cfg.load_config()
        self.config_values = {
            "mount_type": cfg.get_option("mount_type", "Alt/Az"),
            "mount_control": bool(cfg.get_option("mount_control", False)),
            "indi_goto_method": str(cfg.get_option("indi_goto_method", "pifinder")),
            "indi_tracking_guide_enabled": bool(
                cfg.get_option("indi_tracking_guide_enabled", True)
            ),
            "indi_pifinder_goto_near_threshold_deg": float(
                cfg.get_option("indi_pifinder_goto_near_threshold_deg", 1.0)
            ),
            "indi_pifinder_goto_max_gotos": int(
                cfg.get_option(
                    "indi_pifinder_goto_max_gotos", PIFINDER_DEFAULT_MAX_GOTOS
                )
            ),
            "indi_goto_refine_accuracy_arcmin": float(
                cfg.get_option("indi_goto_refine_accuracy_arcmin", 3.0)
            ),
            "indi_tracking_guide_threshold_arcmin": float(
                cfg.get_option("indi_tracking_guide_threshold_arcmin", 3.0)
            ),
            "indi_tracking_guide_settle_seconds": float(
                cfg.get_option("indi_tracking_guide_settle_seconds", 1.0)
            ),
            "indi_tracking_guide_motion_arcmin": float(
                cfg.get_option("indi_tracking_guide_motion_arcmin", 15.0)
            ),
            "indi_tracking_guide_goto_recovery_enabled": bool(
                cfg.get_option("indi_tracking_guide_goto_recovery_enabled", True)
            ),
            "indi_tracking_guide_goto_threshold_deg": float(
                cfg.get_option("indi_tracking_guide_goto_threshold_deg", 0.25)
            ),
            "indi_tracking_guide_min_target_alt_deg": float(
                cfg.get_option(
                    "indi_tracking_guide_min_target_alt_deg",
                    TRACKING_TARGET_MIN_ALT_DEFAULT_DEG,
                )
            ),
            "indi_tracking_guide_manual_retarget_enabled": bool(
                cfg.get_option("indi_tracking_guide_manual_retarget_enabled", True)
            ),
        }
        if self.runtime_goto_method is not None:
            self.config_values["indi_goto_method"] = self.runtime_goto_method
        self.last_config_load = now

    def _mount_status_summary(self) -> dict[str, Any]:
        try:
            with open(MOUNT_STATUS_FILE, encoding="utf-8") as status_in:
                status = json.load(status_in)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"available": False}

        return {
            "available": True,
            "state": status.get("state"),
            "message": status.get("message"),
            "updated": status.get("updated"),
            "device": status.get("device"),
            "park_state": status.get("park_state"),
            "driver_mount_status": status.get("driver_mount_status"),
            "raw_mount_status": status.get("raw_mount_status"),
            "tracking_enabled": status.get("tracking_enabled"),
            "mount_motion_active": status.get("mount_motion_active"),
            "goto_motion_active": status.get("goto_motion_active"),
            "manual_motion_direction": status.get("manual_motion_direction"),
            "manual_motion_origin": status.get("manual_motion_origin"),
            "last_user_motion_started_wall": status.get(
                "last_user_motion_started_wall"
            ),
            "last_user_motion_stopped_wall": status.get(
                "last_user_motion_stopped_wall"
            ),
            "guide_pulse_until_wall": status.get("guide_pulse_until_wall"),
            "guide_correction_mode": status.get("guide_correction_mode"),
            "guide_observation_after_wall": status.get("guide_observation_after_wall"),
            "target_ra": status.get("target_ra"),
            "target_dec": status.get("target_dec"),
            "sync_goto": status.get("sync_goto"),
        }

    def _status_payload(self) -> dict[str, Any]:
        return {
            "service_state": self.service_state,
            "phase": self.phase,
            "wait_reason": self.wait_reason,
            "last_command": self.last_command,
            "active_target_ra": self.active_target_ra,
            "active_target_dec": self.active_target_dec,
            "current_ra": self.current_ra,
            "current_dec": self.current_dec,
            "correction_count": self.correction_count,
            "final_sync_sent": self.final_sync_sent,
            "tracking_target_ra": self.tracking_target_ra,
            "tracking_target_dec": self.tracking_target_dec,
            "manual_target_origin": self.manual_target_origin,
            "tracking_guide_state": self.tracking_guide_state,
            "tracking_guide_suspended": self.tracking_guide_suspended,
            "tracking_guide_active_sent": self.tracking_guide_active_sent,
            "tracking_guide_last_action": self.tracking_guide_last_action,
            "tracking_guide_error_arcmin": self.tracking_guide_error_arcmin,
            "tracking_guide_accuracy_arcmin": self.tracking_guide_accuracy_arcmin,
            "tracking_guide_recovery_mode": self.tracking_guide_recovery_mode,
            "tracking_guide_recovery_count": self.tracking_guide_recovery_count,
            "tracking_guide_manual_retarget_count": self.manual_retarget_count,
            "tracking_guide_settle_remaining": self.tracking_guide_settle_remaining,
            "goto_method": self.config_values.get("indi_goto_method", "pifinder"),
            "tracking_guide_enabled": self.config_values.get(
                "indi_tracking_guide_enabled", True
            ),
            "last_error_arcmin": self.last_error_arcmin,
            "goto_plan": self.goto_plan,
            "last_action": self.last_action,
            "mountcontrol_queue_available": self.mountcontrol_queue is not None,
            "pointing": self._refresh_pointing_status(),
            "mount_status": self._mount_status_summary(),
            "config": self.config_values,
            "started": self.started_at,
            "updated": time.time(),
        }

    def _write_status(self, *, force: bool = False) -> None:
        if self.service_state == "error":
            # An intentional cancel is not an operational failure.
            if (
                self.last_action != "pending GoTo canceled"
                or "timed out" in self.wait_reason
            ):
                self.error_notifier.emit(
                    self.phase, self.wait_reason or self.last_action
                )
        elif self.tracking_guide_state == "failed":
            self.error_notifier.emit("tracking_failed", self.tracking_guide_last_action)
        now = time.monotonic()
        if not force and now - self.updated_at < STATUS_WRITE_SECONDS:
            return

        utils.create_path(utils.runtime_dir)
        payload = self._status_payload()
        tmp_path = STATUS_FILE.with_name(f"{STATUS_FILE.name}.{os.getpid()}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as status_out:
            json.dump(payload, status_out, indent=2, sort_keys=True)
            status_out.flush()
        tmp_path.replace(STATUS_FILE)
        self.updated_at = now


def run(
    service_queue: Queue,
    mountcontrol_queue: Optional[Queue],
    shared_state: Any,
    log_queue: Queue,
    alert_queue: Optional[Queue] = None,
) -> None:
    MultiprocLogging.configurer(log_queue)
    service = IndiGotoGuideService(
        service_queue, mountcontrol_queue, shared_state, alert_queue
    )
    service.run()
