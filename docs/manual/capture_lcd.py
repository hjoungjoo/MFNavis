"""Capture unmodified MFNavis LCD framebuffers for both manual editions.

Run from the repository root with the development Python environment.
Uses the production UI classes and the 128x128 SSD1351 layout in a dummy
output device, isolated settings/databases/queues, and bundled example data.
No camera, SPI device, operating service, or connected mount is controlled.
"""

from __future__ import annotations

import argparse
import copy
import datetime
from dataclasses import replace
import gettext
import hashlib
import inspect
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "assets/lcd"
MOMENT = datetime.datetime(2026, 10, 9, 13, 0, tzinfo=datetime.timezone.utc)


def capture(language, day_frame):
    os.chdir(ROOT / "python")
    sys.path.insert(0, str(ROOT / "python"))
    import PiFinder.i18n  # noqa: F401

    gettext.translation(
        "messages",
        localedir=ROOT / "python/locale",
        languages=[language],
        fallback=True,
    ).install()
    from PiFinder import utils

    with tempfile.TemporaryDirectory(prefix="mfnavis-lcd-manual-") as directory:
        sandbox = Path(directory)
        (sandbox / "cache").mkdir()
        catalog_cache = utils.data_dir / "cache/catalogs"
        if catalog_cache.is_dir():
            shutil.copytree(catalog_cache, sandbox / "cache/catalogs")
        runtime = sandbox / "runtime"
        runtime.mkdir()
        with (
            patch.object(utils, "data_dir", sandbox),
            patch.object(utils, "observations_db", sandbox / "observations.db"),
            patch.object(utils, "runtime_dir", runtime),
            patch("time.time", return_value=MOMENT.timestamp()),
        ):
            from PiFinder.config import Config

            cfg = Config()
            for option, value in {
                "language": language,
                "mount_control": True,
                "indi_goto_method": "mfnavis",
                "camera_lens": "10mm",
                "camera_exp": 400000,
                "filter.altitude": -1,
                "filter.magnitude": None,
                "filter.observed": "Any",
            }.items():
                cfg.set_option(option, value)
            from PiFinder import cat_images

            # The illustrated views do not use downloaded survey images.
            with patch.object(cat_images, "get_display_image", return_value=None):
                capture_screens(cfg, language, runtime, day_frame)


def capture_screens(cfg, language, runtime, day_frame):
    from PiFinder.catalogs import CatalogBuilder, CatalogFilter
    from PiFinder.displays import get_display
    from PiFinder.state import Location, SharedStateObj, SQM, UIState
    from PiFinder.types.positioning import (
        Pointing,
        PointingAxis,
        PointingEstimate,
        PointingMatrix,
        SolveDiagnostics,
        SolveSource,
    )
    from PiFinder.ui import menu_structure
    from PiFinder.ui.menu_manager import MenuManager
    from PiFinder.ui.object_details import (
        DM_CAMERA,
        DM_DESC,
        DM_LOCATE,
        UIObjectDetails,
    )
    from PiFinder.ui.log import UILog
    from PiFinder.ui.operation_error import UIOperationError
    from PiFinder.ui.preview import (
        DISPLAY_IMAGE,
        DISPLAY_SINGLE,
        DISPLAY_STARS,
        DISPLAY_STATS,
    )
    from PiFinder.ui.sqm_calibration import UISQMCalibration
    from PiFinder.ui.sqm_sweep import UISQMSweep

    print(f"Preparing {language} LCD capture context", flush=True)
    state = SharedStateObj()
    state.set_ui_state(UIState())
    location = Location()
    location.lat, location.lon, location.altitude = 37.5, 127.0, 100.0
    location.lock, location.lock_type, location.source = True, 2, "Manual"
    state.set_location(location)
    state.set_datetime(MOMENT, force=True)
    direction = Pointing(RA=56.75, Dec=24.12, Roll=0.0)
    state.set_solution(
        PointingEstimate(
            pointing=PointingMatrix(
                camera=PointingAxis(solve=direction, estimate=direction),
                aligned=PointingAxis(solve=direction, estimate=direction),
            ),
            Alt=45.0,
            Az=120.0,
            solve_source=SolveSource.CAMERA,
            estimate_time=MOMENT.timestamp(),
            last_solve_success=MOMENT.timestamp(),
            constellation="Tau",
            diagnostics=SolveDiagnostics(Matches=12, RMSE=0.5, FOV=10.2),
        )
    )
    state.set_target_pixel((256, 256))
    state.set_sqm(SQM(value=21.3, source="Manual"))
    metadata = state.last_image_metadata()
    metadata.update(exposure_end=MOMENT.timestamp(), exposure_time=400000)
    state.set_last_image_metadata(metadata)
    night = Image.open(ROOT / "test_images/pleiades.png").convert("RGB")
    daylight = Image.open(day_frame).convert("RGB") if day_frame else night
    display = get_display("headless")
    commands = {
        name: queue.Queue()
        for name in (
            "camera",
            "console",
            "ui_queue",
            "align_command",
            "align_response",
            "gps",
            "mountcontrol",
            "goto_guide",
        )
    }
    catalogs = CatalogBuilder().build(
        state, queue.Queue(), include_dynamic_catalogs=False
    )
    loader = getattr(catalogs, "_background_loader", None)
    if loader is not None:
        # Priority catalogs (including Messier) are available synchronously.
        # No screenshot needs the large deferred catalog set.
        loader.stop()
    filters = CatalogFilter(shared_state=state)
    filters.load_from_config(cfg)
    catalogs.set_catalog_filter(filters)
    with patch.object(MenuManager, "preload_modules", lambda self: None):
        manager = MenuManager(display, night, state, commands, cfg, catalogs)
    destination = OUTPUT / language
    destination.mkdir(parents=True, exist_ok=True)
    records = []

    def open_screen(path=None, item=None):
        if path is not None:
            node = menu_structure.pifinder_menu
            for name in path:
                node = next(
                    entry for entry in node["items"] if entry["name"] in {name, _(name)}
                )
            item = node
        manager.add_to_stack(copy.deepcopy(item))
        screen = manager.stack[-1]
        if "force" in inspect.signature(screen.update).parameters:
            screen.update(force=True)
        else:
            screen.update()
        return screen

    def save(name, screen=None):
        screen = screen or manager.stack[-1]
        frame = screen.screen.copy()
        if frame.size != (128, 128) or frame.getbbox() is None:
            raise RuntimeError(f"Empty or incorrectly sized LCD capture: {name}")
        path = destination / f"{name}.png"
        frame.save(path)
        records.append(
            {
                "name": name,
                "file": path.relative_to(HERE).as_posix(),
                "ui_class": type(screen).__name__,
                "title": screen.title,
                "size": list(frame.size),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        print(language, name, type(screen).__name__, flush=True)

    mount = {
        "state": "connected",
        "message": "Ready",
        "device": "Example mount",
        "updated": MOMENT.timestamp(),
        "ra": 56.75,
        "dec": 24.12,
        "home_state": "Home",
        "park_state": "Unparked",
        "slew_rate": 5,
        "tracking_enabled": True,
        "mount_motion_active": False,
    }
    (runtime / "mount_control_status.json").write_text(json.dumps(mount))
    root = open_screen([])
    save("main_menu", root)
    manager.key_long_square()
    manager.update()
    # The quick menu's composite framebuffer is published by MenuManager.
    path = destination / "quick_menu.png"
    state.screen().save(path)
    records.append(
        {
            "name": "quick_menu",
            "file": path.relative_to(HERE).as_posix(),
            "ui_class": "MenuManager",
            "title": "Quick Menu",
            "size": [128, 128],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
    manager.exit_marking_menu()
    focus = open_screen(["Start", "Focus"])
    for mode in (DISPLAY_IMAGE, DISPLAY_STARS, DISPLAY_SINGLE, DISPLAY_STATS):
        focus.display_mode = mode
        focus.update(force=True)
        save(f"focus_{mode}", focus)
    focus.inactive()
    align = open_screen(["Start", "Align"])
    save("align_start", align)
    align.key_square()
    align.update(force=True)
    save("align_select", align)
    align.key_right()
    align.update(force=True)
    save("align_selected", align)
    day = open_screen(["Start", "Align (Day)"])
    day.camera_image = daylight
    day.key_square()
    day.update(force=True)
    save("align_day_quadrants", day)
    day.key_right()
    save("align_day_fine", day)
    save("gps_status", open_screen(["Start", "GPS Status"]))
    save("chart", open_screen(["Chart"]))
    save("objects_menu", open_screen(["Objects"]))
    messier = open_screen(["Objects", "By Catalog", "Messier"])
    messier.key_number(3)
    messier.key_number(1)
    messier.update(force=True)
    save("messier", messier)
    save("filters", open_screen(["Objects", "Set Filters"]))
    save("filter_multi", open_screen(["Objects", "Set Filters", "Type"]))
    save("name_search", open_screen(["Objects", "Name Search"]))
    obj = catalogs.get_object("M", 45)
    if obj is None:
        raise RuntimeError("M45 missing from the bundled catalog")
    arrived = Pointing(RA=obj.ra + 0.002, Dec=obj.dec - 0.001, Roll=0.0)
    state.set_solution(
        replace(
            state.solution(),
            pointing=PointingMatrix(
                camera=PointingAxis(solve=arrived, estimate=arrived),
                aligned=PointingAxis(solve=arrived, estimate=arrived),
            ),
            last_solve_attempt=MOMENT.timestamp(),
        )
    )
    guide = {
        "updated": MOMENT.timestamp(),
        "phase": "tracking",
        "service_state": "running",
        "tracking_target_ra": obj.ra,
        "tracking_target_dec": obj.dec,
        "tracking_guide_state": "enabled",
        "tracking_guide_enabled": True,
        "tracking_error_arcsec": 12.0,
    }
    (runtime / "indi_goto_guide_status.json").write_text(json.dumps(guide))
    detail = open_screen(
        item={
            "name": obj.display_name,
            "class": UIObjectDetails,
            "object": obj,
            "object_list": [obj],
        }
    )
    for name, mode in (
        ("object_push", DM_LOCATE),
        ("object_camera", DM_CAMERA),
        ("object_description", DM_DESC),
    ):
        detail.object_display_mode = mode
        detail.update(force=True)
        save(name, detail)
    save("log", open_screen(item={"name": "LOG", "class": UILog, "object": obj}))
    save("custom_coordinates", open_screen(["Objects", "Custom"]))
    save("sqm", open_screen(["SQM"]))
    save(
        "sqm_calibration",
        open_screen(item={"name": _("SQM Calibration"), "class": UISQMCalibration}),
    )
    sweep = open_screen(item={"name": "SQM Sweep", "class": UISQMSweep})
    for digit in (2, 1, 3, 0):
        sweep.key_number(digit)
    sweep.update(force=True)
    save("sqm_sweep", sweep)
    save("settings_menu", open_screen(["Settings"]))
    save("setting_select", open_screen(["Settings", "User Pref...", "Language"]))
    save("indi_status", open_screen(["Start", "INDI", "STATUS"]))
    save("indi_init", open_screen(["Start", "INDI", "INIT"]))
    save("indi_guide", open_screen(["Start", "INDI", "Guide"]))
    multi = open_screen(["Settings", "INDI Setting", "Multi Align"])
    save("multi_points", multi)
    multi.key_right()
    multi.update(force=True)
    save("multi_mode", multi)
    backlash = open_screen(["Settings", "INDI Setting", "Backlash"])
    backlash.key_plus()
    for digit in (2, 5):
        backlash.key_number(digit)
    backlash.key_minus()
    for digit in (1, 8):
        backlash.key_number(digit)
    backlash.update(force=True)
    save("backlash", backlash)
    save("advanced", open_screen(["Settings", "Advanced"]))
    from PiFinder import sys_utils_fake
    from PiFinder.ui import status

    with patch.object(status.sys_utils, "Network", sys_utils_fake.Network):
        save("status", open_screen(["Tools", "Status"]))
    save("equipment", open_screen(["Tools", "Equipment"]))
    save(
        "location_entry",
        open_screen(["Tools", "Place & Time", "Set Location", "Enter Coords"]),
    )
    save("time_entry", open_screen(["Tools", "Place & Time", "Set Time/Date"]))
    save("shutdown_confirm", open_screen(["Tools", "Power", "Shutdown"]))
    error = open_screen(item={"name": "ERROR", "class": UIOperationError})
    error.add_error(
        {"source": "INDI", "code": "DISCONNECTED", "message": _("No status")}
    )
    error.update()
    save("operation_error", error)
    manifest = {
        "language": language,
        "display": "SSD1351 layout / headless",
        "resolution": [128, 128],
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "example_data": True,
        "capture_kind": "unmodified LCD framebuffer rendered by production UI",
        "live_hardware": False,
        "example_datetime": MOMENT.isoformat(),
        "camera_frame": "test_images/pleiades.png",
        "camera_frame_sha256": hashlib.sha256(
            (ROOT / "test_images/pleiades.png").read_bytes()
        ).hexdigest(),
        "day_frame": "supplied device camera frame"
        if day_frame
        else "test_images/pleiades.png",
        "captures": records,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    if loader is not None:
        loader.stop()
    print(f"Captured {len(records)} {language} LCD screens", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("ko", "en", "all"), default="all")
    parser.add_argument(
        "--day-frame", type=Path, help="Optional saved 512x512 daylight camera frame"
    )
    args = parser.parse_args()
    if args.language == "all":
        for language in ("ko", "en"):
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--language",
                language,
            ]
            if args.day_frame:
                command.extend(["--day-frame", str(args.day_frame.resolve())])
            subprocess.run(command, check=True)
    else:
        capture(args.language, args.day_frame.resolve() if args.day_frame else None)


if __name__ == "__main__":
    main()
