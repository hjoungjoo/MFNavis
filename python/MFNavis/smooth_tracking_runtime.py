"""Independent latest-ROI worker and service policy for optional smooth tracking."""

from dataclasses import asdict
import logging
import time
import uuid

from PiFinder.tracking_contracts import (
    COAST_REASONS,
    TrackingPermission,
    TrackingProfile,
    fingerprint,
)
from PiFinder.tracking_quality import StarTracker, build_reference
from PiFinder.tracking_commands import control_epoch

logger = logging.getLogger("SmoothTracking")


def optics_identity(cfg, shared):
    return fingerprint(
        {
            "camera": shared.camera_type(),
            "target": shared.target_pixel(),
            **{
                name: cfg.get_option(name)
                for name in (
                    "camera_lens",
                    "camera_lens_focal_length_mm",
                    "camera_rotation",
                    "screen_direction",
                    "wide_solver_calibration_store_v1",
                )
            },
        }
    )


def publish_reference(shared_state, cfg, solution, metadata, info, raw):
    if (
        cfg is None
        or cfg.get_option("smooth_tracking_mode", "active") == "off"
        or raw is None
    ):
        return
    try:
        profile = TrackingProfile.from_dict(
            cfg.get_option("smooth_tracking_profile", {}) or {}
        )
        reference = build_reference(
            solution,
            metadata,
            info,
            raw["frame"].shape,
            shared_state.target_pixel(),
            shared_state.camera_type(),
            profile,
        )
        shared_state.smooth_tracking("reference", reference)
    except Exception:
        # Failure to build a new anchor never blesses the last anchor as fresh.
        logger.debug("Smooth tracking reference unavailable", exc_info=True)


def run_worker(shared_state, stop_event):
    """One in-flight frame plus the shared latest slot, with no backlog."""
    from PiFinder import config

    cfg = config.Config()
    tracker = None
    last_session = None
    last_key = None
    try:
        while not stop_event.wait(0.05):
            snapshot = shared_state.smooth_tracking()
            request, reference = snapshot["request"], snapshot["reference"]
            if not request:
                tracker = None
                continue
            try:
                if request["session"] != last_session:
                    tracker, last_key = None, None
                    last_session = request["session"]
                if cfg.get_option("smooth_tracking_mode", "active") != request["mode"]:
                    shared_state.smooth_tracking("fault", "configuration_changed")
                    continue
                if (
                    fingerprint(cfg.get_option("smooth_tracking_profile", {}) or {})
                    != request["profile_hash"]
                ):
                    shared_state.smooth_tracking("fault", "profile_changed")
                    continue
                integrated = request.get("target_integration", False)
                if integrated and not cfg.get_option(
                    "smooth_tracking_target_integration_enabled", False
                ):
                    shared_state.smooth_tracking("fault", "integration_disabled")
                    continue
                if snapshot["fault"] or (not reference and not integrated):
                    continue
                if optics_identity(cfg, shared_state) != request["optics"]:
                    shared_state.smooth_tracking(
                        "fault", "optics_configuration_changed"
                    )
                    continue
                if tuple(shared_state.target_pixel()) != tuple(
                    request["target_pixel"] if integrated else reference["target_pixel"]
                ):
                    shared_state.smooth_tracking("fault", "alignment_changed")
                    continue
                if shared_state.camera_type() != (
                    request["camera"] if integrated else reference["camera"]
                ):
                    shared_state.smooth_tracking("fault", "camera_changed")
                    continue
                if tracker is None:
                    profile = TrackingProfile.from_dict(request["profile"])
                    if integrated:
                        from PiFinder.tracking_targets import (
                            initial_reference,
                            TargetTracker,
                        )
                        from PiFinder.visual_tracking_target import TargetEphemeris

                        seed = shared_state.tracking_alignment()["seed"]
                        if not seed:
                            continue
                        ephemeris = TargetEphemeris(shared_state)
                        try:
                            anchor = initial_reference(
                                seed, request, profile, ephemeris, reference
                            )
                        except LookupError as exc:
                            shared_state.smooth_tracking(
                                "status", {"state": "ACQUIRING", "reason": str(exc)}
                            )
                            continue
                        tracker = TargetTracker(anchor, request, profile, ephemeris)
                    else:
                        tracker = StarTracker(reference, request, profile)
                    shared_state.smooth_tracking("active_reference", tracker.reference)
                    shared_state.smooth_tracking("rois", tracker.roi_request())
                elif integrated:
                    tracker.adopt_solve(reference)
                    tracker.offer_seed(shared_state.tracking_alignment()["seed"])
                elif reference["id"] != tracker.reference["id"] and (
                    time.monotonic() - tracker.reference["timing"]["midpoint"]
                    > tracker.profile.reference_valid_s / 2
                    or (snapshot["measurement"] and not snapshot["measurement"].valid)
                ):
                    if reference["geometry_key"] != tracker.context.geometry:
                        shared_state.smooth_tracking(
                            "fault", "optical_geometry_changed"
                        )
                        continue
                    # Catalog identities are absolute. Preserve the latest pose
                    # as search prediction; never roll it back to a late solve.
                    tracker = StarTracker(reference, request, tracker.profile)
                    shared_state.smooth_tracking("active_reference", reference)
                    shared_state.smooth_tracking("rois", tracker.roi_request())
                frame = shared_state.smooth_tracking_frame()
                if frame is None:
                    continue
                metadata = frame["metadata"]
                key = metadata.get("capture_epoch"), metadata.get("capture_sequence")
                if key == last_key:
                    continue
                last_key = key
                result = tracker.measure(frame, time.monotonic())
                shared_state.smooth_tracking("measurement", result)
                if result.valid:
                    shared_state.smooth_tracking("rois", tracker.roi_request())
            except Exception as exc:
                logger.exception("Smooth tracking worker held")
                shared_state.smooth_tracking(
                    "fault", f"worker_error:{type(exc).__name__}"
                )
    finally:
        shared_state.smooth_tracking("fault", "worker_stopped")


def start_session(service, command):
    from PiFinder import config
    from PiFinder.visual_tracking_target import TargetEphemeris

    cfg = config.Config()
    mode = cfg.get_option("smooth_tracking_mode", "active")
    if mode not in {"shadow", "active"}:
        raise ValueError("smooth tracking mode must be shadow or active")
    if cfg.get_option("indi_goto_method", "pifinder") != "pifinder":
        raise ValueError("MFNavis GoTo mode required")
    integrated = bool(
        cfg.get_option("smooth_tracking_target_integration_enabled", False)
    )
    if command.get("frame") not in {"catalog", "of_date"} or (
        command.get("body") and not integrated
    ):
        raise ValueError("explicit fixed-star coordinate frame required")
    target = TargetEphemeris(service.shared_state).resolve(
        float(command["ra"]),
        float(command["dec"]),
        frame=command["frame"],
        body=command.get("body") if integrated else None,
        identify_planets=command.get("identify_planets", True) if integrated else False,
    )
    data = cfg.get_option("smooth_tracking_profile", {}) or {}
    profile = TrackingProfile.from_dict(data)
    calibration = command.get("type") == "smooth_tracking_calibrate"
    if calibration and target.body:
        raise ValueError("pulse calibration requires a fixed star field")
    if calibration and mode != "active":
        raise ValueError("select active mode for explicit pulse calibration")
    if calibration and not (profile.verified or profile.equipment_verified):
        raise ValueError("calibration requires verified equipment/timing/Stop bounds")
    if mode == "active" and not profile.verified and not calibration:
        raise ValueError("equipment response/timing profile has not been verified")
    mount = service._mount_status_summary()
    if not mount.get("available"):
        raise ValueError("mount status unavailable")
    if (
        integrated
        and not calibration
        and mode == "active"
        and (
            mount.get("tracking_enabled") is not True
            or service._mount_summary_reports_parked(mount)
        )
    ):
        raise ValueError("tracking is off or mount is parked")
    request = {
        "session": uuid.uuid4().hex,
        "mode": "active" if calibration else mode,
        "purpose": "calibration" if calibration else "tracking",
        "target": (target.ra, target.dec),
        "profile": profile.to_dict(),
        "profile_hash": fingerprint(data),
        "optics": optics_identity(cfg, service.shared_state),
        "started_mono": time.monotonic(),
        "connection": int(mount.get("connection_epoch", -1)),
        "control": control_epoch(service.mountcontrol_queue),
        "prediction": bool(cfg.get_option("smooth_tracking_prediction_enabled", True)),
        "axis": bool(cfg.get_option("smooth_tracking_axis_recovery_enabled", False)),
        "goto": bool(cfg.get_option("smooth_tracking_goto_recovery_enabled", False)),
    }
    if integrated and not calibration:
        from PiFinder.tracking_targets import astronomical_time

        request.update(
            target_integration=True,
            tracking_target=asdict(target),
            target_identity=target.identity,
            target_revision=command.get("alignment_request_id", uuid.uuid4().hex),
            target_pixel=tuple(service.shared_state.target_pixel()),
            camera=service.shared_state.camera_type(),
            astronomical_time=service.shared_state.datetime().timestamp(),
            wall_time=time.time(),
            axis=False,
            goto=False,
        )
        request["target"] = TargetEphemeris(service.shared_state).position(
            target, astronomical_time(request, request["wall_time"])
        )
        import numpy as np
        from PiFinder.visual_tracking import plate_basis

        # The response was measured in model_target east/north. Transport it
        # into this session's fixed target axes once; moving ephemerides do
        # not keep rotating the controller or changing its context.
        transport = (
            plate_basis(*request["target"], 0)[1:]
            @ plate_basis(*profile.model_target, 0)[1:].T
        )
        request["profile"]["response"] = (
            transport @ np.asarray(profile.response)
        ).tolist()
        # Body and relative-star coast need independent validation. Preserve
        # the existing star controller's prediction while the image is valid.
        request["profile"]["coast_verified"] = False
        if command.get("solved_alignment"):
            reference = service.shared_state.smooth_tracking()["reference"]
            plate = (
                getattr(service.shared_state.solution(), "alignment_projection", None)
                or {}
            )
            if reference and reference["timing"] == plate.get("tracking_timing"):
                request["accepted_reference_id"] = reference["id"]
                if reference["geometry_key"] == profile.geometry:
                    # A normal solved Align changes the holding pixel. The
                    # same measured optics/response can be used with the new
                    # pixel; this rebind is session-local, never a config write.
                    request["profile"]["geometry"] = fingerprint(
                        dict(
                            info=reference["info"],
                            shape=reference["raw_shape"],
                            target=request["target_pixel"],
                            camera=reference["camera"],
                        )
                    )
    service.shared_state.smooth_tracking("arm", request)
    if mode == "active" or calibration:
        # Keep legacy recovery suspended even after a worker/configuration stop
        # removes the request. Only an explicit legacy restart releases this.
        service.smooth_tracking_legacy_suspended = True
        service.tracking_guide_suspended = True
        service.phase = "idle"
        service.solve_fallback_armed = False
        service._cancel_initial_goto_wait("smooth tracking session")
        service._disable_tracking_guide("smooth tracking owns corrections")
        service._disable_pulse_align()
        service._reset_tracking_recovery()
    return request


def tick_policy(service):
    """Return True when visual owns corrections, including acquisition/hold."""
    shared = service.shared_state
    if not hasattr(shared, "smooth_tracking"):
        return False
    snapshot = shared.smooth_tracking()
    request = snapshot["request"]
    if not request:
        return False
    active = request["mode"] == "active"
    if request["control"] != control_epoch(service.mountcontrol_queue):
        shared.smooth_tracking("stop", "user_command")
        if active:
            service.tracking_guide_suspended = True
        return active
    m = snapshot["measurement"]
    mount = service._mount_status_summary()
    now = time.monotonic()
    recovering = snapshot["status"].get("state") in {"GOTO_RECOVERY", "REACQUIRING"}
    if (
        recovering
        and m
        and not snapshot["fault"]
        and request["goto"]
        and service._mount_status_fresh(mount)
        and not service._mount_summary_reports_parked(mount)
        and int(mount.get("connection_epoch", -1)) == request["connection"]
    ):
        shared.smooth_tracking(
            "recovery_permission",
            TrackingPermission(
                m.context,
                now + 2.5,
                snapshot["quality_revision"],
                False,
                False,
                True,
                "recovery",
            ),
        )
        return active
    coast = bool(
        m and m.reason in COAST_REASONS and request["profile"].get("coast_verified")
    )
    if (
        not m
        or (not m.valid and not coast)
        or snapshot["fault"]
        or not mount.get("available")
        or not service._mount_status_fresh(mount)
        or mount.get("tracking_enabled") is not True
        or service._mount_summary_reports_parked(mount)
        or service._mount_summary_reports_motion(mount)
        or int(mount.get("connection_epoch", -1)) != request["connection"]
    ):
        if snapshot.get("permission") is not None:
            shared.smooth_tracking("revoke", "policy_conditions_unavailable")
        return active
    # Lower-frequency policy grants a lease; executor independently rechecks
    # current optical age and fresh driver evidence on every packet.
    shared.smooth_tracking(
        "permission",
        TrackingPermission(
            m.context,
            now + 2.5,
            snapshot["quality_revision"],
            request["prediction"],
            request["axis"] and not request.get("target_integration"),
            request["goto"] and not request.get("target_integration"),
            "coast" if coast else request.get("purpose", "tracking"),
        ),
    )
    service.tracking_guide_state = snapshot["status"].get("state", "ACQUIRING")
    service.tracking_guide_last_action = snapshot["status"].get("reason", "")
    return active


def public_status(snapshot):
    """JSON-sized diagnostics; no arrays, RAW buffers, or serialized permission."""
    m = snapshot.get("measurement")
    ref = snapshot.get("reference")
    return {
        **snapshot["status"],
        "fault": snapshot["fault"],
        "mode": (snapshot.get("request") or {}).get("mode", "off"),
        "target_identity": (snapshot.get("request") or {}).get("target_identity"),
        "target_revision": (snapshot.get("request") or {}).get("target_revision"),
        "quality_revision": snapshot["quality_revision"],
        "reference": {
            key: ref.get(key)
            for key in (
                "id",
                "geometry_key",
                "camera",
                "capture_identity",
                "timing",
                "absolute_bound",
            )
        }
        if ref
        else None,
        "measurement": {
            "sequence": m.sequence,
            "quality": m.quality,
            "reason": m.reason,
            "source": m.source,
            "degrees_of_freedom": m.degrees_of_freedom,
            "target_radec": m.target_radec,
            "stars": m.stars,
            "rmse_px": m.rmse_px,
            "error_arcsec": m.error,
            "bound_arcsec": m.bound_arcsec,
            "timing": asdict(m.timing),
        }
        if m
        else None,
    }
