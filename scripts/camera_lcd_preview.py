#!/usr/bin/env python3
"""Temporary camera-to-LCD live preview for PiFinder hardware.

This script owns both the Pi camera and the OLED/LCD directly, so stop the
PiFinder service before running it. It treats the IMX462 raw stream as mono,
averaging each nominal RGGB 2x2 block and stretching contrast for display.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from PiFinder import displays  # noqa: E402
from PiFinder.sqm.camera_profiles import detect_camera_type, get_camera_profile  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuously capture camera raw frames and display them on the LCD."
    )
    parser.add_argument("--display", default="ssd1351", help="PiFinder display name")
    parser.add_argument(
        "--spi-hz",
        type=int,
        default=20_000_000,
        help="SPI clock for SSD1351 display tests",
    )
    parser.add_argument("--exposure-us", type=int, default=100, help="Manual exposure")
    parser.add_argument("--gain", type=float, default=1.0, help="Manual analogue gain")
    parser.add_argument(
        "--auto-exposure",
        action="store_true",
        help="Let libcamera choose exposure and analogue gain",
    )
    parser.add_argument("--fps", type=float, default=2.0, help="Display update limit")
    parser.add_argument("--brightness", type=int, default=255, help="Display brightness")
    parser.add_argument(
        "--denoise",
        type=float,
        default=0.70,
        help="Temporal smoothing amount for display only, 0.0-0.95",
    )
    parser.add_argument(
        "--min-contrast",
        type=float,
        default=256.0,
        help="Minimum raw contrast window before stretching to 8-bit display",
    )
    parser.add_argument(
        "--snapshot",
        default="/tmp/camera_lcd_preview_latest.png",
        help="Path to save the latest displayed frame",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Seconds to run; 0 means run until SIGTERM/Ctrl-C",
    )
    parser.add_argument(
        "--red",
        action="store_true",
        help="Render as red night-vision image instead of grayscale",
    )
    parser.add_argument(
        "--no-overlay",
        action="store_true",
        help="Do not draw FPS/exposure text overlay",
    )
    return parser.parse_args()


def _get_display(display_name: str, spi_hz: int):
    if display_name == "ssd1351":
        return displays.DisplaySSD1351(bus_speed_hz=spi_hz)
    return displays.get_display(display_name)


def _mono_from_raw(raw: np.ndarray, profile) -> np.ndarray:
    raw = profile.crop_and_rotate(raw).astype(np.float32, copy=False)
    raw = raw[: raw.shape[0] // 2 * 2, : raw.shape[1] // 2 * 2]
    return (
        raw[0::2, 0::2]
        + raw[0::2, 1::2]
        + raw[1::2, 0::2]
        + raw[1::2, 1::2]
    ) * 0.25


def _stretch_to_u8(
    mono: np.ndarray,
    state: dict[str, float],
    min_contrast: float,
) -> np.ndarray:
    lo = float(np.percentile(mono, 1.0))
    hi = float(np.percentile(mono, 99.5))
    min_contrast = max(1.0, float(min_contrast))
    if hi < lo + min_contrast:
        mid = (lo + hi) * 0.5
        lo = mid - min_contrast * 0.5
        hi = mid + min_contrast * 0.5

    if "lo" not in state:
        state["lo"] = lo
        state["hi"] = hi
    else:
        alpha = 0.2
        state["lo"] = alpha * lo + (1.0 - alpha) * state["lo"]
        state["hi"] = alpha * hi + (1.0 - alpha) * state["hi"]

    lo = state["lo"]
    hi = max(state["hi"], lo + min_contrast)
    stretched = (mono - lo) * (255.0 / (hi - lo))
    return np.clip(stretched, 0, 255).astype(np.uint8)


def _frame_to_display(
    frame_u8: np.ndarray,
    resolution: tuple[int, int],
    red: bool,
    overlay: str | None,
) -> Image.Image:
    image = Image.fromarray(frame_u8, mode="L").resize(resolution)
    if red:
        rgb = Image.merge("RGB", (image, Image.new("L", resolution, 0), Image.new("L", resolution, 0)))
    else:
        rgb = image.convert("RGB")

    if overlay:
        draw = ImageDraw.Draw(rgb)
        draw.rectangle((0, 0, resolution[0], 12), fill=(0, 0, 0))
        draw.text((2, 1), overlay, fill=(255, 0, 0) if red else (255, 255, 255))
    return rgb


def main() -> int:
    args = _parse_args()
    running = True

    def _stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    from picamera2 import Picamera2

    display = _get_display(args.display, args.spi_hz)
    display.set_brightness(args.brightness)

    camera = Picamera2()
    camera_type = detect_camera_type(camera.camera.id)
    profile = get_camera_profile(camera_type)
    camera_config = camera.create_still_configuration(
        {"size": (512, 512)},
        raw={"size": profile.raw_size, "format": profile.format},
    )
    camera.configure(camera_config)
    controls = {"AeEnable": bool(args.auto_exposure)}
    if not args.auto_exposure:
        controls.update(
            {
                "AnalogueGain": float(args.gain),
                "ExposureTime": int(args.exposure_us),
            }
        )
    camera.set_controls(controls)
    camera.start()

    snapshot = Path(args.snapshot)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    stretch_state: dict[str, float] = {}
    min_period = 1.0 / args.fps if args.fps > 0 else 0.0
    next_frame_at = time.monotonic()
    start = time.monotonic()
    last_snapshot = 0.0
    frames = 0
    fps_clock = start
    fps = 0.0
    smooth_mono = None

    print(
        f"preview: camera={camera.camera.id} profile={camera_type} "
        f"display={args.display} resolution={display.resolution} "
        f"spi_hz={args.spi_hz} "
        f"auto_exposure={args.auto_exposure} "
        f"exposure_us={args.exposure_us} gain={args.gain}",
        flush=True,
    )

    try:
        while running:
            now = time.monotonic()
            if args.duration > 0 and now - start >= args.duration:
                break
            if now < next_frame_at:
                time.sleep(min(next_frame_at - now, 0.02))
                continue
            next_frame_at = now + min_period

            request = camera.capture_request()
            raw = request.make_array("raw").copy().view(np.uint16)
            metadata = request.get_metadata()
            request.release()

            mono = _mono_from_raw(raw, profile)
            denoise = min(max(float(args.denoise), 0.0), 0.95)
            if denoise > 0.0:
                if smooth_mono is None or smooth_mono.shape != mono.shape:
                    smooth_mono = mono.copy()
                else:
                    smooth_mono = denoise * smooth_mono + (1.0 - denoise) * mono
                mono = smooth_mono
            frame_u8 = _stretch_to_u8(mono, stretch_state, args.min_contrast)

            frames += 1
            if now - fps_clock >= 1.0:
                fps = frames / (now - fps_clock)
                fps_clock = now
                frames = 0

            overlay = None
            if not args.no_overlay:
                overlay = (
                    f"{fps:3.1f}fps "
                    f"{metadata.get('ExposureTime', args.exposure_us)}us "
                    f"g{metadata.get('AnalogueGain', args.gain):.1f}"
                )
            frame = _frame_to_display(frame_u8, display.resolution, args.red, overlay)
            display.device.display(frame.convert(display.device.mode))

            if now - last_snapshot >= 1.0:
                frame.save(snapshot)
                last_snapshot = now
    finally:
        camera.stop()
        camera.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
