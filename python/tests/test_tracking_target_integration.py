"""Independent target motion, saturated lunar RAW and alignment deadlines.

These tests belong to the target integration extension. The original smooth
tracking test group remains the field-test baseline with the extension off.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
import pickle
import queue

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

from PiFinder.tracking_alignment import (
    AlignmentDispatcher,
    AlignmentLedger,
    alignment_command,
    alignment_decision,
)
from PiFinder.tracking_contracts import CaptureTiming, fingerprint
from PiFinder.tracking_mailbox import TrackingMailbox
from PiFinder.tracking_quality import extract_rois, native_points
from PiFinder.tracking_targets import (
    TargetTracker,
    initial_reference,
    measure_planet,
    publish_seed,
)
from PiFinder.visual_tracking import plate_basis, vector_radec
from PiFinder.visual_tracking_target import TrackingTarget
from test_smooth_tracking_runtime import reference_scene

pytestmark = pytest.mark.unit


class Ephemeris:
    def _horizon_roll(self, ra, dec, timestamp):
        return (timestamp - 1100) * 0.01

    def position(self, target, timestamp):
        if target.body:
            return (40 + (timestamp - 1100) * 0.001) % 360, 20 + (
                timestamp - 1100
            ) * 0.0002
        return target.ra, target.dec

    def basis(
        self,
        target,
        timestamp,
        geometry,
        *,
        alignment_timestamp,
        alignment_roll_deg,
        mount_type,
    ):
        roll = alignment_roll_deg
        if mount_type == "Alt/Az":
            roll += (timestamp - alignment_timestamp) * 0.01
        return geometry.aligned_basis(*self.position(target, timestamp), roll)

    def angular_radius(self, target, timestamp):
        return np.radians(0.25 if target.body == "MOON" else 0.02)


def scene(body=None, rotation=0, mount_type="EQ"):
    ref, request, p = reference_scene(rotation)
    request.update(
        target_integration=True,
        tracking_target=asdict(TrackingTarget(40, 20, body)),
        target=(40, 20),
        target_pixel=ref["target_pixel"],
        camera="sim",
        optics="optics",
        wall_time=1100.0,
        astronomical_time=1100.0,
    )
    key = fingerprint(
        dict(
            info=ref["info"],
            shape=ref["raw_shape"],
            target=ref["target_pixel"],
            camera="sim",
        )
    )
    local = dict(
        verified=True,
        optics="optics",
        raw_shape=ref["raw_shape"],
        info=ref["info"],
        fov_deg=4.0,
        roll_deg=12.0,
        bound_arcsec=0.1,
        roll_target=(40.0, 20.0),
        roll_timestamp=1100.0,
    )
    p = replace(
        p,
        geometry=key,
        local_reference=local,
        mount_type=mount_type,
        pier_side="PIER_EAST" if mount_type == "EQ" else "",
        max_error_bound_arcsec=30.0,
    )
    original_points = native_points(
        ref["points"],
        ref["raw_shape"],
        (ref["geometry"]["height"], ref["geometry"]["width"]),
        ref["info"],
    )
    seed = dict(
        metadata=dict(
            capture_epoch="capture", capture_sequence=1, tracking_timing=ref["timing"]
        ),
        info=ref["info"],
        raw_shape=ref["raw_shape"],
        points=original_points.tolist(),
    )
    reference = initial_reference(seed, request, p, Ephemeris())
    return TargetTracker(reference, request, p, Ephemeris())


def frame(
    tracker,
    seq,
    *,
    east_arcsec=0,
    north_arcsec=0,
    stars=True,
    disk=False,
    saturated=False,
):
    now = 100 + seq * 0.5
    wall = now + 1000
    nominal = tracker.predict(wall)
    # A known independent physical camera offset, in catalog axes.
    position = vector_radec(nominal[0])
    moved = plate_basis(
        position[0] + east_arcsec / (3600 * np.cos(np.radians(position[1]))),
        position[1] + north_arcsec / 3600,
        tracker.reference["alignment_roll"],
    )
    # Apply a small physical translation while retaining the nominal field roll.
    pose = (
        moved @ plate_basis(*position, tracker.reference["alignment_roll"]).T @ nominal
    )
    shape = tracker.reference["raw_shape"]
    yy, xx = np.indices(shape)
    raw = np.full(shape, 50.0)
    if stars:
        coords = native_points(
            tracker.geometry.project(tracker.reference["world"], pose),
            shape,
            (tracker.geometry.height, tracker.geometry.width),
            tracker.reference["info"],
        )
        for y, x in coords:
            raw += 1000 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.3**2))
    if disk:
        target = tracker.ephemeris.position(tracker.target, wall)
        from PiFinder.visual_tracking import sky_vector

        coord = native_points(
            tracker.geometry.project([sky_vector(*target)], pose),
            shape,
            (tracker.geometry.height, tracker.geometry.width),
            tracker.reference["info"],
        )[0]
        radius = tracker.geometry.focal * np.tan(
            tracker.ephemeris.angular_radius(tracker.target, wall)
        )
        disk_image = gaussian_filter(
            (np.hypot(yy - coord[0], xx - coord[1]) < radius).astype(float), 0.7
        )
        raw += disk_image * (6000 if saturated else 2500)
        raw = np.minimum(raw, 4095)
    rois = tracker.roi_request()
    timing = CaptureTiming(
        now - 0.2, now - 0.05, now - 0.125, 0.001, wall - 0.125, True, "clock"
    )
    return dict(
        metadata=dict(
            capture_epoch="capture",
            capture_sequence=seq,
            tracking_timing=asdict(timing),
            actual_exposure_us=100000,
            actual_gain=1,
        ),
        reference=tracker.context.reference,
        raw_shape=shape,
        patches=extract_rois(raw, rois["centers"], rois["radius"]),
        body_patch=extract_rois(raw, [rois["body_center"]], rois["body_radius"])[0]
        if "body_center" in rois
        else None,
    ), now


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_relative_stars_hold_unseen_dso_without_catalog_and_correct_camera_motion(
    rotation,
):
    tracker = scene(rotation=rotation)
    image, now = frame(tracker, 2, east_arcsec=5, north_arcsec=-3)
    result = tracker.measure(image, now)
    assert result.valid and result.source == "user_star_anchor"
    assert result.error == pytest.approx((-5, 3), abs=0.6)
    assert result.camera_radec_roll is None and result.aligned_radec is None
    assert result.model_pointing is not None


@pytest.mark.parametrize("body", ["MOON", "JUPITER", "SATURN"])
def test_background_stars_account_for_body_ra_dec_motion(body):
    tracker = scene(body)
    context = tracker.context
    # The target moves by ~1 arcminute, while the fixed background is projected
    # through the new physical target-holding pose.
    image, now = frame(tracker, 32)
    result = tracker.measure(image, now)
    assert result.valid
    assert np.linalg.norm(result.error) < 0.6
    assert result.context == context
    assert result.target_radec != tracker.context.target


@pytest.mark.parametrize("body", [None, "JUPITER"])
def test_altaz_field_rotation_is_nominal_motion_not_drift(body):
    tracker = scene(body, mount_type="Alt/Az")
    image, now = frame(tracker, 32)
    result = tracker.measure(image, now)
    assert result.valid
    assert np.linalg.norm(result.error) < 0.6


def test_clock_change_and_exposure_transition_hold_even_with_a_visible_moon():
    tracker = scene("MOON")
    image, now = frame(tracker, 2, stars=False, disk=True)
    assert tracker.measure(image, now).valid
    image, now = frame(tracker, 3, stars=False, disk=True)
    image["metadata"]["actual_gain"] = 2
    assert tracker.measure(image, now).reason == "exposure_transition"
    image, now = frame(tracker, 4, stars=False, disk=True)
    image["metadata"]["tracking_timing"]["clock_epoch"] = "new-clock"
    assert tracker.measure(image, now).reason == "clock_epoch_changed"


def test_local_optics_cannot_be_inferred_from_user_confirmation():
    tracker = scene()
    seed = dict(
        metadata=dict(
            capture_epoch="capture",
            capture_sequence=1,
            tracking_timing=tracker.reference["timing"],
        ),
        info=tracker.reference["info"],
        raw_shape=tracker.reference["raw_shape"],
        points=[],
    )
    with pytest.raises(LookupError, match="verified_local_optics_required"):
        initial_reference(
            seed,
            tracker.request,
            replace(tracker.profile, local_reference={}),
            Ephemeris(),
        )
    with pytest.raises(LookupError, match="waiting_distributed_stars"):
        initial_reference(seed, tracker.request, tracker.profile, Ephemeris())


def test_new_alignment_and_correction_packets_have_distinct_lifetimes():
    from PiFinder.tracking_commands import (
        PriorityMountQueue,
        control_epoch,
        stale_command,
    )

    commands = PriorityMountQueue()
    old = alignment_command(40.0, 20.0)
    commands.put(old)
    assert control_epoch(commands) == 1
    old = commands.get(timeout=1)
    commands.put(dict(type="manual_movement", direction="east"))
    assert stale_command(old, commands)
    ledger = AlignmentLedger()
    ledger.update("motion_start", dict(now=1))
    ledger.update("motion_complete", dict(now=2))
    ledger.update("deadline", dict(generation=1, deadline=17))
    ledger.update("reset")
    assert ledger.update()["motion"]["completed_mono"] is None


def test_delayed_solve_updates_current_pose_without_rewinding_context():
    tracker = scene()
    image, now = frame(tracker, 2)
    assert tracker.measure(image, now).valid
    context = tracker.context
    catalog = deepcopy(tracker.reference)
    catalog.update(sequence=2, id="late-solve", pose=tracker.pose.tolist(), rmse_px=0.1)
    catalog["timing"] = image["metadata"]["tracking_timing"]
    tracker.adopt_solve(catalog)
    image, now = frame(tracker, 3)
    result = tracker.measure(image, now)
    assert result.valid and result.source == "catalog_solve"
    assert result.context == context and result.sequence == 3
    assert result.timing.midpoint > catalog["timing"]["midpoint"]
    assert np.linalg.norm(result.error) < 0.6


def test_new_background_stars_can_anchor_to_a_past_valid_lunar_frame():
    tracker = scene("MOON")
    world = deepcopy(tracker.reference["world"])
    tracker.reference["world"] = []
    image, now = frame(tracker, 2, stars=False, disk=True)
    result = tracker.measure(image, now)
    assert result.valid
    points = native_points(
        tracker.geometry.project(world, tracker.pose),
        tracker.reference["raw_shape"],
        (tracker.geometry.height, tracker.geometry.width),
        tracker.reference["info"],
    )
    tracker.offer_seed(
        dict(
            metadata=image["metadata"],
            info=tracker.reference["info"],
            raw_shape=tracker.reference["raw_shape"],
            points=points.tolist(),
        )
    )
    image, now = frame(tracker, 3, stars=False, disk=True)
    assert tracker.measure(image, now).valid
    assert len(tracker.reference["world"]) >= tracker.profile.min_stars
    assert tracker.reference["absolute_bound"] >= result.bound_arcsec
    for seq in range(4, 9):
        image, now = frame(tracker, seq, disk=False)
        result = tracker.measure(image, now)
    assert result.valid and result.source == "user_star_anchor"


def test_web_alignment_queues_common_request_and_exposes_state(monkeypatch, tmp_path):
    from test_smooth_tracking_api import make_motion_client, setup_client

    client, mount, server = setup_client(
        make_motion_client.__wrapped__(monkeypatch, tmp_path)
    )
    ledger = AlignmentLedger()
    server.shared_state.tracking_alignment = ledger.update
    response = client.post(
        "/indi/smooth_tracking",
        json=dict(action="align", ra=40, dec=20, frame="catalog"),
    )
    assert response.status_code == 400
    response = client.post(
        "/indi/smooth_tracking",
        json=dict(action="configure", mode="shadow", target_integration_enabled=True),
    )
    assert response.status_code == 200
    response = client.post(
        "/indi/smooth_tracking",
        json=dict(action="align", ra=40, dec=20, frame="catalog", body="MOON"),
    )
    assert response.status_code == 202 and response.json["request_id"]
    command = server.goto_guide_queue.get_nowait()
    assert command["type"] == "tracking_align" and command["body"] == "MOON"
    assert mount.empty()
    ledger.update("status", dict(state="waiting_solve", remaining_s=3))
    assert client.get("/indi/smooth_tracking").json["alignment"]["remaining_s"] == 3


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_saturated_lunar_interior_uses_geometric_limb_and_keeps_two_axis_measurement(
    rotation,
):
    tracker = scene("MOON", rotation)
    image, now = frame(
        tracker,
        2,
        stars=False,
        disk=True,
        saturated=True,
        east_arcsec=12,
        north_arcsec=-8,
    )
    result = tracker.measure(image, now)
    assert result.valid and result.source == "moon_limb"
    assert result.error == pytest.approx((-12, 8), abs=8)
    assert result.degrees_of_freedom == 2
    assert result.camera_radec_roll is None and result.aligned_radec is None


def test_lunar_full_saturation_and_missing_limb_revoke_old_permission():
    tracker = scene("MOON")
    image, now = frame(tracker, 2, stars=False, disk=True)
    good = tracker.measure(image, now)
    assert good.valid
    mailbox = TrackingMailbox()
    mailbox.arm(tracker.request)
    mailbox.publish(good)
    image, now = frame(tracker, 3, stars=False)
    image["body_patch"]["pixels"][:] = 4095
    bad = tracker.measure(image, now)
    assert not bad.valid and bad.reason == "moon_limb_unavailable"
    mailbox.publish(bad)
    assert mailbox.snapshot()["permission"] is None


def test_independent_lunar_tracking_outlives_catalog_reference_expiry():
    tracker = scene("MOON")
    for seq in range(2, 260):
        image, now = frame(tracker, seq, stars=False, disk=True)
        result = tracker.measure(image, now)
        assert result.valid
    assert (
        now - tracker.reference["timing"]["midpoint"]
        > tracker.profile.reference_valid_s
    )


def test_planet_rejects_competing_moon_and_hot_pixel():
    tracker = scene("JUPITER")
    yy, xx = np.indices((41, 41))
    pixels = 50 + 1000 * np.exp(-((yy - 20) ** 2 + (xx - 20) ** 2) / 4)
    patch = dict(pixels=pixels, origin=(0, 0))
    assert measure_planet(patch, (20, 20), tracker.profile, 4095)
    patch["pixels"] += 1000 * np.exp(-((yy - 20) ** 2 + (xx - 30) ** 2) / 4)
    assert measure_planet(patch, (20, 20), tracker.profile, 4095) is None
    patch["pixels"][:] = 50
    patch["pixels"][20, 20] = 2000
    assert measure_planet(patch, (20, 20), tracker.profile, 4095) is None


def test_alignment_timer_excludes_correction_motion_and_repeated_requests():
    ledger = AlignmentLedger()
    ledger.update("motion_start", dict(now=0.0))
    ledger.update("motion_complete", dict(now=10.0))
    ledger.update("deadline", dict(generation=1, deadline=25.0))
    ledger.update("motion_start", dict(now=12.0, purpose="correction"))
    ledger.update("motion_complete", dict(now=13.0, purpose="correction"))
    ledger.update("deadline", dict(generation=1, deadline=40.0))
    ledger.update("motion_complete", dict(now=20.0))
    motion = ledger.update()["motion"]
    assert motion["completed_mono"] == 10 and motion["deadline"] == 25
    assert alignment_decision(motion, 15) == "waiting_solve"
    assert alignment_decision(motion, 25) == "user_center_arrival"
    assert alignment_decision(motion, 25, solved=True) == "solved_alignment"
    assert (
        alignment_decision(motion, 15, terminal_failure=True) == "user_center_arrival"
    )
    assert (
        pickle.loads(pickle.dumps(ledger)).update()["motion"]["completed_mono"] is None
    )


def dispatcher_scene(
    monkeypatch, *, solved=True, failed=False, elapsed=3.0, options=None
):
    ledger, mailbox = AlignmentLedger(), TrackingMailbox()
    ledger.update("motion_start", dict(now=0.0))
    ledger.update("motion_complete", dict(now=1.0))
    target_pixel = [260, 250]
    shared = SimpleNamespace(
        tracking_alignment=ledger.update,
        smooth_tracking=lambda a="snapshot", v=None: getattr(
            mailbox, {"stop": "stop"}.get(a, "snapshot")
        )(v)
        if a != "snapshot"
        else mailbox.snapshot(),
        target_pixel=lambda: tuple(target_pixel),
        set_target_pixel=Mock(
            side_effect=lambda pixel: target_pixel.__setitem__(slice(None), pixel)
        ),
        camera_type=lambda: "sim",
        imu=lambda: None,
    )
    shared.datetime = lambda: SimpleNamespace(timestamp=lambda: 1100.0)
    mount = dict(available=True, mount_motion_active=False, goto_motion_active=False)
    service = SimpleNamespace(
        shared_state=shared,
        mountcontrol_queue=queue.Queue(),
        _mount_status_summary=lambda: mount,
        _mount_status_fresh=lambda m: True,
        _cancel_initial_goto_wait=Mock(),
        _disable_tracking_guide=Mock(),
        _disable_pulse_align=Mock(),
        _reset_tracking_recovery=Mock(),
        _forward_to_mountcontrol=Mock(),
        alert_queue=None,
    )
    settings = dict(
        {
            "smooth_tracking_target_integration_enabled": True,
            "smooth_tracking_mode": "off",
            "alignment_solve_wait_max_s": 15.0,
        },
        **(options or {}),
    )
    cfg = SimpleNamespace(
        get_option=lambda k, default=None: settings.get(k, default),
        set_option=Mock(),
    )
    target = TrackingTarget(40.0, 20.0, "MOON")
    ephemeris = Mock(
        resolve=Mock(return_value=target), position=Mock(return_value=(40.0, 20.0))
    )
    monkeypatch.setattr(
        "PiFinder.visual_tracking_target.TargetEphemeris", lambda shared: ephemeris
    )
    monkeypatch.setattr(
        "PiFinder.alignment_projection.current_solved_target_pixel",
        lambda *a, **kw: (260, 250) if solved else (_ for _ in ()).throw(LookupError()),
    )
    monkeypatch.setattr(
        "PiFinder.tracking_alignment.time.monotonic", lambda: 1 + elapsed
    )
    if failed:
        ledger.update(
            "attempt", dict(start_mono=1.1, end_mono=2.0, terminal=True, success=False)
        )
    return ledger, shared, service, cfg, AlignmentDispatcher(service)


@pytest.mark.parametrize(
    "solved,failed,elapsed,expected",
    [
        (True, False, 3.0, "solved_alignment"),
        (False, False, 3.0, "waiting_solve"),
        (False, True, 3.0, "user_center_arrival"),
        (False, False, 20.0, "user_center_arrival"),
        (True, True, 15.0, "solved_alignment"),
    ],
)
def test_common_dispatcher_completes_once_and_uses_remaining_wait(
    monkeypatch, solved, failed, elapsed, expected
):
    ledger, shared, _service, cfg, dispatcher = dispatcher_scene(
        monkeypatch, solved=solved, failed=failed, elapsed=elapsed
    )
    command = alignment_command(40.0, 20.0, origin="lcd", body="MOON")
    dispatcher.submit(command, cfg)
    status = ledger.update()["status"]
    assert status.get("result", status["state"]) == expected
    if expected == "waiting_solve":
        assert status["remaining_s"] == 12.0
        monkeypatch.setattr(
            "PiFinder.alignment_projection.current_solved_target_pixel",
            lambda *args, **kwargs: (260, 250),
        )
        monkeypatch.setattr("PiFinder.tracking_alignment.time.monotonic", lambda: 8.0)
        dispatcher.tick(cfg)
        assert ledger.update()["status"]["result"] == "solved_alignment"
        assert cfg.set_option.call_count == 1
    else:
        previous = deepcopy(status)
        dispatcher.submit(command, cfg)
        dispatcher.tick(cfg)
        assert ledger.update()["status"] == previous
        assert shared.set_target_pixel.call_count == int(solved)
        if solved:
            cfg.set_option.assert_called_once_with("target_pixel", (260, 250))
        else:
            cfg.set_option.assert_not_called()


@pytest.mark.parametrize("origin", ["lcd", "skysafari", "web", "user"])
def test_common_dispatcher_persists_only_successful_lcd_alignment(monkeypatch, origin):
    ledger, shared, _service, cfg, dispatcher = dispatcher_scene(monkeypatch)
    dispatcher.submit(alignment_command(40.0, 20.0, origin=origin), cfg)
    assert ledger.update()["status"]["result"] == "solved_alignment"
    shared.set_target_pixel.assert_called_once_with((260, 250))
    if origin == "lcd":
        cfg.set_option.assert_called_once_with("target_pixel", (260, 250))
    else:
        cfg.set_option.assert_not_called()


@pytest.mark.parametrize("sync_result", [True, False, "timeout"])
def test_skysafari_solved_alignment_syncs_eod_before_arming_video(
    monkeypatch, sync_result
):
    ledger, shared, service, cfg, dispatcher = dispatcher_scene(
        monkeypatch,
        options=dict(mount_control=True, smooth_tracking_mode="active"),
    )
    conversion = Mock(return_value=(40.2, 20.1))
    monkeypatch.setattr("PiFinder.calc_utils.catalog_to_equinox_of_date", conversion)
    start = Mock()
    monkeypatch.setattr("PiFinder.smooth_tracking_runtime.start_session", start)
    command = alignment_command(40, 20, origin="skysafari")
    dispatcher.submit(command, cfg)
    assert ledger.update()["status"]["state"] == "waiting_mount_sync"
    assert shared.set_target_pixel.call_count == 1
    assert start.call_count == 0
    sync = service._forward_to_mountcontrol.call_args.args[0]
    assert sync["type"] == "tracking_alignment_sync"
    assert (sync["ra"], sync["dec"]) == (40.2, 20.1)
    assert sync["request_id"] == command["request_id"]
    assert conversion.call_args.args[:2] == (40.0, 20.0)
    if sync_result == "timeout":
        monkeypatch.setattr("PiFinder.tracking_alignment.time.monotonic", lambda: 20.0)
    else:
        ledger.update(
            "mount_sync", dict(request_id=command["request_id"], ok=sync_result)
        )
    dispatcher.tick(cfg)
    assert ledger.update()["status"]["state"] == "complete"
    assert ledger.update()["status"]["result"] == "solved_alignment"
    assert start.call_count == int(sync_result is True)
    assert ledger.update()["status"]["tracking"] == (
        "acquiring"
        if sync_result is True
        else "mount_sync_timeout"
        if sync_result == "timeout"
        else "mount_sync_failed"
    )
    dispatcher.tick(cfg)
    assert start.call_count == int(sync_result is True)
    cfg.set_option.assert_not_called()


def test_skysafari_unsolved_arrival_never_sends_mount_sync(monkeypatch):
    ledger, shared, service, cfg, dispatcher = dispatcher_scene(
        monkeypatch, solved=False, elapsed=20, options=dict(mount_control=True)
    )
    dispatcher.submit(alignment_command(40, 20, origin="skysafari"), cfg)
    assert ledger.update()["status"]["result"] == "user_center_arrival"
    assert shared.set_target_pixel.call_count == 0
    cfg.set_option.assert_not_called()
    assert service._forward_to_mountcontrol.call_count == 1
    assert (
        service._forward_to_mountcontrol.call_args.args[0]["type"]
        == "tracking_alignment_hold"
    )


def test_internal_alignment_sync_retains_epoch_and_acknowledges_real_mount_result():
    from PiFinder.mountcontrol_indi import MountControlIndi
    from PiFinder.tracking_commands import PriorityMountQueue

    commands = PriorityMountQueue()
    commands.put(dict(type="tracking_align"))
    commands.get(timeout=1)
    ledger = AlignmentLedger()
    mount = SimpleNamespace(
        mount_queue=commands,
        _smooth_runtime=None,
        shared_state=SimpleNamespace(tracking_alignment=ledger.update),
        _check_motion_limits=Mock(),
        sync_mount=Mock(return_value=True),
    )
    followup = dict(
        type="tracking_alignment_sync",
        request_id="confirmed-solve",
        ra=40.2,
        dec=20.1,
        _control_epoch=1,
        origin="skysafari_align",
        pointing_source="skysafari_target",
    )
    commands.put(followup)
    MountControlIndi.handle_command(mount, commands.get(timeout=1))
    assert ledger.update()["mount_sync"] == dict(request_id="confirmed-solve", ok=True)
    assert mount.sync_mount.call_args.args == (40.2, 20.1)
    commands.put(dict(followup, expires_mono=0.0))
    MountControlIndi.handle_command(mount, commands.get(timeout=1))
    assert ledger.update()["mount_sync"]["ok"] is False
    assert mount.sync_mount.call_count == 1
    commands.put(dict(type="manual_movement", direction="east"))
    commands.get(timeout=1)
    commands.put(followup)
    MountControlIndi.handle_command(mount, commands.get(timeout=1))
    assert mount.sync_mount.call_count == 1


@pytest.mark.parametrize("purpose", ["observation", "correction"])
def test_aborted_goto_aligns_only_after_physical_idle_without_resetting_correction_deadline(
    purpose,
):
    from PiFinder.mountcontrol_indi import MountControlIndi

    ledger = AlignmentLedger()
    ledger.update("motion_start", dict(now=0.0))
    if purpose == "correction":
        ledger.update("motion_complete", dict(now=1.0))
        ledger.update("deadline", dict(generation=1, deadline=16.0))
        ledger.update("motion_start", dict(now=2.0, purpose="correction"))
    busy = [True]
    mount = SimpleNamespace(
        shared_state=SimpleNamespace(tracking_alignment=ledger.update),
        _goto_motion=dict(motion_purpose=purpose),
        _manual_motion_direction=None,
        _manual_motion_origin=None,
        _cancel_sync_goto=Mock(),
        _guide_active_pulses={},
        _guide_pid={},
        _guide_holdover=SimpleNamespace(reset=Mock()),
        _apply_indi_properties=Mock(return_value=True),
        _indi_property_on=lambda prop: prop,
        _clear_manual_motion_deadline=Mock(),
        _console=Mock(),
        _indi_mount_is_busy=lambda: busy[0],
        _device_switch_on=lambda *args: False,
        _alignment_motion=lambda action, p: ledger.update(
            action, dict(purpose=p, now=3.0)
        ),
    )
    assert MountControlIndi.stop_mount(mount)
    assert mount._alignment_stop_pending == purpose
    MountControlIndi._check_alignment_stop_complete(mount)
    assert ledger.update()["motion"]["moving"] is (purpose == "observation")
    assert ledger.update()["correction_moving"] is (purpose == "correction")
    busy[0] = False
    MountControlIndi._check_alignment_stop_complete(mount)
    assert ledger.update()["motion"]["moving"] is False
    assert ledger.update()["correction_moving"] is False
    if purpose == "correction":
        assert ledger.update()["motion"]["completed_mono"] == 1.0
        assert ledger.update()["motion"]["deadline"] == 16.0
    else:
        assert ledger.update()["motion"]["completed_mono"] == 3.0


def test_current_accepted_plate_aligns_without_imu_and_old_motion_plates_are_excluded(
    monkeypatch,
):
    import time
    from PiFinder.alignment_projection import current_solved_target_pixel

    now = time.monotonic()
    plate = dict(
        captured_at=time.time() - 1,
        context=("optics",),
        RA=40.0,
        Dec=20.0,
        Roll=0.0,
        FOV=4.0,
        frame=(480, 640, 480),
        tracking_timing=dict(start_min=now - 1.5),
    )
    estimate = SimpleNamespace(
        alignment_projection=plate,
        last_solve_success=plate["captured_at"],
        imu_anchor=None,
    )
    shared = SimpleNamespace(solution=lambda: estimate, imu=lambda: None)
    monkeypatch.setattr(
        "PiFinder.alignment_projection.projection_context", lambda *a: ("optics",)
    )
    assert current_solved_target_pixel(
        shared, None, 40, 20, motion=dict(moving=False, completed_mono=now - 2)
    ) == pytest.approx((256 + 1 / 30, 256 + 1 / 30))
    with pytest.raises(LookupError, match="precedes observation"):
        current_solved_target_pixel(
            shared, None, 40, 20, motion=dict(moving=False, completed_mono=now - 0.5)
        )
    with pytest.raises(LookupError, match="precedes correction"):
        current_solved_target_pixel(
            shared,
            None,
            40,
            20,
            motion=dict(moving=False, completed_mono=now - 2, pose_after=now - 0.2),
        )


def test_align_hold_cancels_pending_recovery_and_drops_old_automatic_packets():
    from PiFinder.mountcontrol_indi import MountControlIndi
    from PiFinder.tracking_commands import PriorityMountQueue

    commands = PriorityMountQueue()
    commands.put(alignment_command(40, 20))
    commands.get(timeout=1)
    mount = SimpleNamespace(
        mount_queue=commands,
        _smooth_runtime=None,
        _cancel_sync_goto=Mock(),
        _pending_goto_refine="old",
        _check_motion_limits=Mock(),
    )
    assert MountControlIndi.handle_command(mount, dict(type="tracking_alignment_hold"))
    assert (
        mount._pending_goto_refine is None and mount._guide_correction_enabled is False
    )
    assert mount._cancel_sync_goto.call_count == 1

    assert MountControlIndi.handle_command(
        mount, dict(type="sync_and_goto", _control_epoch=0)
    )
    assert mount._cancel_sync_goto.call_count == 1


def test_new_session_transports_response_across_polar_tangent_axes(monkeypatch):
    from PiFinder.smooth_tracking_runtime import start_session

    tracker = scene()
    data = replace(tracker.profile, model_target=(180.0, 89.99)).to_dict()
    options = dict(
        smooth_tracking_mode="active",
        smooth_tracking_target_integration_enabled=True,
        smooth_tracking_profile=data,
        indi_goto_method="mfnavis",
    )
    cfg = SimpleNamespace(
        get_option=lambda name, default=None: options.get(name, default)
    )
    monkeypatch.setattr("PiFinder.config.Config", lambda: cfg)
    ephemeris = Mock(
        resolve=Mock(return_value=TrackingTarget(0.0, 89.99)),
        position=Mock(return_value=(0.0, 89.99)),
    )
    monkeypatch.setattr(
        "PiFinder.visual_tracking_target.TargetEphemeris", lambda shared: ephemeris
    )
    mailbox = TrackingMailbox()
    shared = SimpleNamespace(
        camera_type=lambda: "sim",
        target_pixel=lambda: (270, 290),
        datetime=lambda: SimpleNamespace(timestamp=lambda: 1100.0),
        smooth_tracking=lambda action, value: mailbox.arm(value),
    )
    service = SimpleNamespace(
        shared_state=shared,
        mountcontrol_queue=queue.Queue(),
        _mount_status_summary=lambda: dict(
            available=True, tracking_enabled=True, connection_epoch=1
        ),
        _mount_summary_reports_parked=lambda m: False,
        _cancel_initial_goto_wait=Mock(),
        _disable_tracking_guide=Mock(),
        _disable_pulse_align=Mock(),
        _reset_tracking_recovery=Mock(),
    )
    request = start_session(
        service,
        dict(
            type="smooth_tracking_start",
            ra=0,
            dec=89.99,
            frame="catalog",
            identify_planets=False,
        ),
    )
    # Opposite meridians near the pole are physically nearby but their east
    # and north tangent axes reverse. Reusing the original matrix reverses
    # the correction; the transported matrix has the expected opposite sign.
    assert np.asarray(request["profile"]["response"]) == pytest.approx(
        -np.asarray(data["response"]), abs=1e-8
    )
    assert request["profile_hash"] == fingerprint(data)
    assert request["target"] == (0.0, 89.99)
    assert request["axis"] is False and request["goto"] is False


def test_physical_raw_seed_never_promotes_pending_confirmation_to_final_failure():
    ledger = AlignmentLedger()
    shared = SimpleNamespace(tracking_alignment=ledger.update)
    timing = asdict(CaptureTiming(1, 2, 1.5, 0.01, 1001.5, True, "clock"))
    metadata = dict(tracking_timing=timing, frame_id=1, capture_sequence=1)
    publish_seed(
        shared,
        metadata,
        dict(rotation_deg=0),
        dict(frame_id=1, frame=np.zeros((64, 64))),
        None,
        moving=False,
        success=False,
        confirming=True,
    )
    assert ledger.update()["attempt"]["terminal"] is False
    metadata["synthetic"] = True
    publish_seed(
        shared, metadata, {}, None, None, moving=False, success=False, confirming=False
    )
    assert ledger.update()["attempt"]["terminal"] is False
