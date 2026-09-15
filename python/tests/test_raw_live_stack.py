import io
import json
from types import SimpleNamespace

import numpy as np
from PIL import Image

from PiFinder.raw_live_stack import (
    DisplayFrameBuilder,
    SOURCE_CROPPED,
    SOURCE_ORIGINAL,
    SOURCE_STAR_ONLY,
    RawLiveStackProcessor,
    download_color_mode,
    download_image_format,
    normalize_settings,
    publish_selected_frame,
    publish_solver_preprocessed_frame,
)
from PiFinder.livecam_config import processing_enabled
from PiFinder.livecam_config import (
    CONFIG_PREFIX,
    DEFAULT_SETTINGS,
    default_settings_for_config,
    save_settings_to_config,
    settings_from_config,
)
from PiFinder.sqm.camera_profiles import CameraProfile


class DummySharedState:
    def __init__(self):
        self._frame = None
        self._solver_preprocessed_frame = None
        self._solver_preprocess_status = {
            "enabled": False,
            "state": "disabled",
            "frame_count": 0,
        }
        self._sep_overlay = None
        self.set_calls = 0

    def raw_live_frame(self):
        return self._frame

    def set_raw_live_frame(self, value):
        self.set_calls += 1
        self._frame = value

    def solver_preprocessed_frame(self):
        return self._solver_preprocessed_frame

    def solver_preprocessed_frame_info(self):
        if not self._solver_preprocessed_frame:
            return None
        return self._solver_preprocessed_frame.get("info")

    def set_solver_preprocessed_frame(self, value):
        self._solver_preprocessed_frame = value

    def solver_preprocess_status(self):
        return dict(self._solver_preprocess_status)

    def set_solver_preprocess_status(self, value):
        self._solver_preprocess_status = dict(value)

    def sep_overlay(self):
        return self._sep_overlay

    def set_sep_overlay(self, value):
        self._sep_overlay = value


class DummyConfig:
    def __init__(self, options=None):
        self.options = options or {}

    def get_option(self, key, default=None):
        return self.options.get(key, default)


def _profile(rotation_90=0):
    return CameraProfile(
        format="R10",
        raw_size=(4, 3),
        analog_gain=1.0,
        crop_y=(1, 1),
        crop_x=(1, 1),
        rotation_90=rotation_90,
    )


def _bayer_profile():
    return CameraProfile(
        format="SRGGB12",
        raw_size=(4, 4),
        analog_gain=1.0,
        crop_y=(0, 0),
        crop_x=(0, 0),
        rotation_90=0,
    )


def _mono_bayer_profile():
    """The imx462 case: SRGGB12 driver label on a sensor that measures as
    true mono (impl doc §6.4)."""
    return CameraProfile(
        format="SRGGB12",
        raw_size=(4, 4),
        analog_gain=1.0,
        crop_y=(0, 0),
        crop_x=(0, 0),
        rotation_90=0,
        mono=True,
    )


def test_publish_disabled_does_not_touch_shared_frame():
    shared = DummySharedState()
    shared.set_raw_live_frame({"frame": np.ones((2, 2), dtype=np.uint16)})
    set_calls = shared.set_calls

    publish_selected_frame(
        shared,
        {"processing_enabled": False},
        _profile(),
        "test",
        np.ones((3, 4), dtype=np.uint16),
        np.ones((1, 2), dtype=np.uint16),
    )

    assert shared.raw_live_frame() is not None
    assert shared.set_calls == set_calls


def test_processing_enabled_coerces_string_values():
    assert processing_enabled({"processing_enabled": "true"})
    assert not processing_enabled({"processing_enabled": "false"})


def test_solver_preprocess_enabled_is_normalized_as_boolean():
    assert normalize_settings({"solver_preprocess_enabled": "true"})[
        "solver_preprocess_enabled"
    ]
    assert not normalize_settings({"solver_preprocess_enabled": "false"})[
        "solver_preprocess_enabled"
    ]


def test_star_only_is_a_valid_livecam_input_source():
    settings = normalize_settings({"input_frame_source": SOURCE_STAR_ONLY})

    assert settings["input_frame_source"] == SOURCE_STAR_ONLY


def test_star_only_uses_already_warm_solver_preprocessed_frame():
    shared = DummySharedState()
    raw = np.full((4, 4), 10, dtype=np.uint16)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _profile(),
        "test",
        raw,
        raw,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    preprocessed = np.full((4, 4), 200, dtype=np.uint16)
    publish_solver_preprocessed_frame(
        shared,
        preprocessed,
        _profile(),
        "test",
        {"exposure_end": 2.0, "frame_id": 2, "gain": 3.0},
        preprocess_frames=5,
    )
    shared.set_solver_preprocess_status(
        {
            "enabled": True,
            "state": "ready",
            "frame_count": 5,
            "frame_limit": 5,
            "error": None,
        }
    )
    settings = normalize_settings(
        {
            "processing_enabled": True,
            "solver_preprocess_enabled": True,
            "input_frame_source": SOURCE_STAR_ONLY,
            "web_image_format": "png",
        }
    )
    processor = RawLiveStackProcessor()

    status = processor.status(shared, settings)
    rendered = processor.render_raw_tiff(shared, settings)

    assert status["frame"]["frame_id"] == 2
    assert status["frame"]["producer"] == "solver_preprocessor"
    assert status["frame"]["preprocess_frames"] == 5
    assert status["preprocess"]["state"] == "ready"
    assert rendered is not None
    image = np.asarray(Image.open(io.BytesIO(rendered[0])))
    np.testing.assert_array_equal(image, preprocessed)


def test_star_only_status_reports_solver_warmup_without_stale_raw_frame():
    shared = DummySharedState()
    raw = np.full((4, 4), 10, dtype=np.uint16)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _profile(),
        "test",
        raw,
        raw,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    shared.set_solver_preprocess_status(
        {
            "enabled": True,
            "state": "warming",
            "frame_count": 1,
            "frame_limit": 5,
            "error": None,
        }
    )
    settings = normalize_settings(
        {
            "processing_enabled": True,
            "solver_preprocess_enabled": True,
            "input_frame_source": SOURCE_STAR_ONLY,
        }
    )

    status = RawLiveStackProcessor().status(shared, settings)

    assert status["has_frame"] is False
    assert status["frame"] is None
    assert status["preprocess"]["state"] == "warming"
    assert status["preprocess"]["frame_count"] == 1


def test_star_only_uses_camera_fallback_when_solver_preprocessing_is_off():
    shared = DummySharedState()
    fallback = np.full((4, 4), 33, dtype=np.uint16)
    publish_selected_frame(
        shared,
        {
            "processing_enabled": True,
            "input_frame_source": SOURCE_STAR_ONLY,
        },
        _profile(),
        "test",
        fallback,
        fallback,
        metadata={"timestamp": 1.0, "frame_id": 7},
        stage_frames={SOURCE_STAR_ONLY: fallback},
    )
    settings = normalize_settings(
        {
            "processing_enabled": True,
            "solver_preprocess_enabled": False,
            "input_frame_source": SOURCE_STAR_ONLY,
        }
    )

    status = RawLiveStackProcessor().status(shared, settings)

    assert status["has_frame"] is True
    assert status["frame"]["frame_id"] == 7
    assert status["preprocess"] is None


def test_default_settings_for_config_restores_livecam_defaults():
    defaults = default_settings_for_config(DummyConfig({"camera_rotation": 90}))

    for key, value in DEFAULT_SETTINGS.items():
        assert defaults[key] == value
    assert defaults["display_rotation_degrees"] == 270


class WritableConfig:
    """Config double that records set_option writes."""

    def __init__(self, options=None):
        self.options = dict(options or {})

    def get_option(self, key, default=None):
        return self.options.get(key, default)

    def set_option(self, key, value):
        self.options[key] = value


def test_processing_enabled_is_never_read_from_config():
    # Even if a stale persisted value says on, a fresh session must start off.
    cfg = WritableConfig({f"{CONFIG_PREFIX}processing_enabled": True})

    settings = settings_from_config(cfg)

    assert settings["processing_enabled"] is False


def test_processing_enabled_is_not_persisted():
    cfg = WritableConfig()

    returned = save_settings_to_config(cfg, {"processing_enabled": True})

    # Returned/live settings keep the toggle for the running session ...
    assert returned["processing_enabled"] is True
    # ... but it is never written to the persisted config.
    assert f"{CONFIG_PREFIX}processing_enabled" not in cfg.options
    # Other settings still persist normally.
    assert cfg.options[f"{CONFIG_PREFIX}stack_mode"] == "mean"


def test_solver_preprocess_enabled_defaults_on_and_is_persisted():
    assert settings_from_config(WritableConfig())["solver_preprocess_enabled"] is True

    stored_off = WritableConfig({f"{CONFIG_PREFIX}solver_preprocess_enabled": False})
    assert settings_from_config(stored_off)["solver_preprocess_enabled"] is False

    cfg = WritableConfig()
    returned = save_settings_to_config(cfg, {"solver_preprocess_enabled": False})
    assert returned["solver_preprocess_enabled"] is False
    assert cfg.options[f"{CONFIG_PREFIX}solver_preprocess_enabled"] is False


def test_publish_original_rotates_without_crop():
    shared = DummySharedState()
    original = np.arange(12, dtype=np.uint16).reshape(3, 4)
    cropped = np.array([[99, 100]], dtype=np.uint16)

    publish_selected_frame(
        shared,
        {"processing_enabled": True, "input_frame_source": SOURCE_ORIGINAL},
        _profile(rotation_90=1),
        "test",
        original,
        cropped,
    )

    entry = shared.raw_live_frame()
    assert entry["info"]["source"] == SOURCE_ORIGINAL
    assert entry["frame"].shape == (4, 3)
    np.testing.assert_array_equal(entry["frame"], np.rot90(original, 1))


def test_publish_star_only_rotates_like_original_raw():
    shared = DummySharedState()
    star_only = np.arange(12, dtype=np.uint16).reshape(3, 4)

    publish_selected_frame(
        shared,
        {"processing_enabled": True, "input_frame_source": SOURCE_STAR_ONLY},
        _profile(rotation_90=1),
        "test",
        None,
        None,
        stage_frames={SOURCE_STAR_ONLY: star_only},
    )

    entry = shared.raw_live_frame()
    assert entry["info"]["source"] == SOURCE_STAR_ONLY
    assert entry["info"]["rotation_90"] == 1
    np.testing.assert_array_equal(entry["frame"], np.rot90(star_only, 1))


def test_publish_stage_source_uses_stage_frame():
    shared = DummySharedState()
    stage = np.full((2, 2), 7.5, dtype=np.float32)

    publish_selected_frame(
        shared,
        {"processing_enabled": True, "input_frame_source": "bias_subtracted"},
        _profile(),
        "test",
        np.ones((3, 4), dtype=np.uint16),
        np.ones((1, 2), dtype=np.uint16),
        stage_frames={"bias_subtracted": stage},
    )

    entry = shared.raw_live_frame()
    assert entry["info"]["source"] == "bias_subtracted"
    assert np.array_equal(entry["frame"], stage)
    # Float stages are still in sensor ADU: the profile format is kept.
    assert entry["info"]["raw_format"] == "R10"


def test_publish_uint8_stage_drops_raw_format():
    """8-bit stages are not ADU; Raw Display must scale by dtype, not
    the sensor bit depth."""
    shared = DummySharedState()

    publish_selected_frame(
        shared,
        {"processing_enabled": True, "input_frame_source": "solver_input"},
        _profile(),
        "test",
        None,
        None,
        stage_frames={"solver_input": np.full((2, 2), 200, dtype=np.uint8)},
    )

    assert shared.raw_live_frame()["info"]["raw_format"] is None


def test_publish_stage_source_without_frame_publishes_nothing():
    """capture() does not have solver_input; the loop publishes it later.
    A stage-selecting call site missing that stage must stay silent."""
    shared = DummySharedState()

    publish_selected_frame(
        shared,
        {"processing_enabled": True, "input_frame_source": "solver_input"},
        _profile(),
        "test",
        np.ones((3, 4), dtype=np.uint16),
        np.ones((1, 2), dtype=np.uint16),
        stage_frames={},
    )

    assert shared.raw_live_frame() is None


def test_stage_sources_survive_normalize():
    for source in (
        "bias_subtracted",
        "digital_gain",
        "stretched_8bit",
        "resized_512",
        "solver_input",
    ):
        assert (
            normalize_settings({"input_frame_source": source})["input_frame_source"]
            == source
        )


def test_publish_cropped_uses_cropped_frame():
    shared = DummySharedState()
    original = np.arange(12, dtype=np.uint16).reshape(3, 4)
    cropped = np.array([[99, 100]], dtype=np.uint16)

    publish_selected_frame(
        shared,
        {"processing_enabled": True, "input_frame_source": SOURCE_CROPPED},
        _profile(rotation_90=1),
        "test",
        original,
        cropped,
    )

    entry = shared.raw_live_frame()
    assert entry["info"]["source"] == SOURCE_CROPPED
    np.testing.assert_array_equal(entry["frame"], cropped)


def test_publish_applies_display_rotation_after_source_selection():
    shared = DummySharedState()
    original = np.arange(12, dtype=np.uint16).reshape(3, 4)
    cropped = np.array([[1, 2], [3, 4]], dtype=np.uint16)

    publish_selected_frame(
        shared,
        {
            "processing_enabled": True,
            "input_frame_source": SOURCE_CROPPED,
            "display_rotation_degrees": 90,
        },
        _profile(),
        "test",
        original,
        cropped,
    )

    entry = shared.raw_live_frame()
    np.testing.assert_array_equal(entry["frame"], np.rot90(cropped, 1))
    assert entry["info"]["display_rotation_degrees"] == 90


def test_processor_renders_selected_raw_image():
    shared = DummySharedState()
    frame = np.arange(100, dtype=np.uint16).reshape(10, 10)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _profile(),
        "test",
        frame,
        frame[2:8, 2:8],
    )

    settings = normalize_settings(
        {
            "processing_enabled": True,
            "display_size": 64,
            "web_image_format": "png",
        }
    )
    processor = RawLiveStackProcessor()

    rendered = processor.render_image(shared, settings)

    assert rendered is not None
    image_bytes, mimetype = rendered
    assert mimetype == "image/png"
    assert image_bytes.startswith(b"\x89PNG")


def test_display_size_zero_keeps_original_display_dimensions():
    builder = DisplayFrameBuilder(display_size=0)

    image = builder.build(np.arange(50, dtype=np.uint16).reshape(5, 10))

    assert image.size == (10, 5)


def test_raw_display_is_linear_not_normalized():
    """Raw Display maps ADU linearly: doubling the signal doubles the pixels.

    The percentile stretch renormalizes every frame to the same display
    range, which cancels a global multiplication -- with it applied to
    Raw Display too, changing gain/exposure was invisible in the preview.
    """
    builder = DisplayFrameBuilder(
        preview_mode="raw_display", color_mode="color", raw_format="SRGGB12"
    )
    base = np.full((8, 8), 400, dtype=np.uint16)

    dim = np.asarray(builder.build(base).convert("L"), dtype=float).mean()
    bright = np.asarray(builder.build(base * 2).convert("L"), dtype=float).mean()

    # 400/4095*255 ~ 24.9, 800/4095*255 ~ 49.8
    assert 23 <= dim <= 27
    assert 48 <= bright <= 52


def test_stretched_mode_still_normalizes():
    """The stretched preview keeps the old per-frame normalization."""
    builder = DisplayFrameBuilder(preview_mode="stretched", color_mode="color")
    frame = np.arange(64, dtype=np.uint16).reshape(8, 8)

    dim = np.asarray(builder.build(frame).convert("L"), dtype=float).mean()
    bright = np.asarray(builder.build(frame * 8).convert("L"), dtype=float).mean()

    assert abs(dim - bright) < 2  # renormalized to the same display range


def test_raw_display_bit_depth_falls_back_to_dtype():
    """No parseable raw format: uint8 scales by 255, uint16 by 65535."""
    builder = DisplayFrameBuilder(
        preview_mode="raw_display", color_mode="color", raw_format=None
    )
    eight_bit = np.full((4, 4), 128, dtype=np.uint8)
    mean8 = np.asarray(builder.build(eight_bit).convert("L"), dtype=float).mean()
    assert 126 <= mean8 <= 130

    sixteen_bit = np.full((4, 4), 32768, dtype=np.uint16)
    mean16 = np.asarray(builder.build(sixteen_bit).convert("L"), dtype=float).mean()
    assert 126 <= mean16 <= 130


def test_stack_frame_limit_allows_large_livecam_windows():
    assert normalize_settings({"stack_frame_limit": 999})["stack_frame_limit"] == 500
    assert normalize_settings({"stack_frame_limit": 0})["stack_frame_limit"] == 1


def test_stack_enabled_follows_output_source():
    latest = normalize_settings(
        {"output_source": "latest_selected_raw", "stack_enabled": True}
    )
    stacked = normalize_settings({"output_source": "stack", "stack_enabled": False})

    assert latest["stack_enabled"] is False
    assert stacked["stack_enabled"] is True


def test_processor_keeps_rolling_stack_frame_limit():
    shared = DummySharedState()
    processor = RawLiveStackProcessor()
    settings = normalize_settings(
        {
            "processing_enabled": True,
            "stack_enabled": True,
            "output_source": "stack",
            "stack_mode": "mean",
            "stack_frame_limit": 2,
            "display_size": 64,
        }
    )

    for frame_id, value in enumerate([10, 20, 30], start=1):
        frame = np.full((4, 4), value, dtype=np.uint16)
        publish_selected_frame(
            shared,
            {"processing_enabled": True},
            _profile(),
            "test",
            frame,
            frame,
            metadata={"timestamp": float(frame_id), "frame_id": frame_id},
        )
        assert processor.render_image(shared, settings) is not None

    status = processor.status(shared, settings)
    assert status["stack"]["frame_count"] == 2
    assert status["stack"]["accepted_count"] == 3
    np.testing.assert_allclose(processor._stack_display_frame(settings), 25.0)


def test_theme_color_mode_tints_luminance_image():
    builder = DisplayFrameBuilder(
        display_size=4,
        color_mode="theme",
        web_theme="red",
    )

    image = builder.build(np.arange(16, dtype=np.uint8).reshape(4, 4))

    assert image.mode == "RGB"
    r, g, b = image.getpixel((3, 3))
    assert r > g > b


def test_download_honors_selected_format():
    """web_image_format is download-only (live preview is always JPEG),
    so the chosen format must come back verbatim -- including webp."""
    assert download_image_format({"web_image_format": "webp"}) == "webp"
    assert download_image_format({"web_image_format": "jpeg"}) == "jpeg"
    assert download_image_format({"web_image_format": "png"}) == "png"


def test_download_is_grayscale_not_theme_tinted():
    """Mono-sensor downloads drop both the theme tint and the fabricated
    chroma: on a sensor that measures as true mono a debayered RGB download
    is colour noise (impl doc §6.4). The preview keeps its theme tint.
    Declared colour variants keep chroma instead -- see
    test_colour_variant_download_keeps_real_chroma."""
    shared = DummySharedState()
    frame = np.arange(100, dtype=np.uint16).reshape(10, 10)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _mono_bayer_profile(),
        "test",
        frame,
        frame,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    settings = normalize_settings(
        {
            "processing_enabled": True,
            "color_mode": "theme",
            "web_image_format": "png",
            "display_size": 64,
        }
    )
    processor = RawLiveStackProcessor()

    themed_bytes, _ = processor.render_image(shared, settings, web_theme="red")
    download_bytes, _ = processor.render_image(
        shared,
        settings,
        image_format="png",
        color_mode=download_color_mode(shared),
        web_theme="red",
        accept_new_frame=False,
    )

    assert Image.open(io.BytesIO(themed_bytes)).mode == "RGB"
    assert Image.open(io.BytesIO(download_bytes)).mode == "L"


def test_mono_color_mode_builds_grayscale_from_bayer_labelled_frame():
    builder = DisplayFrameBuilder(color_mode="mono", raw_format="SRGGB12")
    image = builder.build(np.arange(64, dtype=np.uint16).reshape(8, 8))
    assert image.mode == "L"


def test_mono_sensor_preview_keeps_full_resolution():
    """A mono sensor's Bayer label must not trigger the debayer: it halves
    the resolution and fabricates chroma from noise. The full 2D frame goes
    through the display pipeline untouched."""
    shared = DummySharedState()
    frame = np.arange(100, dtype=np.uint16).reshape(10, 10)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _mono_bayer_profile(),
        "test",
        frame,
        frame,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    assert shared.raw_live_frame()["info"]["mono"] is True

    processor = RawLiveStackProcessor()
    settings = normalize_settings(
        {"processing_enabled": True, "web_image_format": "png"}
    )
    themed_bytes, _ = processor.render_image(shared, settings, web_theme="red")
    assert Image.open(io.BytesIO(themed_bytes)).size == (10, 10)  # not (5, 5)

    download_bytes, _ = processor.render_image(
        shared,
        settings,
        image_format="png",
        color_mode=download_color_mode(shared),
        accept_new_frame=False,
    )
    image = Image.open(io.BytesIO(download_bytes))
    assert image.mode == "L"
    assert image.size == (10, 10)


def test_colour_variant_download_keeps_real_chroma():
    """A declared colour variant (CameraProfile.mono False) keeps colour in
    downloads -- the grayscale rule exists for mono sensors whose Bayer label
    would fabricate chroma (§6.4), not for a real CFA."""
    shared = DummySharedState()
    frame = np.arange(100, dtype=np.uint16).reshape(10, 10)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _bayer_profile(),
        "imx462_color",
        frame,
        frame,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    assert shared.raw_live_frame()["info"]["mono"] is False

    processor = RawLiveStackProcessor()
    settings = normalize_settings(
        {"processing_enabled": True, "web_image_format": "png"}
    )
    download_bytes, _ = processor.render_image(
        shared,
        settings,
        image_format="png",
        color_mode=download_color_mode(shared),
        accept_new_frame=False,
    )
    image = Image.open(io.BytesIO(download_bytes))
    assert image.mode == "RGB"
    assert image.size == (5, 5)  # a real CFA debayers to half resolution


def test_real_bayer_sensor_still_debayers_to_half_res():
    builder = DisplayFrameBuilder(color_mode="color", raw_format="SRGGB12")
    image = builder.build(np.arange(100, dtype=np.uint16).reshape(10, 10))
    assert image.mode == "RGB"
    assert image.size == (5, 5)


def test_mono_sensor_bayer_2x2_average_preview_is_reachable():
    """On a Bayer-labelled mono frame the explicit binned preview used to be
    dead code (the forced debayer won first)."""
    builder = DisplayFrameBuilder(
        preview_mode="bayer_2x2_average",
        color_mode="mono",
        raw_format="SRGGB12",
        mono=True,
    )
    image = builder.build(np.arange(100, dtype=np.uint16).reshape(10, 10))
    assert image.mode == "L"
    assert image.size == (5, 5)


OVERLAY_GREEN = (0, 255, 128)
OVERLAY_ORANGE = (255, 150, 0)


def _color_pixels(png_bytes, color):
    arr = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
    ys, xs = np.where(
        (arr[..., 0] == color[0])
        & (arr[..., 1] == color[1])
        & (arr[..., 2] == color[2])
    )
    return np.column_stack((ys, xs))


def _green_pixels(png_bytes):
    return _color_pixels(png_bytes, OVERLAY_GREEN)


def test_sep_overlay_marks_centroid_on_preview():
    shared = DummySharedState()
    frame = np.full((64, 48), 500, dtype=np.uint16)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _mono_bayer_profile(),
        "test",
        frame,
        frame,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    shared.set_sep_overlay(
        {
            "centroids": [[20.0, 30.0]],
            "frame_hw": [64, 48],
            "masked": 0,
            "sigma": 3.5,
            "timestamp": 1.0,
        }
    )
    settings = normalize_settings(
        {"processing_enabled": True, "web_image_format": "png"}
    )
    png, _ = RawLiveStackProcessor().render_image(shared, settings, overlay_sep=True)
    # no matched info -> candidates only: orange, never the trusted green
    assert len(_green_pixels(png)) == 0
    marks = _color_pixels(png, OVERLAY_ORANGE)
    assert len(marks) > 0
    d = np.hypot(marks[:, 0] - 20.0, marks[:, 1] - 30.0)
    # every marker pixel sits on the circle around the centroid
    assert d.max() <= 8.0 and d.min() >= 1.0


def test_sep_overlay_follows_display_rotation():
    """Detection coords are pre-display-rotation; the drawn marker must
    land where np.rot90 moved the pixel (the publish-path rotation)."""
    shared = DummySharedState()
    frame = np.full((64, 48), 500, dtype=np.uint16)
    publish_selected_frame(
        shared,
        {"processing_enabled": True, "display_rotation_degrees": 90},
        _mono_bayer_profile(),
        "test",
        frame,
        frame,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    shared.set_sep_overlay(
        {
            "centroids": [[20.0, 30.0]],
            "frame_hw": [64, 48],
            "masked": 0,
            "sigma": 3.5,
            "timestamp": 1.0,
        }
    )
    settings = normalize_settings(
        {
            "processing_enabled": True,
            "web_image_format": "png",
            "display_rotation_degrees": 90,
        }
    )
    png, _ = RawLiveStackProcessor().render_image(shared, settings, overlay_sep=True)
    marks = _color_pixels(png, OVERLAY_ORANGE)
    assert len(marks) > 0
    # np.rot90 CCW: (y, x) -> (W-1-x, y) on the 48x64 canvas
    ey, ex = 48 - 1 - 30.0, 20.0
    d = np.hypot(marks[:, 0] - ey, marks[:, 1] - ex)
    assert d.max() <= 8.0


def test_sep_overlay_two_tier_marks_matched_and_candidates():
    """With a matched list, confirmed stars draw green and the remaining
    candidates draw orange -- the user can trust green unconditionally."""
    shared = DummySharedState()
    frame = np.full((64, 48), 500, dtype=np.uint16)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _mono_bayer_profile(),
        "test",
        frame,
        frame,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    shared.set_sep_overlay(
        {
            "centroids": [[20.0, 30.0], [45.0, 12.0]],
            "matched": [[20.0, 30.0]],
            "frame_hw": [64, 48],
            "masked": 0,
            "sigma": 4.0,
            "timestamp": 1.0,
        }
    )
    settings = normalize_settings(
        {"processing_enabled": True, "web_image_format": "png"}
    )
    png, _ = RawLiveStackProcessor().render_image(shared, settings, overlay_sep=True)
    arr = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))

    def near(color, ey, ex, r=9):
        ys, xs = np.where(
            (arr[..., 0] == color[0])
            & (arr[..., 1] == color[1])
            & (arr[..., 2] == color[2])
        )
        if len(ys) == 0:
            return False
        return bool((np.hypot(ys - ey, xs - ex) <= r).any())

    assert near((0, 255, 128), 20, 30)  # matched -> green at its position
    assert near((255, 150, 0), 45, 12)  # candidate -> orange
    assert not near((255, 150, 0), 20, 30)  # matched is not double-marked


def test_sep_overlay_skips_stale_detection():
    shared = DummySharedState()
    frame = np.full((64, 48), 500, dtype=np.uint16)
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _mono_bayer_profile(),
        "test",
        frame,
        frame,
        metadata={"timestamp": 100.0, "frame_id": 1},
    )
    shared.set_sep_overlay(
        {
            "centroids": [[20.0, 30.0]],
            "frame_hw": [64, 48],
            "masked": 0,
            "sigma": 3.5,
            "timestamp": 1.0,  # 99 s older than the frame
        }
    )
    settings = normalize_settings(
        {"processing_enabled": True, "web_image_format": "png"}
    )
    png, _ = RawLiveStackProcessor().render_image(shared, settings, overlay_sep=True)
    assert len(_green_pixels(png)) == 0
    assert len(_color_pixels(png, OVERLAY_ORANGE)) == 0


def test_tiff_download_is_lossless_16bit_raw_data():
    """format=tiff exports the raw ADU values: 16-bit, no stretch, no
    debayer -- byte-identical to the sensor data for offline processing."""
    shared = DummySharedState()
    shared.ui_state = lambda: SimpleNamespace(
        target=lambda: SimpleNamespace(
            object_id=9, display_name="saved target", ra=123.4, dec=-12.3
        )
    )
    frame = (np.arange(100, dtype=np.uint16) * 40).reshape(10, 10)  # up to 3960
    publish_selected_frame(
        shared,
        {"processing_enabled": True},
        _bayer_profile(),
        "test",
        frame,
        frame,
        metadata={"timestamp": 1.0, "frame_id": 1},
    )
    processor = RawLiveStackProcessor()
    settings = normalize_settings({"processing_enabled": True})

    rendered = processor.render_raw_tiff(shared, settings)
    assert rendered is not None
    tiff_bytes, mimetype = rendered
    assert mimetype == "image/tiff"
    image = Image.open(io.BytesIO(tiff_bytes))
    metadata = json.loads(image.tag_v2[270])
    assert metadata["input_frame_info"]["frame_id"] == 1
    assert metadata["observation"]["target"]["ra_deg"] == 123.4
    assert metadata["observation"]["pointing"] is None
    assert image.mode in {"I;16", "I"}
    np.testing.assert_array_equal(np.asarray(image, dtype=np.uint16), frame)


def test_tiff_download_of_mean_stack_stays_in_sensor_range():
    shared = DummySharedState()
    processor = RawLiveStackProcessor()
    settings = normalize_settings(
        {
            "processing_enabled": True,
            "stack_enabled": True,
            "output_source": "stack",
            "stack_mode": "mean",
            "stack_frame_limit": 2,
        }
    )
    for frame_id, value in enumerate([100, 300], start=1):
        frame = np.full((4, 4), value, dtype=np.uint16)
        publish_selected_frame(
            shared,
            {"processing_enabled": True},
            _bayer_profile(),
            "test",
            frame,
            frame,
            metadata={"timestamp": float(frame_id), "frame_id": frame_id},
        )
        assert processor.render_image(shared, settings) is not None

    tiff_bytes, _ = processor.render_raw_tiff(shared, settings)
    image = np.asarray(Image.open(io.BytesIO(tiff_bytes)), dtype=np.uint16)
    np.testing.assert_array_equal(image, np.full((4, 4), 200, dtype=np.uint16))


def test_live_view_endpoint_always_streams_jpeg():
    """MF pin: the live preview must not honor web_image_format.

    The /api/camera/raw-stack/image route is a closure inside
    register_api_routes, so pin it at the source level: the live endpoint
    passes an explicit image_format="jpeg" (PNG encoding of the full-size
    frame drops the refresh rate; the setting governs downloads only).
    """
    import inspect

    from PiFinder import api_extensions

    src = inspect.getsource(api_extensions.register_api_routes)
    route_marker = 'raw-stack/image"'
    start = src.index(route_marker)
    end = src.index('@app.route("/api/camera/raw-stack/download")')
    endpoint_src = src[start:end]
    assert 'image_format="jpeg"' in endpoint_src
