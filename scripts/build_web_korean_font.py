"""Build the offline Korean web font from the bundled Sarasa font.

Development-only dependencies: fonttools[woff] (FontTools and Brotli).
Run from any directory: python scripts/build_web_korean_font.py
"""

from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fonts/sarasa-mono-sc-light-nerd-font+patched.ttf"
OUTPUT = ROOT / "python/views/css/mfnavis-korean.woff2"


def main():
    font = TTFont(SOURCE)
    options = subset.Options()
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14, 16, 17]
    options.name_legacy = True
    options.name_languages = [0x409]
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(
        unicodes=set(range(0x1100, 0x1200))
        | set(range(0x3130, 0x3190))
        | set(range(0xAC00, 0xD7B0))
    )
    subsetter.subset(font)
    names = {
        1: "MFNavis Korean",
        2: "Regular",
        3: "MFNavis Korean 1.0",
        4: "MFNavis Korean",
        6: "MFNavisKorean-Regular",
        13: "Licensed under the SIL Open Font License, Version 1.1.",
        14: "https://openfontlicense.org/",
        16: "MFNavis Korean",
        17: "Regular",
    }
    for key, value in names.items():
        font["name"].setName(value, key, 3, 1, 0x409)
    font.flavor = "woff2"
    font.save(OUTPUT)
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
