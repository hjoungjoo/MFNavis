"""Persistent MF wide-lens calibration profiles.

Only pure profile conversion and config-backed storage live here.  No caller
is allowed to mutate an active calibration in memory: a complete profile is
written atomically through :class:`PiFinder.config.Config`, then is selected
again by its camera/lens fingerprint.  This makes a completed manual or
automatic calibration survive a reboot without being applied to a different
sensor, crop, or lens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Final, Mapping

from PiFinder.sqm.camera_profiles import CameraProfile
from PiFinder.mf_manual_lens import calibration_lens_key


CALIBRATION_STORE_OPTION: Final[str] = "wide_solver_calibration_store_v1"
STORE_VERSION: Final[int] = 1
VALID_DIRECTIONS: Final[frozenset[str]] = frozenset({"barrel", "pincushion"})
VALID_REFERENCE_KINDS: Final[frozenset[str]] = frozenset(
    {"semi_height", "full_image_height", "image_circle_radius"}
)


class CalibrationValidationError(ValueError):
    """Raised when a manual TV-distortion profile is not physically defined."""


@dataclass(frozen=True)
class ManualTvDistortion:
    """A data-sheet TV distortion value with enough geometry to scale it.

    The sign is never inferred from a vendor's signed percentage.  The user
    supplies ``direction`` separately because sign conventions vary between
    data sheets.
    """

    tv_distortion_percent: float
    direction: str
    reference_image_height_mm: float
    reference_kind: str
    source_note: str = ""

    def reference_radius_mm(self) -> float:
        if self.reference_kind in {"semi_height", "image_circle_radius"}:
            return float(self.reference_image_height_mm)
        if self.reference_kind == "full_image_height":
            return float(self.reference_image_height_mm) / 2.0
        raise CalibrationValidationError(
            f"Unsupported TV-distortion reference kind: {self.reference_kind}"
        )

    def validate(self) -> None:
        if self.direction not in VALID_DIRECTIONS:
            raise CalibrationValidationError(
                "TV-distortion direction must be barrel or pincushion"
            )
        if self.reference_kind not in VALID_REFERENCE_KINDS:
            raise CalibrationValidationError("TV-distortion reference kind is invalid")
        if self.reference_radius_mm() <= 0:
            raise CalibrationValidationError(
                "TV-distortion reference radius must be positive"
            )
        if not 0 <= abs(float(self.tv_distortion_percent)) <= 100:
            raise CalibrationValidationError(
                "TV distortion must be between -100 and 100 percent"
            )


def sensor_radius_mm(profile: CameraProfile) -> float:
    """Distance from optical centre to the used crop corner in millimetres."""

    width_px, height_px = profile.crop_size
    pitch_mm = float(profile.pixel_pitch_um) / 1000.0
    if width_px <= 0 or height_px <= 0 or pitch_mm <= 0:
        raise CalibrationValidationError("Camera profile has no usable physical crop")
    return ((width_px * pitch_mm / 2.0) ** 2 + (height_px * pitch_mm / 2.0) ** 2) ** 0.5


def initial_k1_from_tv(profile: CameraProfile, tv: ManualTvDistortion) -> float:
    """Scale a TV-distortion specification to the current sensor footprint.

    ``k1`` uses a first-order Brown--Conrady approximation at the sensor
    corner.  It is deliberately a provisional starting value: on-sky matched
    stars must still validate or replace it before a final calibration is
    promoted.
    """

    tv.validate()
    sign = -1.0 if tv.direction == "barrel" else 1.0
    magnitude = abs(float(tv.tv_distortion_percent)) / 100.0
    radius_ratio = sensor_radius_mm(profile) / tv.reference_radius_mm()
    return sign * magnitude * radius_ratio**2


def calibration_fingerprint(
    camera_type: str, lens_key: str, profile: CameraProfile
) -> str:
    """Fingerprint the physical geometry a calibration is valid for."""

    payload = {
        "camera_type": str(camera_type),
        "lens_key": str(lens_key),
        "raw_size": list(profile.raw_size),
        "crop_size": list(profile.crop_size),
        "pixel_pitch_um": float(profile.pixel_pitch_um),
        "model_version": 1,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


def calibration_context_key(camera_type: str, lens_key: str) -> str:
    return f"{camera_type}:{lens_key}"


def build_manual_tv_profile(
    camera_type: str,
    lens_key: str,
    profile: CameraProfile,
    tv: ManualTvDistortion,
    revision: int,
) -> dict[str, Any]:
    """Create a serialisable provisional profile from a TV-lens data sheet."""

    if revision < 1:
        raise CalibrationValidationError("Calibration revision must be positive")
    k1 = initial_k1_from_tv(profile, tv)
    return {
        "id": f"manual-tv-{camera_type}-{lens_key}-{revision}",
        "version": 1,
        "source": "manual_tv",
        "provisional": True,
        "model": "brown_conrady",
        "coefficients": {"k1": k1, "k2": 0.0, "k3": 0.0, "p1": 0.0, "p2": 0.0},
        "tv_input": {
            "distortion_percent": float(tv.tv_distortion_percent),
            "direction": tv.direction,
            "reference_image_height_mm": float(tv.reference_image_height_mm),
            "reference_kind": tv.reference_kind,
            "source_note": tv.source_note,
            "sensor_radius_mm": sensor_radius_mm(profile),
        },
        "fingerprint": calibration_fingerprint(camera_type, lens_key, profile),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_auto_sky_profile(
    camera_type: str,
    lens_key: str,
    profile: CameraProfile,
    coefficients: Mapping[str, float],
    fit_summary: Mapping[str, Any],
    revision: int,
) -> dict[str, Any]:
    """Create a completed on-sky Brown--Conrady calibration profile.

    The fitter and its observing-session policy remain separate from the
    persistent store.  This boundary only accepts a complete, finite
    coefficient set and records the validation evidence alongside it.
    """

    if revision < 1:
        raise CalibrationValidationError("Calibration revision must be positive")
    try:
        normalised = {
            key: float(coefficients.get(key, 0.0))
            for key in ("k1", "k2", "k3", "p1", "p2")
        }
    except (TypeError, ValueError) as exc:
        raise CalibrationValidationError(
            "Automatic calibration coefficients must be numeric"
        ) from exc
    if not all(math.isfinite(value) for value in normalised.values()):
        raise CalibrationValidationError(
            "Automatic calibration coefficients must be finite"
        )
    if any(abs(value) > 1.0 for value in normalised.values()):
        raise CalibrationValidationError(
            "Automatic calibration coefficient is outside the safe range"
        )
    return {
        "id": f"auto-{camera_type}-{lens_key}-{revision}",
        "version": 1,
        "source": "auto_sky",
        "provisional": False,
        "verified_from_sky": True,
        "model": "brown_conrady",
        "coefficients": normalised,
        "fit_summary": dict(fit_summary),
        "fingerprint": calibration_fingerprint(camera_type, lens_key, profile),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalise_store(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"version": STORE_VERSION, "profiles": {}, "active": {}}
    profiles = value.get("profiles")
    active = value.get("active")
    return {
        "version": STORE_VERSION,
        "profiles": dict(profiles) if isinstance(profiles, Mapping) else {},
        "active": dict(active) if isinstance(active, Mapping) else {},
    }


class CalibrationProfileStore:
    """Small config-backed store for manual and automatic lens calibrations."""

    def __init__(self, cfg) -> None:
        self._cfg = cfg

    def _load(self) -> dict[str, Any]:
        return _normalise_store(self._cfg.get_option(CALIBRATION_STORE_OPTION, {}))

    def load_active(
        self, camera_type: str, lens_key: str, profile: CameraProfile
    ) -> dict[str, Any] | None:
        """Return only an active profile matching this exact optical geometry."""

        lens_key = calibration_lens_key(
            lens_key, self._cfg.get_option("camera_lens_focal_length_mm")
        )

        store = self._load()
        context = calibration_context_key(camera_type, lens_key)
        profile_id = store["active"].get(context)
        candidate = store["profiles"].get(profile_id)
        if not isinstance(candidate, Mapping):
            return None
        if candidate.get("fingerprint") != calibration_fingerprint(
            camera_type, lens_key, profile
        ):
            return None
        return dict(candidate)

    def save_manual_tv(
        self,
        camera_type: str,
        lens_key: str,
        profile: CameraProfile,
        tv: ManualTvDistortion,
    ) -> dict[str, Any]:
        """Persist and select a new manual-TV profile for this camera/lens."""

        lens_key = calibration_lens_key(
            lens_key, self._cfg.get_option("camera_lens_focal_length_mm")
        )

        store = self._load()
        context = calibration_context_key(camera_type, lens_key)
        old_id = store["active"].get(context)
        old = store["profiles"].get(old_id)
        revision = 1
        if isinstance(old, Mapping):
            try:
                revision = int(str(old.get("id", "")).rsplit("-", 1)[1]) + 1
            except (IndexError, ValueError):
                revision = 1
        candidate = build_manual_tv_profile(
            camera_type, lens_key, profile, tv, revision
        )
        self.save_profile(camera_type, lens_key, profile, candidate)
        return candidate

    def save_profile(
        self,
        camera_type: str,
        lens_key: str,
        profile: CameraProfile,
        candidate: Mapping[str, Any],
    ) -> None:
        """Persist/select a validated manual or automatic calibration profile.

        The automatic sky fitter will call this same method after its
        central/mid/edge hold-out check.  Keeping the persistence path common
        prevents automatic profiles from having weaker reboot guarantees than
        manual TV baselines.
        """

        lens_key = calibration_lens_key(
            lens_key, self._cfg.get_option("camera_lens_focal_length_mm")
        )

        profile_id = candidate.get("id")
        if not isinstance(profile_id, str) or not profile_id:
            raise CalibrationValidationError("Calibration profile needs a non-empty id")
        expected_fingerprint = calibration_fingerprint(camera_type, lens_key, profile)
        if candidate.get("fingerprint") != expected_fingerprint:
            raise CalibrationValidationError(
                "Calibration profile does not match this camera/lens geometry"
            )
        store = self._load()
        context = calibration_context_key(camera_type, lens_key)
        store["profiles"][profile_id] = dict(candidate)
        store["active"][context] = profile_id
        self._cfg.set_option(CALIBRATION_STORE_OPTION, store)

    def save_auto_sky(
        self,
        camera_type: str,
        lens_key: str,
        profile: CameraProfile,
        coefficients: Mapping[str, float],
        fit_summary: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist and select a validated on-sky profile for this geometry."""

        lens_key = calibration_lens_key(
            lens_key, self._cfg.get_option("camera_lens_focal_length_mm")
        )

        store = self._load()
        prefix = f"auto-{camera_type}-{lens_key}-"
        revisions = []
        for profile_id in store["profiles"]:
            if not isinstance(profile_id, str) or not profile_id.startswith(prefix):
                continue
            try:
                revisions.append(int(profile_id[len(prefix) :]))
            except ValueError:
                continue
        candidate = build_auto_sky_profile(
            camera_type,
            lens_key,
            profile,
            coefficients,
            fit_summary,
            revision=max(revisions, default=0) + 1,
        )
        self.save_profile(camera_type, lens_key, profile, candidate)
        return candidate

    def clear(self, camera_type: str, lens_key: str, profile: CameraProfile) -> int:
        """Remove every saved profile for one exact camera/lens geometry."""

        lens_key = calibration_lens_key(
            lens_key, self._cfg.get_option("camera_lens_focal_length_mm")
        )

        store = self._load()
        context = calibration_context_key(camera_type, lens_key)
        fingerprint = calibration_fingerprint(camera_type, lens_key, profile)
        profile_ids = [
            profile_id
            for profile_id, candidate in store["profiles"].items()
            if isinstance(candidate, Mapping)
            and candidate.get("fingerprint") == fingerprint
        ]
        for profile_id in profile_ids:
            store["profiles"].pop(profile_id, None)
        store["active"].pop(context, None)
        self._cfg.set_option(CALIBRATION_STORE_OPTION, store)
        return len(profile_ids)
