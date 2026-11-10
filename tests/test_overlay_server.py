import http.client
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request

import pytest
from PIL import Image

from conftest import free_port, make_image


@pytest.fixture
def served(app):
    make_image(os.path.join(app._BASE_DIR, "p.png"))
    cfg = {"games": [{"id": "abcd1234", "name": "Camp", "characters": [
        {"name": "Thorin", "character_id": "123", "portrait_injured": "p.png", "show_hp_numbers": True},
        {"name": "Ally",   "character_id": "456"}]}]}
    app.OVERLAY_HUB.sync_config(cfg)
    port = app.start_overlay_server(free_port())
    assert port
    return app, f"http://127.0.0.1:{port}"


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers["Content-Type"], r.read()
    except urllib.error.HTTPError as e:
        return e.code, None, b""


def info(cur, mx, temp=0):
    return {"pct": cur / mx, "cur": cur, "mx": mx, "temp": temp,
            "death_saves": {"fail": 0, "success": 0, "stable": False}, "conditions": []}


def test_pages_and_state(served):
    app, base = served
    status, _, body = get(base + "/")
    assert status == 200 and b"Thorin" in b"" + body and b"/party/abcd1234" in body
    assert get(base + "/overlay/123")[0] == 200
    assert get(base + "/party/abcd1234")[0] == 200
    assert json.loads(get(base + "/api/123")[2])["live"] is False

    app.OVERLAY_HUB.set_live("123", True)
    app.OVERLAY_HUB.update_hp("123", info(8, 20, temp=3))
    st = json.loads(get(base + "/api/123")[2])
    assert (st["live"], st["loaded"], st["state"], st["cur"], st["temp"]) == (True, True, "bloodied", 8, 3)
    assert st["portrait"] == "portrait_injured"

    party = json.loads(get(base + "/api/party/abcd1234")[2])
    assert [c["cid"] for c in party["characters"]] == ["123", "456"]


def test_portrait_png_is_transparent_and_scoped(served):
    app, base = served
    status, ctype, body = get(base + "/portrait/123/portrait_injured")
    img = Image.open(io.BytesIO(body))
    assert status == 200 and ctype == "image/png" and img.size == (560, 560)
    assert img.getpixel((5, 280))[3] == 0          # letterbox area stays transparent
    for bad in ("/portrait/123/portrait_dead", "/portrait/123/../../x", "/api/999",
                "/api/party/ffff", "/nope"):
        assert get(base + bad)[0] == 404


def test_server_sent_events_push_changes(served):
    app, base = served
    host, port = base.replace("http://", "").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.request("GET", "/events/123")
    resp = conn.getresponse()
    assert resp.getheader("Content-Type") == "text/event-stream"

    def next_event():
        while True:
            line = resp.fp.readline().decode()
            if line.startswith("data: "):
                return json.loads(line[6:])

    first = next_event()
    assert first["characters"][0]["live"] is False
    app.OVERLAY_HUB.set_live("123", True)
    threading.Timer(0.2, lambda: app.OVERLAY_HUB.update_hp("123", info(5, 20))).start()
    deadline = time.time() + 5
    while time.time() < deadline:
        ev = next_event()["characters"][0]
        if ev["loaded"]:
            assert ev["cur"] == 5
            break
    else:
        pytest.fail("no update event")
    conn.close()


def test_second_instance_gets_detected_and_cannot_share_port(app):
    port = free_port()
    assert not app.app_already_running(port)
    assert app.start_overlay_server(port) == port
    assert app.app_already_running(port)
    assert app.start_overlay_server(port) != port      # exclusive bind
