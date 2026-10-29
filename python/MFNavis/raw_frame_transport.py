"""Linux RAM-backed RAW slots, with locked copies and exact-frame validation.

Only small descriptors cross the manager. Readers take an owned NumPy copy;
no solver sees a buffer which the camera can overwrite. Old slots fail closed.
memfd storage disappears when the camera exits, including abnormal exits.
"""

import fcntl
import mmap
import os
import struct
import uuid

import numpy as np

TRANSPORT = "memfd-v1"
_HEADER = struct.Struct("<8s16sQQ")
_MAGIC = b"MFRAW001"


class RawFramePublisher:
    def __init__(self, slots=4):
        self._fds = [
            os.memfd_create("mfnavis-raw", os.MFD_CLOEXEC) for _ in range(slots)
        ]
        self._token = uuid.uuid4().bytes
        self._sequence = 0

    def publish(self, frame):
        frame = np.asarray(frame)
        if frame.ndim != 2 or frame.dtype.hasobject:
            raise ValueError("RAW must be a numeric 2D array")
        self._sequence += 1
        fd = self._fds[self._sequence % len(self._fds)]
        size = _HEADER.size + frame.nbytes
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.ftruncate(fd, size)
            with mmap.mmap(fd, size) as memory:
                memory[: _HEADER.size] = bytes(_HEADER.size)
                target = np.ndarray(
                    frame.shape, dtype=frame.dtype, buffer=memory, offset=_HEADER.size
                )
                np.copyto(target, frame)
                del target
                memory[: _HEADER.size] = _HEADER.pack(
                    _MAGIC, self._token, self._sequence, frame.nbytes
                )
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
        return {
            "transport": TRANSPORT,
            "path": f"/proc/{os.getpid()}/fd/{fd}",
            "token": self._token,
            "sequence": self._sequence,
            "shape": frame.shape,
            "dtype": frame.dtype.str,
        }

    def close(self):
        fds, self._fds = self._fds, []
        for fd in fds:
            os.close(fd)

    def __del__(self):
        self.close()


def read_frame(reference):
    """Return an owned, correctly oriented frame, or None if expired/unavailable."""
    if not isinstance(reference, dict) or reference.get("transport") != TRANSPORT:
        return None
    fd = None
    try:
        shape = tuple(reference["shape"])
        dtype = np.dtype(reference["dtype"])
        if len(shape) != 2 or min(shape) <= 0 or dtype.hasobject:
            return None
        nbytes = int(shape[0]) * int(shape[1]) * dtype.itemsize
        if not 0 < nbytes <= 128 * 1024 * 1024:
            return None
        fd = os.open(reference["path"], os.O_RDONLY | os.O_CLOEXEC)
        fcntl.flock(fd, fcntl.LOCK_SH)
        expected = (_MAGIC, reference["token"], reference["sequence"], nbytes)
        header = os.pread(fd, _HEADER.size, 0)
        if len(header) != _HEADER.size or _HEADER.unpack(header) != expected:
            return None
        with mmap.mmap(fd, _HEADER.size + nbytes, access=mmap.ACCESS_READ) as memory:
            frame = np.ndarray(shape, dtype=dtype, buffer=memory, offset=_HEADER.size)
            if "crop" in reference:
                top, bottom, left, right = reference["crop"]
                frame = frame[top : shape[0] - bottom, left : shape[1] - right]
            frame = np.rot90(frame, reference.get("rotation", 0)).copy()
        return frame
    except (OSError, ValueError, KeyError, TypeError):
        return None
    finally:
        if fd is not None:
            os.close(fd)  # releases the shared lock too


def materialize_raw(entry):
    if not isinstance(entry, dict) or "frame_ref" not in entry:
        return entry
    frame = read_frame(entry["frame_ref"])
    if frame is None:
        return None
    return {**entry, "frame": frame}


def camera_raw(shared_state):
    getter = getattr(shared_state, "camera_raw_reference", None)
    reference = getter() if callable(getter) else None
    if isinstance(reference, dict) and reference.get("transport") == TRANSPORT:
        return read_frame(reference)
    return shared_state.cam_raw()
