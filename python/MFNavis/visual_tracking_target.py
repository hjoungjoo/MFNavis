"""Reuse existing target identification/ephemerides for tracking experiments."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from PiFinder.visual_tracking import plate_basis, sky_vector, vector_radec


@dataclass(frozen=True)
class TrackingTarget:
    ra: float
    dec: float
    body: str | None = None
    source: str = "catalog"

    def __post_init__(self):
        sky_vector(self.ra, self.dec)
        if self.body is not None and not self.body:
            raise ValueError("empty body identifier")

    @property
    def identity(self):
        return self.body or f"fixed:{self.ra % 360:.10f},{self.dec:.10f}"


class TargetEphemeris:
    """Observer-local wrapper. All returned directions use catalog axes.

    The timestamp supplied here is astronomical UTC Unix time, not a replay
    publication timestamp. The existing application singleton is used only
    within the owning solver process, with the observer location refreshed.
    """

    def __init__(self, shared_state):
        self.shared_state = shared_state

    def helper(self):
        from PiFinder.calc_utils import sf_utils

        location = self.shared_state.location()
        if location is None or not getattr(location, "lock", False):
            raise ValueError("observer location is not confirmed")
        sf_utils.set_location(location.lat, location.lon, location.altitude or 0)
        return sf_utils

    def resolve(self, ra, dec, *, frame="catalog", body=None, identify_planets=False):
        from PiFinder import track_freq_policy
        from PiFinder.calc_utils import (
            catalog_to_equinox_of_date,
            equinox_of_date_to_catalog,
        )

        sky_vector(ra, dec)
        if frame not in {"catalog", "of_date"}:
            raise ValueError("coordinate frame must be explicit")
        self.helper()
        dt = self.shared_state.datetime()
        if dt is None or dt.tzinfo is None:
            raise ValueError("UTC observation time is required")
        if body is None and identify_planets:
            match = (
                (ra, dec)
                if frame == "of_date"
                else catalog_to_equinox_of_date(ra, dec, dt)
            )
            body = track_freq_policy.planet_at_coordinates(*match, self.shared_state)
        if body is not None:
            body = body.upper()
            if body not in self.helper().planet_names or body == "SUN":
                raise ValueError("unsupported observing body")
        if frame == "of_date":
            ra, dec = equinox_of_date_to_catalog(ra, dec, dt)
        return TrackingTarget(float(ra), float(dec), body, frame)

    def position(self, target, timestamp):
        if not math.isfinite(timestamp):
            raise ValueError("invalid astronomical time")
        if target.body is None:
            return target.ra, target.dec
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
        item = self.helper().calc_planets(dt).get(target.body)
        if item is None:
            raise ValueError("body position unavailable")
        return tuple(float(v) for v in item["radec"])

    def angular_radius(self, target, timestamp):
        """Independent apparent size, using the same observer and UTC epoch."""
        helper = self.helper()
        name = target.body
        # The centre detector does not need a planetary limb fit; a bounded
        # acquisition patch still uses a conservative physical body radius.
        radii_km = {
            "MOON": 1737.4,
            "JUPITER": 71492.0,
            "SATURN": 120536.0,
            "MARS": 3396.2,
            "VENUS": 6051.8,
            "MERCURY": 2440.5,
            "URANUS": 25559.0,
            "NEPTUNE": 24764.0,
            "PLUTO": 1188.3,
        }
        if name not in radii_km:
            raise ValueError("body size unavailable")
        index = next(
            i
            for i, n in enumerate(helper.planet_names)
            if n.replace("_BARYCENTER", "") == name
        )
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
        observer = helper.observer_loc.at(helper.ts.from_datetime(dt))
        distance = float(
            observer.observe(helper.planets[index]).apparent().distance().km
        )
        return math.asin(radii_km[name] / distance)

    def basis(
        self,
        target,
        timestamp,
        geometry,
        *,
        mount_type,
        alignment_timestamp,
        alignment_roll_deg,
    ):
        """Predict the pose holding the target, with mount-specific field roll.

        Use a projected zenith vector for Alt/Az, avoiding branch-specific
        hour-angle signs. EQ retains the calibrated roll; a pier/rotator
        change must invalidate the session at the caller.
        """
        ra, dec = self.position(target, timestamp)
        roll = alignment_roll_deg
        if mount_type == "Alt/Az":
            first = self.position(target, alignment_timestamp)
            roll += self._horizon_roll(ra, dec, timestamp) - self._horizon_roll(
                *first, alignment_timestamp
            )
        elif mount_type != "EQ":
            raise ValueError("unknown mount geometry")
        return geometry.aligned_basis(ra, dec, roll)

    def _horizon_roll(self, ra, dec, timestamp):
        from PiFinder.calc_utils import equinox_of_date_to_catalog

        helper = self.helper()
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
        # Zenith RA is local sidereal time in date axes. Rotate its basis into
        # the same axes as the plate/target before comparing camera roll.
        location = self.shared_state.location()
        zra, zdec = equinox_of_date_to_catalog(
            helper.get_lst_hrs(dt) * 15, location.lat, dt
        )
        zenith = sky_vector(zra, zdec)
        basis = plate_basis(ra, dec, 0)
        east, north = float(zenith @ basis[1]), float(zenith @ basis[2])
        if math.hypot(east, north) < math.sin(math.radians(2)):
            raise ValueError("Alt/Az zenith geometry is ill-conditioned")
        return math.degrees(math.atan2(-east, north))


def aligned_radec_from_basis(basis, geometry):
    return vector_radec(geometry.rays([geometry.target_yx])[0] @ basis)
