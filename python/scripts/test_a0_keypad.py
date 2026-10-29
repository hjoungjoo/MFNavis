#!/usr/bin/env python3
"""Observe A0 matrix events without dispatching any application/mount action.

Stop mfnavis.service before running; restart it afterward. This diagnostic
does not change settings, FRAM, LED/reset pins, or service configuration.
"""

import argparse
import json
import queue
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.seconds <= 600:
        parser.error("--seconds must be between 0 and 600")
    status = subprocess.run(
        ["systemctl", "is-active", "mfnavis.service"], capture_output=True, text=True
    )
    if status.stdout.strip() not in {"inactive", "failed"}:
        parser.error("Stop mfnavis.service before opening its GPIO matrix")

    from PiFinder.board_config import A0_MODE
    from PiFinder.keyboard_pi import GPIO, KeyboardPi
    from PiFinder.keyboard_mapping import key_label

    keyboard = KeyboardPi(queue.Queue(), A0_MODE)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(keyboard.rows, GPIO.IN)
    GPIO.setup(keyboard.cols, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    pressed = set()
    released = set()
    started = time.monotonic()
    print(json.dumps({"status": "ready", "seconds": args.seconds}), flush=True)
    try:
        while time.monotonic() - started < args.seconds:
            now = time.monotonic()
            for event in keyboard.a0_keypad.update(keyboard._scan_matrix(), now):
                event["elapsed"] = round(now - started, 3)
                event["label"] = key_label(event["key_id"])
                if not event["repeat"]:
                    (pressed if event["pressed"] else released).add(event["key_id"])
                print(json.dumps(event), flush=True)
            time.sleep(1 / 60)
    finally:
        GPIO.cleanup(keyboard.rows + keyboard.cols)
    print(
        json.dumps(
            {
                "status": "finished",
                "pressed": sorted(pressed),
                "released": sorted(released),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
