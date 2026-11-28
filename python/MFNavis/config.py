#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles non-volatile config options
"""

import json
import fcntl
import os
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from PiFinder import utils, equipment, locations
from PiFinder.source_version import get_source_version
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger("config")

# How often a reader may re-stat config.json to notice another process's
# writes. get_option() is called from draw loops, so the file is checked at
# most this often rather than on every lookup; a quarter second is far below
# what anyone can perceive on screen.
REFRESH_INTERVAL = 0.25


def normalize_goto_method(value: Any) -> Any:
    """Accept the legacy GoTo mode while exposing the MFNavis setting value."""
    return "mfnavis" if value == "pifinder" else value


# The target pixel lives in the square native camera frame the solver works
# in (see SharedStateObj.target_pixel); (Y, X) centre means "no alignment
# offset known".
CAMERA_NATIVE_RES = 512
IMAGE_CENTER_PIXEL = (CAMERA_NATIVE_RES / 2, CAMERA_NATIVE_RES / 2)


def _as_target_pixel(value) -> Optional[tuple[float, float]]:
    """``value`` as a (Y, X) float pair inside the camera frame, or None.

    Anything else -- the wrong shape, a non-number, a bool (which float()
    would happily turn into 0 or 1), NaN/inf, or a pixel off the frame -- is
    not a point the solver can use.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(v, bool) for v in value):
        return None
    try:
        y, x = (float(v) for v in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(0.0 <= v < CAMERA_NATIVE_RES for v in (y, x)):
        return None  # also rejects NaN, which fails every comparison
    return (y, x)


class Config:
    def __init__(self):
        """
        load all settings from config file
        """
        # Set up session config items
        # These are transient
        self._session_config_dict = {}
        self._file_stamp: Optional[Tuple[int, int]] = None
        self._last_stamp_check = 0.0
        self.load_config()

    def load_config(self):
        """
        Loads all config from disk useful if another
        process has changed config
        """
        self.config_file_path = Path(utils.data_dir, "config.json")

        self.default_file_path = Path(utils.pifinder_dir, "default_config.json")
        self._file_stamp = self._current_file_stamp()
        if not os.path.exists(self.config_file_path):
            self._config_dict = {}
        else:
            with open(self.config_file_path, "r") as config_file:
                logger.info("Loading config from %s", self.config_file_path)
                self._config_dict = json.load(config_file)

        # open default default_config
        with open(self.default_file_path, "r") as config_file:
            self._default_config_dict = json.load(config_file)

        # Retired tile recovery settings must not survive upgrades. Keep the
        # separately stored lens calibration used by ordinary full-frame solves.
        retired_options = {"wide_solver_enabled", "mf_wide_excluded_tiles_by_optics"}
        if retired_options.intersection(self._config_dict):
            with self._write_lock():
                self._refresh_from_disk()
                for option in retired_options:
                    self._config_dict.pop(option, None)
                self.dump_config()

        self.equipment = self._decode_equipment(self.get_option("equipment"))
        self._equipment_snapshot = self.equipment.to_dict()

        # Load the locations config
        loc_config = self.get_option("locations")
        if loc_config is None:
            self.locations = locations.Locations(locations=[])
        else:
            self.locations = locations.Locations.from_dict(loc_config)

    def _decode_equipment(self, settings):
        defaults = self._default_config_dict.get("equipment")
        if not defaults or settings is None:
            return equipment.Equipment(telescopes=[], eyepieces=[])
        values = deepcopy(settings)
        for key, index in (
            ("telescopes", "active_telescope_index"),
            ("eyepieces", "active_eyepiece_index"),
        ):
            if not values.get(key):
                values[key] = deepcopy(defaults[key])
            if values.get(index, 1000) >= len(values[key]):
                values[index] = 0
        for record in values["telescopes"]:
            if not isinstance(record, dict):
                continue
            pixel = record.get("target_pixel")
            if pixel is not None and _as_target_pixel(pixel) is None:
                logger.warning(
                    "Ignoring unusable alignment point %r on telescope %r",
                    pixel,
                    record.get("name"),
                )
                record["target_pixel"] = None
        try:
            return equipment.Equipment.from_dict(values)
        except (ValueError, TypeError, KeyError):
            logger.exception("Could not load saved equipment; falling back to defaults")
            return equipment.Equipment.from_dict(defaults)

    def _latest_equipment(self):
        self._refresh_from_disk()
        return self._decode_equipment(
            self._config_dict.get(
                "equipment", self._default_config_dict.get("equipment")
            )
        )

    def _write_equipment(self, updated):
        previous = self._config_dict.copy()
        self._config_dict["equipment"] = updated.to_dict()
        try:
            self.dump_config()
        except Exception:
            self._config_dict = previous
            raise
        self.equipment = updated
        self._equipment_snapshot = updated.to_dict()

    def save_equipment(self):
        """Apply the fields edited on the LCD or web to the latest equipment.

        Another process can align a telescope while this menu is open.
        Selecting an eyepiece or editing the telescope must retain its point.
        """
        edited = self.equipment
        before = equipment.Equipment.from_dict(self._equipment_snapshot)
        with self._write_lock():
            updated = self._latest_equipment()
            if edited.telescopes != before.telescopes:
                if updated.telescopes != before.telescopes:
                    raise ValueError("Telescope list changed during edit")
                for index, scope in enumerate(edited.telescopes):
                    # A web form replaces a renamed record in its original slot.
                    # When removing a row, match surviving records by value.
                    if scope in before.telescopes:
                        old = before.telescopes.index(scope)
                    elif len(edited.telescopes) == len(before.telescopes):
                        old = index
                    else:
                        continue
                    scope.target_pixel = updated.telescopes[old].target_pixel
                updated.telescopes = edited.telescopes
            if edited.eyepieces != before.eyepieces:
                updated.eyepieces = edited.eyepieces
            if edited.active_telescope_index != before.active_telescope_index:
                if (
                    updated.telescopes != edited.telescopes
                    and edited.active_telescope is not None
                ):
                    updated.set_active_telescope(edited.active_telescope)
                else:
                    updated.active_telescope_index = edited.active_telescope_index
            if edited.active_eyepiece_index != before.active_eyepiece_index:
                updated.active_eyepiece_index = edited.active_eyepiece_index
            self._write_equipment(updated)

    def save_locations(self):
        """
        Saves the locations object state
        """
        self.set_option("locations", self.locations.to_dict())

    def _read_config_file(self) -> dict:
        """
        Current on-disk config, or {} when it is missing/unreadable
        """
        try:
            with open(self.config_file_path, "r") as config_file:
                on_disk = json.load(config_file)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            # A partially written or corrupt file: better to keep what we have
            # in memory than to throw away every setting.
            logger.warning("Could not read config %s: %s", self.config_file_path, e)
            return dict(self._config_dict)
        return on_disk if isinstance(on_disk, dict) else {}

    def _current_file_stamp(self) -> Optional[Tuple[int, int]]:
        """
        (mtime, size) of the config file, or None when it is missing
        """
        try:
            stat = os.stat(self.config_file_path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _refresh_from_disk(self) -> None:
        """
        Pull in config keys other processes wrote since we loaded

        config.json is shared by the main/UI, camera and web processes, each
        holding its own Config instance loaded at startup. Writing our own
        in-memory copy back would revert every key another process changed in
        the meantime (e.g. the camera process saving camera_exp used to undo
        the LiveCam settings the web UI had just written). Everything this
        process changed is already on disk, so the file is the newer state.
        """
        stamp = self._current_file_stamp()
        on_disk = self._read_config_file()
        if on_disk:
            self._config_dict = on_disk
        self._file_stamp = stamp
        self._last_stamp_check = time.monotonic()

    def _refresh_if_file_changed(self) -> None:
        """
        Reload when another process has written the file since our last read

        Without this a reader keeps serving the values it loaded at startup:
        setting the exposure from the web LiveCam page left the Camera Exp
        menu and its focus-screen suffix showing the old one until the main
        process happened to reload.
        """
        now = time.monotonic()
        if now - self._last_stamp_check < REFRESH_INTERVAL:
            return
        self._last_stamp_check = now
        if self._current_file_stamp() == self._file_stamp:
            return
        self._refresh_from_disk()

    def ensure_source_version(self):
        """Stamp the running source after startup restoration, preserving settings."""
        with self._write_lock():
            self._refresh_from_disk()
            if self._config_dict.get("source_version") != get_source_version():
                previous = dict(self._config_dict)
                try:
                    self.dump_config()
                except Exception:
                    self._config_dict = previous
                    raise

    def dump_config(self):
        """
        Write config to config file

        Writes to a temporary file and renames it into place so a reader in
        another process never sees a half-written config.json.
        """
        self._config_dict["source_version"] = get_source_version()
        if "indi_goto_method" in self._config_dict:
            self._config_dict["indi_goto_method"] = normalize_goto_method(
                self._config_dict["indi_goto_method"]
            )
        tmp_path = self.config_file_path.with_name(
            f"{self.config_file_path.name}.{os.getpid()}.tmp"
        )
        try:
            with open(tmp_path, "w") as config_file:
                os.fchmod(config_file.fileno(), 0o600)
                json.dump(self._config_dict, config_file, indent=4)
                config_file.flush()
                os.fsync(config_file.fileno())
            # FRAM is authoritative on A0: validate/commit its new slot before
            # publishing the SD copy. Failure leaves the old file/slot intact.
            from PiFinder.fram_config import backup_if_enabled

            backup_if_enabled(
                self.config_file_path,
                utils.runtime_dir,
                self._config_dict,
                self.default_file_path,
            )
            os.replace(tmp_path, self.config_file_path)
            # Our own write is not a reason to reload on the next read.
            self._file_stamp = self._current_file_stamp()
            self._last_stamp_check = time.monotonic()
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    @contextmanager
    def _write_lock(self):
        """Serialize cross-process read/merge/write transactions."""
        lock_path = Path(utils.runtime_dir, "config.json.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def set_options(self, options: dict[str, Any]) -> None:
        """Persist multiple plain options in one locked atomic transaction."""
        if not isinstance(options, dict):
            raise TypeError("options must be a dict")
        invalid = [
            key
            for key in options
            if key.startswith(("session.", "equipment.", "locations."))
        ]
        if invalid:
            raise ValueError(
                "set_options only accepts plain persistent options: "
                + ", ".join(invalid)
            )
        if not options:
            return
        with self._write_lock():
            self._refresh_from_disk()
            previous = dict(self._config_dict)
            self._config_dict.update(options)
            try:
                self.dump_config()
            except Exception:
                self._config_dict = previous
                raise

    def get_stored_option(self, option: str, default: Any = None) -> Any:
        """Return only the user config value, without default_config fallback."""
        self._refresh_if_file_changed()
        return self._config_dict.get(option, default)

    def set_option(self, option, value):
        if option in {"indi_goto_method", "session.indi_goto_method"}:
            value = normalize_goto_method(value)
        if option.startswith("session."):
            self._session_config_dict[option] = value
        elif option.startswith("equipment."):
            option = option.split(".")[1]
            if option == "active_telescope":
                self.equipment.set_active_telescope(value)
            if option == "active_eyepiece":
                self.equipment.set_active_eyepiece(value)

            self.save_equipment()

        elif option.startswith("locations."):
            # Just save locations when any locations option changes
            self.save_locations()

        else:
            # Merge onto the current file rather than over it: another process
            # may have changed unrelated keys since we loaded.
            self.set_options({option: value})

    def get_option(self, option, default: Any = None):
        if option in {"indi_goto_method", "session.indi_goto_method"}:
            if option.startswith("session."):
                return normalize_goto_method(
                    self._session_config_dict.get(option, default)
                )
            self._refresh_if_file_changed()
            return normalize_goto_method(
                self._config_dict.get(
                    option, self._default_config_dict.get(option, default)
                )
            )
        if option.startswith("session."):
            return self._session_config_dict.get(option, default)
        elif option.startswith("equipment."):
            option = option.split(".")[1]
            if option == "active_telescope":
                return self.equipment.active_telescope
            if option == "active_eyepiece":
                return self.equipment.active_eyepiece
        elif option.startswith("locations."):
            option = option.split(".")[1]
            if option == "default":
                return self.locations.default_location
        else:
            # equipment/locations above stay on the in-memory objects (they are
            # rebuilt by an explicit load_config()); plain options come from
            # whatever is on disk now, whichever process wrote it.
            self._refresh_if_file_changed()
            return self._config_dict.get(
                option, self._default_config_dict.get(option, default)
            )

    def alignment_scope(self):
        """Identify the selected record even when two scopes share one pixel."""
        return self.equipment.active_telescope_index, self.equipment.active_telescope

    def active_target_pixel(self) -> tuple[float, float]:
        """The alignment point the solver should use now, as (Y, X).

        The active telescope's own point if it has been aligned; otherwise
        the global ``target_pixel`` (the point every telescope shared before
        alignment became per-telescope, and the one used when no telescope
        is selected); otherwise the image centre.  A stored value that is
        not a usable pixel is skipped rather than raised, so a hand-edited
        config cannot stop the solver.
        """
        telescope = self.equipment.active_telescope
        if telescope is not None:
            pixel = _as_target_pixel(telescope.target_pixel)
            if pixel is not None:
                return pixel
        pixel = _as_target_pixel(self.get_option("target_pixel"))
        if pixel is not None:
            return pixel
        return IMAGE_CENTER_PIXEL

    def save_target_pixel(self, target_pixel) -> None:
        """Persist a new alignment point, (Y, X), for the active telescope.

        With no telescope selected it goes to the global ``target_pixel``,
        which is also what every not-yet-aligned telescope falls back to.
        """
        pixel = _as_target_pixel(target_pixel)
        if pixel is None:
            raise ValueError(f"Not a target pixel: {target_pixel!r}")
        telescope = self.equipment.active_telescope
        if telescope is None:
            self.set_option("target_pixel", list(pixel))
        else:
            with self._write_lock():
                updated = self._latest_equipment()
                if (
                    updated.active_telescope_index
                    != self.equipment.active_telescope_index
                    or updated.active_telescope != telescope
                ):
                    raise ValueError("Active telescope changed during alignment")
                updated.active_telescope.target_pixel = list(pixel)
                self._write_equipment(updated)

    def reset_filters(self):
        """
        Removes all filter. keys from the
        config dict and writes it out.
        Effectively resetting filters to default
        """
        with self._write_lock():
            self._refresh_from_disk()
            keys_to_remove = []
            for _k in self._config_dict:
                if _k.startswith("filter."):
                    keys_to_remove.append(_k)

            for _k in keys_to_remove:
                self._config_dict.pop(_k)

            self.dump_config()

    def __str__(self):
        return str(self._config_dict)

    def __repr__(self):
        return str(self._config_dict)
