#!/usr/bin/env python3
"""Plan/apply MFNavis device branding, preserving legacy systemd aliases.

Run --plan first. --apply requires root and backs up every replaced file. It
restarts only migrated active units and restarts hostapd if its SSID changes.
The system account, data paths, Wi-Fi secrets and connection UUIDs are preserved.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

UNITS = (
    "pifinder",
    "pifinder_splash",
    "pifinder_apsta_prepare",
    "pifinder_apsta_monitor",
    "pifinder_gps_time_sync",
)


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def unit_plan(stems=UNITS):
    items = []
    for stem in stems:
        old, new = (
            stem + ".service",
            stem.replace("pifinder", "mfnavis", 1) + ".service",
        )
        canonical = Path("/etc/systemd/system") / new
        if canonical.exists():
            continue
        candidates = [
            Path("/etc/systemd/system") / old,
            Path("/lib/systemd/system") / old,
        ]
        source = next((p for p in candidates if p.is_file()), None)
        if source is None:
            continue
        content = source.read_text()
        content = re.sub(
            r"(?m)^Description=(.*)$",
            lambda m: "Description=" + m[1].replace("PiFinder", "MFNavis"),
            content,
        )
        content = content.replace(
            "After=basic.target pifinder.service", "After=basic.target mfnavis.service"
        )
        if f"Alias={old}" not in content:
            content = content.replace("[Install]\n", f"[Install]\nAlias={old}\n")
        items.append(
            {
                "old": old,
                "new": new,
                "content": content,
                "active": run(
                    "systemctl", "is-active", "--quiet", old, check=False
                ).returncode
                == 0,
                "enabled": run(
                    "systemctl", "is-enabled", old, check=False
                ).stdout.strip()
                == "enabled",
            }
        )
    return items


def network_plan():
    if shutil.which("nmcli") is None:
        return []
    rows = run(
        "nmcli", "-t", "--escape", "no", "-f", "UUID,NAME", "connection", "show"
    ).stdout.splitlines()
    result = []
    for row in rows:
        uuid, _, name = row.partition(":")
        if name.startswith("PiFinder "):
            result.append(
                {
                    "uuid": uuid,
                    "old": name,
                    "new": "MFNavis " + name[len("PiFinder ") :],
                }
            )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--unit", action="append", choices=UNITS)
    parser.add_argument("--services-only", action="store_true")
    args = parser.parse_args()
    units = unit_plan(args.unit or UNITS)
    connections = [] if args.services_only else network_plan()
    ap = Path("/etc/hostapd/hostapd.conf")
    ap_text = ap.read_text() if ap.is_file() else ""
    ap_new = re.sub(r"(?m)^ssid=PiFinderAP$", "ssid=MFNavisAP", ap_text)
    if args.services_only:
        ap_new = ap_text
    plan = {
        "units": [{k: v for k, v in u.items() if k != "content"} for u in units],
        "network_profile_count": len(connections),
        "ssid_change": ap_new != ap_text,
        "account_and_paths": "unchanged",
    }
    print(json.dumps(plan, indent=2))
    if not args.apply or not (units or connections or ap_new != ap_text):
        return
    if os.geteuid() != 0:
        parser.error("--apply requires root")
    backup = args.backup or Path("/var/backups") / (
        "mfnavis-branding-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    saved = []

    def save(path):
        record = {"path": str(path), "exists": path.exists() or path.is_symlink()}
        if path.is_symlink():
            record["link"] = os.readlink(path)
        elif path.is_file():
            target = backup / str(path).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            record["copy"] = str(target)
        saved.append(record)

    for u in units:
        for path in (
            Path("/etc/systemd/system") / u["old"],
            Path("/etc/systemd/system") / u["new"],
        ):
            save(path)
    if ap_new != ap_text:
        save(ap)
    journal = {"files": saved, "units": plan["units"], "connections": connections}
    (backup / "journal.json").write_text(json.dumps(journal, indent=2))
    # Validate complete staged units before stopping or changing anything live.
    stage = backup / "staged"
    stage.mkdir()
    for u in units:
        (stage / u["new"]).write_text(u["content"])
    if units:
        run("systemd-analyze", "verify", *[str(stage / u["new"]) for u in units])
    try:
        for u in reversed(units):
            if u["active"]:
                run("systemctl", "stop", u["old"])
            if u["enabled"]:
                run("systemctl", "disable", u["old"])
        for u in units:
            target = Path("/etc/systemd/system") / u["new"]
            target.write_text(u["content"])
            alias = target.with_name(u["old"])
            alias.unlink(missing_ok=True)
            alias.symlink_to(u["new"])
        run("systemctl", "daemon-reload")
        for u in units:
            if u["enabled"]:
                run("systemctl", "enable", u["new"])
            if u["active"]:
                run("systemctl", "start", u["new"])
                run("systemctl", "is-active", "--quiet", u["new"])
        for row in connections:
            run(
                "nmcli",
                "connection",
                "modify",
                "uuid",
                row["uuid"],
                "connection.id",
                row["new"],
            )
        if ap_new != ap_text:
            ap.write_text(ap_new)
            if (
                run(
                    "systemctl", "is-active", "--quiet", "hostapd.service", check=False
                ).returncode
                == 0
            ):
                run("systemctl", "restart", "hostapd.service")
        (backup / "complete").touch()
    except Exception:
        # Restore aliases, service enablement and network names on partial failure.
        for u in units:
            run("systemctl", "stop", u["new"], check=False)
            run("systemctl", "disable", u["new"], check=False)
        for row in reversed(saved):
            path = Path(row["path"])
            if path.is_symlink() or path.is_file():
                path.unlink()
            if "link" in row:
                path.symlink_to(row["link"])
            elif "copy" in row:
                shutil.copy2(row["copy"], path)
        run("systemctl", "daemon-reload", check=False)
        for u in units:
            if u["enabled"]:
                run("systemctl", "enable", u["old"], check=False)
            if u["active"]:
                run("systemctl", "start", u["old"], check=False)
        for row in connections:
            run(
                "nmcli",
                "connection",
                "modify",
                "uuid",
                row["uuid"],
                "connection.id",
                row["old"],
                check=False,
            )
        if ap_new != ap_text:
            run("systemctl", "restart", "hostapd.service", check=False)
        raise
    print(f"MFNavis branding applied; rollback files: {backup}")


if __name__ == "__main__":
    main()
