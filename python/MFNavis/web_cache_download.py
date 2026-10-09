"""One resumable cache warm-up job owned by the web server.

The child process group keeps long network requests out of Flask workers and
allows stopping both the warm-up script and its image downloader. Completed
cache files survive stops and service restarts; no downloads start on import.
"""

import copy
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from flask import jsonify, request, session

from PiFinder import utils
from PiFinder.cache_progress import PROGRESS_PREFIX

logger = logging.getLogger("CacheDownload")
ACTIVE_STATES = {"running", "stopping"}


class CacheDownloadJob:
    def __init__(self, state_path=None, script=None):
        self.state_path = Path(state_path or utils.data_dir / "cache_download.json")
        self.script = Path(
            script
            or Path(__file__).resolve().parents[2] / "scripts/warm_mfnavis_caches.py"
        )
        self._lock = threading.RLock()
        self._process = None
        self._last_save = 0
        self._state = {"status": "idle", "logs": []}
        try:
            saved = json.loads(self.state_path.read_text())
            if isinstance(saved, dict):
                self._state.update(saved)
        except (OSError, ValueError):
            pass
        if self._state["status"] in ACTIVE_STATES:
            self._state["status"] = "interrupted"

    def _save(self):
        if self._state["status"] in ACTIVE_STATES and "started_at" in self._state:
            self._state["elapsed"] = max(0, time.time() - self._state["started_at"])
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=self.state_path.parent, prefix=".cache-job-"
        )
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self._state, stream)
            os.replace(temporary, self.state_path)
            self._last_save = time.monotonic()
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def snapshot(self):
        with self._lock:
            state = copy.deepcopy(self._state)
        if state["status"] in ACTIVE_STATES:
            state["elapsed"] = max(0, time.time() - state["started_at"])
        progress = state.get("progress", {})
        processed = progress.get("processed", 0)
        state["eta"] = (
            max(0, progress["total"] - progress["completed"])
            * progress.get("elapsed", 0)
            / processed
            if processed and state["status"] == "running"
            else None
        )
        try:
            state["free_bytes"] = shutil.disk_usage(utils.data_dir).free
        except OSError:
            state["free_bytes"] = None
        return state

    def start(self, options=None, resume=False):
        with self._lock:
            if self._state["status"] in ACTIVE_STATES:
                raise RuntimeError("A cache download is already running")
            if resume:
                options = self._state.get("options")
                if options is None:
                    raise ValueError("There is no cache download to resume")
            options = options or {}
            images = options.get("images", "both")
            workers = options.get("workers", 4)
            skip_runtime = options.get("skip_runtime", False)
            if images not in {"both", "poss", "none"}:
                raise ValueError("Invalid image selection")
            if type(workers) is not int or not 1 <= workers <= 10:
                raise ValueError("Workers must be between 1 and 10")
            if type(skip_runtime) is not bool:
                raise ValueError("Invalid runtime cache selection")
            args = [
                sys.executable,
                "-u",
                str(self.script),
                "--progress-json",
                "--images",
                images,
                "--workers",
                str(workers),
            ]
            if skip_runtime:
                args.append("--skip-runtime")
            self._state = {
                "status": "running",
                "stage": "preparing",
                "progress": {},
                "options": {
                    "images": images,
                    "workers": workers,
                    "skip_runtime": skip_runtime,
                },
                "started_at": time.time(),
                "elapsed": 0,
                "logs": [],
                "error": "",
            }
            try:
                self._save()
                env = os.environ.copy()
                env["MFNAVIS_PYTHON"] = sys.executable
                self._process = subprocess.Popen(
                    args,
                    cwd=self.script.parent.parent,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            except OSError as exc:
                self._state.update(status="failed", error=str(exc))
                try:
                    self._save()
                except OSError:
                    logger.exception("Could not save cache download failure")
                raise
            threading.Thread(
                target=self._monitor, args=(self._process,), daemon=True
            ).start()
            return self.snapshot()

    def _monitor(self, process):
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                with self._lock:
                    if line.startswith(PROGRESS_PREFIX):
                        try:
                            progress = json.loads(line[len(PROGRESS_PREFIX) :])
                            self._state["stage"] = progress["stage"]
                            self._state["progress"] = progress
                        except (ValueError, KeyError, TypeError):
                            logger.warning("Invalid cache download progress")
                    else:
                        self._state["logs"] = (self._state["logs"] + [line[:1000]])[
                            -20:
                        ]
                    if time.monotonic() - self._last_save >= 5:
                        self._save()
            code = process.wait()
            with self._lock:
                stopped = self._state["status"] == "stopping"
                self._state["status"] = (
                    "stopped" if stopped else "completed" if code == 0 else "failed"
                )
                self._state["elapsed"] = time.time() - self._state["started_at"]
                self._state["returncode"] = code
                self._save()
        except Exception as exc:
            logger.exception("Cache download monitor failed")
            self._signal(process, signal.SIGKILL)
            process.wait()
            with self._lock:
                self._state.update(status="failed", error=str(exc))
                try:
                    self._save()
                except OSError:
                    logger.exception("Could not save cache download status")
        finally:
            process.stdout.close()
            with self._lock:
                if self._process is process:
                    self._process = None

    @staticmethod
    def _signal(process, sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    def stop(self):
        with self._lock:
            if self._state["status"] == "running" and self._process is not None:
                self._state["status"] = "stopping"
                try:
                    self._save()
                except OSError:
                    logger.exception("Could not save cache stop request")
                self._signal(self._process, signal.SIGTERM)
                threading.Thread(
                    target=self._finish_stop, args=(self._process,), daemon=True
                ).start()
            return self.snapshot()

    def _finish_stop(self, process):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # The parent may exit before a descendant closes the progress pipe.
        # Kill any remaining members of this job's group before declaring stop.
        with self._lock:
            if self._process is process:
                self._signal(process, signal.SIGKILL)


def register_cache_download_routes(app, job=None):
    job = job or CacheDownloadJob()
    app.extensions["cache_download_job"] = job

    @app.route("/tools/api/cache-download", methods=["GET", "POST"])
    def cache_download():
        if not session.get("authenticated"):
            return jsonify(error="Unauthorized"), 401
        if request.method == "GET":
            response = jsonify(job.snapshot())
            response.headers["Cache-Control"] = "no-store"
            return response
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Expected a JSON object"), 400
        try:
            action = data.get("action")
            if action == "stop":
                state = job.stop()
            elif action == "resume":
                state = job.start(resume=True)
            elif action == "start":
                state = job.start(data)
            else:
                raise ValueError("Invalid cache download action")
            return jsonify(state)
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        except OSError:
            logger.exception("Could not start cache download")
            return jsonify(error="Could not start cache download"), 500
