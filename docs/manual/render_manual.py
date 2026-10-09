"""Print the manual after fonts finish loading, using Chromium's local CDP.

Run with the development environment:
.venv-dev-trixie/bin/python docs/manual/render_manual.py
Dependencies: trio, trio-websocket, installed Chromium.
"""

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

import trio
from trio_websocket import open_websocket_url

HERE = Path(__file__).resolve().parent


async def render(ws_url):
    async with open_websocket_url(ws_url, max_message_size=32 * 1024 * 1024) as ws:
        sequence = 0

        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            identifier = sequence
            await ws.send_message(
                json.dumps({"id": identifier, "method": method, "params": params or {}})
            )
            while True:
                response = json.loads(await ws.get_message())
                if response.get("id") == identifier:
                    if "error" in response:
                        raise RuntimeError(response["error"])
                    return response.get("result", {})

        await call("Page.enable")
        await call("Page.navigate", {"url": (HERE / "user_manual_ko.html").as_uri()})
        await call(
            "Runtime.evaluate",
            {
                "expression": "new Promise(resolve => { if (document.readyState === 'complete') resolve(); else window.addEventListener('load', resolve, {once:true}); }).then(() => document.fonts.ready).then(() => Promise.all([document.fonts.load('400 17px MFKo', '목차'), document.fonts.load('700 20px MFKo', '목차')])).then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))",
                "awaitPromise": True,
            },
        )
        # Repainting at a stable font state prevents missing glyphs in PDF.
        result = await call(
            "Page.printToPDF",
            {
                "printBackground": True,
                "preferCSSPageSize": True,
                "displayHeaderFooter": False,
            },
        )
        (HERE / "user_manual_ko.pdf").write_bytes(base64.b64decode(result["data"]))
        print("Printed user_manual_ko.pdf after document.fonts.ready")


def main():
    with tempfile.TemporaryDirectory(prefix="mfnavis-manual-chrome-") as profile:
        # The Language menu includes native names such as 中文. Make the
        # bundled CJK font available to Chromium's fallback font selection.
        font_config = Path(profile) / "fonts.conf"
        font_config.write_text(
            '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">'
            '<fontconfig><include>/etc/fonts/fonts.conf</include>'
            f'<dir>{HERE.parents[1] / "fonts"}</dir>'
            f'<cachedir>{Path(profile) / "font-cache"}</cachedir></fontconfig>'
        )
        browser_env = os.environ.copy()
        browser_env["FONTCONFIG_FILE"] = str(font_config)
        browser = subprocess.Popen(
            [
                "chromium",
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--remote-debugging-port=0",
                f"--user-data-dir={profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=browser_env,
        )
        try:
            portfile = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 15
            while not portfile.exists():
                if browser.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Chromium did not start")
                time.sleep(0.1)
            port = portfile.read_text().splitlines()[0]
            with urlopen(f"http://127.0.0.1:{port}/json") as response:
                pages = json.load(response)
            page = next(p for p in pages if p["type"] == "page")
            trio.run(render, page["webSocketDebuggerUrl"])
        finally:
            browser.terminate()
            browser.wait(timeout=10)


if __name__ == "__main__":
    main()
