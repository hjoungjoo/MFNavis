"""Build the offline Korean user manual and its original diagram assets.

Run: python3 docs/manual/build_manual.py
Dependencies: Pillow, Markdown. PDF printing uses Chromium separately.
"""

import base64
import html
from pathlib import Path

import markdown
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ASSETS = HERE / "assets"
FONT = ROOT / "fonts/sarasa-mono-sc-light-nerd-font+patched.ttf"
RED = "#a53240"
INK = "#243345"
MUTED = "#596a7b"
LINE = "#ced8e1"
PAPER = "#ffffff"


class Diagram:
    """Keep PNG and editable SVG drawings in the same coordinate system."""

    def __init__(self, width, height, title):
        self.image = Image.new("RGB", (width, height), PAPER)
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" role="img">',
            f"<title>{html.escape(title)}</title>",
            f'<rect width="{width}" height="{height}" fill="white"/>',
        ]

    def rect(self, x, y, w, h, fill=PAPER, outline=LINE, radius=12):
        self.draw.rounded_rectangle(
            (x, y, x + w, y + h), radius=radius, fill=fill, outline=outline, width=2
        )
        self.svg.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'rx="{radius}" fill="{fill}" stroke="{outline}" stroke-width="2"/>'
        )

    def text(self, x, y, value, size=22, color=INK):
        font = ImageFont.truetype(str(FONT), size)
        self.draw.text((x, y), value, font=font, fill=color)
        self.svg.append(
            f'<text x="{x}" y="{y + size}" fill="{color}" '
            f'font-family="DejaVu Sans,Arial,sans-serif" font-size="{size}">'
            f"{html.escape(value)}</text>"
        )

    def line(self, points, color=LINE, width=3):
        self.draw.line(points, fill=color, width=width)
        coords = " ".join(f"{x},{y}" for x, y in points)
        self.svg.append(
            f'<polyline points="{coords}" fill="none" stroke="{color}" '
            f'stroke-width="{width}"/>'
        )

    def save(self, name):
        self.image.save(ASSETS / f"{name}.png")
        (ASSETS / f"{name}.svg").write_text(
            "\n".join(self.svg + ["</svg>"]), encoding="utf-8"
        )


def branches(name, title, rows, footnote=""):
    step = 86
    height = 94 + len(rows) * step + (38 if footnote else 0)
    d = Diagram(1380, height, f"{title} menu structure")
    d.text(
        32,
        20,
        "MFNavis / Menu overview" if title == "MFNavis" else f"MFNavis / {title}",
        28,
        RED,
    )
    center = 82 + (len(rows) - 1) * step / 2 + 26
    d.rect(32, center - 27, 230, 56, RED, RED)
    d.text(49, center - 17, title, 25, PAPER)
    d.line([(262, center), (295, center)])
    d.line([(295, 108), (295, 108 + (len(rows) - 1) * step)])
    for i, (label, descriptions) in enumerate(rows):
        y = 82 + i * step
        d.line([(295, y + 26), (330, y + 26)])
        d.rect(330, y, 285, 56, "#f6f8fa")
        d.text(347, y + 13, label, 23)
        d.line([(615, y + 26), (647, y + 26)])
        for j, description in enumerate(descriptions):
            d.text(663, y + 3 + j * 29, description, 21, MUTED)
    if footnote:
        d.text(32, height - 40, footnote, 19, RED)
    d.save(name)


def make_diagrams():
    branches(
        "menu_overview",
        "MFNavis",
        [
            ("Start", ["Focus / Align / Align (Day) / GPS Status", "INDI *"]),
            ("Chart", ["Live sky chart / Zoom / Center object"]),
            (
                "Objects",
                [
                    "All Filtered / By Catalog / Recent / Obs Lists",
                    "Custom / Name Search / Set Filters",
                ],
            ),
            ("SQM", ["Sky brightness", "Quick Menu: CALIB / SWEEP"]),
            (
                "Settings",
                [
                    "User / Chart / Image / Camera / WiFi / Mount",
                    "INDI Setting * / Advanced / IMU Settings",
                ],
            ),
            (
                "Tools",
                [
                    "Status / Equipment / Place & Time / Console",
                    "Software Upd / Test / Experimental / Power",
                ],
            ),
        ],
        "* Visible only when Mount Control is On. Child lists are abbreviated.",
    )
    branches(
        "start_menu",
        "Start",
        [
            ("Focus", ["Camera focus / HFD / Exposure"]),
            ("Align", ["Select a star / Match eyepiece center"]),
            ("Align (Day)", ["Select a landmark / Save target point"]),
            ("GPS Status", ["Location fix / Satellites"]),
            (
                "INDI *",
                [
                    "STATUS / INIT / Guide",
                    "INIT: Connect / Set Location / Home / Park ...",
                ],
            ),
        ],
        "* Visible only when Mount Control is On.",
    )
    branches(
        "objects_menu",
        "Objects",
        [
            ("All Filtered", ["Filtered objects from selected catalogs"]),
            ("By Catalog", ["Planets / Comets / NGC / Messier", "DSO... / Stars..."]),
            ("Recent", ["Objects viewed during this session"]),
            ("Obs Lists", ["Saved observing lists"]),
            ("Custom", ["Enter RA / Dec"]),
            ("Name Search", ["Enter name / Open results"]),
            (
                "Set Filters",
                ["Reset All / Catalogs / Type", "Altitude / Magnitude / Observed"],
            ),
        ],
        "Object list -> RIGHT -> Object details -> RIGHT -> LOG",
    )
    branches(
        "settings_menu",
        "Settings",
        [
            (
                "User Pref...",
                [
                    "Key Bright / Sleep / Animation / Scroll",
                    "Search Input / Az Arrows / Language",
                ],
            ),
            (
                "Chart...",
                [
                    "Coordinates / Reticle / Constellation",
                    "DSO / RA-DEC / Center Object",
                ],
            ),
            ("Image...", ["NSEW Labels / Object Size"]),
            ("Camera Exp", ["Auto / Star / Fixed exposure"]),
            ("Camera Gain", ["Profile / Fixed gain"]),
            ("WiFi Mode", ["Client Mode / AP Mode / AP+STA Mode"]),
            ("Mount Type", ["Alt/Az / Equatorial"]),
            ("INDI Setting *", ["Multi Align / Backlash / Goto/Guide"]),
            (
                "Advanced",
                [
                    "Hardware / Lens / Distortion / GPS / Time",
                    "Bluetooth / Joystick / Keyboard / WiFi Recover",
                ],
            ),
            ("IMU Settings", ["Sensitivity / Compass / Calibration"]),
        ],
        "* Visible only when Mount Control is On. Values are listed in the manual.",
    )
    branches(
        "tools_menu",
        "Tools",
        [
            ("Status", ["Solve / Network / Device status"]),
            ("Equipment", ["Telescope / Eyepiece"]),
            (
                "Place & Time",
                [
                    "GPS Status / Time Sync / Set Location",
                    "Set Time/Date / Reset Location / Reset Time/Date",
                ],
            ),
            ("Console", ["System messages"]),
            ("Software Upd", ["Available update / Cancel"]),
            ("Test Mode", ["Indoor demonstration using a saved image"]),
            (
                "Experimental",
                [
                    "Polar Align / Mount Control",
                    "Dev Tools -> Telemetry -> Record / Images / Load",
                ],
            ),
            ("Power", ["Shutdown / Restart -> Confirm / Cancel"]),
        ],
    )
    d = Diagram(1380, 290, "Observation quick start")
    labels = [
        ("01", "FOCUS"),
        ("02", "GPS/TIME"),
        ("03", "ALIGN"),
        ("04", "OBJECT"),
        ("05", "LOG"),
        ("06", "SHUTDOWN"),
    ]
    d.text(28, 18, "MFNavis / Observing sequence", 28, RED)
    for i, (number, label) in enumerate(labels):
        x = 25 + i * 225
        d.rect(x, 85, 202, 142, "#f6f8fa")
        d.text(x + 17, 100, number, 24, RED)
        d.text(x + 17, 153, label, 25)
        if i < len(labels) - 1:
            d.line([(x + 202, 157), (x + 223, 157)], RED)
    d.save("quick_start")
    d = Diagram(1380, 365, "Common keypad navigation")
    d.text(28, 18, "MFNavis / Common controls (schematic)", 28, RED)
    for x, y, label in [
        (125, 82, "UP"),
        (25, 167, "LEFT"),
        (125, 252, "DOWN"),
        (225, 167, "RIGHT"),
        (125, 167, "SQUARE"),
    ]:
        d.rect(x, y, 94, 65, RED if label == "SQUARE" else "#f6f8fa")
        d.text(x + 8, y + 19, label, 20, PAPER if label == "SQUARE" else INK)
    for i, value in enumerate(
        [
            "UP / DOWN: choose an item",
            "RIGHT: open / select   LEFT: go back",
            "Hold LEFT: return to MFNavis menu",
            "Hold SQUARE: Quick Menu",
            "SQUARE + PLUS / MINUS: LCD brightness",
        ]
    ):
        d.text(400, 90 + i * 47, value, 25)
    d.save("common_keys")
    d = Diagram(1380, 390, "INDI Guide numeric direction keys")
    d.text(28, 18, "MFNavis / INDI Guide", 28, RED)
    for row, values in enumerate(
        [("7", "8 N", "9 +"), ("4 W", "5", "6 E"), ("1", "2 S", "3 -")]
    ):
        for col, value in enumerate(values):
            x, y = 28 + col * 105, 86 + row * 87
            active = value not in ("7", "5", "1")
            d.rect(x, y, 94, 70, "#f9e9eb" if active else "#f6f8fa")
            d.text(x + 10, y + 19, value, 25, RED if active else MUTED)
    for i, value in enumerate(
        [
            "8 / 2 / 4 / 6: hold to move N / S / W / E",
            "Release direction key: stop manual motion",
            "9 / 3: speed up / down",
            "SQUARE: Sync   0: Guide Correction toggle",
            "Object details: 5 = GoTo, 0 = Stop + tracking off",
        ]
    ):
        d.text(390, 87 + i * 49, value, 24, RED if i == 4 else INK)
    d.save("mount_keys")


def make_html():
    source = (HERE / "user_manual_ko.md").read_text(encoding="utf-8")
    content = markdown.markdown(source, extensions=["tables", "toc", "fenced_code"])
    import re

    # Keep short instructions together so a heading does not land on a page
    # with only the start of its procedure or table.
    def keep_topic(match):
        topic = match.group(0)
        plain = html.unescape(re.sub(r"<[^>]+>", "", topic))
        return (
            '<section class="keep">' + topic + "</section>"
            if len(plain) < 300
            else topic
        )

    content = re.sub(r"<h3\b.*?(?=<h[23]\b|\Z)", keep_topic, content, flags=re.S)
    # All assets are embedded: the HTML can be read offline as a single file.
    for path in ASSETS.glob("*.png"):
        uri = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
        content = content.replace(f"assets/{path.name}", uri)
    font = base64.b64encode(
        (ROOT / "python/views/css/mfnavis-korean.woff2").read_bytes()
    ).decode()
    css = """
@font-face { font-family: MFKo; src: url(data:font/woff2;base64,FONT_DATA) format('woff2'); unicode-range: U+1100-11FF,U+3130-318F,U+AC00-D7AF; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: #e9edf1; color: #223042; font-family: MFKo,Arial,sans-serif; line-height: 1.8; }
main { max-width: 960px; margin: 32px auto; background: white; padding: 60px 68px; box-shadow: 0 8px 32px #20304015; }
h1 { font-size: 34px; line-height: 1.4; color: #982d3b; margin: 0 0 16px; }
h2 { font-size: 25px; color: #982d3b; line-height: 1.5; margin: 54px 0 22px; padding-top: 16px; border-top: 2px solid #982d3b; }
h3 { font-size: 19px; margin: 30px 0 12px; color: #223042; }
p { margin: 12px 0; }
strong { font-weight: 700; }
code { font-family: MFKo,Arial,sans-serif; background: #f2f4f7; color: #344459; padding: 2px 4px; border-radius: 3px; overflow-wrap: anywhere; }
img { display: block; width: 100%; height: auto; margin: 22px auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; line-height: 1.7; margin: 18px 0 26px; }
th { text-align: left; background: #f0f3f6; color: #223042; font-weight: 700; }
th,td { border: 1px solid #d8e0e7; padding: 9px 11px; vertical-align: top; overflow-wrap: anywhere; }
td:first-child { width: 24%; }
ol,ul { padding-left: 25px; }
li { padding-left: 3px; margin: 9px 0; }
nav { background: #f6f8fa; border-left: 4px solid #982d3b; margin: 26px 0 38px; padding: 20px 24px; }
nav a { color: #344459; text-decoration: none; display: block; font-size: 14px; line-height: 2.1; }
nav p { font-size: 17px; margin: 0 0 8px; color: #982d3b; font-weight: 400; }
.tools { max-width: 960px; margin: 24px auto 0; text-align: right; }
button { border: 0; border-radius: 5px; background: #982d3b; color: white; padding: 12px 20px; font-family: inherit; cursor: pointer; }
.footer { margin-top: 38px; color: #617285; font-size: 12px; }
@media(max-width:700px) { main { padding: 28px 20px; margin: 0; } h1 { font-size: 27px; } table { font-size: 11px; } th,td { padding: 6px; } .tools { padding: 10px; margin: 0; } }
@page { size: A4; margin: 17mm 16mm 19mm;
 @bottom-left { content: 'MFNavis LCD User Manual'; font-family: Arial,sans-serif; font-size: 8pt; color: #617285; }
 @bottom-right { content: counter(page); font-family: Arial,sans-serif; font-size: 8pt; color: #617285; }
}
@media print {
 body { background: white; font-size: 10pt; line-height: 1.75; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
 main { width: auto; max-width: none; margin: 0; padding: 0; box-shadow: none; }
 h1 { font-size: 27pt; } h2 { font-size: 19pt; break-before: page; margin: 0 0 16pt; padding-top: 10pt; }
 h3 { font-size: 13pt; margin: 18pt 0 8pt; break-after: avoid; }
 p { orphans: 3; widows: 3; }
 table { font-size: 8.5pt; line-height: 1.65; } th,td { padding: 5.5pt; }
 thead { display: table-header-group; } tr { break-inside: avoid; }
 img { max-height: 195mm; object-fit: contain; break-inside: avoid; margin: 14pt auto; }
 li { break-inside: avoid; } nav { padding: 14pt 20pt; margin: 18pt 0; }
 .keep { break-inside: avoid; }
 .tools,.footer { display: none; }
}
""".replace("FONT_DATA", font)
    headings = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', content)
    nav = (
        '<nav aria-label="목차"><p>목차</p>'
        + "".join(
            f'<a href="#{identifier}">{label}</a>' for identifier, label in headings
        )
        + "</nav>"
    )
    first = content.index("<h2 ")
    content = content[:first] + nav + content[first:]
    output = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>MFNavis LCD 사용자 매뉴얼</title><style>"
        + css
        + "</style></head><body>"
        '<div class="tools"><button onclick="window.print()">인쇄 또는 PDF 저장</button></div>'
        "<main>"
        + content
        + '<p class="footer">MFNavis · 사용자 매뉴얼 초안 · 2026년 10월 9일</p>'
        "</main></body></html>"
    )
    (HERE / "user_manual_ko.html").write_text(output, encoding="utf-8")
    print(
        f"Built {len(headings)} chapters, {len(list(ASSETS.glob('*.png')))} diagrams, offline HTML"
    )


if __name__ == "__main__":
    ASSETS.mkdir(exist_ok=True)
    make_diagrams()
    make_html()
