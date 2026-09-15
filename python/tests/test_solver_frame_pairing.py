from PiFinder.solver import (
    _preprocessed_fast_path_allowed,
    _read_matching_solver_inputs,
)


def _frame(frame_id):
    return {"image": object(), "metadata": {"frame_id": frame_id}}


def _raw(frame_id):
    return {"frame": object(), "frame_id": frame_id}


class SequencedState:
    def __init__(self, frames, raws):
        self.frames = iter(frames)
        self.raws = iter(raws)
        self.frame_reads = 0
        self.raw_reads = 0

    def solver_frame(self):
        self.frame_reads += 1
        return next(self.frames)

    def solver_raw(self):
        self.raw_reads += 1
        return next(self.raws)


def test_matching_pair_returns_without_retry():
    state = SequencedState([_frame(10)], [_raw(10)])

    frame, raw = _read_matching_solver_inputs(state)

    assert frame["metadata"]["frame_id"] == 10
    assert raw["frame_id"] == 10
    assert state.frame_reads == 1
    assert state.raw_reads == 1


def test_publication_race_retries_to_new_matching_pair():
    state = SequencedState([_frame(10), _frame(11)], [_raw(11), _raw(11)])

    frame, raw = _read_matching_solver_inputs(state)

    assert frame["metadata"]["frame_id"] == 11
    assert raw["frame_id"] == 11
    assert state.frame_reads == 2
    assert state.raw_reads == 2


def test_never_accepts_mismatched_raw():
    state = SequencedState([_frame(10), _frame(11)], [_raw(20), _raw(21)])

    frame, raw = _read_matching_solver_inputs(state)

    assert frame["metadata"]["frame_id"] == 11
    assert raw is None


def test_invalid_envelope_is_ignored_safely():
    state = SequencedState([None, {"metadata": {}}], [_raw(1), _raw(2)])

    frame, raw = _read_matching_solver_inputs(state)

    assert frame is None
    assert raw is None
    assert state.raw_reads == 0


def test_trusted_stationary_preprocessor_can_replace_slow_raw_fallbacks():
    assert _preprocessed_fast_path_allowed(
        enabled=True,
        trusted=True,
        moving=False,
        aligning=False,
    )


def test_auto_keeps_raw_attempts_even_after_preprocessed_solution_is_trusted():
    assert not _preprocessed_fast_path_allowed(
        enabled=True, trusted=True, moving=False, aligning=False, scheduling_mode="auto"
    )


def test_slow_raw_fallbacks_remain_during_unsafe_states():
    assert not _preprocessed_fast_path_allowed(
        enabled=False,
        trusted=True,
        moving=False,
        aligning=False,
    )
    assert not _preprocessed_fast_path_allowed(
        enabled=True,
        trusted=False,
        moving=False,
        aligning=False,
    )
    assert not _preprocessed_fast_path_allowed(
        enabled=True,
        trusted=True,
        moving=True,
        aligning=False,
    )
    assert not _preprocessed_fast_path_allowed(
        enabled=True,
        trusted=True,
        moving=False,
        aligning=True,
    )
