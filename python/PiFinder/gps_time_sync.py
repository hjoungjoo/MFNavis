#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Time-source monitor for PiFinder.

chronyd is the only system-clock manager: it selects the more accurate of the
NTP pool (when a network is available) and the GPS SHM refclock fed by gpsd
(in the field). This monitor does not write the system clock. It observes
chronyd tracking state and GPS time candidates for the status UI and the
mount-sync trust gate, and writes constrained requests for the privileged
helper when RTC updates are enabled.

Reduced on 2026-07-25 (docs/mf_report/mf_field_test_20260724_analysis_ko.md, item A3):
the PiFinder-side SNTP client, software PPS ticks, direct system-clock writes
(Clock Manager = PiFinder) and the Best/GPS/NTP source modes were removed —
source selection is chronyd's job.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Optional

import pytz

from PiFinder import utils


logger = logging.getLogger("GPS.TimeSync")

DATA_DIR = Path(os.environ.get("PIFINDER_DATA_DIR", utils.data_dir))
# STATUS_FILE is rewritten every few seconds while time sync is active and is
# meaningless after a reboot, so it lives on the tmpfs runtime dir (/dev/shm)
# to spare the SD card -- the same treatment as the other volatile status
# files (pointing / mount / GoTo). REQUEST_FILE and HELPER_STATUS_FILE are
# deliberately kept on the SD data dir: they are low-frequency AND shared with
# the privileged helper that runs as root (pifinder_gps_time_sync.service).
# Keeping them under the pifinder-owned home dir avoids a /dev/shm/pifinder
# directory-ownership race (whoever creates the tmpfs dir first owns it, and a
# root-owned 0755 dir would block the pifinder user from writing REQUEST_FILE).
STATUS_FILE = utils.runtime_dir / "gps_time_status.json"
REQUEST_FILE = DATA_DIR / "gps_time_sync_request.json"
HELPER_STATUS_FILE = DATA_DIR / "gps_time_sync_helper_status.json"
# Written the first time chronyd reports a synchronized clock this boot. Lives
# on tmpfs so a reboot (which restores a stale fake-hwclock time) clears it,
# while a mere pifinder.service restart keeps it. The mount time-sync gate and
# the LCD warning read this marker (docs/mf_report/mf_field_test_20260724_analysis_ko.md,
# item A4).
CLOCK_TRUST_FILE = utils.runtime_dir / "clock_trusted.json"


def _read_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


def read_clock_trust_marker(
    marker_file: Path = CLOCK_TRUST_FILE,
    boot_id_fn: Callable[[], str] = _read_boot_id,
) -> Optional[dict[str, Any]]:
    """Return the trust marker payload if it belongs to the current boot."""
    try:
        with open(marker_file, "r", encoding="utf-8") as marker_in:
            payload = json.load(marker_in)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("boot_id") != boot_id_fn():
        return None
    return payload


def write_clock_trust_marker(
    source: str,
    marker_file: Path = CLOCK_TRUST_FILE,
    boot_id_fn: Callable[[], str] = _read_boot_id,
    time_fn: Callable[[], float] = time.time,
) -> None:
    try:
        utils.create_path(marker_file.parent)
        payload = {
            "boot_id": boot_id_fn(),
            "source": source,
            "trusted_unix": time_fn(),
        }
        tmp_file = marker_file.with_name(marker_file.name + ".tmp")
        with open(tmp_file, "w", encoding="utf-8") as marker_out:
            json.dump(payload, marker_out, indent=2, sort_keys=True)
        tmp_file.replace(marker_file)
        logger.info("Clock trust marker written (source=%s)", source)
    except Exception:
        logger.exception("Could not write clock trust marker")


def clock_is_trusted(
    check_chrony: bool = False,
    marker_file: Path = CLOCK_TRUST_FILE,
    boot_id_fn: Callable[[], str] = _read_boot_id,
    chrony_client: Optional["ChronyClient"] = None,
) -> bool:
    """True when the system clock has been synchronized at least once this boot.

    The fast path is the tmpfs marker. With ``check_chrony`` a live
    ``chronyc tracking`` query is used as fallback (and primes the marker on
    success) so the gate works even before the monitor's next poll or with
    the observation framework disabled.
    """
    if read_clock_trust_marker(marker_file, boot_id_fn) is not None:
        return True
    if not check_chrony:
        return False
    client = chrony_client or ChronyClient()
    result = client.query()
    if result.get("ok") and result.get("state") == "stable":
        write_clock_trust_marker(
            "chrony-direct", marker_file=marker_file, boot_id_fn=boot_id_fn
        )
        return True
    return False


class ClockSyncRequestWriter:
    """Write requests for the privileged GPS time-sync helper."""

    def __init__(
        self,
        request_file: Path = REQUEST_FILE,
        boot_id_fn: Callable[[], str] = _read_boot_id,
    ):
        self.request_file = request_file
        self.boot_id_fn = boot_id_fn

    def write_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            utils.create_path(self.request_file.parent)
            payload = dict(payload)
            payload["boot_id"] = self.boot_id_fn()
            tmp_file = self.request_file.with_name(self.request_file.name + ".tmp")
            with open(tmp_file, "w", encoding="utf-8") as request_out:
                json.dump(payload, request_out, indent=2, sort_keys=True)
            tmp_file.replace(self.request_file)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": f"request written to {self.request_file}"}

    def clear_request(self) -> None:
        try:
            self.request_file.unlink()
        except FileNotFoundError:
            return
        except Exception:
            logger.exception("Could not clear time sync request")


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _utc_datetime(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return pytz.timezone("UTC").localize(dt)
    return dt.astimezone(pytz.timezone("UTC"))


def _first_float(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    for word in value.replace(",", " ").split():
        try:
            return float(word)
        except ValueError:
            continue
    return None


class ChronyClient:
    """Read chronyd tracking state through chronyc."""

    def __init__(
        self,
        time_fn: Callable[[], float] = time.time,
        run_fn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ):
        self.time_fn = time_fn
        self.run_fn = run_fn

    def _parse_tracking(self, output: str) -> dict[str, Any]:
        fields = {}
        for line in output.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()

        reference = fields.get("Reference ID", "")
        reference_name = None
        if "(" in reference and reference.endswith(")"):
            reference_name = reference.rsplit("(", 1)[1][:-1]

        leap_status = fields.get("Leap status", "")
        system_time = fields.get("System time", "")
        system_offset = _first_float(system_time)
        if system_offset is not None and "slow" in system_time.lower():
            system_offset = -abs(system_offset)

        state = "stable"
        message = "chronyd is tracking a time source"
        if not reference or reference.startswith("00000000"):
            state = "unsynced"
            message = "chronyd is not synchronized"
        elif leap_status and leap_status.lower() != "normal":
            state = "unsynced"
            message = f"chronyd leap status is {leap_status}"

        return {
            "ok": True,
            "state": state,
            "message": message,
            "reference_id": reference,
            "reference_name": reference_name,
            "stratum": _as_int(fields.get("Stratum"), 0),
            "ref_time_utc": fields.get("Ref time (UTC)"),
            "system_time_offset_seconds": system_offset,
            "last_offset_seconds": _first_float(fields.get("Last offset")),
            "rms_offset_seconds": _first_float(fields.get("RMS offset")),
            "root_delay_seconds": _first_float(fields.get("Root delay")),
            "root_dispersion_seconds": _first_float(fields.get("Root dispersion")),
            "skew_ppm": _first_float(fields.get("Skew")),
            "leap_status": leap_status,
            "raw": fields,
            "received_unix": self.time_fn(),
        }

    def query(self, timeout_seconds: float = 1.0) -> dict[str, Any]:
        try:
            result = self.run_fn(
                ["chronyc", "-n", "tracking"],
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            return {"ok": False, "state": "missing", "message": "chronyc not found"}
        except Exception as exc:
            return {"ok": False, "state": "unavailable", "message": str(exc)}

        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            return {
                "ok": False,
                "state": "unavailable",
                "message": output.strip() or f"chronyc exited {result.returncode}",
            }
        return self._parse_tracking(output)


class GpsTimeSyncMonitor:
    """Observe chronyd and GPS time quality; request RTC updates if enabled."""

    def __init__(
        self,
        time_sync_enabled: Optional[bool] = None,
        enabled: bool = False,
        chrony_enabled: bool = False,
        rtc_sync_enabled: bool = False,
        chrony_poll_interval_seconds: float = 30.0,
        chrony_timeout_seconds: float = 1.0,
        chrony_stale_seconds: float = 120.0,
        min_samples: int = 5,
        sample_window_seconds: float = 120.0,
        stale_seconds: float = 30.0,
        max_tacc_ns: int = 1_000_000_000,
        stable_jitter_ms: float = 250.0,
        stable_offset_ms: float = 1000.0,
        status_write_interval_seconds: float = 5.0,
        rtc_sync_min_interval_seconds: float = 3600.0,
        status_file: Path = STATUS_FILE,
        helper_status_file: Path = HELPER_STATUS_FILE,
        clock_trust_file: Path = CLOCK_TRUST_FILE,
        time_fn: Callable[[], float] = time.time,
        monotonic_fn: Callable[[], float] = time.monotonic,
        request_writer: Optional[ClockSyncRequestWriter] = None,
        chrony_client: Optional[ChronyClient] = None,
    ):
        if time_sync_enabled is None:
            time_sync_enabled = enabled or chrony_enabled or rtc_sync_enabled
        self.time_sync_enabled = time_sync_enabled
        self.enabled = enabled
        self.chrony_enabled = chrony_enabled
        self.rtc_sync_enabled = rtc_sync_enabled
        self.chrony_poll_interval_seconds = max(5.0, chrony_poll_interval_seconds)
        self.chrony_timeout_seconds = max(0.1, chrony_timeout_seconds)
        self.chrony_stale_seconds = max(5.0, chrony_stale_seconds)
        self.min_samples = max(1, min_samples)
        self.sample_window_seconds = max(1.0, sample_window_seconds)
        self.stale_seconds = max(1.0, stale_seconds)
        self.max_tacc_ns = max_tacc_ns
        self.stable_jitter_seconds = max(0.001, stable_jitter_ms / 1000.0)
        self.stable_offset_seconds = max(0.001, stable_offset_ms / 1000.0)
        self.status_write_interval_seconds = max(0.5, status_write_interval_seconds)
        self.rtc_sync_min_interval_seconds = max(1.0, rtc_sync_min_interval_seconds)
        self.status_file = status_file
        self.helper_status_file = helper_status_file
        self.clock_trust_file = clock_trust_file
        self.time_fn = time_fn
        self.monotonic_fn = monotonic_fn
        self.request_writer = request_writer or ClockSyncRequestWriter()
        self.chrony_client = chrony_client or ChronyClient(time_fn=time_fn)

        self.samples: Deque[dict[str, Any]] = deque()
        self.state = "disabled"
        self.message = "Time sync disabled"
        self.gps_state = "disabled"
        self.gps_message = "GPS time source disabled"
        self.last_status_write_monotonic: Optional[float] = None
        self.latest_sample: Optional[dict[str, Any]] = None

        self.chrony_state = "disabled"
        self.chrony_message = "chronyd time source disabled"
        self.latest_chrony_sample: Optional[dict[str, Any]] = None
        self.last_chrony_poll_monotonic: Optional[float] = None

        self.selected_source: Optional[dict[str, Any]] = None

        self.rtc_sync_state = "disabled"
        self.rtc_sync_message = "RTC sync disabled"
        self.rtc_request_count = 0
        self.last_rtc_request_monotonic: Optional[float] = None
        self.last_rtc_request_utc: Optional[str] = None

    @classmethod
    def from_config(
        cls,
        cfg,
        status_file: Path = STATUS_FILE,
        helper_status_file: Path = HELPER_STATUS_FILE,
    ) -> "GpsTimeSyncMonitor":
        return cls(
            time_sync_enabled=_as_bool(cfg.get_option("time_sync_enabled", True), True),
            enabled=_as_bool(cfg.get_option("gps_time_sync", True), True),
            chrony_enabled=_as_bool(cfg.get_option("chrony_time_sync", True), True),
            rtc_sync_enabled=_as_bool(cfg.get_option("rtc_sync", False)),
            chrony_poll_interval_seconds=_as_float(
                cfg.get_option("chrony_poll_interval_seconds", 30.0), 30.0
            ),
            chrony_timeout_seconds=_as_float(
                cfg.get_option("chrony_timeout_seconds", 1.0), 1.0
            ),
            chrony_stale_seconds=_as_float(
                cfg.get_option("chrony_stale_seconds", 120.0), 120.0
            ),
            min_samples=_as_int(cfg.get_option("gps_time_sync_min_samples", 5), 5),
            sample_window_seconds=_as_float(
                cfg.get_option("gps_time_sync_window_seconds", 120.0), 120.0
            ),
            stale_seconds=_as_float(
                cfg.get_option("gps_time_sync_stale_seconds", 30.0), 30.0
            ),
            max_tacc_ns=_as_int(
                cfg.get_option("gps_time_sync_max_tacc_ns", 1_000_000_000),
                1_000_000_000,
            ),
            stable_jitter_ms=_as_float(
                cfg.get_option("gps_time_sync_stable_jitter_ms", 250.0), 250.0
            ),
            stable_offset_ms=_as_float(
                cfg.get_option("gps_time_sync_stable_offset_ms", 1000.0), 1000.0
            ),
            rtc_sync_min_interval_seconds=_as_float(
                cfg.get_option("rtc_sync_min_interval_seconds", 3600.0), 3600.0
            ),
            status_file=status_file,
            helper_status_file=helper_status_file,
        )

    def update_config(self, cfg) -> None:
        updated = self.from_config(
            cfg,
            status_file=self.status_file,
            helper_status_file=self.helper_status_file,
        )
        self.time_sync_enabled = updated.time_sync_enabled
        self.enabled = updated.enabled
        self.chrony_enabled = updated.chrony_enabled
        self.rtc_sync_enabled = updated.rtc_sync_enabled
        self.chrony_poll_interval_seconds = updated.chrony_poll_interval_seconds
        self.chrony_timeout_seconds = updated.chrony_timeout_seconds
        self.chrony_stale_seconds = updated.chrony_stale_seconds
        self.min_samples = updated.min_samples
        self.sample_window_seconds = updated.sample_window_seconds
        self.stale_seconds = updated.stale_seconds
        self.max_tacc_ns = updated.max_tacc_ns
        self.stable_jitter_seconds = updated.stable_jitter_seconds
        self.stable_offset_seconds = updated.stable_offset_seconds
        self.status_write_interval_seconds = updated.status_write_interval_seconds
        self.rtc_sync_min_interval_seconds = updated.rtc_sync_min_interval_seconds
        self._refresh_action_wait_states()
        self.write_status(force=True)

    def _active(self) -> bool:
        return self.time_sync_enabled and (
            self.enabled or self.chrony_enabled or self.rtc_sync_enabled
        )

    def write_startup_status(self) -> None:
        if not self.time_sync_enabled:
            self._set_state("disabled", "Time sync disabled")
        elif self.chrony_enabled:
            self._set_state("waiting_for_time_source", "Waiting for chronyd")
        elif self.enabled:
            self._set_state("waiting_for_time_source", "Waiting for time source")
        else:
            self._set_state("disabled", "Time sync has no enabled source")

        self._refresh_action_wait_states()
        if self._active() or self.status_file.exists():
            self.write_status(force=True)

    def _set_state(self, state: str, message: str) -> bool:
        changed = state != self.state or message != self.message
        self.state = state
        self.message = message
        return changed

    def _set_gps_state(self, state: str, message: str) -> bool:
        changed = state != self.gps_state or message != self.gps_message
        self.gps_state = state
        self.gps_message = message
        return changed

    def _set_chrony_state(self, state: str, message: str) -> bool:
        changed = state != self.chrony_state or message != self.chrony_message
        self.chrony_state = state
        self.chrony_message = message
        return changed

    def _prune_samples(self, now_monotonic: float) -> None:
        while (
            self.samples
            and now_monotonic - self.samples[0]["monotonic"]
            > self.sample_window_seconds
        ):
            self.samples.popleft()

    def _offset_stats(self) -> dict[str, Optional[float]]:
        offsets = [
            sample["offset_seconds"]
            for sample in self.samples
            if sample.get("offset_seconds") is not None
        ]
        if not offsets:
            return {
                "latest_seconds": None,
                "mean_seconds": None,
                "jitter_seconds": None,
                "min_seconds": None,
                "max_seconds": None,
            }
        latest = offsets[-1]
        min_offset = min(offsets)
        max_offset = max(offsets)
        return {
            "latest_seconds": latest,
            "mean_seconds": sum(offsets) / len(offsets),
            "jitter_seconds": max_offset - min_offset,
            "min_seconds": min_offset,
            "max_seconds": max_offset,
        }

    def _extract_sample(
        self, gps_content: Any
    ) -> tuple[Optional[datetime.datetime], Optional[int], str, bool]:
        if isinstance(gps_content, datetime.datetime):
            return _utc_datetime(gps_content), None, "GPS", True
        if not isinstance(gps_content, dict):
            return None, None, "unknown", False

        gps_dt = gps_content.get("time")
        if not isinstance(gps_dt, datetime.datetime):
            return None, None, str(gps_content.get("source", "unknown")), False

        tacc = gps_content.get("tAcc")
        if tacc is not None:
            tacc = _as_int(tacc, -1)
        return (
            _utc_datetime(gps_dt),
            tacc,
            str(gps_content.get("source", "GPS")),
            _as_bool(gps_content.get("valid", True), True),
        )

    def observe_time(self, gps_content: Any, reference_dt: Any = None) -> None:
        if not self.time_sync_enabled or not self.enabled:
            return

        now_monotonic = self.monotonic_fn()
        gps_dt, tacc_ns, source, valid = self._extract_sample(gps_content)
        if gps_dt is None:
            changed = self._set_gps_state(
                "invalid_sample", "GPS time sample missing time"
            )
            changed = self._evaluate_state() or changed
            self.write_status(force=changed)
            return

        ref_dt = None
        offset_seconds = None
        if isinstance(reference_dt, datetime.datetime):
            ref_dt = _utc_datetime(reference_dt)
            offset_seconds = (gps_dt - ref_dt).total_seconds()

        sample = {
            "gps_time": gps_dt.isoformat(),
            "source": source,
            "valid": valid,
            "tAcc_ns": tacc_ns,
            "reference_time": ref_dt.isoformat() if ref_dt else None,
            "offset_seconds": offset_seconds,
            "system_offset_seconds": gps_dt.timestamp() - self.time_fn(),
            "monotonic": now_monotonic,
            "received_unix": self.time_fn(),
        }
        for key in (
            "message_class",
            "lock_type",
            "mode",
            "satellites_seen",
            "satellites_used",
            "hdop",
            "pdop",
        ):
            if isinstance(gps_content, dict) and key in gps_content:
                sample[key] = gps_content[key]
        self.latest_sample = sample
        self.samples.append(sample)
        self._prune_samples(now_monotonic)

        changed = self._evaluate_state()
        changed = self._maybe_apply_sync_actions() or changed
        self.write_status(force=changed or len(self.samples) == 1)

    def _evaluate_gps_state(self) -> bool:
        if not self.enabled:
            return self._set_gps_state("disabled", "GPS time source disabled")

        if self.latest_sample is None:
            return self._set_gps_state("waiting_for_gps_time", "Waiting for GPS time")

        if self.monotonic_fn() - self.latest_sample["monotonic"] > self.stale_seconds:
            return self._set_gps_state(
                "stale",
                f"No GPS time sample for more than {self.stale_seconds:.0f}s",
            )

        if not self.latest_sample.get("valid", True):
            return self._set_gps_state(
                "low_quality",
                "GPS time candidate is present but is not valid yet",
            )

        tacc_ns = self.latest_sample.get("tAcc_ns")
        if tacc_ns is not None and tacc_ns >= 0 and tacc_ns > self.max_tacc_ns:
            return self._set_gps_state(
                "low_quality",
                f"GPS time accuracy {tacc_ns} ns exceeds {self.max_tacc_ns} ns",
            )

        stats = self._offset_stats()
        if stats["latest_seconds"] is None:
            return self._set_gps_state(
                "no_reference",
                "GPS time received before MFNavis internal time was available",
            )

        if len(self.samples) < self.min_samples:
            return self._set_gps_state(
                "collecting",
                f"Collecting GPS time samples {len(self.samples)}/{self.min_samples}",
            )

        latest_offset = abs(stats["latest_seconds"] or 0.0)
        jitter = stats["jitter_seconds"] or 0.0
        if (
            latest_offset <= self.stable_offset_seconds
            and jitter <= self.stable_jitter_seconds
        ):
            return self._set_gps_state("stable", "GPS time is stable")

        return self._set_gps_state(
            "unstable",
            "GPS time offset or jitter is outside the configured threshold",
        )

    def _gps_quality_seconds(self) -> Optional[float]:
        if self.latest_sample is None:
            return None
        tacc_ns = self.latest_sample.get("tAcc_ns")
        if isinstance(tacc_ns, (int, float)) and tacc_ns >= 0:
            return tacc_ns / 1_000_000_000.0
        jitter = self._offset_stats().get("jitter_seconds")
        if isinstance(jitter, (int, float)):
            return max(jitter, self.stable_jitter_seconds)
        return self.stable_jitter_seconds

    def _sample_time_for_now(
        self, sample: dict[str, Any], key: str
    ) -> Optional[datetime.datetime]:
        sample_time = sample.get(key)
        if not isinstance(sample_time, str) or not sample_time:
            return None
        try:
            sample_dt = _utc_datetime(datetime.datetime.fromisoformat(sample_time))
        except ValueError:
            return None

        sample_monotonic = sample.get("monotonic")
        if isinstance(sample_monotonic, (int, float)):
            age = self.monotonic_fn() - sample_monotonic
            if age > 0:
                sample_dt += datetime.timedelta(seconds=age)
        return sample_dt

    def _gps_candidate(self) -> Optional[dict[str, Any]]:
        if self.gps_state != "stable" or self.latest_sample is None:
            return None
        age = self.monotonic_fn() - self.latest_sample["monotonic"]
        if age > self.stale_seconds:
            return None
        gps_dt = self._sample_time_for_now(self.latest_sample, "gps_time")
        if gps_dt is None:
            return None
        quality_seconds = self._gps_quality_seconds()
        return {
            "source": "GPS",
            "time": gps_dt.isoformat(),
            "valid": True,
            "quality_seconds": quality_seconds,
            "age_seconds": age,
            "tAcc_ns": self.latest_sample.get("tAcc_ns"),
            "message_class": self.latest_sample.get("message_class"),
            "server": None,
        }

    def _chrony_candidate(self) -> Optional[dict[str, Any]]:
        if self.chrony_state != "stable" or self.latest_chrony_sample is None:
            return None
        age = self.monotonic_fn() - self.latest_chrony_sample["monotonic"]
        if age > self.chrony_stale_seconds:
            return None

        quality_seconds = self.latest_chrony_sample.get("rms_offset_seconds")
        if not isinstance(quality_seconds, (int, float)):
            quality_seconds = self.latest_chrony_sample.get("root_dispersion_seconds")
        if not isinstance(quality_seconds, (int, float)):
            offset = self.latest_chrony_sample.get("system_time_offset_seconds")
            quality_seconds = abs(offset) if isinstance(offset, (int, float)) else None

        return {
            "source": "Chrony",
            "time": datetime.datetime.fromtimestamp(
                self.time_fn(), tz=pytz.UTC
            ).isoformat(),
            "valid": True,
            "quality_seconds": quality_seconds,
            "age_seconds": age,
            "reference_id": self.latest_chrony_sample.get("reference_id"),
            "reference_name": self.latest_chrony_sample.get("reference_name"),
            "stratum": self.latest_chrony_sample.get("stratum"),
            "leap_status": self.latest_chrony_sample.get("leap_status"),
        }

    def _evaluate_selected_source(self) -> bool:
        # chronyd manages the system clock and already selects the most
        # accurate of its sources (NTP / GPS refclock); the monitor only
        # mirrors that choice.
        candidate = self._chrony_candidate() if self.chrony_enabled else None
        if candidate is not None:
            changed = candidate != self.selected_source
            self.selected_source = candidate
            changed = (
                self._set_state("stable", "Selected Chrony time source") or changed
            )
            return changed

        previous_selected = self.selected_source
        self.selected_source = None
        changed = previous_selected is not None

        if self.chrony_enabled and self.chrony_state not in (
            "disabled",
            "waiting_for_chrony",
        ):
            return self._set_state(self.chrony_state, self.chrony_message) or changed
        if self.enabled and self.gps_state not in ("disabled", "waiting_for_gps_time"):
            return self._set_state(self.gps_state, self.gps_message) or changed
        if self.chrony_enabled:
            return self._set_state(self.chrony_state, self.chrony_message) or changed
        if self.enabled:
            return self._set_state(self.gps_state, self.gps_message) or changed
        return self._set_state("disabled", "Time sync has no enabled source") or changed

    def _evaluate_state(self) -> bool:
        if not self.time_sync_enabled:
            self.selected_source = None
            self._set_gps_state("disabled", "GPS time source disabled")
            self._set_chrony_state("disabled", "chronyd time source disabled")
            return self._set_state("disabled", "Time sync disabled")

        changed = self._evaluate_gps_state()
        changed = self._evaluate_selected_source() or changed
        return changed

    def _set_rtc_sync_state(self, state: str, message: str) -> bool:
        changed = state != self.rtc_sync_state or message != self.rtc_sync_message
        self.rtc_sync_state = state
        self.rtc_sync_message = message
        return changed

    def _selected_datetime(self) -> Optional[datetime.datetime]:
        if not self.selected_source:
            return None
        selected_time = self.selected_source.get("time")
        if not isinstance(selected_time, str) or not selected_time:
            return None
        try:
            return _utc_datetime(datetime.datetime.fromisoformat(selected_time))
        except ValueError:
            return None

    def _apply_chrony_result(self, result: dict[str, Any]) -> bool:
        now_monotonic = self.monotonic_fn()
        sample = {
            "valid": False,
            "state": result.get("state", "unavailable"),
            "message": result.get("message", "chronyd status unavailable"),
            "monotonic": now_monotonic,
            "received_unix": result.get("received_unix", self.time_fn()),
        }
        sample.update(
            {
                key: result.get(key)
                for key in (
                    "reference_id",
                    "reference_name",
                    "stratum",
                    "ref_time_utc",
                    "system_time_offset_seconds",
                    "last_offset_seconds",
                    "rms_offset_seconds",
                    "root_delay_seconds",
                    "root_dispersion_seconds",
                    "skew_ppm",
                    "leap_status",
                )
            }
        )

        if not result.get("ok", True):
            self.latest_chrony_sample = sample
            return self._set_chrony_state(
                str(result.get("state") or "unavailable"),
                str(result.get("message") or "chronyd status unavailable"),
            )

        sample["valid"] = result.get("state") == "stable"
        self.latest_chrony_sample = sample
        if sample["valid"] and read_clock_trust_marker(self.clock_trust_file) is None:
            # First synchronized clock this boot -> arm the trust gate (A4).
            write_clock_trust_marker("chrony", marker_file=self.clock_trust_file)
        return self._set_chrony_state(
            str(result.get("state") or "stable"),
            str(result.get("message") or "chronyd is tracking a time source"),
        )

    def _poll_chrony(self, now_monotonic: float) -> bool:
        if not self.time_sync_enabled or not self.chrony_enabled:
            return self._set_chrony_state("disabled", "chronyd time source disabled")

        changed = False
        if (
            self.latest_chrony_sample is not None
            and now_monotonic - self.latest_chrony_sample["monotonic"]
            > self.chrony_stale_seconds
        ):
            changed = self._set_chrony_state("stale", "chronyd sample is stale")

        due = (
            self.last_chrony_poll_monotonic is None
            or now_monotonic - self.last_chrony_poll_monotonic
            >= self.chrony_poll_interval_seconds
        )
        if not due:
            return changed

        self.last_chrony_poll_monotonic = now_monotonic
        result = self.chrony_client.query(self.chrony_timeout_seconds)
        return self._apply_chrony_result(result) or changed

    def _sync_block_reason(self) -> Optional[tuple[str, str]]:
        if not self.time_sync_enabled:
            return "disabled", "Time sync disabled"
        if self.selected_source is None:
            return "waiting_for_time_source", "Waiting for a stable time source"
        if self.state != "stable":
            return (
                "waiting_for_time_source",
                f"Waiting for stable time source; current state is {self.state}",
            )
        if self._selected_datetime() is None:
            return "waiting_for_time_source", "Selected time could not be parsed"
        return None

    def _cooldown_active(
        self, last_monotonic: Optional[float], min_interval_seconds: float
    ) -> bool:
        if last_monotonic is None:
            return False
        return self.monotonic_fn() - last_monotonic < min_interval_seconds

    def _rtc_request_action(self) -> tuple[bool, Optional[dict[str, Any]]]:
        if not self.rtc_sync_enabled:
            changed = self._set_rtc_sync_state("disabled", "RTC sync disabled")
            return changed, None

        if self._cooldown_active(
            self.last_rtc_request_monotonic, self.rtc_sync_min_interval_seconds
        ):
            changed = self._set_rtc_sync_state(
                "cooldown", "Waiting before the next RTC sync request"
            )
            return changed, None

        return False, {
            "enabled": True,
            "min_interval_seconds": self.rtc_sync_min_interval_seconds,
        }

    def _request_id(self, actions: dict[str, Any]) -> str:
        action_names = "-".join(sorted(actions))
        return f"{int(self.monotonic_fn() * 1000)}-{action_names}"

    def _write_sync_request(
        self,
        sync_dt: datetime.datetime,
        actions: dict[str, Any],
    ) -> bool:
        latest = self.latest_sample or {}
        selected = self.selected_source or {}
        payload = {
            "version": 1,
            "request_id": self._request_id(actions),
            "created_monotonic": self.monotonic_fn(),
            "created_unix": self.time_fn(),
            "sync_time": sync_dt.isoformat(),
            "gps_time": sync_dt.isoformat(),
            "monitor_state": self.state,
            "status_file": str(self.status_file),
            "helper_status_file": str(self.helper_status_file),
            "actions": actions,
            "selected": {
                "source": selected.get("source"),
                "time": selected.get("time"),
                "valid": selected.get("valid"),
                "quality_seconds": selected.get("quality_seconds"),
                "tAcc_ns": selected.get("tAcc_ns"),
                "reference_id": selected.get("reference_id"),
                "reference_name": selected.get("reference_name"),
            },
            "latest": {
                "source": latest.get("source"),
                "valid": latest.get("valid"),
                "tAcc_ns": latest.get("tAcc_ns"),
                "message_class": latest.get("message_class"),
            },
            "sources": {
                "chrony": self._chrony_candidate(),
                "gps": self._gps_candidate(),
            },
            "samples": {
                "count": len(self.samples),
                "min_required": self.min_samples,
            },
        }
        result = self.request_writer.write_request(payload)
        if not result.get("ok"):
            message = str(result.get("message") or "Could not write sync request")
            return self._set_rtc_sync_state("request_error", message)

        now_monotonic = self.monotonic_fn()
        sync_time = sync_dt.isoformat()
        message = str(result.get("message") or "Sync request written")
        changed = False
        if "rtc" in actions:
            self.rtc_request_count += 1
            self.last_rtc_request_monotonic = now_monotonic
            self.last_rtc_request_utc = sync_time
            changed = self._set_rtc_sync_state(
                "requested", "RTC sync requested for privileged helper"
            )
        logger.info("Time sync helper request written: %s", message)
        return changed

    def _clear_sync_request(self) -> None:
        self.request_writer.clear_request()

    def _refresh_action_wait_states(self) -> bool:
        changed = False
        block_reason = self._sync_block_reason()
        if block_reason is not None:
            block_state, block_message = block_reason
            if self.rtc_sync_enabled:
                changed = (
                    self._set_rtc_sync_state(block_state, block_message) or changed
                )
            else:
                changed = (
                    self._set_rtc_sync_state("disabled", "RTC sync disabled") or changed
                )
        return changed

    def _maybe_apply_sync_actions(self) -> bool:
        block_changed = self._refresh_action_wait_states()
        if self._sync_block_reason() is not None:
            self._clear_sync_request()
            return block_changed

        sync_dt = self._selected_datetime()
        if sync_dt is None:
            return block_changed

        changed, rtc_action = self._rtc_request_action()
        changed = changed or block_changed

        if rtc_action is not None:
            changed = self._write_sync_request(sync_dt, {"rtc": rtc_action}) or changed
        return changed

    # poll() is called from the UI main loop, which runs at the display
    # frame rate (~30 Hz). Everything here works on ~1 Hz signals (GPS
    # samples, chrony state), so re-evaluating per frame only burns CPU
    # in the busiest process -- profiling put this among the UI loop's
    # top spots (2026-07-29). Event-driven entry points (observe_time,
    # note_reset, update_config) are NOT throttled.
    POLL_MIN_INTERVAL_S = 1.0

    def poll(self) -> None:
        if not self._active():
            return

        now_monotonic = self.monotonic_fn()
        last_poll = getattr(self, "_last_poll_monotonic", None)
        if last_poll is not None and now_monotonic - last_poll < (
            self.POLL_MIN_INTERVAL_S
        ):
            return
        self._last_poll_monotonic = now_monotonic
        chrony_changed = self._poll_chrony(now_monotonic)
        changed = False

        if self.enabled:
            if self.latest_sample is None:
                changed = (
                    self._set_gps_state("waiting_for_gps_time", "Waiting for GPS time")
                    or changed
                )
            elif now_monotonic - self.latest_sample["monotonic"] > self.stale_seconds:
                changed = self._set_gps_state(
                    "stale",
                    f"No GPS time sample for more than {self.stale_seconds:.0f}s",
                )

        changed = self._evaluate_state() or changed or chrony_changed
        changed = self._maybe_apply_sync_actions() or changed
        self.write_status(force=changed)

    def note_reset(self) -> None:
        if not self._active():
            return
        self.samples.clear()
        self.latest_sample = None
        changed = self._set_gps_state("waiting_for_gps_time", "MFNavis datetime reset")
        changed = self._evaluate_state() or changed
        changed = self._refresh_action_wait_states() or changed
        self.write_status(force=changed)

    def _read_helper_status(self) -> Optional[dict[str, Any]]:
        try:
            with open(self.helper_status_file, "r", encoding="utf-8") as helper_in:
                payload = json.load(helper_in)
        except FileNotFoundError:
            return None
        except Exception:
            logger.exception("Could not read time sync helper status")
            return {"state": "read_error"}
        return payload if isinstance(payload, dict) else {"state": "invalid_status"}

    def status_payload(self) -> dict[str, Any]:
        stats = self._offset_stats()
        latest = self.latest_sample or {}
        chrony_latest = self.latest_chrony_sample or {}
        age = None
        if latest.get("monotonic") is not None:
            age = self.monotonic_fn() - latest["monotonic"]
        chrony_age = None
        if chrony_latest.get("monotonic") is not None:
            chrony_age = self.monotonic_fn() - chrony_latest["monotonic"]

        return {
            "enabled": self.time_sync_enabled,
            "time_sync_enabled": self.time_sync_enabled,
            "state": self.state,
            "message": self.message,
            "updated_unix": self.time_fn(),
            "clock_manager": "chrony",
            "clock_trusted": read_clock_trust_marker(self.clock_trust_file) is not None,
            "selected": self.selected_source,
            "gps_time_sync_enabled": self.enabled,
            "gps_time_sync_state": self.gps_state,
            "gps_time_sync_message": self.gps_message,
            "chrony_time_sync_enabled": self.chrony_enabled,
            "chrony_time_sync_state": self.chrony_state,
            "chrony_time_sync_message": self.chrony_message,
            "rtc_sync_enabled": self.rtc_sync_enabled,
            "rtc_sync_state": self.rtc_sync_state,
            "samples": {
                "count": len(self.samples),
                "min_required": self.min_samples,
                "window_seconds": self.sample_window_seconds,
                "stale_seconds": self.stale_seconds,
            },
            "latest": {
                "gps_time": latest.get("gps_time"),
                "source": latest.get("source"),
                "valid": latest.get("valid"),
                "tAcc_ns": latest.get("tAcc_ns"),
                "message_class": latest.get("message_class"),
                "lock_type": latest.get("lock_type"),
                "mode": latest.get("mode"),
                "satellites_seen": latest.get("satellites_seen"),
                "satellites_used": latest.get("satellites_used"),
                "hdop": latest.get("hdop"),
                "pdop": latest.get("pdop"),
                "reference_time": latest.get("reference_time"),
                "offset_seconds": latest.get("offset_seconds"),
                "system_offset_seconds": latest.get("system_offset_seconds"),
                "age_seconds": age,
            },
            "chrony": {
                "enabled": self.chrony_enabled,
                "state": self.chrony_state,
                "message": self.chrony_message,
                "reference_id": chrony_latest.get("reference_id"),
                "reference_name": chrony_latest.get("reference_name"),
                "stratum": chrony_latest.get("stratum"),
                "ref_time_utc": chrony_latest.get("ref_time_utc"),
                "leap_status": chrony_latest.get("leap_status"),
                "system_time_offset_seconds": chrony_latest.get(
                    "system_time_offset_seconds"
                ),
                "last_offset_seconds": chrony_latest.get("last_offset_seconds"),
                "rms_offset_seconds": chrony_latest.get("rms_offset_seconds"),
                "root_delay_seconds": chrony_latest.get("root_delay_seconds"),
                "root_dispersion_seconds": chrony_latest.get("root_dispersion_seconds"),
                "skew_ppm": chrony_latest.get("skew_ppm"),
                "age_seconds": chrony_age,
                "poll_interval_seconds": self.chrony_poll_interval_seconds,
                "timeout_seconds": self.chrony_timeout_seconds,
                "stale_seconds": self.chrony_stale_seconds,
            },
            "sources": {
                "chrony": {
                    "enabled": self.chrony_enabled,
                    "state": self.chrony_state,
                    "message": self.chrony_message,
                    "candidate": self._chrony_candidate(),
                },
                "gps": {
                    "enabled": self.enabled,
                    "state": self.gps_state,
                    "message": self.gps_message,
                    "candidate": self._gps_candidate(),
                },
            },
            "offset": stats,
            "thresholds": {
                "max_tAcc_ns": self.max_tacc_ns,
                "stable_jitter_seconds": self.stable_jitter_seconds,
                "stable_offset_seconds": self.stable_offset_seconds,
            },
            "rtc_sync": {
                "enabled": self.rtc_sync_enabled,
                "state": self.rtc_sync_state,
                "message": self.rtc_sync_message,
                "request_count": self.rtc_request_count,
                "min_interval_seconds": self.rtc_sync_min_interval_seconds,
                "last_request_monotonic": self.last_rtc_request_monotonic,
                "last_request_utc": self.last_rtc_request_utc,
            },
            "helper": self._read_helper_status(),
        }

    def write_status(self, force: bool = False) -> None:
        if not self._active() and not force:
            return

        now_monotonic = self.monotonic_fn()
        if (
            not force
            and self.last_status_write_monotonic is not None
            and now_monotonic - self.last_status_write_monotonic
            < self.status_write_interval_seconds
        ):
            return

        try:
            utils.create_path(self.status_file.parent)
            tmp_file = self.status_file.with_name(self.status_file.name + ".tmp")
            with open(tmp_file, "w", encoding="utf-8") as status_out:
                json.dump(self.status_payload(), status_out, indent=2, sort_keys=True)
            tmp_file.replace(self.status_file)
            self.last_status_write_monotonic = now_monotonic
        except Exception:
            logger.exception("Could not write time sync status")
