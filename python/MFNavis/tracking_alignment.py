"""Bounded, nonblocking user alignment, independent of the tracking controller.

The service owns requests; the shared ledger owns observation motion epochs.
Correction motion never advances the observation deadline.
"""

from copy import deepcopy
import math
import threading
import time
import uuid


INTEGRATION_OPTION = "smooth_tracking_target_integration_enabled"


class AlignmentLedger:
    def __init__(self):
        self.lock = threading.RLock()
        self.motion = {"generation": 0, "moving": False, "completed_mono": None}
        self.status = {"state": "idle"}
        self.attempt = None
        self.seed = None
        self.mount_sync = None
        self.correction_moving = False
        self.pose_after = 0.0

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        self.__init__()

    def update(self, action="snapshot", value=None):
        with self.lock:
            if action == "snapshot":
                return deepcopy(
                    dict(
                        motion=self.motion,
                        status=self.status,
                        attempt=self.attempt,
                        seed=self.seed,
                        mount_sync=self.mount_sync,
                        correction_moving=self.correction_moving,
                        pose_after=self.pose_after,
                    )
                )
            if action == "motion_start":
                if value.get("purpose", "observation") == "observation":
                    self.motion = dict(
                        generation=self.motion["generation"] + 1,
                        moving=True,
                        completed_mono=None,
                        started_mono=value["now"],
                        id=value.get("id", uuid.uuid4().hex),
                    )
                else:
                    self.correction_moving = True
            elif action == "motion_complete":
                if (
                    value.get("purpose", "observation") == "observation"
                    and (
                        value.get("id") is None or value["id"] == self.motion.get("id")
                    )
                    and self.motion["moving"]
                ):
                    self.motion.update(moving=False, completed_mono=value["now"])
                    self.motion.pop("deadline", None)
                elif value.get("purpose") == "correction":
                    self.correction_moving = False
                    self.pose_after = max(self.pose_after, value["now"])
            elif action == "pose_after":
                self.pose_after = max(self.pose_after, value)
            elif action == "stationary":
                if not self.motion["moving"] and self.motion["completed_mono"] is None:
                    self.motion.update(completed_mono=value["now"], origin="stationary")
            elif action == "deadline":
                if value["generation"] == self.motion["generation"]:
                    self.motion.setdefault("deadline", value["deadline"])
            elif action == "attempt":
                if not self.attempt or value["end_mono"] > self.attempt["end_mono"]:
                    self.attempt = deepcopy(value)
            elif action == "seed":
                self.seed = deepcopy(value)
            elif action == "mount_sync":
                self.mount_sync = deepcopy(value)
            elif action == "status":
                self.status = deepcopy(value)
            elif action == "reset":
                self.motion = dict(
                    generation=self.motion["generation"] + 1,
                    moving=False,
                    completed_mono=None,
                )
                self.attempt = self.seed = None
                self.mount_sync = None
                self.correction_moving, self.pose_after = False, 0.0
                self.status = dict(state="idle", reason="process_started")
            else:
                raise ValueError("unknown alignment ledger operation")


def alignment_command(
    ra, dec, *, frame="catalog", body=None, identify_planets=True, origin="user"
):
    from PiFinder.visual_tracking import sky_vector

    sky_vector(float(ra), float(dec))
    if frame not in {"catalog", "of_date"}:
        raise ValueError("explicit target frame required")
    return dict(
        type="tracking_align",
        request_id=uuid.uuid4().hex,
        ra=float(ra),
        dec=float(dec),
        frame=frame,
        body=body,
        identify_planets=identify_planets,
        origin=origin,
    )


def alignment_decision(motion, now, *, solved=False, terminal_failure=False):
    """Pure ordering rule; a usable solve wins the deadline race."""
    if motion["moving"]:
        return "waiting_motion"
    if solved:
        return "solved_alignment"
    if motion["completed_mono"] is None:
        return "waiting_motion"
    if terminal_failure:
        return "user_center_arrival"
    if now >= motion["deadline"]:
        return "user_center_arrival"
    return "waiting_solve"


class AlignmentDispatcher:
    def __init__(self, service):
        self.service = service
        self.pending = None
        self.last_completed = None
        self.imu_moving = False
        self.enabled = None

    def cancel(self, reason):
        if self.pending:
            self._status("cancelled", reason=reason)
        self.pending = None

    def submit(self, command, cfg):
        from PiFinder.tracking_commands import control_epoch
        from PiFinder.tracking_contracts import fingerprint
        from PiFinder.smooth_tracking_runtime import optics_identity
        from PiFinder.visual_tracking_target import TargetEphemeris

        if command["request_id"] == self.last_completed or (
            self.pending and self.pending["request_id"] == command["request_id"]
        ):
            return
        self.cancel("superseded")
        shared = self.service.shared_state
        target = TargetEphemeris(shared).resolve(
            command["ra"],
            command["dec"],
            frame=command["frame"],
            body=command.get("body"),
            identify_planets=command.get("identify_planets", True),
        )
        wait = float(cfg.get_option("alignment_solve_wait_max_s", 15.0))
        if not math.isfinite(wait) or not 0 < wait <= 300:
            raise ValueError("invalid bounded alignment solve wait")
        motion = shared.tracking_alignment()["motion"]
        self.pending = dict(
            command,
            target=target,
            control=control_epoch(self.service.mountcontrol_queue),
            generation=motion["generation"],
            wait=wait,
            requested_mono=time.monotonic(),
            mode=cfg.get_option("smooth_tracking_mode", "active"),
            profile_hash=fingerprint(
                cfg.get_option("smooth_tracking_profile", {}) or {}
            ),
            optics=optics_identity(cfg, shared),
            target_pixel=tuple(shared.target_pixel()),
            mount_sync_enabled=bool(
                command.get("origin") == "skysafari"
                and cfg.get_option("mount_control", False)
                and cfg.get_option("skysafari_indi_sync", True)
            ),
        )
        # Alignment takes ownership of arrival; older GoTo recovery must not
        # run while waiting for the user's final, manually centred position.
        self.service._cancel_initial_goto_wait("user alignment")
        self.service.solve_fallback_armed = False
        self.service.smooth_tracking_legacy_suspended = True
        self.service._disable_tracking_guide("user alignment")
        self.service._disable_pulse_align()
        self.service._reset_tracking_recovery()
        shared.smooth_tracking("stop", "user_alignment")
        self.service._forward_to_mountcontrol(
            dict(type="tracking_alignment_hold", _control_epoch=self.pending["control"])
        )
        self.tick(cfg)

    def _status(self, state, **fields):
        self.service.shared_state.tracking_alignment(
            "status", dict(state=state, request_id=self.pending["request_id"], **fields)
        )

    def observe_motion(self, mount, now, settle=0.0):
        """Also catch physical hand pushes using a usable IMU sample."""
        shared = self.service.shared_state
        imu = shared.imu()
        usable = imu is not None and imu.is_usable(now=time.time())
        ledger = shared.tracking_alignment()
        pulse_until = float(mount.get("guide_pulse_until_wall") or 0)
        if pulse_until:
            pulse_until += settle
        pulse_until = max(
            pulse_until, float(mount.get("guide_observation_after_wall") or 0)
        )
        correction = pulse_until > time.time() or ledger["correction_moving"]
        if pulse_until > 0:
            shared.tracking_alignment("pose_after", now + pulse_until - time.time())
        motion = ledger["motion"]
        if usable and imu.moving and not correction and not motion["moving"]:
            shared.tracking_alignment(
                "motion_start", dict(now=now, purpose="observation")
            )
            shared.smooth_tracking("stop", "manual_motion")
            self.imu_moving = True
        if self.imu_moving and usable and not imu.moving:
            shared.tracking_alignment("motion_complete", dict(now=now))
            self.imu_moving = False
        stationary = (
            self.service._mount_status_fresh(mount)
            and mount.get("mount_motion_active") is False
            and mount.get("goto_motion_active") is False
            and (not usable or not imu.moving)
        )
        if stationary and not correction:
            shared.tracking_alignment("stationary", dict(now=now))

    def tick(self, cfg):
        from PiFinder.alignment_projection import current_solved_target_pixel
        from PiFinder.tracking_commands import control_epoch
        from PiFinder.tracking_contracts import fingerprint
        from PiFinder.smooth_tracking_runtime import optics_identity
        from PiFinder.visual_tracking_target import TargetEphemeris

        service, now = self.service, time.monotonic()
        shared = service.shared_state
        enabled = cfg.get_option(INTEGRATION_OPTION, False)
        if enabled != self.enabled:
            if self.enabled is not None:
                self.cancel("configuration_changed")
                shared.tracking_alignment("reset")
                self.imu_moving = False
            self.enabled = enabled
        if not enabled:
            self.cancel("configuration_changed")
            return
        mount = service._mount_status_summary()
        profile = cfg.get_option("smooth_tracking_profile", {}) or {}
        settle = float(profile.get("settle_s", 0.3))
        if not math.isfinite(settle) or settle < 0:
            self.cancel("invalid_settle_bound")
            return
        self.observe_motion(mount, now, settle)
        ledger = shared.tracking_alignment()
        motion = ledger["motion"]
        if motion["completed_mono"] is not None and "deadline" not in motion:
            wait = float(cfg.get_option("alignment_solve_wait_max_s", 15.0))
            if math.isfinite(wait) and 0 < wait <= 300:
                shared.tracking_alignment(
                    "deadline",
                    dict(
                        generation=motion["generation"],
                        deadline=motion["completed_mono"] + wait,
                    ),
                )
                motion = shared.tracking_alignment()["motion"]
        p = self.pending
        if not p:
            return
        if cfg.get_option("smooth_tracking_mode", "active") != p["mode"]:
            self.cancel("configuration_changed")
            return
        if (
            p["control"] != control_epoch(service.mountcontrol_queue)
            or p["generation"] != motion["generation"]
            or tuple(shared.target_pixel()) != p["target_pixel"]
            or fingerprint(cfg.get_option("smooth_tracking_profile", {}) or {})
            != p["profile_hash"]
            or optics_identity(cfg, shared) != p["optics"]
        ):
            self.cancel("context_changed")
            return
        if p["mount_sync_enabled"] != bool(
            p.get("origin") == "skysafari"
            and cfg.get_option("mount_control", False)
            and cfg.get_option("skysafari_indi_sync", True)
        ):
            self.cancel("configuration_changed")
            return
        if "sync_requested_mono" in p:
            receipt = ledger.get("mount_sync") or {}
            if receipt.get("request_id") == p["request_id"]:
                self._finish(
                    cfg,
                    "solved_alignment",
                    "accepted_solve",
                    tracking_error=None if receipt.get("ok") else "mount_sync_failed",
                )
            elif now - p["sync_requested_mono"] >= 15.0:
                self._finish(
                    cfg,
                    "solved_alignment",
                    "accepted_solve",
                    tracking_error="mount_sync_timeout",
                )
            return
        # A pulse changes the physical pose but not the observation deadline.
        settling = ledger["pose_after"] > now
        if settling or ledger["correction_moving"]:
            self._status("waiting_motion", reason="motion_or_status_unconfirmed")
            return
        coordinates = TargetEphemeris(shared).position(
            p["target"], shared.datetime().timestamp()
        )
        try:
            pixel = current_solved_target_pixel(
                shared,
                cfg,
                *coordinates,
                motion=dict(motion, pose_after=ledger["pose_after"]),
            )
        except LookupError:
            pixel = None
        except (ValueError, TypeError, KeyError) as exc:
            self._status("error", reason=str(exc))
            self.pending = None
            return
        if pixel is None and not service._mount_status_fresh(mount):
            self._status("waiting_motion", reason="motion_or_status_unconfirmed")
            return
        attempt = ledger["attempt"] or {}
        terminal = bool(
            attempt.get("terminal")
            and not attempt.get("success")
            and motion["completed_mono"] is not None
            and attempt.get("start_mono", -1) >= motion["completed_mono"]
        )
        decision = alignment_decision(
            motion, now, solved=pixel is not None, terminal_failure=terminal
        )
        if decision.startswith("waiting"):
            self._status(
                decision, remaining_s=max(0, motion.get("deadline", now) - now)
            )
            return
        if decision == "solved_alignment":
            shared.set_target_pixel(pixel)
            if p.get("origin") == "lcd":
                cfg.set_option("target_pixel", pixel)
            reason = "accepted_solve"
            if p["mount_sync_enabled"]:
                from PiFinder.calc_utils import catalog_to_equinox_of_date

                # The INDI property is EQUATORIAL_EOD_COORD; ephemerides and
                # image projection use catalog axes. Never sync a user anchor.
                ra_eod, dec_eod = catalog_to_equinox_of_date(
                    *coordinates, shared.datetime()
                )
                p["target_pixel"] = tuple(pixel)
                p["sync_requested_mono"] = now
                queued = service._forward_to_mountcontrol(
                    dict(
                        type="tracking_alignment_sync",
                        request_id=p["request_id"],
                        _control_epoch=p["control"],
                        expires_mono=now + 15.0,
                        ra=ra_eod,
                        dec=dec_eod,
                        origin="skysafari_align",
                        pointing_source="skysafari_target",
                    )
                )
                if queued:
                    self._status(
                        "waiting_mount_sync",
                        result=decision,
                        reason=reason,
                        target_pixel=tuple(pixel),
                    )
                else:
                    self._finish(
                        cfg, decision, reason, tracking_error="mount_sync_unavailable"
                    )
                return
        else:
            reason = (
                "solve_failed"
                if terminal
                else (
                    "already_waited"
                    if p["requested_mono"] >= motion["deadline"]
                    else "solve_wait_expired"
                )
            )
        self._finish(cfg, decision, reason)

    def _finish(self, cfg, decision, reason, *, tracking_error=None):
        from PiFinder.smooth_tracking_runtime import start_session

        service, p = self.service, self.pending
        shared = service.shared_state

        tracking = tracking_error or "off"
        if (
            tracking_error is None
            and cfg.get_option("smooth_tracking_mode", "active") != "off"
        ):
            try:
                start_session(
                    service,
                    dict(
                        type="smooth_tracking_start",
                        ra=p["target"].ra,
                        dec=p["target"].dec,
                        frame="catalog",
                        body=p["target"].body,
                        identify_planets=False,
                        user_center_arrival=decision == "user_center_arrival",
                        solved_alignment=decision == "solved_alignment",
                        alignment_request_id=p["request_id"],
                    ),
                )
                tracking = "acquiring"
            except (ValueError, TypeError, KeyError) as exc:
                tracking = str(exc)
        self._status(
            "complete",
            result=decision,
            reason=reason,
            target_identity=p["target"].identity,
            target_pixel=tuple(shared.target_pixel()),
            tracking=tracking,
        )
        self.last_completed = p["request_id"]
        if getattr(service, "alert_queue", None) is not None:
            service.alert_queue.put(
                "Alignment set"
                if decision == "solved_alignment"
                else "Tracking centre confirmed"
            )
        self.pending = None
