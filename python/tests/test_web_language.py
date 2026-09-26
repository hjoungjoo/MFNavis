"""Web language selection and translation completeness are independent of device locale."""

from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
import json
import re
import shutil
import subprocess

from babel.messages.extract import extract, extract_from_dir
from babel.messages.pofile import read_po
from flask_babel import gettext
import pytest

from PiFinder import server as server_module, sys_utils_fake
from PiFinder.web_i18n import CATALOG_LABELS, CLIENT_MESSAGES

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "/",
    "/login",
    "/network",
    "/gps",
    "/locations",
    "/equipment",
    "/tools",
    "/livecam",
    "/logs",
    "/remote",
    "/catalogs?home=1",
    "/catalogs/M",
    "/solver-capture",
    "/advanced",
    "/observations",
    "/indi",
)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ignored = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "i"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "i"}:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            self.text.append(data)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(server_module.sys_utils, "Network", sys_utils_fake.Network)
    cfg = server_module.config.Config()
    cfg.locations.locations = []
    cfg.equipment.telescopes = []
    cfg.equipment.eyepieces = []
    monkeypatch.setattr(cfg, "load_config", lambda: None)
    monkeypatch.setattr(server_module.config, "Config", lambda: cfg)
    monkeypatch.setattr(
        server_module,
        "ObservationsDatabase",
        lambda: SimpleNamespace(get_sessions=lambda: []),
    )
    instance = server_module.Server()
    instance.app.testing = True
    return instance.app


def authenticated_client(app, language):
    client = app.test_client()
    client.set_cookie("mfnavis_web_language", language)
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client


@pytest.mark.parametrize(
    "cookie,expected",
    [(None, "en"), ("ko", "ko"), ("en", "en"), ("fr", "en"), ("../../ko", "en")],
)
def test_language_defaults_and_validation(app, cookie, expected):
    headers = {"Accept-Language": "ko-KR,ko;q=0.9"}
    if cookie is not None:
        headers["Cookie"] = "mfnavis_web_language=" + cookie
    with app.test_request_context("/", headers=headers):
        assert server_module.server_locale() == expected
        assert gettext("Aperture") == ("구경" if expected == "ko" else "Aperture")


def test_preferences_do_not_leak_between_browsers(app):
    korean = authenticated_client(app, "ko")
    english = authenticated_client(app, "en")
    for client, expected in [(korean, "ko"), (english, "en"), (korean, "ko")]:
        page = client.get("/login").text
        assert f'lang="{expected}"' in page
        assert page.count('class="browser-default pf-language-select"') == 2
        assert 'value="' + expected + '" selected' in page


@pytest.mark.parametrize("path", PAGES)
@pytest.mark.parametrize("language", ["en", "ko"])
def test_pages_render_in_selected_language(app, path, language):
    response = authenticated_client(app, language).get(path)
    assert response.status_code == 200
    assert "Cookie" in response.vary
    assert f'lang="{language}"' in response.text
    parser = VisibleText()
    parser.feed(response.text)
    text = " ".join(parser.text)
    if language == "en":
        # User-entered values and original catalog records are not translated.
        # The fixture data on these pages contains no Korean source records.
        assert not re.search("[가-힣]", text)
    elif path != "/solver-capture":
        assert "한국어" in text
        assert "Network Setup" not in text
        assert "Open-source licenses" not in text
        assert "Home" not in text


class IndiPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = {}
        self.scripts = []
        self.script = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.elements[attrs["id"]] = attrs
        if tag == "script" and "src" not in attrs:
            self.script = []

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.scripts.append("".join(self.script))
            self.script = None

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)


@pytest.mark.parametrize(
    "base_url,expected",
    [
        ("http://mfnavis.local/", "http://mfnavis.local:8624/"),
        ("http://192.0.2.10:8080/", "http://192.0.2.10:8624/"),
        ("https://mfnavis.example/", "http://mfnavis.example:8624/"),
        ("http://[2001:db8::10]:8080/", "http://[2001:db8::10]:8624/"),
    ],
)
def test_indi_manager_link_is_ready_without_javascript(app, base_url, expected):
    with app.test_request_context("/indi", base_url=base_url):
        server_module.session["authenticated"] = True
        page = IndiPage(app.full_dispatch_request().get_data(as_text=True))
    link = page.elements["indi_web_manager_link"]
    assert link["href"] == expected
    assert "data-pf-no-spa" in link


@pytest.mark.parametrize("language", ["en", "ko"])
@pytest.mark.parametrize("device", ["", "Telescope Simulator", "LX200 OnStepX"])
def test_indi_initializes_with_and_without_onstep_forms(
    app, monkeypatch, language, device
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the INDI JavaScript regression tests")
    monkeypatch.setattr(
        server_module.sys_utils, "get_indi_profile_device_name", lambda: device
    )
    page = IndiPage(authenticated_client(app, language).get("/indi").text)
    has_guide_form = "pulse_guide_rate_form" in page.elements
    assert has_guide_form == (device == "LX200 OnStepX")
    script = next(s for s in page.scripts if "pulse_guide_rate_form" in s)
    result = subprocess.run(
        [node, str(Path(__file__).with_name("js") / "indi_initialization.mjs")],
        input=json.dumps({"script": script, "hasGuideForm": has_guide_form}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_web_message_has_a_compiled_korean_translation(app):
    with (ROOT / "locale/ko/LC_MESSAGES/messages.po").open() as stream:
        catalog = read_po(stream)
    messages = (
        {
            row[2]
            for row in extract_from_dir(
                str(ROOT / "views"), method_map=[("**.html", "jinja2")]
            )
            if isinstance(row[2], str)
        }
        | set(CLIENT_MESSAGES)
        | set(CATALOG_LABELS.values())
    )
    for source in (ROOT / "MFNavis/server.py", ROOT / "MFNavis/web_i18n.py"):
        with source.open("rb") as stream:
            messages.update(
                row[1] for row in extract("python", stream) if isinstance(row[1], str)
            )
    # These are protocol identifiers and the product name, not English prose.
    identifiers = {"INDI", "IP", "MAC", "MFNavis"}
    with app.test_request_context("/", headers={"Cookie": "mfnavis_web_language=ko"}):
        for message in sorted(messages):
            entry = catalog.get(message)
            assert entry and entry.string and not entry.fuzzy, message
            assert gettext(message) == entry.string, message
            assert message in identifiers or re.search("[가-힣]", entry.string), message


def test_astronomy_terminology(app):
    expected = {
        "RA": "적경",
        "Dec": "적위",
        "Alt": "고도",
        "Az": "방위각",
        "Aperture": "구경",
        "Eyepieces": "접안렌즈",
        "Magnitude": "등급",
        "Transit": "남중",
        "GoTo": "자동 도입",
    }
    with app.test_request_context("/", headers={"Cookie": "mfnavis_web_language=ko"}):
        for source, translated in expected.items():
            assert gettext(source) == translated
