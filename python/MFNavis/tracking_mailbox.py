"""Bounded shared-state mailbox. Decisions follow capture order, not completion."""

from copy import deepcopy
import threading
import time
from PiFinder.tracking_contracts import COAST_REASONS


class TrackingMailbox:
    def __getstate__(self):
        # Serialized shared state is diagnostic, never an armed session.
        return {"status": self.snapshot()["status"]}

    def __setstate__(self, state):
        self.__init__()

    def __init__(self):
        self.lock = threading.RLock()
        self.request = None
        self.reference = None
        self.active_reference = None
        self.blocked_key = None
        self.measurement = None
        self.revision = 0
        self.invalid_revision = 0
        self.fault = ""
        self.permission = None
        self.recovery_permission = None
        self.status = {"state": "DISABLED", "reason": "not_armed"}
        self.rois = None
        self.worker_seen = 0.0

    def arm(self, request):
        with self.lock:
            self.request = deepcopy(request)
            self.measurement = self.permission = self.rois = None
            self.recovery_permission = None
            self.active_reference = self.blocked_key = None
            self.revision += 1
            self.invalid_revision = self.revision
            self.fault = ""
            self.status = {"state": "ACQUIRING", "reason": "new_session"}

    def stop(self, reason):
        with self.lock:
            self.request = self.permission = self.rois = None
            self.recovery_permission = None
            self.revision += 1
            self.invalid_revision = self.revision
            self.fault = str(reason)
            self.status = {"state": "DISABLED", "reason": self.fault}

    def publish_reference(self, reference):
        with self.lock:
            old = self.reference
            if old and old["capture_epoch"] == reference["capture_epoch"]:
                if old["sequence"] >= reference["sequence"]:
                    return False
            self.reference = deepcopy(reference)
            return True

    def publish(self, measurement):
        with self.lock:
            if (
                not self.request
                or measurement.context.session != self.request["session"]
            ):
                return False
            old = self.measurement
            if old:
                if old.context.capture_epoch != measurement.context.capture_epoch:
                    self.fail("capture_epoch_changed")
                    return False
                if measurement.sequence < old.sequence:
                    return False
                if measurement.sequence == old.sequence and (
                    not old.valid or measurement.valid
                ):
                    return False
            self.measurement = deepcopy(measurement)
            self.revision += 1
            self.worker_seen = time.monotonic()
            if not measurement.valid:
                self.invalid_revision = self.revision
                self.permission = None
            return True

    def fail(self, reason):
        with self.lock:
            self.fault = str(reason)
            self.permission = None
            self.recovery_permission = None
            self.revision += 1
            self.invalid_revision = self.revision
            self.status = {"state": "QUALITY_HOLD", "reason": self.fault}

    def revoke(self, reason):
        with self.lock:
            self.blocked_key = self.measurement.key if self.measurement else None
            self.permission = None
            self.revision += 1
            self.invalid_revision = self.revision
            self.status = {"state": "QUALITY_HOLD", "reason": str(reason)}

    def grant(self, permission):
        with self.lock:
            if (
                self.fault
                or not self.request
                or not self.measurement
                or (
                    not self.measurement.valid
                    and not (
                        permission.purpose == "coast"
                        and self.measurement.reason in COAST_REASONS
                    )
                )
                or self.measurement.key == self.blocked_key
                or permission.context != self.measurement.context
                or permission.quality_floor < self.invalid_revision
                or permission.quality_floor > self.revision
            ):
                return False
            self.permission = permission
            return True

    def snapshot(self):
        with self.lock:
            return deepcopy(
                {
                    "request": self.request,
                    "reference": self.reference,
                    "active_reference": self.active_reference,
                    "measurement": self.measurement,
                    "quality_revision": self.revision,
                    "invalid_revision": self.invalid_revision,
                    "fault": self.fault,
                    "permission": self.permission,
                    "recovery_permission": self.recovery_permission,
                    "status": self.status,
                    "worker_seen": self.worker_seen,
                }
            )

    def set_status(self, status):
        with self.lock:
            self.status = deepcopy(status)

    def set_rois(self, value):
        with self.lock:
            self.rois = deepcopy(value)

    def activate_reference(self, reference):
        with self.lock:
            self.active_reference = deepcopy(reference)

    def grant_recovery(self, permission):
        with self.lock:
            if (
                self.fault
                or not self.request
                or permission.purpose != "recovery"
                or permission.context.session != self.request["session"]
                or not permission.allow_goto
            ):
                return False
            self.recovery_permission = permission
            return True

    def get_rois(self):
        with self.lock:
            return deepcopy(self.rois)
