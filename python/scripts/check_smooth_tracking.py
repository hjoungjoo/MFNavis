#!/usr/bin/env python3
"""Read-only indoor capability evidence. Never sends a mount property."""

import argparse
import json
import time
from pathlib import Path
from PiFinder.tracking_mount_adapter import query_properties
from PiFinder.tracking_contracts import TrackingProfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=7624)
    parser.add_argument("--device", required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "read_only": True,
        "wall_time": time.time(),
        "device": args.device,
        "axis_recovery_supported": False,
        "active_verified": False,
        "verification_remaining": [
            "sensor exposure clock mapping",
            "directional optical pulse response",
            "device command/Stop bounds",
            "prediction error during optical loss",
            "physical recovery path limits",
        ],
    }
    if args.profile:
        profile = TrackingProfile.from_dict(json.loads(args.profile.read_text()))
        report["profile_id"] = profile.profile_id
        report["profile_declares_verified"] = profile.verified
    started = time.monotonic()
    report["readback"] = query_properties(args.host, args.port, args.device)
    report["query_seconds"] = time.monotonic() - started
    result = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(result + "\n")
    print(result)


if __name__ == "__main__":
    main()
