"""Structured, latched operation failures for the LCD (not console text parsing)."""

import time


class ErrorNotifier:
    def __init__(self, queue, source):
        self.queue = queue
        self.source = source
        self.seen = set()

    def reset(self):
        """A new operation may report the same failure again."""
        self.seen.clear()

    def emit(self, code, message):
        key = (str(code), str(message))
        if key in self.seen or self.queue is None:
            return
        self.seen.add(key)
        self.queue.put(
            {
                "type": "operation_error",
                "source": self.source,
                "code": key[0],
                "message": key[1],
                "time": time.time(),
                "monotonic": time.monotonic(),
            }
        )


class MountErrorGate:
    """Boot-time connection attempts are expected, until a real mount is ready."""

    def __init__(self):
        self.ready_at = None

    def observe(self, event):
        if event.get("type") == "mount_ready":
            if self.ready_at is None:
                self.ready_at = event["monotonic"]
            return False
        return (
            self.ready_at is not None
            and event.get("type") == "operation_error"
            and event.get("monotonic", -1) >= self.ready_at
        )


def mount_failure(state):
    return state.endswith("_failed") or state in {
        "error",
        "disconnected",
        "server_unavailable",
        "missing_pyindi",
        "no_telescope",
        "usb_absent",
        "invalid_connection_config",
    }
