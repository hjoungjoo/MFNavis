#!/usr/bin/env python3
"""Test the connected IMX678 through MFNavis; stop the app before running.

Run with the runtime venv and an external timeout (e.g. timeout 120s).
Writes RAW, preview and metadata to --output; never changes app configuration.
"""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import PiFinder.i18n  # noqa: E402, F401
from PiFinder.camera_pi import CameraPI  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "cycles": []}
    try:
        # Closing and reopening exercises runtime power-down and restart.
        for cycle in range(3):
            camera = CameraPI(20_000)
            try:
                if not camera.camera_type.startswith("imx678"):
                    raise RuntimeError(f"Expected IMX678, got {camera.camera_type}")
                result = {
                    "camera_type": camera.camera_type,
                    "raw_configuration": str(
                        camera.camera.camera_configuration()["raw"]
                    ),
                    "frames": [],
                }
                report["cycles"].append(result)
                last_timestamp = None
                for exposure, gain in ((20_000, 1), (100_000, 2), (400_000, 4)):
                    camera.set_camera_config(exposure, gain)
                    for frame in range(12):
                        request = camera.camera.capture_request()
                        try:
                            raw = camera._raw_array(request)
                            metadata = request.get_metadata()
                        finally:
                            request.release()
                        if raw.shape != (2180, 3856) or raw.dtype != np.uint16:
                            raise RuntimeError(f"Invalid RAW: {raw.shape}, {raw.dtype}")
                        if int(raw.max()) > 4095:
                            raise RuntimeError("RAW exceeds 12-bit range")
                        timestamp = int(metadata["SensorTimestamp"])
                        if last_timestamp is not None and timestamp <= last_timestamp:
                            raise RuntimeError("Sensor timestamps did not advance")
                        last_timestamp = timestamp
                        if frame < 8:
                            continue  # Allow delayed sensor controls to settle.
                        actual_exp = metadata["ExposureTime"]
                        actual_gain = metadata["AnalogueGain"]
                        if abs(actual_exp - exposure) > max(1000, exposure * 0.05):
                            raise RuntimeError(
                                f"Exposure mismatch: {actual_exp} vs {exposure}"
                            )
                        if abs(actual_gain - gain) > gain * 0.1:
                            raise RuntimeError(
                                f"Gain mismatch: {actual_gain} vs {gain}"
                            )
                        result["frames"].append(
                            {
                                "requested_exposure_us": exposure,
                                "requested_gain": gain,
                                "exposure_us": actual_exp,
                                "gain": actual_gain,
                                "timestamp_ns": timestamp,
                                "min": int(raw.min()),
                                "max": int(raw.max()),
                                "mean": float(raw.mean()),
                                "std": float(raw.std()),
                            }
                        )
                    if cycle == 0:
                        np.save(args.output / f"raw-{exposure}us.npy", raw)
                preview = camera.capture()
                if preview.size != (512, 512):
                    raise RuntimeError(f"Invalid MFNavis preview size: {preview.size}")
                preview.save(args.output / f"preview-cycle-{cycle}.png")
                result["diagnostics"] = camera.last_capture_diagnostics
            finally:
                camera.stop_camera()
                camera.camera.close()
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        (args.output / "capture-report.json").write_text(
            json.dumps(report, indent=2, default=str) + "\n"
        )
    print("PASS: 3 power cycles, 108 RAW frames, exposure/gain and MFNavis previews")


if __name__ == "__main__":
    main()
