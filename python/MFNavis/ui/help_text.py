"""Render editable product help pages on the existing 128-pixel help canvas."""

from PIL import Image, ImageDraw


def render_help_text(text, font):
    # Help artwork uses a fixed 128px canvas even on larger displays.
    font = font.font_variant(size=10)
    image = Image.new("RGB", (128, 128), "black")
    draw = ImageDraw.Draw(image)
    line_height = max(12, font.getbbox("Ag")[3] + 2)
    lines = []
    for paragraph in text.strip().splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and draw.textlength(candidate, font=font) > 120:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    if len(lines) * line_height > 124:
        raise ValueError("Help text exceeds one page; split it into more pages")
    for index, line in enumerate(lines):
        draw.text((4, 2 + index * line_height), line, font=font, fill=(180, 180, 180))
    return image
