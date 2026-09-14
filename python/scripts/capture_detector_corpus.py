"""Record existing LiveCam RAW output without changing camera or services."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.request import urlopen

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--url", default="http://127.0.0.1")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    def get(path):
        with urlopen(args.url + path, timeout=15) as response:
            return response.read()

    def state():
        return json.loads(get("/api/camera/raw-stack/control"))

    before = state()
    settings = before["settings"]
    if settings["stack_enabled"] or settings["input_frame_source"] != "original_raw":
        raise RuntimeError("LiveCam must already expose unstacked original RAW")
    (args.output / "before.json").write_text(json.dumps(before, indent=2))
    seen = set()
    rows = []
    started = time.monotonic()
    try:
        for index in range(args.frames):
            start = time.monotonic()
            controls_before = json.loads(get("/api/camera/controls"))
            raw = get("/api/camera/raw-stack/download?format=tiff")
            frame = np.asarray(Image.open(io.BytesIO(raw)))
            controls_after = json.loads(get("/api/camera/controls"))
            snapshot = state()
            solution = json.loads(get("/api/solution"))
            suffix = f"{index + 1:03d}"
            digest = hashlib.sha256(raw).hexdigest()
            (args.output / f"raw_{suffix}.tiff").write_bytes(raw)
            for name, payload in [("controls", controls_after), ("status", solution)]:
                (args.output / f"{name}_{suffix}.json").write_text(json.dumps(payload))
            row = {
                "file": f"raw_{suffix}.tiff",
                "sha256": digest,
                "duplicate": digest in seen,
                "wall_timestamp": time.time(),
                "elapsed_s": time.monotonic() - started,
                "shape": list(frame.shape),
                "dtype": str(frame.dtype),
                "min": int(frame.min()),
                "max": int(frame.max()),
                "p50": float(np.median(frame)),
                "controls_before": controls_before,
                "controls_after": controls_after,
                "raw_status_after": snapshot,
                "metadata_note": "API snapshots bracket download; not atomically tied to TIFF exposure",
            }
            seen.add(digest)
            rows.append(row)
            with (args.output / "manifest.jsonl").open("a") as stream:
                stream.write(json.dumps(row) + "\n")
            if (index + 1) % 15 == 0:
                print(f"captured {index + 1}, unique {len(seen)}", flush=True)
            time.sleep(max(0.0, args.interval - (time.monotonic() - start)))
    finally:
        after = state()
        (args.output / "after.json").write_text(json.dumps(after, indent=2))
        summary = {
            "frames": len(rows),
            "unique_frames": len(seen),
            "elapsed_s": time.monotonic() - started,
            "settings_unchanged": before["settings"] == after["settings"],
            "conditions": "User: fixed instrument, no mount, some light pollution and lights",
            "capture": "Read-only HTTP GET; no camera controls or service writes",
        }
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
