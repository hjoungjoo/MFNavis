import multiprocessing as mp
import time

import numpy as np
import pytest

from PiFinder.raw_frame_transport import RawFramePublisher, read_frame, camera_raw
from PiFinder.state import SharedStateObj
from PiFinder.solver import _read_matching_solver_inputs

pytestmark = pytest.mark.unit


def test_owned_copy_crop_rotation_expiration_and_cleanup():
    publisher = RawFramePublisher(slots=2)
    try:
        source = np.arange(8 * 10, dtype=np.uint16).reshape(8, 10)
        ref = publisher.publish(source)
        view = {**ref, "crop": (1, 2, 2, 1), "rotation": 1}
        first = read_frame(view)
        np.testing.assert_array_equal(first, np.rot90(source[1:-2, 2:-1]))
        first[:] = 999
        np.testing.assert_array_equal(read_frame(ref), source)
        publisher.publish(source + 1)
        publisher.publish(source + 2)
        assert read_frame(ref) is None
        live = publisher.publish(source)
    finally:
        publisher.close()
    assert read_frame(live) is None


def test_atomic_solver_pair_and_legacy_readers_keep_exact_pixels(monkeypatch):
    publisher = RawFramePublisher()
    state = SharedStateObj()
    frame = np.arange(80, dtype=np.uint16).reshape(8, 10)
    try:
        ref = publisher.publish(frame)
        raw = {"frame_ref": ref, "frame_id": 10}
        state.set_camera_raw_refs({**ref, "crop": (0, 0, 1, 1)}, raw)
        state.set_solver_frame(
            {
                "image": frame.astype(np.uint8),
                "metadata": {"frame_id": 10, "exposure_end": 100},
            }
        )
        # A newer camera RAW must not be substituted into the retained envelope.
        state.set_camera_raw_refs(publisher.publish(frame + 100), {"frame_id": 11})
        envelope, raw = _read_matching_solver_inputs(state)
        assert envelope["metadata"]["frame_id"] == raw["frame_id"] == 10
        np.testing.assert_array_equal(raw["frame"], frame)
        np.testing.assert_array_equal(state.solver_frame()["raw"]["frame"], frame)
        np.testing.assert_array_equal(camera_raw(state), frame + 100)
        np.testing.assert_array_equal(state.cam_raw(), frame + 100)
        import PiFinder.raw_frame_transport as transport

        monkeypatch.setattr(
            transport, "read_frame", lambda ref: pytest.fail("Duplicate RAW read")
        )
        envelope, raw = _read_matching_solver_inputs(state, newer_than=100)
        assert raw is None
        assert envelope["image"] is None
        assert envelope["metadata"]["frame_id"] == 10
    finally:
        publisher.close()


def _publish_frames(connection):
    publisher = RawFramePublisher(slots=2)
    try:
        for value in range(30):
            reference = publisher.publish(np.full((256, 512), value, dtype=np.uint16))
            connection.send((value, reference))
            time.sleep(0.002)
        connection.send(None)
        connection.recv()  # Keep the owning fds alive until the reader has finished.
    finally:
        publisher.close()
        connection.close()


def test_solver_rejects_expired_slot_then_accepts_fresh_matching_pair():
    publisher = RawFramePublisher(slots=1)
    state = SharedStateObj()
    frame = np.full((32, 32), 12, dtype=np.uint16)
    try:
        old = publisher.publish(frame)
        state.set_camera_raw_refs(old, {"frame_ref": old, "frame_id": 10})
        state.set_solver_frame({"image": frame, "metadata": {"frame_id": 10}})
        new = publisher.publish(frame + 1)
        envelope, raw = _read_matching_solver_inputs(state)
        assert envelope["metadata"]["frame_id"] == 10
        assert raw is None
        state.set_camera_raw_refs(new, {"frame_ref": new, "frame_id": 11})
        state.set_solver_frame({"image": frame + 1, "metadata": {"frame_id": 11}})
        envelope, raw = _read_matching_solver_inputs(state)
        assert envelope["metadata"]["frame_id"] == raw["frame_id"] == 11
        np.testing.assert_array_equal(raw["frame"], frame + 1)
    finally:
        publisher.close()


def test_concurrent_processes_never_deliver_torn_or_wrong_generation_frames():
    context = mp.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_publish_frames, args=(child,))
    process.start()
    child.close()
    valid = 0
    try:
        while True:
            assert parent.poll(10)
            item = parent.recv()
            if item is None:
                break
            value, ref = item
            frame = read_frame(ref)
            if frame is not None:
                assert np.all(frame == value)
                valid += 1
        assert valid > 0
        parent.send(True)
        process.join(5)
        assert process.exitcode == 0
        assert read_frame(ref) is None
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()


@pytest.mark.parametrize("rotation", [0, 1, 2, 3])
def test_camera_capture_matches_legacy_raw_preview_and_solver_inputs(rotation):
    from dataclasses import replace
    from types import SimpleNamespace
    from PiFinder.camera_pi import CameraPI
    from PiFinder.sqm import get_camera_profile

    class LegacyState(SharedStateObj):
        def raw_frame_transport(self):
            return None

    raw = np.random.default_rng(42).integers(0, 4096, (64, 96), dtype=np.uint16)
    results = []
    for state in (LegacyState(), SharedStateObj()):
        camera = CameraPI.__new__(CameraPI)
        camera.profile = replace(
            get_camera_profile("imx678_color"),
            raw_size=(96, 64),
            crop_x=(8, 8),
            crop_y=(2, 2),
            rotation_90=rotation,
        )
        camera.camera_type = "imx678_color"
        camera.exposure_time, camera.gain = 1000, 20
        camera._auto_star_controller = None
        camera._capture_sequence = camera._estimated_sensor_drops = 0
        camera._radiometer_sequence = 0
        camera._last_sensor_timestamp_ns = None
        camera._raw_size, camera._raw_shift = (96, 64), 4
        camera._publish_solver_raw = True
        camera.shared_state = state
        request = SimpleNamespace(
            make_array=lambda name: raw << 4,
            get_metadata=lambda: {
                "SensorTimestamp": 100,
                "ExposureTime": 1000,
                "AnalogueGain": 20,
            },
            release=lambda: None,
        )
        camera.camera = SimpleNamespace(capture_request=lambda: request)
        preview = np.asarray(camera.capture())
        state.set_solver_frame({"image": preview, "metadata": {"frame_id": 100}})
        _, solver_raw = _read_matching_solver_inputs(state)
        results.append((preview, state.cam_raw(), solver_raw["frame"]))
        if hasattr(camera, "_raw_publisher"):
            camera._raw_publisher.close()
    for before, after in zip(*results):
        np.testing.assert_array_equal(before, after)
