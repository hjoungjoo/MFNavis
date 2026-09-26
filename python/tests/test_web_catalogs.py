"""Tests for PiFinder.web_catalogs (web catalog pages, APIs, push)."""

import os
import queue
from types import SimpleNamespace

import pytest
from flask import Flask

from PiFinder import utils


class FakeUIState:
    def __init__(self):
        self.recent = []
        self.pushto = False

    def add_recent(self, obj):
        self.recent.append(obj)

    def set_new_pushto(self, value):
        self.pushto = value


class FakeSharedState:
    def __init__(self):
        self._ui_state = FakeUIState()

    def location(self):
        # lock=True so the planet catalog uses THIS location. With lock=False
        # _observer_location falls back to the config's default location,
        # which exists on a developer's device but not in CI -- there the
        # planet list came back empty and the tests failed.
        return SimpleNamespace(lat=37.5, lon=127.1, altitude=0.0, lock=True)

    def datetime(self):
        return None

    def ui_state(self):
        return self._ui_state


class FakeServer:
    def __init__(self):
        self.shared_state = FakeSharedState()
        self.ui_queue = queue.Queue()
        self.mountcontrol_queue = queue.Queue()
        self.goto_guide_queue = queue.Queue()


@pytest.fixture()
def web_app():
    from PiFinder.web_catalogs import register_catalog_routes

    views_path = os.path.abspath(
        os.path.join(os.path.dirname(utils.__file__), "..", "views")
    )
    app = Flask(__name__, template_folder=views_path)
    app.secret_key = "test"
    app.jinja_env.add_extension("jinja2.ext.i18n")
    app.jinja_env.install_null_translations()
    server = FakeServer()
    register_catalog_routes(app, server)
    return app, server


def _login(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
    return client


def _m31_object_id():
    import sqlite3

    conn = sqlite3.connect(f"file:{utils.pifinder_db}?mode=ro", uri=True)
    row = conn.execute(
        "SELECT object_id FROM catalog_objects"
        " WHERE catalog_code = 'M' AND sequence = 31"
    ).fetchone()
    conn.close()
    return row[0]


@pytest.mark.unit
def test_pages_and_apis_require_auth(web_app):
    app, _server = web_app
    client = app.test_client()
    for url in ("/catalogs", "/catalogs/M", "/catalogs/object/224"):
        response = client.get(url)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]
    assert client.get("/catalogs/api/objects?catalog=M").status_code == 401
    assert client.get("/catalogs/api/search?q=andromeda").status_code == 401
    assert (
        client.get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1").status_code
        == 401
    )
    assert client.get("/catalogs/api/altitude/224").status_code == 401
    assert client.get("/catalogs/image/224").status_code == 401


@pytest.mark.unit
def test_catalogs_home_resumes_last_visited_page(web_app):
    app, _server = web_app
    client = _login(app.test_client())

    # Visiting a catalog list page remembers it in the cookie.
    assert client.get("/catalogs/M").status_code == 200

    # Arriving from outside the catalog section resumes there...
    response = client.get("/catalogs", headers={"Referer": "http://x/remote"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/catalogs/M")

    # ...navigating home FROM a catalog page still shows the home,
    response = client.get("/catalogs", headers={"Referer": "http://x/catalogs/M"})
    assert response.status_code == 200

    # and ?home=1 is the explicit escape hatch.
    response = client.get("/catalogs?home=1", headers={"Referer": "http://x/remote"})
    assert response.status_code == 200


@pytest.mark.unit
def test_catalogs_home_resumes_at_object_detail(web_app):
    app, _server = web_app
    client = _login(app.test_client())
    object_id = _m31_object_id()

    assert client.get(f"/catalogs/object/{object_id}").status_code == 200

    # No Referer at all (bookmark / address bar) also resumes.
    response = client.get("/catalogs")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/catalogs/object/{object_id}")


@pytest.mark.unit
def test_home_page(web_app):
    app, _server = web_app
    response = _login(app.test_client()).get("/catalogs")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "NGC" in body and "Messier" in body or "M" in body
    assert 'id="pfcat-nearby"' not in body


@pytest.fixture()
def nearby_catalog(monkeypatch):
    """Small isolated catalog, including cross-catalog duplicates."""
    import sqlite3
    from PiFinder import web_catalogs

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE objects (id INTEGER PRIMARY KEY, ra REAL, dec REAL,"
        " obj_type TEXT, const TEXT, mag TEXT, size TEXT);"
        "CREATE TABLE catalog_objects (id INTEGER PRIMARY KEY, object_id INTEGER,"
        " catalog_code TEXT, sequence INTEGER);"
        "CREATE TABLE names (id INTEGER PRIMARY KEY, object_id INTEGER, common_name TEXT);"
    )
    for number in range(65, 0, -1):
        conn.execute(
            "INSERT INTO objects VALUES (?, ?, 0, 'Gx', 'And', NULL, NULL)",
            (number, number),
        )
        conn.execute(
            "INSERT INTO catalog_objects VALUES (?, ?, 'NGC', ?)",
            (number, number, number),
        )
    conn.execute("INSERT INTO catalog_objects VALUES (100, 11, 'M', 11)")
    monkeypatch.setattr(
        web_catalogs,
        "_query",
        lambda sql, params=(): conn.execute(sql, params).fetchall(),
    )
    monkeypatch.setattr(
        web_catalogs,
        "_pointing_status",
        lambda: {"current": {"ra": 0, "dec": 0, "valid": True}},
    )
    monkeypatch.setattr(
        web_catalogs,
        "_altaz_calculator",
        lambda shared: SimpleNamespace(
            radec_to_altaz=lambda ra, dec, alt_only=False: (25 if ra > 10 else -5, 90)
        ),
    )
    monkeypatch.setattr(web_catalogs, "_calc_planets", lambda shared: {})
    monkeypatch.setattr(web_catalogs, "_observed_set", lambda: set())
    monkeypatch.setattr(
        web_catalogs, "sky_conditions", lambda shared: {"enabled": False}
    )
    yield conn
    conn.close()


@pytest.mark.unit
def test_nearby_sorted_visible_and_scoped(web_app, nearby_catalog):
    app, _server = web_app
    response = _login(app.test_client()).get(
        "/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1"
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.get_json()
    assert data["total"] == 55
    assert data["pages"] == 2
    assert "limit" not in data
    objects = data["objects"]
    assert [obj["object_id"] for obj in objects] == list(range(11, 61))
    assert [obj["distance"] for obj in objects] == list(range(11, 61))
    assert all(obj["alt"] > 0 for obj in objects)
    assert objects[0]["display"] == "NGC 11"


@pytest.mark.unit
def test_nearby_preserves_full_catalog_and_pagination(web_app, nearby_catalog):
    app, _server = web_app
    client = _login(app.test_client())
    base = "/catalogs/api/objects?catalog=NGC&sort=nearby"
    first = client.get(base).get_json()
    second = client.get(base + "&page=2").get_json()
    assert first["total"] == second["total"] == 65
    assert first["pages"] == second["pages"] == 2
    assert [o["object_id"] for o in first["objects"] + second["objects"]] == list(
        range(1, 66)
    )
    assert first["objects"][0]["alt"] < 0  # Up now is a separate filter.
    assert len(client.get(base + "&page_size=200").get_json()["objects"]) == 65
    messier = client.get("/catalogs/api/objects?catalog=M&sort=nearby").get_json()
    assert messier["total"] == 1
    assert messier["objects"][0]["display"] == "M 11"


@pytest.mark.unit
def test_nearby_combines_existing_filters(web_app, nearby_catalog, monkeypatch):
    from PiFinder import web_catalogs

    nearby_catalog.execute("INSERT INTO names VALUES (1, 11, 'Special target')")
    nearby_catalog.execute(
        'UPDATE objects SET mag = \'{"filter_mag": 6, "mags": [6]}\' WHERE id = 11'
    )
    monkeypatch.setattr(web_catalogs, "_observed_set", lambda: {("NGC", 11)})
    app, _server = web_app
    client = _login(app.test_client())
    url = "/catalogs/api/objects?catalog=NGC&sort=nearby&q=Special&types=Gx&const=And&mag_max=7&up_now=1"
    data = client.get(url + "&observed=yes").get_json()
    assert data["total"] == 1
    assert data["objects"][0]["display"] == "NGC 11"
    assert data["objects"][0]["observed"] is True
    assert client.get(url + "&observed=no").get_json()["total"] == 0
    assert client.get(url.replace("types=Gx", "types=PN")).get_json()["total"] == 0


@pytest.mark.unit
def test_nearby_keeps_missing_coordinates_in_full_list(web_app, nearby_catalog):
    nearby_catalog.execute("UPDATE objects SET ra = NULL WHERE id = 1")
    app, _server = web_app
    data = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=NGC&sort=nearby&page_size=200")
        .get_json()
    )
    assert data["total"] == 65
    assert data["objects"][-1]["object_id"] == 1
    assert data["objects"][-1]["distance"] is None


@pytest.mark.unit
def test_nearby_without_location_can_sort_without_up_now(
    web_app, nearby_catalog, monkeypatch
):
    from PiFinder import web_catalogs

    monkeypatch.setattr(web_catalogs, "_altaz_calculator", lambda shared: None)
    app, _server = web_app
    client = _login(app.test_client())
    url = "/catalogs/api/objects?catalog=NGC&sort=nearby"
    data = client.get(url).get_json()
    assert data["total"] == 65
    assert data["alt_available"] is False
    assert client.get(url + "&up_now=1").status_code == 409


@pytest.mark.unit
def test_nearby_has_no_large_catalog_altitude_limit(
    web_app, nearby_catalog, monkeypatch
):
    from PiFinder import web_catalogs

    monkeypatch.setattr(web_catalogs, "ALT_COMPUTE_LIMIT", 1)
    app, _server = web_app
    data = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
        .get_json()
    )
    assert data["total"] == 55
    assert data["alt_enabled"] is True


@pytest.mark.unit
def test_old_global_nearby_endpoint_removed(web_app):
    app, _server = web_app
    assert _login(app.test_client()).get("/catalogs/api/nearby").status_code == 404


@pytest.mark.unit
def test_nearby_visibility_ranks_before_pagination(
    web_app, nearby_catalog, monkeypatch
):
    from PiFinder import web_catalogs

    nearby_catalog.execute(
        "UPDATE objects SET obj_type = '*', mag = '{\"filter_mag\": 16, \"mags\": [16]}'"
    )
    nearby_catalog.execute(
        'UPDATE objects SET mag = \'{"filter_mag": 6, "mags": [6]}\' WHERE id > 60'
    )
    monkeypatch.setattr(
        web_catalogs,
        "sky_conditions",
        lambda shared: {
            "enabled": True,
            "limiting_mag": 12,
        },
    )
    app, _server = web_app
    data = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
        .get_json()
    )
    assert data["sort"] == "nearby"
    assert data["ranking"] == "visibility_distance"
    assert len(data["objects"]) == 50
    # These targets lay beyond the old nearest-50 cutoff. Within each tier,
    # distance still determines order, and the cross-catalog duplicate is one row.
    assert [o["object_id"] for o in data["objects"][:5]] == list(range(61, 66))
    assert all(o["visibility"]["label"] == "Favorable" for o in data["objects"][:5])
    assert [o["object_id"] for o in data["objects"][5:]] == list(range(11, 56))
    second = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1&page=2")
        .get_json()
    )
    assert second["total"] == 55
    assert [o["object_id"] for o in second["objects"]] == list(range(56, 61))


@pytest.mark.unit
def test_nearby_planets_use_same_visibility_rank(web_app, nearby_catalog, monkeypatch):
    from PiFinder import web_catalogs

    monkeypatch.setattr(
        web_catalogs,
        "sky_conditions",
        lambda shared: {
            "enabled": True,
            "limiting_mag": 12,
        },
    )
    monkeypatch.setattr(
        web_catalogs,
        "_calc_planets",
        lambda shared: {
            "MOON": {"radec": (90, 0), "altaz": (40, 90), "mag": -10},
            "PLUTO": {"radec": (1, 0), "altaz": (40, 90), "mag": 15},
        },
    )
    app, _server = web_app
    data = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=PL&sort=nearby&up_now=1")
        .get_json()
    )
    assert len(data["objects"]) == 2
    assert data["objects"][0]["display"] == "Moon"
    assert data["objects"][1]["display"] == "Pluto"


@pytest.mark.unit
def test_nearby_wrap_pole_and_current_position(web_app, nearby_catalog, monkeypatch):
    from PiFinder import web_catalogs

    nearby_catalog.execute("DELETE FROM objects WHERE id > 3")
    nearby_catalog.executemany(
        "UPDATE objects SET ra = ?, dec = ? WHERE id = ?",
        [(359.9, 0, 1), (0.3, 0, 2), (180, 89.9, 3)],
    )
    monkeypatch.setattr(
        web_catalogs,
        "_altaz_calculator",
        lambda shared: SimpleNamespace(radec_to_altaz=lambda *a, **kw: (30, 90)),
    )
    app, _server = web_app
    client = _login(app.test_client())
    objects = client.get(
        "/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1"
    ).get_json()["objects"]
    assert [obj["object_id"] for obj in objects] == [1, 2, 3]
    assert objects[0]["distance"] == pytest.approx(0.1)

    monkeypatch.setattr(
        web_catalogs, "_pointing_status", lambda: {"current": {"ra": 0, "dec": 90}}
    )
    data = client.get(
        "/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1"
    ).get_json()
    assert data["center"]["dec"] == 90
    assert data["objects"][0]["object_id"] == 3
    assert data["objects"][0]["distance"] == pytest.approx(0.1)


@pytest.mark.unit
def test_nearby_planets_respect_up_now(web_app, nearby_catalog, monkeypatch):
    from PiFinder import web_catalogs

    monkeypatch.setattr(
        web_catalogs,
        "_calc_planets",
        lambda shared: {
            "MOON": {"radec": (10.5, 0), "altaz": (40, 90), "mag": -10},
            "MARS": {"radec": (0, 0), "altaz": (-10, 90)},
        },
    )
    app, _server = web_app
    objects = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=PL&sort=nearby&up_now=1")
        .get_json()["objects"]
    )
    assert len(objects) == 1
    assert objects[0]["href"] == "/catalogs/planet/moon"
    assert objects[0]["distance"] == 10.5
    assert not any(obj["display"] == "Mars" for obj in objects)


@pytest.mark.unit
@pytest.mark.parametrize(
    "current",
    [
        {},
        {"ra": None, "dec": 0},
        {"ra": float("nan"), "dec": 0},
        {"ra": 0, "dec": 91},
        {"ra": 0, "dec": 0, "valid": False},
    ],
)
def test_nearby_unavailable_pointing(web_app, nearby_catalog, monkeypatch, current):
    from PiFinder import web_catalogs

    monkeypatch.setattr(web_catalogs, "_pointing_status", lambda: {"current": current})
    app, _server = web_app
    response = _login(app.test_client()).get(
        "/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1"
    )
    assert response.status_code == 409
    assert "pointing unavailable" in response.get_json()["error"]


@pytest.mark.unit
def test_nearby_unsolved_imu_then_solved(web_app, nearby_catalog, monkeypatch):
    """An unanchored IMUPLUS sample can browse, then yield to a plate solve."""
    from PiFinder import web_catalogs

    status = {
        "current": {"valid": False, "ra": None, "dec": None},
        "solved": {"valid": False},
        "imu": {
            "valid": True,
            "ra": 15,
            "dec": 0,
            "source": "imu_fallback",
            "metadata": {"uses_magnetometer": False, "alignment_applied": False},
        },
    }
    monkeypatch.setattr(web_catalogs, "_pointing_status", lambda: status)
    app, _server = web_app
    client = _login(app.test_client())
    response = client.get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
    assert response.status_code == 200
    data = response.get_json()
    assert data["center"] == {
        "ra": 15,
        "dec": 0,
        "source": "imu_fallback",
        "unaligned": True,
    }
    assert len(data["objects"]) == 50
    assert data["objects"][0]["object_id"] == 15

    status["current"] = {"valid": True, "ra": 40, "dec": 0, "source": "solve"}
    data = client.get(
        "/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1"
    ).get_json()
    assert data["center"]["source"] == "solve"
    assert data["center"]["unaligned"] is False
    assert data["objects"][0]["object_id"] == 40


@pytest.mark.unit
@pytest.mark.parametrize(
    "source", ["solve", "pifinder_imu_estimate", "mount", "mount_imu_delta"]
)
def test_nearby_preserves_selected_coordinate(
    web_app, nearby_catalog, monkeypatch, source
):
    from PiFinder import web_catalogs

    monkeypatch.setattr(
        web_catalogs,
        "_pointing_status",
        lambda: {
            "current": {"valid": True, "ra": 30, "dec": 0, "source": source},
            "solved": {"valid": True, "ra": 40, "dec": 0, "source": "solve"},
            "imu": {"valid": True, "ra": 15, "dec": 0, "source": "imu_fallback"},
        },
    )
    app, _server = web_app
    data = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
        .get_json()
    )
    assert data["center"]["source"] == source
    assert data["objects"][0]["object_id"] == 30


@pytest.mark.unit
def test_nearby_solved_fallback_precedes_imu(web_app, nearby_catalog, monkeypatch):
    from PiFinder import web_catalogs

    monkeypatch.setattr(
        web_catalogs,
        "_pointing_status",
        lambda: {
            "current": {"valid": False},
            "solved": {"valid": True, "ra": 40, "dec": 0, "source": "solve"},
            "imu": {"valid": True, "ra": 15, "dec": 0, "source": "imu_fallback"},
        },
    )
    app, _server = web_app
    data = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
        .get_json()
    )
    assert data["center"]["source"] == "solve"
    assert data["objects"][0]["object_id"] == 40


@pytest.mark.unit
@pytest.mark.parametrize(
    "metadata",
    [
        {"uses_magnetometer": True},
        {"alignment_applied": True},
    ],
)
def test_nearby_imu_absolute_heading(web_app, nearby_catalog, monkeypatch, metadata):
    from PiFinder import web_catalogs

    monkeypatch.setattr(
        web_catalogs,
        "_pointing_status",
        lambda: {
            "imu": {"valid": True, "ra": 15, "dec": 0, "metadata": metadata},
        },
    )
    app, _server = web_app
    data = (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
        .get_json()
    )
    assert data["center"]["source"] == "imu_fallback"
    assert data["center"]["unaligned"] is False


@pytest.mark.unit
def test_nearby_rejects_invalid_imu_and_unselected_mount(
    web_app, nearby_catalog, monkeypatch
):
    from PiFinder import web_catalogs

    monkeypatch.setattr(
        web_catalogs,
        "_pointing_status",
        lambda: {
            "current": {"valid": False},
            "imu": {"valid": False, "ra": 15, "dec": 0},
            "mount": {"valid": True, "aligned": False, "ra": 40, "dec": 0},
        },
    )
    app, _server = web_app
    assert (
        _login(app.test_client())
        .get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
        .status_code
        == 409
    )


@pytest.mark.unit
def test_nearby_unavailable_location_and_empty_sky(
    web_app, nearby_catalog, monkeypatch
):
    from PiFinder import web_catalogs

    app, _server = web_app
    client = _login(app.test_client())
    monkeypatch.setattr(web_catalogs, "_altaz_calculator", lambda shared: None)
    response = client.get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
    assert response.status_code == 409
    assert "location unavailable" in response.get_json()["error"]

    monkeypatch.setattr(
        web_catalogs,
        "_altaz_calculator",
        lambda shared: SimpleNamespace(radec_to_altaz=lambda *a, **kw: (-5, 90)),
    )
    response = client.get("/catalogs/api/objects?catalog=NGC&sort=nearby&up_now=1")
    assert response.status_code == 200
    assert response.get_json()["objects"] == []


@pytest.mark.unit
def test_catalog_page_and_404(web_app):
    app, _server = web_app
    client = _login(app.test_client())
    page = client.get("/catalogs/M")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert (
        body.index('id="pfcat-upnow"')
        < body.index('id="pfcat-nearby"')
        < body.index('id="pfcat-sort"')
    )
    assert client.get("/catalogs/NOPE").status_code == 404


@pytest.mark.unit
def test_objects_api_basic(web_app):
    app, _server = web_app
    client = _login(app.test_client())
    data = client.get("/catalogs/api/objects?catalog=M").get_json()
    assert data["total"] == 110
    assert data["objects"][0]["display"] == "M 1"
    # alt availability depends on a saved default location in local config
    assert data["alt_available"] in (True, False)

    galaxies = client.get("/catalogs/api/objects?catalog=M&types=Gx").get_json()
    assert 0 < galaxies["total"] < 110
    assert all(o["obj_type"] == "Gx" for o in galaxies["objects"])

    bright = client.get("/catalogs/api/objects?catalog=M&mag_max=5").get_json()
    assert 0 < bright["total"] < 110


@pytest.mark.unit
def test_objects_api_pagination(web_app):
    app, _server = web_app
    client = _login(app.test_client())
    page2 = client.get("/catalogs/api/objects?catalog=M&page=2&page_size=50").get_json()
    assert page2["page"] == 2
    assert page2["pages"] == 3
    assert page2["objects"][0]["display"] == "M 51"


@pytest.mark.unit
def test_search_api(web_app):
    app, _server = web_app
    client = _login(app.test_client())
    data = client.get("/catalogs/api/search?q=Andromeda").get_json()
    assert any("Andromeda" in r["matched_name"] for r in data["results"])
    assert client.get("/catalogs/api/search?q=a").get_json() == {"results": []}


@pytest.mark.unit
def test_search_api_designation_ordering(web_app):
    app, _server = web_app
    client = _login(app.test_client())

    # "m5": exact designation first, then same-prefix longer sequences in
    # numeric order (M5, M50, M51, ...).
    displays = [
        r["display"]
        for r in client.get("/catalogs/api/search?q=m5").get_json()["results"]
    ]
    assert displays[0] == "M 5"
    assert displays[:4] == ["M 5", "M 50", "M 51", "M 52"]

    # Case-insensitive prefix; "ngc1" -> NGC 1, NGC 10, NGC 11, ...
    displays = [
        r["display"]
        for r in client.get("/catalogs/api/search?q=ngc1").get_json()["results"]
    ]
    assert displays[:3] == ["NGC 1", "NGC 10", "NGC 11"]


@pytest.mark.unit
def test_object_page_and_altitude(web_app):
    app, _server = web_app
    client = _login(app.test_client())
    object_id = _m31_object_id()
    page = client.get(f"/catalogs/object/{object_id}")
    assert page.status_code == 200
    assert "M 31" in page.get_data(as_text=True)

    alt = client.get(f"/catalogs/api/altitude/{object_id}").get_json()
    assert "available" in alt
    if alt["available"]:
        assert len(alt["samples"]) > 100 and "transit_time" in alt

    assert client.get("/catalogs/object/99999999").status_code == 404


@pytest.mark.unit
def test_push_requires_auth(web_app):
    app, _server = web_app
    client = app.test_client()
    response = client.post(f"/catalogs/api/push/{_m31_object_id()}", json={})
    assert response.status_code == 401


@pytest.mark.unit
def test_push_authenticated(web_app):
    app, server = web_app
    client = _login(app.test_client())
    response = client.post(f"/catalogs/api/push/{_m31_object_id()}", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["pushed"] == "M 31"
    # GoTo routing mirrors SkySafari: queued when mount_control is on
    assert "goto" in data
    if data["goto"]["action"] == "goto_queued":
        command = server.goto_guide_queue.get_nowait()
        assert command["type"] == "goto_target"
        assert command["ra"] == pytest.approx(10.68, abs=0.1)
    # LCD push mechanism fired
    assert server.ui_queue.get_nowait() == "push_object"
    ui_state = server.shared_state.ui_state()
    assert ui_state.pushto is True
    assert ui_state.recent and ui_state.recent[0].catalog_code == "M"
    assert ui_state.recent[0].sequence == 31
    assert ui_state.recent[0].ra == pytest.approx(10.68, abs=0.1)


@pytest.mark.unit
def test_push_with_nonsidereal_offset(web_app):
    from PiFinder import nonsidereal

    app, server = web_app
    client = _login(app.test_client())
    response = client.post(
        f"/catalogs/api/push/{_m31_object_id()}",
        json={"offset_arcsec_per_s": 0.55},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["track_freq"]["action"] == "set"
    assert data["track_freq"]["hz"] == pytest.approx(
        nonsidereal.hz_from_offset(0.55), abs=1e-6
    )
    server.ui_queue.get_nowait()
    command = server.mountcontrol_queue.get_nowait()
    assert command["type"] == "set_track_freq"
    assert command["hz"] == pytest.approx(57.964, abs=0.01)
    assert command["label"] == "M 31"


@pytest.mark.unit
def test_planet_catalog_listing(web_app):
    app, _server = web_app
    client = _login(app.test_client())
    assert client.get("/catalogs/PL").status_code == 200
    data = client.get("/catalogs/api/objects?catalog=PL").get_json()
    assert data["total"] >= 8
    names = [o["display"] for o in data["objects"]]
    assert "Moon" in names and "Jupiter" in names and "Sun" not in names
    moon = next(o for o in data["objects"] if o["display"] == "Moon")
    assert moon["href"] == "/catalogs/planet/moon"
    assert moon["const"]  # constellation resolved from live position


@pytest.mark.unit
def test_stop_requires_auth(web_app):
    app, _server = web_app
    client = app.test_client()
    response = client.post("/catalogs/api/stop", json={})
    assert response.status_code == 401


@pytest.mark.unit
def test_stop_queues_stop_movement(web_app):
    app, server = web_app
    client = _login(app.test_client())
    response = client.post("/catalogs/api/stop", json={})
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    # Mirrors the SkySafari :Q# routing: the GoTo/Guide service cancels its
    # slew + refinement loop, mount control aborts the motion itself.
    assert server.goto_guide_queue.get_nowait() == {"type": "stop_movement"}
    assert server.mountcontrol_queue.get_nowait() == {"type": "stop_movement"}


@pytest.mark.unit
def test_goto_status_requires_auth(web_app):
    app, _server = web_app
    response = app.test_client().get("/catalogs/api/goto_status")
    assert response.status_code == 401


@pytest.mark.unit
def test_goto_status_reports_progress(web_app, monkeypatch):
    from PiFinder import web_catalogs

    monkeypatch.setattr(
        web_catalogs,
        "_goto_guide_status",
        lambda: {
            "service_state": "running",
            "phase": "pifinder_goto",
            "last_action": "waiting for INDI GoTo",
            "active_target_ra": 100.0,
            "active_target_dec": 20.0,
            "goto_plan": {"goto_attempt": 2, "max_gotos": 10, "error_arcmin": 120.0},
        },
    )
    monkeypatch.setattr(
        web_catalogs,
        "_pointing_status",
        lambda: {"current": {"ra": 98.0, "dec": 21.0, "source": "solve"}},
    )
    monkeypatch.setattr(web_catalogs, "_mount_status", lambda: {"state": "slewing"})

    app, _server = web_app
    client = _login(app.test_client())
    response = client.get("/catalogs/api/goto_status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["active"] is True
    assert data["available"] is True
    assert data["attempt"] == 2 and data["max_gotos"] == 10
    assert data["error_arcmin"] == pytest.approx(120.0)
    assert data["mount_state"] == "slewing"
    assert data["delta"]["ra_deg"] == pytest.approx(2.0)
    assert data["delta"]["dec_deg"] == pytest.approx(-1.0)


@pytest.mark.unit
def test_goto_status_idle_without_target(web_app, monkeypatch):
    from PiFinder import web_catalogs

    monkeypatch.setattr(
        web_catalogs, "_goto_guide_status", lambda: {"service_state": "idle"}
    )
    monkeypatch.setattr(web_catalogs, "_pointing_status", lambda: {})

    app, _server = web_app
    client = _login(app.test_client())
    data = client.get("/catalogs/api/goto_status").get_json()
    assert data["active"] is False
    assert data["available"] is False
    assert "delta" not in data


@pytest.mark.unit
def test_planet_detail_and_push(web_app):
    app, server = web_app
    client = _login(app.test_client())
    page = client.get("/catalogs/planet/moon")
    assert page.status_code == 200
    assert "Moon" in page.get_data(as_text=True)
    assert client.get("/catalogs/planet/nope").status_code == 404

    response = client.post("/catalogs/api/push_planet/moon", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True and data["pushed"] == "Moon"
    # Non-sidereal feed-forward applied automatically
    assert data["track_freq"]["action"] == "set"
    assert server.ui_queue.get_nowait() == "push_object"
    command = server.mountcontrol_queue.get_nowait()
    assert command["type"] == "set_track_freq"
    assert command["label"] == "Moon"
    # Moon rate is slower than sidereal -> below 60.164 Hz
    assert command["hz"] < 60.16


@pytest.fixture
def observation_store(web_app, monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from PiFinder import web_catalogs
    from PiFinder.db.observations_db import ObservationsDatabase

    path = tmp_path / "observations.db"
    monkeypatch.setattr(
        web_catalogs, "ObservationsDatabase", lambda: ObservationsDatabase(path)
    )
    app, server = web_app
    server.shared_state.location = lambda: SimpleNamespace(
        lat=37.5, lon=127.1, altitude=0, lock=True, timezone="Asia/Seoul"
    )
    server.shared_state.local_datetime = lambda: datetime.now(timezone.utc)
    server.shared_state.solution = lambda: None
    return app, server, lambda: ObservationsDatabase(path)


@pytest.mark.unit
def test_catalog_observation_records_selected_object_and_reuses_session(
    observation_store,
):
    app, server, open_db = observation_store
    client = _login(app.test_client())
    oid = _m31_object_id()
    response = client.post(f"/catalogs/api/observe/{oid}")
    assert response.status_code == 200
    url = response.json["url"]
    assert url.startswith("/observations/")
    assert client.post(f"/catalogs/api/observe/{oid}").json["url"] == url
    db = open_db()
    try:
        sessions = db.get_sessions()
        assert len(sessions) == 1
        assert sessions[0]["observations"] == 2
        rows = db.get_logs_by_session(sessions[0]["UID"])
        assert all(row["catalog"] == "M" and row["sequence"] == 31 for row in rows)
    finally:
        db.close()
    assert server.ui_queue.empty()
    assert server.mountcontrol_queue.empty()
    assert server.goto_guide_queue.empty()
    assert 'id="pfcat-observe"' in client.get(f"/catalogs/object/{oid}").text


@pytest.mark.unit
def test_catalog_observation_rejects_unauthorized_missing_object_and_location(
    observation_store,
):
    app, server, open_db = observation_store
    client = app.test_client()
    oid = _m31_object_id()
    assert client.post(f"/catalogs/api/observe/{oid}").status_code == 401
    assert client.post("/catalogs/api/observe_planet/moon").status_code == 401
    _login(client)
    assert client.post("/catalogs/api/observe/999999999").status_code == 404
    assert client.post("/catalogs/api/observe_planet/nonexistent").status_code == 404
    server.shared_state.location = lambda: None
    assert client.post(f"/catalogs/api/observe/{oid}").status_code == 409
    db = open_db()
    try:
        assert db.get_sessions() == []
    finally:
        db.close()


@pytest.mark.unit
def test_catalog_observation_planet(observation_store):
    from PiFinder.web_catalogs import PLANET_SEQUENCE

    app, _server, open_db = observation_store
    client = _login(app.test_client())
    response = client.post("/catalogs/api/observe_planet/moon")
    assert response.status_code == 200
    db = open_db()
    try:
        rows = db.get_logs_by_session(response.json["url"].split("/")[-1])
        assert len(rows) == 1
        assert rows[0]["catalog"] == "PL"
        assert rows[0]["sequence"] == PLANET_SEQUENCE.index("MOON") + 1
    finally:
        db.close()
