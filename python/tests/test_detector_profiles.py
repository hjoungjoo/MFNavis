import pytest

from PiFinder.detector_profiles import configure_profile, profile_environment

pytestmark = pytest.mark.unit


def test_profile_resets_prior_arm_environment(monkeypatch):
    for key in profile_environment():
        monkeypatch.setenv(key, "stale")
    configure_profile("sep")
    configure_profile("mf4p")
    import os

    assert {
        key: os.environ[key] for key in profile_environment()
    } == profile_environment()
    assert profile_environment()["MF_DETECT_PYRAMID"] == "2"
    assert profile_environment()["MF_DETECT_SEP_FALLBACK"] == "1"


def test_invalid_profile_fails_before_switch():
    with pytest.raises(KeyError):
        profile_environment("unknown")
