"""Authentication must run before API handlers can read or change device state."""

import queue
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
import pytest

from PiFinder.api_extensions import register_api_routes

pytestmark = pytest.mark.unit


@pytest.fixture
def api():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-session-key")
    server = SimpleNamespace(
        api_token="test-api-token", keyboard_queue=queue.Queue(), button_dict={}
    )
    register_api_routes(app, server)
    return app, server


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_every_extension_route_rejects_unauthenticated_requests(api, token):
    app, server = api
    client = app.test_client()
    with patch("threading.Timer") as timer:
        for rule in app.url_map.iter_rules():
            if not (rule.rule.startswith("/api/") or rule.rule == "/solver-capture"):
                continue
            path = rule.rule.replace("<dirname>", "test").replace(
                "<filename>", "test.png"
            )
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                response = client.open(
                    path,
                    method=method,
                    query_string={"token": token} if token else {},
                    json={},
                )
                assert response.status_code == 401, (path, method, response.status_code)
        timer.assert_not_called()
    assert server.keyboard_queue.empty()


@pytest.mark.parametrize("auth", ["session", "token"])
def test_authorized_key_request_reaches_handler(api, auth):
    app, server = api
    client = app.test_client()
    query = {}
    if auth == "session":
        with client.session_transaction() as session:
            session["authenticated"] = True
    else:
        query["token"] = server.api_token
    response = client.post("/api/key", json={"button": 1}, query_string=query)
    assert response.status_code == 200
    assert not server.keyboard_queue.empty()


def test_default_is_protected_even_without_token():
    app = Flask(__name__)
    register_api_routes(app, SimpleNamespace())
    assert app.test_client().post("/api/stop").status_code == 401
