"""Capture the current web interface with isolated example data.

Run with the development Python environment and Chromium installed.
The temporary server accepts only explicitly listed read-only requests.
It does not contact hardware, change user settings, or run device commands.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen

from PIL import Image
import trio
from trio_websocket import open_websocket_url
from werkzeug.serving import make_server

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCREENS = (
    ("home", "/", None),
    ("remote", "/remote", None),
    ("catalogs", "/catalogs?home=1", None),
    ("indi_connection", "/indi", "#indi_mount_form"),
    ("indi_goto", "/indi", "#indi_goto_guide_form"),
    ("locations", "/locations?add_new=1", None),
    ("equipment", "/equipment", None),
    ("network", "/network", None),
    ("livecam", "/livecam", None),
    ("tools", "/tools", "#cache-download"),
)


async def capture(ws_url, origin, language, screens=SCREENS):
    destination = HERE / "assets/web" / language
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    async with open_websocket_url(ws_url, max_message_size=32 * 1024 * 1024) as ws:
        sequence = 0

        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            await ws.send_message(
                json.dumps({"id": sequence, "method": method, "params": params or {}})
            )
            while True:
                reply = json.loads(await ws.get_message())
                if reply.get("id") == sequence:
                    if "error" in reply:
                        raise RuntimeError(reply["error"])
                    return reply.get("result", {})

        async def evaluate(expression):
            value = await call(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "awaitPromise": True},
            )
            if "exceptionDetails" in value:
                raise RuntimeError(value["exceptionDetails"])
            return value["result"].get("value")

        await call("Page.enable")
        await call(
            "Network.setCookie",
            {"name": "mfnavis_web_language", "value": language, "url": origin},
        )
        await call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1200, "height": 800, "deviceScaleFactor": 1, "mobile": False},
        )
        for name, route, selector in screens:
            await call("Page.navigate", {"url": origin + route})
            for _ in range(100):
                if await evaluate(
                    f"document.documentElement?.lang === {json.dumps(language)}"
                    ' && document.readyState === "complete"'
                ):
                    break
                await trio.sleep(0.1)
            else:
                raise RuntimeError(f"Page did not load: {language} {route}")
            await evaluate("document.fonts.ready")
            await trio.sleep(0.5)
            params = {"format": "png", "captureBeyondViewport": True}
            if selector:
                # Capture the form and its heading without changing page styles.
                clip = await evaluate(
                    "(() => { const f=document.querySelector("
                    + json.dumps(selector)
                    + "); const h=f.parentElement.querySelector('h5');"
                    "const r=f.getBoundingClientRect(), t=h.getBoundingClientRect();"
                    "return {x:r.x-12+scrollX,y:t.y-12+scrollY,"
                    "width:r.width+24,height:r.bottom-t.y+24,scale:1}; })()"
                )
                params["clip"] = clip
            else:
                await evaluate("window.scrollTo({top:0,behavior:'instant'})")
                params["captureBeyondViewport"] = False
            result = await call("Page.captureScreenshot", params)
            path = destination / f"{name}.png"
            path.write_bytes(base64.b64decode(result["data"]))
            with Image.open(path) as picture:
                dimensions = list(picture.size)
            records.append(
                {
                    "name": name,
                    "route": route,
                    "selector": selector,
                    "file": path.relative_to(HERE).as_posix(),
                    "resolution": dimensions,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
            print(f"Captured {language} web {name}", flush=True)
    manifest_path = destination / "manifest.json"
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if len(screens) != len(SCREENS) and manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        # Keep the original batch's provenance for captures not refreshed.
        for record in records:
            record["source_commit"] = source_commit
        source_commit = previous["source_commit"]
        by_name = {record["name"]: record for record in previous["captures"]}
        by_name.update({record["name"]: record for record in records})
        records = [by_name[name] for name, _, _ in SCREENS if name in by_name]
    manifest = {
        "language": language,
        "source_commit": source_commit,
        "capture_kind": "Chromium capture of production Flask templates and assets",
        "example_data": True,
        "live_hardware": False,
        "viewport": [1200, 800],
        "captures": records,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--screen", choices=[name for name, _, _ in SCREENS], action="append"
    )
    args = parser.parse_args()
    screens = tuple(
        screen for screen in SCREENS if not args.screen or screen[0] in args.screen
    )
    os.chdir(ROOT / "python")
    sys.path.insert(0, str(ROOT / "python"))
    from PiFinder import utils

    with tempfile.TemporaryDirectory(prefix="mfnavis-web-manual-") as directory:
        sandbox = Path(directory)
        runtime = sandbox / "runtime"
        runtime.mkdir()
        with ExitStack() as isolation:
            isolation.enter_context(patch.object(utils, "data_dir", sandbox))
            isolation.enter_context(patch.object(utils, "runtime_dir", runtime))
            isolation.enter_context(
                patch.object(utils, "observations_db", sandbox / "observations.db")
            )
            from PiFinder import server, sys_utils_fake

            class ExampleNetwork(sys_utils_fake.Network):
                def get_ap_name(self):
                    return "MFNavisAP"

                def get_host_name(self):
                    return "mfnavis-example"

                def wifi_mode(self):
                    return "AP"

                def local_ip(self):
                    return "10.10.10.1"

                def get_connected_ssid(self):
                    return "MFNavisAP"

            for name in (
                "get_indi_profile_drivers",
                "get_indi_profile_device_name",
                "get_indi_onstep_properties",
                "read_saved_indi_onstep_connection_config",
                "list_onstep_serial_ports",
            ):
                isolation.enter_context(
                    patch.object(server.sys_utils, name, getattr(sys_utils_fake, name))
                )
            isolation.enter_context(
                patch.object(server.sys_utils, "Network", ExampleNetwork)
            )
            cfg = server.config.Config()
            cfg.locations.locations = []
            isolation.enter_context(patch.object(cfg, "load_config", lambda: None))
            isolation.enter_context(patch.object(server.config, "Config", lambda: cfg))
            isolation.enter_context(
                patch.object(
                    server,
                    "ObservationsDatabase",
                    lambda: SimpleNamespace(get_sessions=lambda: []),
                )
            )
            state = server.MockSharedState()
            state.datetime = lambda: datetime.datetime(
                2026, 10, 9, 13, 0, tzinfo=datetime.timezone.utc
            )
            language = "ko"
            state.screen = lambda: Image.open(
                HERE / f"assets/lcd/{language}/main_menu.png"
            )
            instance = server.Server(
                shared_state=state,
                mountcontrol_queue=queue.Queue(),
                goto_guide_queue=queue.Queue(),
                camera_command_queue=queue.Queue(),
            )
            app = instance.app
            app.testing = True

            @app.before_request
            def read_only():
                from flask import abort, request, session

                routes = {route.split("?")[0] for _, route, _ in SCREENS}
                routes.update(
                    {
                        "/image",
                        "/indi/current_values",
                        "/indi/pointing_status",
                        "/indi/location_time/status",
                        "/api/camera/controls",
                        "/api/camera/raw-stack/status",
                        "/api/camera/raw-stack/image",
                        "/tools/api/cache-download",
                    }
                )
                if request.method != "GET" or not (
                    request.path in routes
                    or request.path.startswith(("/css/", "/js/", "/images/"))
                ):
                    abort(403)
                session["authenticated"] = True

            local_server = make_server("127.0.0.1", 0, app, threaded=True)
            origin = f"http://127.0.0.1:{local_server.server_port}"
            thread = threading.Thread(target=local_server.serve_forever, daemon=True)
            thread.start()
            profile = sandbox / "chromium"
            browser = subprocess.Popen(
                [
                    "chromium",
                    "--headless",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--remote-debugging-port=0",
                    f"--user-data-dir={profile}",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                portfile = profile / "DevToolsActivePort"
                deadline = time.monotonic() + 15
                while not portfile.exists():
                    if browser.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Chromium did not start")
                    time.sleep(0.1)
                port = portfile.read_text().splitlines()[0]
                with urlopen(f"http://127.0.0.1:{port}/json") as response:
                    page = next(
                        item for item in json.load(response) if item["type"] == "page"
                    )
                for language in ("ko", "en"):
                    trio.run(
                        capture, page["webSocketDebuggerUrl"], origin, language, screens
                    )
            finally:
                browser.terminate()
                browser.wait(timeout=10)
                local_server.shutdown()
                thread.join(timeout=5)
                local_server.server_close()


if __name__ == "__main__":
    main()
