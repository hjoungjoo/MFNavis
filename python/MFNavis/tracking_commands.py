"""Cancellation published before FIFO insertion, shared by all command senders."""

from multiprocessing import Queue, Value


INVALIDATING_COMMANDS = frozenset(
    {
        "shutdown",
        "stop_movement",
        "manual_movement",
        "goto_target",
        "sync",
        "sync_and_goto",
        "set_tracking",
        "park_action",
        "reboot_mount",
        "restart_driver",
        "connection_config_changed",
        "discover_serial_connection",
        "sync_location_time",
        "set_slew_rate",
        "increase_slew_rate",
        "decrease_slew_rate",
        "reduce_slew_rate",
        "set_track_freq",
        "reset_track_freq",
        "set_backlash",
        "auto_backlash",
        "backlash_compass_continue",
        "backlash_compass_stop",
        "multipoint_align_start",
        "multipoint_align_select_star",
        "multipoint_align_goto_target",
        "multipoint_align_confirm",
        "multipoint_align_cancel",
        "multipoint_align_clear_target",
        "set_tracking_target",
        "resume_tracking_guide",
        "set_guide_rate",
        "set_track_frequency",
        "start_mount_alignment",
        "start_multipoint_align",
        "confirm_multipoint_align",
        "suspend_tracking_guide",
        "clear_tracking_target",
        "set_goto_method",
        "smooth_tracking_stop",
        "smooth_tracking_start",
        "smooth_tracking_calibrate",
        "tracking_align",
    }
)


class PriorityMountQueue:
    """FIFO compatibility plus a process-shared cancellation epoch.

    The lock protects only epoch publication/dispatch registration, never I/O.
    Hardware Stop latency still includes the already registered in-flight call.
    """

    def __init__(self, cancellation=None, stop_epoch=None):
        self.queue = Queue()
        self.cancellation = cancellation if cancellation is not None else Value("Q", 0)
        self.stop_epoch = stop_epoch if stop_epoch is not None else Value("Q", 0)

    @property
    def control_epoch(self):
        with self.cancellation.get_lock():
            return self.cancellation.value

    def put(self, command, *args, **kwargs):
        if isinstance(command, dict):
            command = dict(command)
            with self.cancellation.get_lock():
                if (
                    command.get("type") in INVALIDATING_COMMANDS
                    and command.get("origin") != "smooth_tracking_recovery"
                ):
                    self.cancellation.value += 1
                if command.get("type") in {
                    "stop_movement",
                    "shutdown",
                } or (
                    command.get("type") == "set_tracking"
                    and command.get("enabled") is False
                ):
                    with self.stop_epoch.get_lock():
                        self.stop_epoch.value = self.cancellation.value
                if command.get("type") in {
                    "tracking_alignment_hold",
                    "tracking_alignment_sync",
                }:
                    # Internal continuations retain the request's epoch even
                    # if a manual command takes over just before insertion.
                    command.setdefault("_control_epoch", self.cancellation.value)
                else:
                    command["_control_epoch"] = self.cancellation.value
        return self.queue.put(command, *args, **kwargs)

    def get(self, *args, **kwargs):
        return self.queue.get(*args, **kwargs)

    def get_nowait(self):
        return self.queue.get_nowait()

    def put_nowait(self, item):
        return self.put(item, block=False)

    def empty(self):
        return self.queue.empty()

    def register_dispatch(self, expected):
        with self.cancellation.get_lock():
            return self.cancellation.value == expected


def control_epoch(command_queue):
    return getattr(command_queue, "control_epoch", 0)


def stale_command(command, command_queue):
    """Cancel stale automatic intents without dropping ordinary FIFO settings.

    A speed selection followed by a direction press must still apply the speed.
    Stop additionally invalidates older queued motion across both queues.
    """
    stamp = command.get("_control_epoch")
    if stamp is None:
        return False
    kind = command.get("type")
    if kind == "toggle_guide_correction" and command.get("enabled") is False:
        # A following GoTo or Stop must still turn off the previous target's
        # guide loop. The mount executor guards optical ownership separately.
        return False
    if kind in {
        "smooth_tracking_start",
        "smooth_tracking_calibrate",
        "toggle_guide_correction",
        "tracking_align",
        "tracking_alignment_hold",
        "tracking_alignment_sync",
    }:
        return stamp != control_epoch(command_queue)
    motion = {
        "goto_target",
        "sync_and_goto",
        "sync",
        "manual_movement",
        "manual_movement_keepalive",
        "set_tracking_target",
        "resume_tracking_guide",
        "auto_backlash",
        "backlash_compass_continue",
        "multipoint_align_start",
        "multipoint_align_goto_target",
        "multipoint_align_confirm",
        "set_tracking",
    }
    stopped = getattr(command_queue, "stop_epoch", None)
    return kind in motion and stopped is not None and stamp < stopped.value
