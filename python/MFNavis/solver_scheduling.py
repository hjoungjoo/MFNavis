"""Choose same-frame recovery or fast RAW with background preprocessing.

This policy schedules work only. The solver keeps ownership of frame identity,
quality/continuity gates and coordinate publication. In particular, a completed
background result is never promoted to a newer frame's pointing.
"""

from __future__ import annotations


class SolverSchedulingPolicy:
    def __init__(
        self,
        mode: str = "auto",
        *,
        stable_raw_frames: int = 3,
        rejected_raw_frames: int = 2,
    ) -> None:
        if mode not in {"auto", "sync"}:
            raise ValueError(f"Unknown solver preprocessing mode: {mode}")
        self.mode = mode
        self.stable_raw_frames = max(1, stable_raw_frames)
        self.rejected_raw_frames = max(1, rejected_raw_frames)
        self.reset()

    def reset(self, reason: str = "warming") -> None:
        self.raw_success_streak = 0
        self.raw_rejection_streak = 0
        self.execution = "sync"
        self.reason = reason

    def choose(self, *, raw_solved: bool, forced_sync: bool = False) -> str:
        if forced_sync:
            self.reset("alignment_or_calibration")
            return self.execution
        if not raw_solved:
            self.reset("raw_failed_same_frame_recovery")
            return self.execution
        self.raw_success_streak += 1
        if self.mode == "sync":
            self.execution = "sync"
            self.reason = "configured_sync"
        elif self.raw_success_streak >= self.stable_raw_frames:
            self.execution = "async"
            self.reason = "stable_raw"
        else:
            self.execution = "sync"
            self.reason = "confirming_raw_recovery"
        return self.execution

    def record_publication(self, *, accepted: bool) -> None:
        """A pattern alone is insufficient if continuity keeps holding RAW.

        Allow one normal RAW/preprocessed transition confirmation. Repeated
        holds switch back to synchronous recovery on the following frame.
        """
        if self.execution != "async":
            self.raw_rejection_streak = 0
        elif accepted:
            self.raw_rejection_streak = 0
        else:
            self.raw_rejection_streak += 1
            if self.raw_rejection_streak >= self.rejected_raw_frames:
                self.reset("raw_publication_stalled")

    def status(self) -> dict:
        return {
            "configured_mode": self.mode,
            "execution": self.execution,
            "reason": self.reason,
            "raw_success_streak": self.raw_success_streak,
            "raw_rejection_streak": self.raw_rejection_streak,
            "stable_raw_frames": self.stable_raw_frames,
        }
