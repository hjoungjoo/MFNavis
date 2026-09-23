"""MFNavis product identity; upstream package/service identifiers stay stable."""

from pathlib import Path
import re

from PIL import Image, ImageOps

PRODUCT_NAME = "MFNavis"
DISTRIBUTOR = "FNPD 한국"
CREATOR = "MagicFly"
LOGO_PATH = Path(__file__).resolve().parents[2] / "images" / "MFNavis logo.png"


def welcome_image(size, *, top_margin=0):
    """Fit the original logo below the status banner without cropping/stretching."""
    width, height = size
    if width <= 0 or height <= 0 or not 0 <= top_margin < height:
        raise ValueError("Logo canvas and available height must be positive")
    canvas = Image.new("RGB", size, (0, 0, 0))
    with Image.open(LOGO_PATH) as source:
        logo = ImageOps.contain(
            source.convert("RGBA"),
            (width, height - top_margin),
            method=Image.Resampling.LANCZOS,
        )
    canvas.paste(
        logo,
        (
            (width - logo.width) // 2,
            top_margin + (height - top_margin - logo.height) // 2,
        ),
        logo,
    )
    return canvas


def product_label(value):
    """Render legacy protocol/status names without changing their wire values."""
    if not isinstance(value, str):
        return value
    return re.sub("pifinder", PRODUCT_NAME, value, flags=re.IGNORECASE)
