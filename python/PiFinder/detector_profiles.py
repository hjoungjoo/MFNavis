"""Explicit test profiles shared by field switching and paired replay."""

import argparse
import json
import os

DEFAULT_PROFILE = "mf4p"
PROFILES = {
    "mf4p": ("mf", 4, 2, 1),
    "mf2": ("mf", 2, 0, 1),
    "mf1": ("mf", 1, 0, 1),
    "mf4o": ("mf", 4, 1, 1),
    "mf8p": ("mf", 8, 2, 1),
    "mf4p-pure": ("mf", 4, 2, 0),
    "sep": ("sep", 4, 2, 0),
}


def profile_environment(name=DEFAULT_PROFILE):
    backend, binning, pyramid, fallback = PROFILES[name]
    return {
        "PIFINDER_TEST_PROFILE": name,
        "PIFINDER_DETECTOR": backend,
        "MF_DETECT_BINNING": str(binning),
        "MF_DETECT_PYRAMID": str(pyramid),
        "MF_DETECT_SEP_FALLBACK": str(fallback),
        "MF_DETECT_RANKING": "response",
        "MF_DETECT_REFINE": "0",
        "MF_DETECT_SIGMA": "4.5",
        "MF_DETECT_MAX_STARS": "48",
    }


def configure_profile(name=DEFAULT_PROFILE):
    os.environ.update(profile_environment(name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", nargs="?", choices=PROFILES, default=DEFAULT_PROFILE)
    parser.add_argument("--systemd", action="store_true")
    args = parser.parse_args()
    values = profile_environment(args.name)
    if args.systemd:
        for key, value in values.items():
            print(f"Environment={key}={value}")
    else:
        print(json.dumps(values, indent=2))


if __name__ == "__main__":
    main()
