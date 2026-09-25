"""Opt-in field evidence capture, independent of solving policy.

The solver and integrator each own a bounded writer. Only explicit requests
enable recording; no camera, exposure, scheduling or mount setting is changed.
NPZ files contain numeric arrays only and can be read with allow_pickle=False.
"""

from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
from enum import Enum
import fcntl
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid

import numpy as np

from PiFinder import utils
from PiFinder.observation import observation_snapshot

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1
CONTROL_NAME = "solver_capture_request.json"
STAGES = (
    "baseline",
    "candidate_gate",
    "frame_reuse",
    "lazy_sep",
    "path_budget",
    "mode_policy",
    "async_worker",
    "temporal_state",
    "validation",
)
SCENES = ("dark_sky", "light_pollution", "local_lamp", "cloud", "transition", "indoor")


def json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Enum):
        return json_value(value.value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if all(hasattr(value, name) for name in ("w", "x", "y", "z")):
        return {name: float(getattr(value, name)) for name in ("w", "x", "y", "z")}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, np.ndarray):
        return json_value(value.tolist())
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return str(value)


def _read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(json_value(value), ensure_ascii=False, allow_nan=False)
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


def _active(request):
    try:
        return bool(
            request.get("active")
            and request.get("boot_id") == _boot_id()
            and time.monotonic() < float(request.get("deadline_monotonic", 0))
        )
    except (TypeError, ValueError):
        return False


def capture_status(runtime=None):
    runtime = Path(runtime or utils.runtime_dir)
    request = _read(runtime / CONTROL_NAME)
    return {
        "request": request,
        "requested_active": _active(request),
        "solver": _read(runtime / "solver_capture_solver_status.json"),
        "integrator": _read(runtime / "solver_capture_integrator_status.json"),
    }


def request_capture(action, options=None, *, runtime=None):
    """Atomic control shared by the CLI and authenticated web routes."""
    runtime = Path(runtime or utils.runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    options = options or {}
    with (runtime / "solver_capture.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = _read(runtime / CONTROL_NAME)
        if action == "start":
            if _active(request):
                raise ValueError("A capture is already requested; stop it first")
            for role in ("solver", "integrator"):
                status = _read(runtime / f"solver_capture_{role}_status.json")
                if (
                    status.get("state") in {"recording", "draining"}
                    and time.time() - status.get("updated", 0) < 10
                ):
                    raise ValueError("Previous capture is still draining")
            duration = float(options.get("duration", 60))
            raw_every = float(options.get("raw_every", 0))
            max_frames = int(options.get("max_frames", 120))
            max_mib = int(options.get("max_mib", 512))
            if not math.isfinite(duration) or not 1 <= duration <= 3600:
                raise ValueError("duration must be 1..3600 seconds")
            if not math.isfinite(raw_every) or not 0 <= raw_every <= 60:
                raise ValueError("raw_every must be 0..60 seconds")
            if not 1 <= max_frames <= 10000 or not 16 <= max_mib <= 8192:
                raise ValueError(
                    "max_frames must be 1..10000; max_mib must be 16..8192"
                )
            mode = options.get("mode", "raw")
            if mode not in {"raw", "telemetry"}:
                raise ValueError("mode must be raw or telemetry")
            request = {
                "schema_version": SCHEMA_VERSION,
                "session_id": uuid.uuid4().hex,
                "active": True,
                "boot_id": _boot_id(),
                "requested_at": time.time(),
                "deadline_monotonic": time.monotonic() + duration,
                "duration": duration,
                "raw_every": raw_every,
                "max_frames": max_frames,
                "max_mib": max_mib,
                "mode": mode,
            }
        elif action not in {"mark", "stop"}:
            raise ValueError("Unknown capture action")
        elif not request.get("session_id"):
            raise ValueError("No capture session")
        if action in {"start", "mark"}:
            if action == "mark" and not _active(request):
                raise ValueError("No active capture to mark")
            stage = options.get("stage", request.get("stage", "baseline"))
            scene = options.get("scene", request.get("scene", "dark_sky"))
            note = options.get("note", request.get("note", ""))
            if stage not in STAGES or scene not in SCENES:
                raise ValueError("Unknown stage or scene")
            if not isinstance(note, str) or len(note) > 500:
                raise ValueError("note must be text, at most 500 characters")
            request.update(stage=stage, scene=scene, note=note)
        if action == "stop":
            request["active"] = False
        request["revision"] = uuid.uuid4().hex
        request["updated"] = time.time()
        _atomic_json(runtime / CONTROL_NAME, request)
    return capture_status(runtime)


def _environment(cfg, source_directory=None):
    from PiFinder.runtime_provenance import detector_provenance

    keys = set(getattr(cfg, "_default_config_dict", {})) | set(
        getattr(cfg, "_config_dict", {})
    )
    selected = {
        key: cfg.get_option(key)
        for key in keys
        if key.startswith(("camera_", "solver_", "livecam_"))
        or key
        in {"target_pixel", "screen_direction", "wide_solver_calibration_store_v1"}
    }
    hashes = {}
    for name in (
        "solver.py",
        "solver_scheduling.py",
        "solver_capture.py",
        "observation.py",
        "detector_profiles.py",
        "star_detect.py",
        "sep_shadow.py",
        "mf_star_only_preprocess.py",
        "solve_acceptance.py",
        "preprocess_bias.py",
        "latest_frame_worker.py",
        "mf_detect_process.py",
        "runtime_provenance.py",
        "tetra3/tetra3/tetra3.py",
        "auto_exposure_framewise.py",
        "camera_pi.py",
        "camera_interface.py",
        "integrator.py",
    ):
        path = Path(__file__).parent / name
        content = path.read_bytes()
        archive_name = name.replace("/", "__")
        hashes[archive_name] = hashlib.sha256(content).hexdigest()
        if source_directory is not None:
            source_directory.mkdir(parents=True, exist_ok=True)
            destination = source_directory / archive_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=utils.pifinder_dir,
            timeout=3,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        revision = None
    return {
        "settings": selected,
        "detector_environment": {
            key: value
            for key, value in os.environ.items()
            if key.startswith(
                (
                    "MF_DETECT_",
                    "PIFINDER_DETECTOR",
                    "PIFINDER_TEST_PROFILE",
                    "MFNAVIS_PREPROCESS_MODE",
                    "TETRA3_SEARCH_OPTIMIZED",
                )
            )
        },
        "git_head": revision,
        "detector_runtime": detector_provenance(),
        "source_sha256": hashes,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "pid": os.getpid(),
        "boot_id": _boot_id(),
        "source_note": "Files on disk at capture start; restart after code changes before comparing.",
    }


class _Writer:
    def __init__(self, request, role, runtime, root, cfg):
        self.request = dict(request)
        self.role, self.runtime, self.cfg = role, runtime, cfg
        self.path = root / request["session_id"]
        self.items: queue.Queue = queue.Queue(maxsize=2 if role == "solver" else 32)
        self.stop = threading.Event()
        self.count = self.dropped = self.bytes = self.raw_count = 0
        self.reason = "stopped"
        self.state = "recording"
        self.thread = threading.Thread(
            target=self.run, name=f"capture-{role}", daemon=True
        )
        self.thread.start()

    def status(self):
        return {
            "session_id": self.request["session_id"],
            "state": self.state,
            "reason": self.reason,
            "updated": time.time(),
            "directory": str(self.path),
            "records": self.count,
            "raw_frames": self.raw_count,
            "dropped_records": self.dropped,
            "bytes_written": self.bytes,
            "pending": self.items.qsize(),
        }

    def run(self):
        try:
            self.path.mkdir(parents=True, exist_ok=True)
            if self.role == "solver":
                _atomic_json(
                    self.path / "manifest.json",
                    {
                        **self.request,
                        "environment": _environment(self.cfg, self.path / "source"),
                        "frame_contract": "Only solver-consumed frames; RAW and 512 share frame_id. No pickle.",
                    },
                )
            previous_revision = None
            with (self.path / f"{self.role}.jsonl").open("x") as stream:
                while not self.stop.is_set() or not self.items.empty():
                    _atomic_json(
                        self.runtime / f"solver_capture_{self.role}_status.json",
                        self.status(),
                    )
                    try:
                        item, arrays = self.items.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    estimated = sum(array.nbytes for array in arrays.values()) + 65536
                    if self.bytes + estimated > self.request["max_mib"] * 1024**2:
                        self.reason = "size_limit"
                        self.dropped += 1
                        break
                    if shutil.disk_usage(self.path).free < estimated + 128 * 1024**2:
                        self.reason = "low_disk_space"
                        self.dropped += 1
                        break
                    if item["phase"]["revision"] != previous_revision:
                        previous_revision = item["phase"]["revision"]
                        stream.write(
                            json.dumps(
                                {"kind": "phase", **item["phase"]}, ensure_ascii=False
                            )
                            + "\n"
                        )
                    if arrays:
                        filename = f"{self.role}_{item['sequence']:06d}.npz"
                        destination = self.path / filename
                        temporary = destination.with_suffix(".part")
                        with temporary.open("wb") as output:
                            np.savez(output, **arrays)
                        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
                        size = temporary.stat().st_size
                        temporary.replace(destination)
                        item["artifact"] = {
                            "file": filename,
                            "sha256": digest,
                            "bytes": size,
                        }
                        self.bytes += size
                        self.raw_count += 1
                    line = (
                        json.dumps(
                            json_value(item), ensure_ascii=False, allow_nan=False
                        )
                        + "\n"
                    )
                    stream.write(line)
                    stream.flush()
                    self.bytes += len(line.encode())
                    self.count += 1
                    if self.count >= self.request["max_frames"]:
                        self.reason = "frame_limit"
                        break
            self.state = "complete"
        except Exception as exc:
            self.state, self.reason = "error", f"{type(exc).__name__}: {exc}"
            logger.exception("Field capture writer failed")
        finally:
            self.stop.set()
            while not self.items.empty():
                self.items.get_nowait()
                self.dropped += 1
            try:
                _atomic_json(self.path / f"{self.role}_summary.json", self.status())
                _atomic_json(
                    self.runtime / f"solver_capture_{self.role}_status.json",
                    self.status(),
                )
            except OSError:
                logger.exception("Could not save capture status")


class CaptureRecorder:
    """Cheap disabled polling; bounded asynchronous lossless writes when armed."""

    def __init__(self, role, cfg=None, *, runtime=None, root=None, shared_state=None):
        self.role, self.cfg = role, cfg
        self.shared_state = shared_state
        self.runtime = Path(runtime or utils.runtime_dir)
        self.root = Path(root or utils.data_dir / "captures" / "solver_sessions")
        self.writer = None
        self.request = {}
        self.next_poll = 0.0
        self.sequence = 0
        self.last_raw = -math.inf
        self.seen_session = None

    def poll(self):
        try:
            now = time.monotonic()
            if now < self.next_poll:
                return
            self.next_poll = now + 0.5
            request = _read(self.runtime / CONTROL_NAME)
            active = _active(request)
            if self.writer and (
                not active
                or request.get("session_id") != self.writer.request["session_id"]
            ):
                if not self.writer.stop.is_set():
                    self.writer.state = "draining"
                    self.writer.reason = (
                        "stopped" if not request.get("active") else "duration_limit"
                    )
                    self.writer.stop.set()
            if active and request.get("session_id") != self.seen_session:
                if self.writer and self.writer.thread.is_alive():
                    return
                self.seen_session = request["session_id"]
                self.sequence = 0
                self.last_raw = -math.inf
                self.writer = _Writer(
                    request, self.role, self.runtime, self.root, self.cfg
                )
            self.request = request if active else {}
        except Exception:
            logger.exception("Could not poll field capture request")

    def begin(self, metadata=None):
        """Freeze phase and frame identity at the start of an attempt."""
        self.poll()
        if not self.request or not self.writer or self.writer.stop.is_set():
            return None
        try:
            metadata = json_value(metadata or {})
        except Exception:
            logger.exception("Could not serialize capture metadata")
            self.writer.dropped += 1
            return None
        self.sequence += 1
        return {
            "kind": self.role,
            "schema_version": SCHEMA_VERSION,
            "session_id": self.request["session_id"],
            "sequence": self.sequence,
            "phase": {
                key: self.request[key]
                for key in ("revision", "stage", "scene", "note", "updated")
            },
            "metadata": metadata,
            "observation": observation_snapshot(self.shared_state)
            if self.shared_state is not None
            else None,
            "started_monotonic_ns": time.monotonic_ns(),
            "started_at": time.time(),
        }

    def finish(self, token, result, *, raw_entry=None, image=None):
        if token is None or self.writer is None:
            return
        try:
            if (
                self.writer.stop.is_set()
                or token["session_id"] != self.writer.request["session_id"]
            ):
                self.writer.dropped += 1
                return
            if self.writer.items.full():
                self.writer.dropped += 1
                return
            token["finished_monotonic_ns"] = time.monotonic_ns()
            token["finished_at"] = time.time()
            token["result"] = json_value(result)
            arrays = {}
            token["raw_status"] = "telemetry_only"
            if self.role == "solver" and self.writer.request["mode"] == "raw":
                if time.monotonic() - self.last_raw < self.writer.request["raw_every"]:
                    token["raw_status"] = "sample_interval"
                elif (
                    not raw_entry
                    or raw_entry.get("frame_id") != token["metadata"].get("frame_id")
                    or token["metadata"].get("frame_id") is None
                ):
                    token["raw_status"] = "missing_matching_raw"
                else:
                    arrays = {
                        "raw": np.array(raw_entry["frame"], copy=True),
                        "solver_512": np.array(image, copy=True),
                    }
                    if any(array.dtype.hasobject for array in arrays.values()):
                        raise ValueError("Capture accepts numeric arrays only")
                    token["raw_metadata"] = json_value(
                        {
                            key: value
                            for key, value in raw_entry.items()
                            if key != "frame"
                        }
                    )
                    token["raw_status"] = "saved"
                    self.last_raw = time.monotonic()
            token["capture_prepare_ms"] = (
                time.monotonic_ns() - token["finished_monotonic_ns"]
            ) / 1e6
            self.writer.items.put_nowait((token, arrays))
        except Exception:
            self.writer.dropped += 1
            logger.exception("Could not enqueue field capture record")

    def close(self):
        if self.writer:
            self.writer.stop.set()
            self.writer.thread.join(timeout=5)


def report_session(directory):
    """Read-only integrity and timing report; never substitutes old coordinates."""
    directory = Path(directory)
    records = {}
    errors = []
    manifest = _read(directory / "manifest.json")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("missing manifest or unsupported schema")
    for name, digest in (
        manifest.get("environment", {}).get("source_sha256", {}).items()
    ):
        if Path(name).name != name:
            errors.append("invalid source path")
            continue
        source = directory / "source" / name
        if (
            not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest() != digest
        ):
            errors.append(f"source/{name}: missing or checksum mismatch")
    for role in ("solver", "integrator"):
        items = []
        path = directory / f"{role}.jsonl"
        if path.exists():
            for number, line in enumerate(path.read_text().splitlines(), 1):
                try:
                    item = json.loads(line)
                    if item.get("kind") == role:
                        items.append(item)
                except (ValueError, AttributeError):
                    errors.append(f"{role}.jsonl:{number}: invalid/incomplete JSON")
        records[role] = items
    for item in records["solver"]:
        artifact = item.get("artifact")
        if not artifact:
            continue
        name = artifact.get("file", "")
        if not re.fullmatch(r"solver_[0-9]+\.npz", name):
            errors.append("invalid artifact path")
            continue
        path = directory / name
        if (
            not path.exists()
            or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]
        ):
            errors.append(f"{name}: missing or checksum mismatch")
    publications = {
        (item["metadata"].get("frame_id"), item["metadata"].get("exposure_end")): item
        for item in records["integrator"]
        if item["result"].get("published")
    }
    latency = []
    phases = {}
    for item in records["solver"]:
        phase_key = (
            item["phase"]["stage"],
            item["phase"]["scene"],
            item["phase"]["revision"],
        )
        phase = phases.setdefault(
            phase_key,
            {
                "phase": item["phase"],
                "records": 0,
                "accepted": 0,
                "raw_saved": 0,
                "latencies": [],
            },
        )
        phase["records"] += 1
        phase["accepted"] += bool(item["result"].get("accepted"))
        phase["raw_saved"] += "artifact" in item
        key = (item["metadata"].get("frame_id"), item["metadata"].get("exposure_end"))
        published = publications.get(key)
        start = item["result"].get("input_ready_monotonic_ns")
        if published and start and item["result"].get("accepted"):
            elapsed = (published["result"]["published_monotonic_ns"] - start) / 1e6
            if elapsed < 0:
                errors.append(f"frame {key}: negative publication delay")
            else:
                latency.append(elapsed)
                phase["latencies"].append(elapsed)
    for phase in phases.values():
        samples = phase.pop("latencies")
        phase["matched_publications"] = len(samples)
        phase["publication_delay_p95_ms"] = (
            float(np.percentile(samples, 95)) if samples else None
        )
    summaries = {role: _read(directory / f"{role}_summary.json") for role in records}
    complete = all(summary.get("state") == "complete" for summary in summaries.values())
    errors.extend(
        f"unfinished artifact: {path.name}" for path in directory.glob("*.part")
    )
    return {
        "directory": str(directory),
        "integrity_errors": errors,
        "complete": complete,
        "phases": list(phases.values()),
        "solver_records": len(records["solver"]),
        "accepted": sum(
            bool(item["result"].get("accepted")) for item in records["solver"]
        ),
        "raw_saved": sum("artifact" in item for item in records["solver"]),
        "matched_publications": len(latency),
        "input_ready_to_publication_ms": {
            "median": float(np.median(latency)) if latency else None,
            "p95": float(np.percentile(latency, 95)) if latency else None,
        },
        "summaries": summaries,
        "manifest": manifest,
        "notes": [
            "Recording overhead is included; compare telemetry and RAW baselines.",
            "Missing publications are not latency samples. RAW covers consumed, not all camera frames.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "mark"):
        command = commands.add_parser(action)
        command.add_argument(
            "--stage",
            choices=STAGES,
            default="baseline" if action == "start" else argparse.SUPPRESS,
        )
        command.add_argument(
            "--scene",
            choices=SCENES,
            default="dark_sky" if action == "start" else argparse.SUPPRESS,
        )
        command.add_argument(
            "--note", default="" if action == "start" else argparse.SUPPRESS
        )
        if action == "start":
            command.add_argument("--duration", type=float, default=60)
            command.add_argument("--mode", choices=("raw", "telemetry"), default="raw")
            command.add_argument("--raw-every", type=float, default=0)
            command.add_argument("--max-frames", type=int, default=120)
            command.add_argument("--max-mib", type=int, default=512)
    commands.add_parser("status")
    commands.add_parser("stop")
    report = commands.add_parser("report")
    report.add_argument("directory", type=Path)
    args = vars(parser.parse_args())
    action = args.pop("action")
    try:
        result = (
            capture_status()
            if action == "status"
            else report_session(args["directory"])
            if action == "report"
            else request_capture(action, args)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if action == "report" and result["integrity_errors"]:
            parser.exit(2)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
