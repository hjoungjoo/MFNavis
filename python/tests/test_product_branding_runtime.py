"""Product rendering and backup compatibility at the real Flask boundary."""

import io
from pathlib import Path

from PIL import ImageFont
import pytest

from PiFinder import server as server_module
from PiFinder.branding import LOGO_PATH, welcome_image
from PiFinder.ui.help_text import render_help_text
from test_server_equipment_forms import FakeConfig

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server_module.config, "Config", FakeConfig)
    app = server_module.Server().app
    app.testing = True
    client = app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client


def test_backup_download_and_legacy_restore(client, monkeypatch, tmp_path):
    archive = tmp_path / "MFNavis_backup.zip"
    archive.write_bytes(b"test archive")
    sys_utils = server_module.sys_utils
    monkeypatch.setattr(sys_utils, "backup_userdata", lambda: str(archive))
    response = client.get("/tools/backup")
    assert response.status_code == 200
    assert "MFNavis_backup.zip" in response.headers["Content-Disposition"]
    assert response.data == archive.read_bytes()
    monkeypatch.setattr(sys_utils, "BACKUP_PATH", str(archive))
    monkeypatch.setattr(sys_utils, "remove_backup", lambda: None)
    restored = []
    monkeypatch.setattr(sys_utils, "restore_userdata", restored.append)
    response = client.post(
        "/tools/restore",
        data={"backup_file": (io.BytesIO(b"legacy payload"), "PiFinder_backup.zip")},
    )
    assert response.status_code == 200
    assert restored == [str(archive)]
    assert archive.read_bytes() == b"legacy payload"


def test_web_assets_and_legal_notices(client):
    assert client.get("/images/mfnavis-logo.png").data == LOGO_PATH.read_bytes()
    manifest = client.get("/manifest.webmanifest").get_json(force=True)
    assert manifest["name"] == "MFNavis"
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200
    assert client.get("/legal/THIRD_PARTY_NOTICES.md").status_code == 200
    assert client.get("/legal/python/pifinder_logconf.json").status_code == 404


@pytest.mark.parametrize("size", [(128, 128), (176, 176), (240, 240), (320, 240)])
def test_logo_and_help_fit_supported_displays(size):
    assert welcome_image(size, top_margin=20).size == size
    for font_name in [
        "RobotoMonoNerdFontMono-Bold.ttf",
        "sarasa-mono-sc-light-nerd-font+patched.ttf",
    ]:
        font = ImageFont.truetype(str(REPO / "fonts" / font_name), 24)
        for page in ["menu", "align"]:
            text = (REPO / "help" / page / "2.txt").read_text()
            rendered = render_help_text(text, font)
            assert rendered.size == (128, 128)
            assert rendered.getbbox() is not None
