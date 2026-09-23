#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PiFinder API Extensions
=======================
Registers machine-readable REST API endpoints on PiFinder's Flask Web Server.

Usage:
    Add the following at the end of Server.__init__ in
    PiFinder/python/PiFinder/server.py, before run() is called:

        from PiFinder.api_extensions import register_api_routes
        register_api_routes(app, self, require_auth=False)

Dependencies: No additional dependencies. Reuses PiFinder's existing Flask / PIL / shared state.
"""

import io
import json
import logging
import time
from pathlib import Path

from flask import request, session, Response, render_template
from PIL import Image
from PiFinder import utils
from PiFinder import config
from PiFinder import camera_controls
from PiFinder import solver_capture
from PiFinder.observation import observation_snapshot
from PiFinder.mf_manual_lens import manual_focal_from_state
from PiFinder.optics import OpticalTrainResolver
from PiFinder.livecam_config import (
    SESSION_ONLY_KEYS,
    default_settings_for_config,
    disabled_status,
    normalize_settings,
    save_settings_to_config,
    settings_from_config,
)

logger = logging.getLogger("PiFinderAPI")

# Starfield instances are cached and may serve concurrent requests. Keep the
# optical state outside them and pass it to each render.
_API_OPTICAL_TRAIN = OpticalTrainResolver()


def _json_response(data, status=200):
    """Unified JSON response format"""
    return Response(
        json.dumps(data, default=str, ensure_ascii=False),
        status=status,
        content_type="application/json; charset=utf-8",
    )


def _pil_to_png_bytes(img: Image.Image) -> bytes:
    """Convert a PIL Image to PNG bytes"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_response(img: Image.Image) -> Response:
    """Wrap a PIL Image in a Flask PNG response"""
    return Response(_pil_to_png_bytes(img), content_type="image/png")


def _pointing_to_dict(p):
    """Serialize a :class:`Pointing` (or ``None``) to a plain
    ``{RA, Dec, Roll}`` dict of floats."""
    if p is None:
        return {"RA": None, "Dec": None, "Roll": None}
    return {"RA": float(p.RA), "Dec": float(p.Dec), "Roll": float(p.Roll)}


def _solution_to_dict(sol) -> dict:
    """Serialize a :class:`PointingEstimate` to the JSON shape the REST API
    has always emitted (the legacy ``solved`` dict keys), so external
    clients (e.g. OpenClaw) keep a stable contract across the dataclass
    migration in PR #429.

    Mapping back to the canonical access shape:

    * top-level ``RA``/``Dec``/``Roll`` ← ``pointing.aligned.estimate``
      (where the eyepiece points — the IMU-progressed aligned pointing).
    * ``camera_center`` ← ``pointing.camera.estimate`` (IMU-progressed
      camera-axis pointing).
    * ``camera_solve`` ← ``pointing.camera.solve`` (the IMU-untouched
      plate-solve at the camera centre).
    * ``solve_time`` ← ``estimate_time`` (renamed in ADR-0013; the old key
      is kept here for wire compatibility).

    ``imu_quat`` from the old dict is intentionally dropped — it was a raw
    numpy quaternion that no endpoint reads and never serialized cleanly.
    """
    pm = sol.pointing
    aligned = _pointing_to_dict(pm.aligned.estimate)
    diag = sol.diagnostics
    return {
        "RA": aligned["RA"],
        "Dec": aligned["Dec"],
        "Roll": aligned["Roll"],
        "camera_center": {
            **_pointing_to_dict(pm.camera.estimate),
            "Alt": None,
            "Az": None,
        },
        "camera_solve": _pointing_to_dict(pm.camera.solve),
        "Alt": float(sol.Alt) if sol.Alt is not None else None,
        "Az": float(sol.Az) if sol.Az is not None else None,
        "solve_source": sol.solve_source.value if sol.solve_source else None,
        "solve_time": sol.estimate_time,
        # cam_solve_time was dropped from the dataclass (value-identical to
        # last_solve_success under epoch semantics); keep the key for clients.
        "cam_solve_time": sol.last_solve_success,
        "last_solve_attempt": sol.last_solve_attempt,
        "last_solve_success": sol.last_solve_success,
        "constellation": sol.constellation,
        "FOV": diag.FOV,
        "Matches": diag.Matches,
        # The star-count controller's feedback signal. Exposed because
        # "Matches 0" alone cannot tell a too-dark frame from a sky full of
        # detections tetra3 could not match -- which is exactly the difference
        # that decides what auto-exposure does next (ADR m0020/m0021).
        "Centroids": diag.Centroids,
        "RMSE": diag.RMSE,
        "Prob": diag.Prob,
        "T_solve": diag.T_solve,
        "T_extract": diag.T_extract,
        # Which path produced the attempt: cedar_center / sep_center /
        # cedar_full / sep_full (plus legacy cedar_512 / tetra3 modes).
        # (empty on messages that predate the field).
        "solve_path": getattr(diag, "solve_path", ""),
        "CedarRawCentroids": getattr(diag, "CedarRawCentroids", None),
        "CedarGatedCentroids": getattr(diag, "CedarGatedCentroids", None),
        "CedarCenterCentroids": getattr(diag, "CedarCenterCentroids", None),
        "SepCentroids": getattr(diag, "SepCentroids", None),
    }


def register_api_routes(app, server_instance, require_auth=False):
    """
    Register all /api/* routes on the Flask app.

    Parameters
    ----------
    app : Flask
        The existing Flask application instance in the PiFinder Server
    server_instance : Server
        The PiFinder Server class instance (self), used to access shared_state, etc.
    require_auth : bool
        Whether to enable session authentication for /api/* endpoints.
        Defaults to False for easier access by automation tools.
    """

    # Built-in simple token authentication (optional), to avoid modifying the auth_required decorator
    api_token = getattr(server_instance, "api_token", None)

    def _check_auth():
        if not require_auth and not api_token:
            return True
        # 1) Session authentication (same as the Web UI)
        if session.get("authenticated"):
            return True
        # 2) URL query token authentication (convenient for scripts/OpenClaw)
        if api_token and request.args.get("token") == api_token:
            return True
        return False

    def _auth_wrapper(func):
        """Return 401 if authentication is enabled and the request is not authorized"""

        def wrapper(*args, **kwargs):
            if not _check_auth():
                return _json_response({"error": "Unauthorized"}, 401)
            return func(*args, **kwargs)

        return wrapper

    def _raw_stack_processor(create: bool = True):
        processor = getattr(server_instance, "raw_live_stack_processor", None)
        if processor is None and create:
            from PiFinder.raw_live_stack import RawLiveStackProcessor

            processor = RawLiveStackProcessor()
            server_instance.raw_live_stack_processor = processor
        return processor

    # settings_from_config re-reads config.json from disk; the LiveCam status
    # poll calls it every 750 ms and the load showed up in the web process CPU
    # profile (2026-07-28). Cache on the file's mtime -- any set_option write
    # (e.g. the LiveCam control POST) touches the file and invalidates.
    _raw_stack_cfg_cache: dict = {"mtime": None, "settings": None}

    def _raw_stack_settings() -> dict:
        cfg_path = Path(utils.data_dir, "config.json")
        try:
            mtime = cfg_path.stat().st_mtime
        except OSError:
            mtime = None
        if (
            _raw_stack_cfg_cache["settings"] is None
            or _raw_stack_cfg_cache["mtime"] != mtime
        ):
            _raw_stack_cfg_cache["settings"] = settings_from_config(config.Config())
            _raw_stack_cfg_cache["mtime"] = mtime
        settings = dict(_raw_stack_cfg_cache["settings"])
        # Session-only switches are never persisted. settings_from_config always
        # returns them at their defaults, so carry forward values toggled for
        # this session; otherwise a status poll would immediately reset them.
        if hasattr(server_instance.shared_state, "livecam_settings"):
            live = server_instance.shared_state.livecam_settings()
            if live:
                for key in SESSION_ONLY_KEYS:
                    if key in live:
                        settings[key] = bool(live[key])
        if hasattr(server_instance.shared_state, "set_livecam_settings"):
            server_instance.shared_state.set_livecam_settings(settings)
        return settings

    # ───────────────────────────────────────────────
    # 1. Aggregated status endpoint (fetch everything at once)
    # ───────────────────────────────────────────────
    @app.route("/solver-capture", endpoint="solver_capture_page")
    @_auth_wrapper
    def solver_capture_page():
        return render_template("solver_capture.html")

    @app.route(
        "/api/solver-capture",
        methods=["GET", "POST"],
        endpoint="solver_capture_control",
    )
    @_auth_wrapper
    def solver_capture_control():
        if request.method == "GET":
            return _json_response(solver_capture.capture_status())
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_response({"error": "JSON object required"}, 400)
        try:
            return _json_response(
                solver_capture.request_capture(
                    payload.get("action"),
                    payload,
                )
            )
        except (ValueError, TypeError, OverflowError) as exc:
            return _json_response({"error": str(exc)}, 400)
        except OSError as exc:
            return _json_response({"error": str(exc)}, 503)

    @app.route("/api/status")
    def api_status():
        try:
            ss = server_instance.shared_state
            loc = ss.location()
            sol = ss.solution()
            dt_utc = ss.datetime()

            data = {
                "power_state": ss.power_state(),
                "solve_state": ss.solve_state(),
                "camera_type": ss.camera_type(),
                "location": loc.to_dict() if loc else None,
                "solution": _solution_to_dict(sol),
                "datetime": {
                    "utc": dt_utc.isoformat() if dt_utc else None,
                    "local": ss.local_datetime().isoformat() if dt_utc else None,
                },
                "imu": ss.imu().to_dict() if ss.imu() else None,
                "sqm": ss.sqm().to_dict() if ss.sqm() else None,
                "software_version": _get_version(server_instance),
            }
            return _json_response(data)
        except Exception as e:
            logger.error("api/status error: %s", e)
            return _json_response({"error": str(e)}, 500)

    # ───────────────────────────────────────────────
    # 2. Atomic endpoints (fetch individual items on demand)
    # ───────────────────────────────────────────────

    @app.route("/api/time")
    def api_time():
        try:
            ss = server_instance.shared_state
            dt_utc = ss.datetime()
            data = {
                "utc": dt_utc.isoformat() if dt_utc else None,
                "local": ss.local_datetime().isoformat() if dt_utc else None,
                "timezone": ss.location().timezone if ss.location() else "UTC",
            }
            return _json_response(data)
        except Exception as e:
            logger.error("api/time error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/location")
    def api_location():
        try:
            server_instance.update_gps()  # 先刷新 GPS 缓存
            loc = server_instance.shared_state.location()
            if loc and loc.lock:
                return _json_response(loc.to_dict())
            return _json_response(
                {
                    "lock": False,
                    "note": "GPS not locked or location unavailable",
                    "location": loc.to_dict() if loc else None,
                },
                503,
            )
        except Exception as e:
            logger.error("api/location error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/observation")
    def api_observation():
        return _json_response(observation_snapshot(server_instance.shared_state))

    @app.route("/api/solution")
    def api_solution():
        try:
            ss = server_instance.shared_state
            if ss.solve_state() is not True:
                return _json_response(
                    {
                        "solve_state": ss.solve_state(),
                        "note": "No valid plate solve yet",
                    },
                    503,
                )
            sol = ss.solution()
            if not sol.has_pointing():
                return _json_response({"note": "Solution data empty"}, 503)

            payload = _solution_to_dict(sol)

            # Add Alt/Az if location and datetime are ready
            if ss.altaz_ready():
                try:
                    from PiFinder.calc_utils import sf_utils

                    ts = sf_utils.ts
                    dt = ss.datetime()
                    aligned = sol.pointing.aligned.estimate
                    ra_h = float(aligned.RA) / 15.0
                    dec_d = float(aligned.Dec)
                    from skyfield.positionlib import position_of_radec

                    p = position_of_radec(
                        ra_hours=ra_h, dec_degrees=dec_d, epoch=ts.J2000
                    )
                    alt, az, _ = p.altaz(
                        observer=sf_utils.topos(
                            ss.location().lat, ss.location().lon, ss.location().altitude
                        ),
                        epoch=ts.from_datetime(dt),
                    )
                    payload["Alt"] = alt.degrees
                    payload["Az"] = az.degrees
                except Exception:
                    pass

            return _json_response(payload)
        except Exception as e:
            logger.error("api/solution error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/visible_stars")
    def api_visible_stars():
        """
        Return the visible star data within the current PiFinder field of view.

        Design goals:
            1. Use the RA / Dec / Roll from camera_solve, without being affected by IMU correction;
            2. Re-render the star field using PiFinder.plot.Starfield;
            3. Return star coordinates for high-resolution rendering in OpenClaw;
            4. Also indicate which stars are recommended for labeling with label=true;
            5. Support render_mag_limit / label_mag_limit / max_labels.

        Query parameters:
            render_mag_limit:
                Magnitude limit used for "drawing star points". Default is 5.5.
                Example: /api/visible_stars?render_mag_limit=5.5

            mag_limit:
                Backward-compatible legacy parameter.
                Used if render_mag_limit is not provided.
                Example: /api/visible_stars?mag_limit=5.5

            label_mag_limit:
                Magnitude limit used for "automatically labeling star names". Default is 2.5.
                Example: /api/visible_stars?label_mag_limit=4.0

            max_labels:
                Maximum number of stars to label. Default is 5.
                If there are too few stars within label_mag_limit, the brightest stars
                currently in the field of view will be added automatically.

            constellation_brightness:
                Brightness of constellation lines. Default is 32.

            shade_frustrum:
                Whether to render the frustum shadow. Default is true.

            include_image:
                Whether to include the PiFinder-rendered star chart as a base64 PNG.
                Default is false.

            use_camera_solve:
                Whether to prefer the camera-axis plate-solve
                (pointing.camera.solve) over the aligned estimate.
                Default is true.

            fov:
                Rendering FOV. Default is 10.2.

            render_size:
                Rendering size. Default is 1088.
                For example, when render_size=2048, x_pos / y_pos will be output
                in a 2048×2048 coordinate system.
        """
        try:
            import base64

            ss = server_instance.shared_state

            # --------------------------------------------------
            # 1. Check plate-solving status
            # --------------------------------------------------
            solve_state = ss.solve_state()

            if solve_state is not True:
                return _json_response(
                    {
                        "success": False,
                        "solve_state": solve_state,
                        "note": "No valid plate solve yet",
                    },
                    503,
                )

            sol = ss.solution()

            if not sol.has_pointing():
                return _json_response(
                    {
                        "success": False,
                        "note": "Solution data empty",
                    },
                    503,
                )

            # --------------------------------------------------
            # 2. Read query parameters
            # --------------------------------------------------

            # Backward compatibility with the legacy mag_limit parameter.
            # In the new logic, render_mag_limit represents the magnitude limit for "drawing star points".
            try:
                render_mag_limit = float(
                    request.args.get(
                        "render_mag_limit",
                        request.args.get("mag_limit", 5.5),
                    )
                )
            except Exception:
                render_mag_limit = 5.5

            # label_mag_limit represents the magnitude limit for "recommended star name labeling".
            try:
                label_mag_limit = float(request.args.get("label_mag_limit", 2.5))
            except Exception:
                label_mag_limit = 2.5

            # If there are not enough stars within label_mag_limit, add the brightest stars currently in the field of view.
            try:
                max_labels = int(request.args.get("max_labels", 5))
            except Exception:
                max_labels = 5

            if max_labels < 0:
                max_labels = 0
            if max_labels > 30:
                max_labels = 30

            try:
                constellation_brightness = int(
                    request.args.get("constellation_brightness", 32)
                )
            except Exception:
                constellation_brightness = 32

            shade_frustrum_q = str(request.args.get("shade_frustrum", "true")).lower()
            shade_frustrum = shade_frustrum_q not in ("0", "false", "no", "off")

            include_image_q = str(request.args.get("include_image", "false")).lower()
            include_image = include_image_q in ("1", "true", "yes", "on")

            use_camera_solve_q = str(
                request.args.get("use_camera_solve", "true")
            ).lower()
            use_camera_solve = use_camera_solve_q not in ("0", "false", "no", "off")

            try:
                solve_fov = sol.diagnostics.FOV
                fov = float(
                    request.args.get(
                        "fov", solve_fov if solve_fov is not None else 10.2
                    )
                )
            except Exception:
                fov = 10.2

            try:
                render_size = int(request.args.get("render_size", 1088))
            except Exception:
                render_size = 1088

            if render_size < 128:
                render_size = 128
            if render_size > 4096:
                render_size = 4096

            # --------------------------------------------------
            # 3. Select the solve source
            # --------------------------------------------------
            source = "camera_solve"

            if use_camera_solve and sol.pointing.camera.solve is not None:
                camera_solve = sol.pointing.camera.solve

                ra = float(camera_solve.RA)
                dec = float(camera_solve.Dec)
                roll = float(camera_solve.Roll)

            else:
                source = "solution"

                aligned = sol.pointing.aligned.estimate
                ra = float(aligned.RA)
                dec = float(aligned.Dec)
                roll = float(aligned.Roll)

            # --------------------------------------------------
            # 4. Get the API-specific Starfield object
            # --------------------------------------------------
            #
            # This relies on the helper function you added earlier:
            #
            #     _get_api_starfield(...)
            #
            # It creates and caches PiFinder.plot.Starfield.
            # This avoids the need to look for the align app's starfield inside server_instance.
            #
            starfield = _get_api_starfield(
                server_instance,
                resolution=(render_size, render_size),
                mag_limit=7,
                fov=fov,
            )

            camera_fov = _API_OPTICAL_TRAIN.resolve(
                ss.camera_type(), ss.camera_lens(), manual_focal_from_state(ss)
            ).fov_degrees

            # --------------------------------------------------
            # 5. Call PiFinder's native star chart rendering logic
            # --------------------------------------------------
            image_obj, visible_stars = starfield.plot_starfield(
                ra,
                dec,
                roll,
                constellation_brightness,
                shade_frustrum=shade_frustrum,
                camera_fov=camera_fov,
            )

            # --------------------------------------------------
            # 6. Build visible_stars
            # --------------------------------------------------
            stars_payload = []
            label_indices = set()
            mag_col = None

            if hasattr(visible_stars, "copy") and hasattr(visible_stars, "columns"):
                df = visible_stars.copy()

                # Look up the magnitude field. PiFinder Starfield usually uses magnitude.
                for candidate in ("vmag", "mag", "magnitude", "Vmag", "V"):
                    if candidate in df.columns:
                        mag_col = candidate
                        break

                # First filter by render_mag_limit: these stars will be used for drawing.
                if mag_col is not None:
                    df = df[df[mag_col].astype(float) <= render_mag_limit].copy()

                # Generate label_indices:
                # 1. First label stars within label_mag_limit;
                # 2. If the count is less than max_labels, add the brightest stars currently in the field of view.
                if mag_col is not None and not df.empty and max_labels > 0:
                    try:
                        bright_df = df[df[mag_col].astype(float) <= label_mag_limit]
                        label_indices.update(bright_df.index.tolist())

                        if len(label_indices) < max_labels:
                            brightest_df = df.sort_values(mag_col).head(max_labels)
                            label_indices.update(brightest_df.index.tolist())
                    except Exception:
                        label_indices = set()

                # Convert the DataFrame to JSON.
                # Note: In the Hipparcos catalog, the index is usually the HIP number,
                # so here we return the index as hip_id.
                for hip_id, row in df.iterrows():
                    item = {}

                    item["hip_id"] = _safe_json_value(hip_id)

                    for key, value in row.to_dict().items():
                        item[key] = _safe_json_value(value)

                    item["display_name"] = _guess_star_name(item)

                    mag_value = _extract_mag_value(item)

                    item["label"] = hip_id in label_indices

                    if mag_value is not None and mag_value <= label_mag_limit:
                        item["label_reason"] = f"magnitude <= {label_mag_limit}"
                    elif item["label"]:
                        item["label_reason"] = f"top {max_labels} brightest in field"
                    else:
                        item["label_reason"] = None

                    stars_payload.append(item)

            elif isinstance(visible_stars, list):
                # Compatibility for the list[dict] case.
                tmp_items = []

                for i, row in enumerate(visible_stars):
                    if isinstance(row, dict):
                        item = {k: _safe_json_value(v) for k, v in row.items()}
                    else:
                        item = {"value": _safe_json_value(row)}

                    if "hip_id" not in item:
                        item["hip_id"] = item.get("HIP", item.get("hip", i))

                    item["display_name"] = _guess_star_name(item)

                    mag_value = _extract_mag_value(item)

                    if mag_value is not None and mag_value > render_mag_limit:
                        continue

                    item["_mag_value_for_sort"] = mag_value
                    tmp_items.append(item)

                # Also apply the labeling logic for the list case.
                bright_items = []
                sortable_items = []

                for item in tmp_items:
                    mag_value = item.get("_mag_value_for_sort")

                    if mag_value is not None:
                        sortable_items.append(item)

                        if mag_value <= label_mag_limit:
                            bright_items.append(item)

                label_ids = set()

                for item in bright_items:
                    label_ids.add(str(item.get("hip_id")))

                if len(label_ids) < max_labels:
                    sortable_items.sort(
                        key=lambda x: (
                            99
                            if x.get("_mag_value_for_sort") is None
                            else x.get("_mag_value_for_sort")
                        )
                    )
                    for item in sortable_items[:max_labels]:
                        label_ids.add(str(item.get("hip_id")))

                for item in tmp_items:
                    mag_value = item.get("_mag_value_for_sort")
                    item.pop("_mag_value_for_sort", None)

                    item["label"] = str(item.get("hip_id")) in label_ids

                    if mag_value is not None and mag_value <= label_mag_limit:
                        item["label_reason"] = f"magnitude <= {label_mag_limit}"
                    elif item["label"]:
                        item["label_reason"] = f"top {max_labels} brightest in field"
                    else:
                        item["label_reason"] = None

                    stars_payload.append(item)

            else:
                return _json_response(
                    {
                        "success": False,
                        "error": "Unsupported visible_stars type",
                        "type": str(type(visible_stars)),
                    },
                    500,
                )

            # --------------------------------------------------
            # 7. Sort: brightest stars first
            # --------------------------------------------------
            try:
                stars_payload.sort(
                    key=lambda s: (
                        99 if _extract_mag_value(s) is None else _extract_mag_value(s)
                    )
                )
            except Exception:
                pass

            label_count = sum(1 for s in stars_payload if s.get("label"))

            # --------------------------------------------------
            # 8. Assemble the response
            # --------------------------------------------------
            data = {
                "success": True,
                "source": source,
                "solve_state": solve_state,
                "camera": {
                    "RA": ra,
                    "Dec": dec,
                    "Roll": roll,
                },
                "filters": {
                    "render_mag_limit": render_mag_limit,
                    "label_mag_limit": label_mag_limit,
                    "max_labels": max_labels,
                    "constellation_brightness": constellation_brightness,
                    "shade_frustrum": shade_frustrum,
                    "fov": fov,
                    "render_size": render_size,
                },
                "count": len(stars_payload),
                "label_count": label_count,
                "visible_stars": stars_payload,
            }

            if include_image:
                png_bytes = _pil_to_png_bytes(image_obj)
                data["image"] = {
                    "format": "png",
                    "encoding": "base64",
                    "data": base64.b64encode(png_bytes).decode("ascii"),
                }

            return _json_response(data)

        except Exception as e:
            logger.exception("api/visible_stars error")
            return _json_response({"success": False, "error": str(e)}, 500)

    @app.route("/api/imu")
    def api_imu():
        try:
            imu = server_instance.shared_state.imu()
            if imu:
                data = imu.to_dict()
                return _json_response(data, 200 if data["usable"] else 503)
            return _json_response({"note": "IMU data not available"}, 503)
        except Exception as e:
            logger.error("api/imu error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/sqm")
    def api_sqm():
        try:
            sqm = server_instance.shared_state.sqm()
            if sqm:
                return _json_response(sqm.to_dict())
            return _json_response({"note": "SQM data not available"}, 503)
        except Exception as e:
            logger.error("api/sqm error: %s", e)
            return _json_response({"error": str(e)}, 500)

    # ───────────────────────────────────────────────
    # 3. Image endpoint (no authentication required, convenient for direct embedding in browsers/OpenClaw)
    # ───────────────────────────────────────────────

    @app.route("/api/screen")
    def api_screen():
        """Return the current screen display as a 128x128 PNG, equivalent to /image"""
        try:
            img = server_instance.shared_state.screen()
            if img is None:
                img = Image.new("RGB", (128, 128), color=(0, 0, 0))
            return _png_response(img)
        except Exception as e:
            logger.error("api/screen error: %s", e)
            empty = Image.new("RGB", (128, 128), color=(73, 109, 137))
            return _png_response(empty)

    @app.route("/api/camera/raw")
    def api_camera_raw():
        """Return the raw CMOS image, if available.

        The stored frame is the sensor's raw values (uint16 holding
        10/12-bit data). Scale linearly by the sensor bit depth to 8-bit
        for display -- reinterpreting the buffer (what this did before)
        wrapped values modulo 256 and produced garbage brightness.
        """
        try:
            raw = server_instance.shared_state.cam_raw()
            if raw is None:
                return _json_response({"note": "No raw image available"}, 503)
            # raw may be a PIL Image or a NumPy array
            if hasattr(raw, "save"):
                img = raw.convert("RGB") if raw.mode != "RGB" else raw
            else:
                import numpy as np

                arr = np.asarray(raw)
                if arr.dtype == np.uint16:
                    bit_depth = 16
                    try:
                        from PiFinder.sqm import get_camera_profile

                        camera_type = server_instance.shared_state.camera_type()
                        if camera_type:
                            bit_depth = get_camera_profile(camera_type).bit_depth
                    except Exception:
                        logger.warning(
                            "api/camera/raw: no camera profile, assuming 16-bit"
                        )
                    arr = np.clip(
                        arr.astype(np.float32) * 255.0 / (2**bit_depth - 1),
                        0,
                        255,
                    ).astype(np.uint8)
                if arr.ndim == 2:
                    img = Image.fromarray(arr, mode="L").convert("RGB")
                else:
                    img = Image.fromarray(arr)
            return _png_response(img)
        except Exception as e:
            logger.error("api/camera/raw error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/camera/stages", methods=["GET", "POST"])
    def api_camera_stages():
        """Trigger or list pipeline stage dumps.

        POST arms a one-shot dump: the next captured frame is written stage
        by stage (cropped raw -> bias subtract -> digital gain -> 8-bit
        stretch -> 512 resize -> rotated solver input) plus stats.json --
        see camera_stage_dump. GET lists the dumps taken so far.
        """
        try:
            # Dumps live on tmpfs and rotate (see utils.runtime_capture_dir);
            # download what matters before power-off. Older sessions saved to
            # the SD (PiFinder_data/captures) are on the filesystem only.
            stages_root = Path(utils.runtime_capture_dir)
            if request.method == "POST":
                camera_queue = getattr(server_instance, "camera_command_queue", None)
                if camera_queue is None:
                    return _json_response(
                        {"error": "Camera command queue unavailable"}, 503
                    )
                camera_queue.put("save_stages")
                return _json_response(
                    {
                        "note": "Stage dump armed; the next frame is written "
                        "stage by stage. Poll GET /api/camera/stages -- the "
                        "dump is complete once stats.json is listed."
                    }
                )

            dumps = []
            if stages_root.exists():
                for dump_dir in sorted(stages_root.glob("stages_*")):
                    if dump_dir.is_dir():
                        dumps.append(
                            {
                                "name": dump_dir.name,
                                "files": sorted(
                                    f.name for f in dump_dir.iterdir() if f.is_file()
                                ),
                            }
                        )
            return _json_response({"dumps": dumps})
        except Exception as e:
            logger.error("api/camera/stages error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/camera/stages/<dirname>/<filename>")
    def api_camera_stages_file(dirname, filename):
        """Download one file from a pipeline stage dump."""
        try:
            # Path components come from the URL: allow only flat names inside
            # a stages_* directory.
            if (
                not dirname.startswith("stages_")
                or "/" in filename
                or ".." in dirname
                or ".." in filename
            ):
                return _json_response({"error": "Invalid path"}, 400)
            path = Path(utils.runtime_capture_dir) / dirname / filename
            if not path.is_file():
                return _json_response({"error": "Not found"}, 404)
            mimetype = {
                ".png": "image/png",
                ".json": "application/json",
                ".npy": "application/octet-stream",
            }.get(path.suffix, "application/octet-stream")
            return Response(path.read_bytes(), content_type=mimetype)
        except Exception as e:
            logger.error("api/camera/stages file error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/camera/debug")
    def api_camera_debug():
        """Return the latest debug frame from the solver_debug_dumps directory"""
        try:
            from pathlib import Path

            debug_dir = utils.debug_dump_dir
            if not debug_dir.exists():
                debug_dir = Path("solver_debug_dumps")
            if not debug_dir.exists():
                return _json_response({"note": "Debug dump directory not found"}, 503)

            files = sorted(
                debug_dir.glob("*.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not files:
                return _json_response({"note": "No debug frames available"}, 503)

            with open(files[0], "rb") as f:
                return Response(f.read(), content_type="image/png")
        except Exception as e:
            logger.error("api/camera/debug error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/camera/raw-stack/status")
    def api_camera_raw_stack_status():
        try:
            settings = _raw_stack_settings()
            processor = _raw_stack_processor(create=False)
            if not settings["processing_enabled"] and processor is None:
                return _json_response(disabled_status(settings))
            data = (processor or _raw_stack_processor()).status(
                server_instance.shared_state, settings
            )
            return _json_response(data)
        except Exception as e:
            logger.error("api/camera/raw-stack/status error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/camera/raw-stack/image")
    def api_camera_raw_stack_image():
        try:
            settings = _raw_stack_settings()
            if not settings["processing_enabled"]:
                return Response(status=204)
            rendered = _raw_stack_processor().render_image(
                server_instance.shared_state,
                settings,
                # Live preview always uses JPEG: PNG encoding of the
                # full-size frame is slow enough to drop the refresh rate.
                # The web_image_format setting only governs downloads.
                image_format="jpeg",
                web_theme=request.args.get("theme", "grey"),
                overlay_sep="sep" in request.args.getlist("overlay"),
                overlay_mark="mark" in request.args.getlist("overlay"),
            )
            if rendered is None:
                return Response(status=204)
            image_bytes, mimetype = rendered
            return Response(image_bytes, content_type=mimetype)
        except Exception as e:
            logger.error("api/camera/raw-stack/image error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/camera/raw-stack/download")
    def api_camera_raw_stack_download():
        try:
            settings = _raw_stack_settings()
            if not settings["processing_enabled"]:
                return Response(status=204)
            from PiFinder.raw_live_stack import (
                download_color_mode,
                download_image_format,
            )

            if request.args.get("format") == "tiff":
                # Lossless 16-bit data export (no stretch, no 8-bit clip)
                rendered = _raw_stack_processor().render_raw_tiff(
                    server_instance.shared_state, settings
                )
                if rendered is None:
                    return Response(status=204)
                image_bytes, mimetype = rendered
                filename = f"pifinder_livecam_{time.strftime('%Y%m%d_%H%M%S')}.tiff"
                return Response(
                    image_bytes,
                    content_type=mimetype,
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"'
                    },
                )

            image_format = download_image_format(settings)
            rendered = _raw_stack_processor().render_image(
                server_instance.shared_state,
                settings,
                image_format=image_format,
                color_mode=download_color_mode(server_instance.shared_state, settings),
                web_theme=request.args.get("theme", "grey"),
                accept_new_frame=False,
                native_resolution=True,
            )
            if rendered is None:
                return Response(status=204)
            image_bytes, mimetype = rendered
            filename = (
                f"pifinder_livecam_{time.strftime('%Y%m%d_%H%M%S')}.{image_format}"
            )
            return Response(
                image_bytes,
                content_type=mimetype,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as e:
            logger.error("api/camera/raw-stack/download error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/camera/raw-stack/control", methods=["GET", "POST"])
    def api_camera_raw_stack_control():
        try:
            if request.method == "GET":
                settings = _raw_stack_settings()
                processor = _raw_stack_processor(create=False)
                if not settings["processing_enabled"] and processor is None:
                    data = disabled_status(settings)
                else:
                    data = (processor or _raw_stack_processor()).status(
                        server_instance.shared_state, settings
                    )
                return _json_response(data)

            payload = request.get_json(silent=True) or {}
            current = _raw_stack_settings()
            processor = _raw_stack_processor(create=False)
            if payload.get("reset_defaults"):
                if processor is not None:
                    processor.reset()
                settings = save_settings_to_config(
                    config.Config(), default_settings_for_config(config.Config())
                )
                if hasattr(server_instance.shared_state, "set_livecam_settings"):
                    server_instance.shared_state.set_livecam_settings(settings)
                if hasattr(server_instance.shared_state, "set_raw_live_frame"):
                    server_instance.shared_state.set_raw_live_frame(None)
                data = disabled_status(settings)
                data["message"] = "LiveCam settings reset to defaults"
                return _json_response(data)

            if payload.get("reset_stack") and processor is not None:
                processor.reset()

            updates = {
                key: value
                for key, value in payload.items()
                if key in current and key not in {"reset_stack", "reset_defaults"}
            }
            settings = normalize_settings({**current, **updates})
            settings = save_settings_to_config(config.Config(), settings)
            if hasattr(server_instance.shared_state, "set_livecam_settings"):
                server_instance.shared_state.set_livecam_settings(settings)
            if not settings["processing_enabled"] and hasattr(
                server_instance.shared_state, "set_raw_live_frame"
            ):
                server_instance.shared_state.set_raw_live_frame(None)
            if (
                not settings["processing_enabled"] or not settings["stack_enabled"]
            ) and processor is not None:
                processor.reset()
            if (
                settings["input_frame_source"] != current.get("input_frame_source")
                or settings["stack_mode"] != current.get("stack_mode")
                or settings["stack_frame_limit"] != current.get("stack_frame_limit")
            ) and processor is not None:
                processor.reset()

            if not settings["processing_enabled"]:
                data = disabled_status(settings)
            else:
                data = _raw_stack_processor().status(
                    server_instance.shared_state, settings
                )
            data["message"] = "LiveCam settings updated"
            return _json_response(data)
        except Exception as e:
            logger.error("api/camera/raw-stack/control error: %s", e)
            return _json_response({"error": str(e)}, 500)

    def _camera_type():
        """Sensor id ("imx462", ...) or None when no camera has reported yet."""
        try:
            return server_instance.shared_state.camera_type()
        except Exception:
            return None

    def _camera_profile_gain():
        """Analog gain the current camera profile defaults to ("Profile")."""
        try:
            from PiFinder.sqm.camera_profiles import get_camera_profile

            camera_type = _camera_type()
            if not camera_type:
                return None
            return float(get_camera_profile(camera_type).analog_gain)
        except Exception:
            return None

    def _camera_controls_payload(message=None) -> dict:
        """Current camera exposure/gain state plus the choices the UI offers.

        ``requested`` values come from config (what was asked for), ``actual``
        values from the last captured frame's metadata (what the camera
        applied, after driver clamping and auto-exposure adjustment).
        """
        cfg = config.Config()
        requested_exposure = cfg.get_option("camera_exp")

        try:
            metadata = server_instance.shared_state.last_image_metadata() or {}
        except Exception:
            metadata = {}

        actual_exposure = metadata.get(
            "actual_exposure_us", metadata.get("exposure_time")
        )
        actual_gain = metadata.get("actual_gain", metadata.get("gain"))
        profile_gain = _camera_profile_gain()

        data = {
            # No queue means this web server is not attached to a camera
            # process (standalone/test runs), so commands would be dropped.
            "available": getattr(server_instance, "camera_command_queue", None)
            is not None,
            "camera_type": _camera_type(),
            "exposure": {
                "mode": camera_controls.exposure_mode(requested_exposure),
                "requested": requested_exposure,
                "actual_us": actual_exposure,
                "presets_us": list(camera_controls.EXPOSURE_PRESETS_US),
                "min_us": camera_controls.MIN_EXPOSURE_US,
                "max_us": camera_controls.MAX_EXPOSURE_US,
            },
            "gain": {
                # Runtime gain lives in the camera process and is not
                # persisted, so the applied value from frame metadata is the
                # only reading available here.
                "actual": actual_gain,
                "requested": metadata.get("gain"),
                "mode": metadata.get("gain_mode"),
                "profile_gain": profile_gain,
                "presets": list(camera_controls.GAIN_PRESETS),
                "min": camera_controls.MIN_GAIN,
                "max": camera_controls.MAX_GAIN,
            },
            "capture_pipeline": {
                "frame_id": metadata.get("frame_id"),
                "sensor_timestamp_ns": metadata.get("sensor_timestamp_ns"),
                **dict(metadata.get("capture_pipeline") or {}),
            },
            "auto_star_control": dict(metadata.get("auto_star_control") or {}),
        }
        if message:
            data["message"] = message
        return data

    @app.route("/api/camera/controls", methods=["GET", "POST"])
    def api_camera_controls():
        """Read or set the camera exposure and gain.

        These are the same global camera settings the on-device Camera Exp /
        Camera Gain menus drive -- there is one camera, and plate solving uses
        the same frames the LiveCam preview does.

        POST body (both keys optional, at least one required):
          {"exposure": 400000 | "auto" | "auto_star", "gain": 20 | "profile"}
        """
        try:
            if request.method == "GET":
                return _json_response(_camera_controls_payload())

            camera_queue = getattr(server_instance, "camera_command_queue", None)
            if camera_queue is None:
                return _json_response(
                    {"error": "Camera command queue unavailable"}, 503
                )

            payload = request.get_json(silent=True) or {}
            if "exposure" not in payload and "gain" not in payload:
                return _json_response(
                    {"error": "Provide 'exposure' and/or 'gain'"}, 400
                )

            commands = []
            notes = []
            applied = {}
            try:
                if "exposure" in payload:
                    exposure, note = camera_controls.normalize_exposure(
                        payload["exposure"]
                    )
                    commands.append(camera_controls.exposure_command(exposure))
                    applied["exposure"] = exposure
                    if note:
                        notes.append(note)
                if "gain" in payload:
                    gain, note = camera_controls.normalize_gain(payload["gain"])
                    commands.append(camera_controls.gain_command(gain))
                    applied["gain"] = gain
                    if note:
                        notes.append(note)
            except ValueError as e:
                return _json_response({"error": str(e)}, 400)

            # Record the exposure before queueing, exactly like the Camera Exp
            # menu does (ui/text_menu.py writes config_option, then its
            # post_callback queues set_exp). The camera process saves it again
            # when it applies the command, but that can be a while on an idle
            # unit -- it only drains the queue once per ~60 loop passes while
            # asleep -- and until then every reader would still report the old
            # exposure. Gain is deliberately not recorded: the Camera Gain menu
            # does not write config either (see camera_interface set_gain).
            if "exposure" in applied:
                config.Config().set_option("camera_exp", applied["exposure"])

            for command in commands:
                camera_queue.put(command)
                logger.info("api/camera/controls queued: %s", command)

            # The camera applies these on its next loop pass, so the payload
            # below still reports the previous frame's metadata; the requested
            # exposure is already the new one.
            data = _camera_controls_payload(
                "; ".join(notes) if notes else "Camera settings sent"
            )
            data["applied"] = applied
            data["notes"] = notes
            return _json_response(data)
        except Exception as e:
            logger.error("api/camera/controls error: %s", e)
            return _json_response({"error": str(e)}, 500)

    # ───────────────────────────────────────────────
    # 4. Lightweight control endpoints (optional, for remote triggering by OpenClaw)
    # ───────────────────────────────────────────────

    @app.route("/api/key", methods=["POST"])
    def api_key():
        """Simulate button input. JSON body: {"button": "UP"} or {"button": 1}"""
        try:
            body = request.get_json(silent=True)
            if not body or "button" not in body:
                return _json_response({"error": "Missing 'button' field"}, 400)
            btn = body["button"]
            # Reuse server_instance's button_dict, if it exists
            bd = getattr(server_instance, "button_dict", {})
            if isinstance(btn, str) and btn in bd:
                server_instance.keyboard_queue.put(bd[btn])
            else:
                server_instance.keyboard_queue.put(int(btn))
            return _json_response({"success": True, "button": btn})
        except Exception as e:
            logger.error("api/key error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        """Cleanly shut down the entire PiFinder application.

        PiFinder's normal shutdown is driven by a terminal Ctrl-C: SIGINT is
        delivered to the *whole* foreground process group at once, so every
        child (camera, solver, integrator, imu, web server, multiprocessing
        helpers) exits from its own KeyboardInterrupt and the main process's
        .join() calls return. Most children run bare ``while True`` loops and
        neither catch KeyboardInterrupt nor watch a stop flag, so signalling
        only the main process would leave it hanging in .join() forever.

        This handler runs inside the web-server child, so ``os.getpgid(0)`` is
        the PiFinder process group. Signalling that group reproduces the Ctrl-C
        path. The signal is fired from a short-lived timer thread so this HTTP
        response can flush before the server process itself is torn down.

        For automation that launched PiFinder in its own session (the expected
        case), this group is isolated from the launcher, so the launcher
        survives and can escalate to SIGTERM/SIGKILL if a child still stalls.

        Body (optional JSON): {"delay": <seconds before signalling, default 0.5>}
        """
        import os
        import signal
        import threading

        try:
            body = request.get_json(silent=True) or {}
            delay = float(body.get("delay", 0.5))
        except Exception:
            delay = 0.5
        # Keep the delay sane: long enough to flush the response, not so long
        # that an automated stop appears to hang.
        delay = min(max(delay, 0.0), 5.0)

        def _shutdown():
            try:
                pgid = os.getpgid(0)
                logger.info("api/stop: sending SIGINT to process group %s", pgid)
                os.killpg(pgid, signal.SIGINT)
            except Exception:
                logger.exception("api/stop: killpg failed; signalling self instead")
                try:
                    os.kill(os.getpid(), signal.SIGINT)
                except Exception:
                    logger.exception("api/stop: self-signal failed")

        threading.Timer(delay, _shutdown).start()
        return _json_response(
            {"success": True, "note": "Shutting down MFNavis", "delay": delay}
        )

    @app.route("/api/mount/track_freq", methods=["GET", "POST"])
    def api_mount_track_freq():
        """Get or set the mount's non-sidereal tracking frequency.

        GET returns the desired frequency from the mount-control status file
        plus conversion constants.

        POST accepts one of (first match wins), all with optional "label":
          {"reset": true}                    -> back to sidereal
          {"hz": 66.0}                       -> frequency directly
          {"arcsec_per_s": 15.09}            -> absolute RA tracking rate
          {"offset_arcsec_per_s": 0.05}      -> target dRA/dt relative to stars

        The command is queued to the mount-control process; the applied state
        appears in GET / the status file once processed.
        """
        from PiFinder import nonsidereal

        status_path = utils.runtime_dir / "mount_control_status.json"

        def _mount_status() -> dict:
            try:
                with open(status_path, "r", encoding="utf-8") as status_in:
                    return json.load(status_in)
            except (OSError, ValueError):
                return {}

        if request.method == "GET":
            status = _mount_status()
            hz = status.get("track_freq_hz")
            return _json_response(
                {
                    "active": hz is not None,
                    "hz": hz,
                    "arcsec_per_s": status.get("track_freq_arcsec_s"),
                    "label": status.get("track_freq_label"),
                    "sidereal_hz": nonsidereal.SIDEREAL_FREQ_HZ,
                    "sidereal_arcsec_per_s": nonsidereal.SIDEREAL_RATE_ARCSEC_S,
                    "accepted_hz_range": [
                        nonsidereal.MIN_FREQ_HZ,
                        nonsidereal.MAX_FREQ_HZ,
                    ],
                    "mount_state": status.get("state"),
                }
            )

        mount_queue = getattr(server_instance, "mountcontrol_queue", None)
        if mount_queue is None:
            return _json_response({"error": "Mount control not available"}, 503)

        body = request.get_json(silent=True) or {}
        label = str(body.get("label", ""))

        if body.get("reset"):
            mount_queue.put({"type": "reset_track_freq"})
            return _json_response({"success": True, "queued": "reset_track_freq"})

        if "hz" in body:
            hz = float(body["hz"])
        elif "arcsec_per_s" in body:
            hz = nonsidereal.hz_from_rate(float(body["arcsec_per_s"]))
        elif "offset_arcsec_per_s" in body:
            hz = nonsidereal.hz_from_offset(float(body["offset_arcsec_per_s"]))
        else:
            return _json_response(
                {
                    "error": "Provide one of: reset, hz, arcsec_per_s, "
                    "offset_arcsec_per_s"
                },
                400,
            )

        clamped, was_clamped = nonsidereal.clamp_hz(hz)
        mount_queue.put({"type": "set_track_freq", "hz": clamped, "label": label})
        return _json_response(
            {
                "success": True,
                "queued": "set_track_freq",
                "hz": clamped,
                "arcsec_per_s": nonsidereal.rate_from_hz(clamped),
                "clamped": was_clamped,
                "label": label,
            }
        )

    logger.info(
        "MFNavis API extensions registered (%s auth)",
        "with" if require_auth else "without",
    )


def _get_version(server_instance) -> str:
    """Try to read the MFNavis software version"""
    try:
        version_txt = getattr(server_instance, "version_txt", None)
        if version_txt:
            with open(version_txt, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return "Unknown"


def _safe_json_value(value):
    """
    Convert pandas / NumPy / NaN objects into JSON-serializable objects.
    """
    try:
        import math
        import numpy as np

        if value is None:
            return None

        # numpy scalar
        if isinstance(value, np.generic):
            value = value.item()

        # NaN / inf
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None

        # Basic built-in types
        if isinstance(value, (str, int, float, bool)):
            return value

        # list / tuple
        if isinstance(value, (list, tuple)):
            return [_safe_json_value(v) for v in value]

        # dict
        if isinstance(value, dict):
            return {str(k): _safe_json_value(v) for k, v in value.items()}

        return str(value)

    except Exception:
        return str(value)


def _guess_star_name(item):
    """
    Try to infer the star name from the fields in visible_stars.
    Different PiFinder versions may use slightly different catalog field names,
    so try several possible field names.。
    """
    name_keys = [
        "common_name",
        "name",
        "proper",
        "proper_name",
        "bayer",
        "bayer_name",
        "bayer_or_flamsteed",
        "label",
        "star_name",
        "hr",
        "hr_id",
        "hip",
        "hip_id",
        "hd",
        "hd_id",
    ]

    for key in name_keys:
        value = item.get(key)
        if value not in (None, "", "nan", "None"):
            return str(value)

    return None


def _extract_mag_value(item):
    """
    Extract the magnitude from a star dictionary.
    """
    for key in ("vmag", "mag", "magnitude", "Vmag", "V"):
        if key in item:
            try:
                return float(item[key])
            except Exception:
                return None
    return None


class _ApiGrayColors:
    """
    Minimal colors object used by PiFinder.plot.Starfield.

    Starfield.__init__ calls colors.get(64) and colors.get(256).
    For API-side star chart re-rendering, we do not need the full UI theme colors;
    we only need to return a valid RGB tuple.
    """

    def get(self, value):
        try:
            v = int(value)
        except Exception:
            v = 255

        if v < 0:
            v = 0
        if v > 255:
            v = 255

        return (v, v, v)


def _get_api_starfield(
    server_instance,
    resolution=(1088, 1088),
    mag_limit=7,
    fov=10.2,
):
    """
    Get or create the API-specific Starfield object.

    Why cache it?
        Starfield initialization loads the Hipparcos catalog and constellation line data,
        so recreating it for every request would be relatively slow.

    Why not look for it in server_instance?
        PiFinder's Web Server object usually does not directly hold the align app's starfield,
        so creating one in the API layer is more stable.
    """
    cache_key = (
        int(resolution[0]),
        int(resolution[1]),
        float(mag_limit),
        float(fov),
    )

    cached_key = getattr(server_instance, "_api_starfield_cache_key", None)
    cached_obj = getattr(server_instance, "_api_starfield_cache", None)

    if cached_key == cache_key and cached_obj is not None:
        return cached_obj

    from PiFinder.plot import Starfield

    colors = _ApiGrayColors()

    starfield = Starfield(
        colors=colors,
        resolution=resolution,
        mag_limit=mag_limit,
        fov=fov,
    )

    server_instance._api_starfield_cache_key = cache_key
    server_instance._api_starfield_cache = starfield

    return starfield
