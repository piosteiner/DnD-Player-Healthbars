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
def served(hb):
    make_image(os.path.join(hb.config.BASE_DIR, "p.png"))
    cfg = {"games": [{"id": "abcd1234", "name": "Camp", "characters": [
        {"name": "Thorin", "character_id": "123", "portrait_injured": "p.png", "show_hp_numbers": True},
        {"name": "Goblin", "character_id": "npc0a1b2c3d", "source": "manual", "max_hp": 7}]}]}
    hb.overlay.HUB.sync_config(cfg)
    port = hb.overlay.start_server(free_port())
    assert port
    return hb, f"http://127.0.0.1:{port}"


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers["Content-Type"], r.read()
    except urllib.error.HTTPError as e:
        return e.code, None, b""


def info(cur, mx, temp=0, npc=False, fail=0):
    return {"pct": cur / mx, "cur": cur, "mx": mx, "temp": temp, "npc": npc,
            "death_saves": {"fail": fail, "success": 0, "stable": False}, "conditions": []}


def test_pages_and_state(served):
    hb, base = served
    hub = hb.overlay.HUB
    status, _, body = get(base + "/")
    assert status == 200 and b"Thorin" in body and b"/party/abcd1234" in body and b"style=bar" in body
    for page in ("/overlay/123", "/overlay/npc0a1b2c3d", "/party/abcd1234"):
        assert get(base + page)[0] == 200
    assert json.loads(get(base + "/api/123")[2])["live"] is False

    hub.set_live("123", True)
    hub.update_hp("123", info(8, 20, temp=3))
    st = json.loads(get(base + "/api/123")[2])
    assert (st["live"], st["loaded"], st["state"], st["cur"], st["temp"]) == (True, True, "bloodied", 8, 3)
    assert st["portrait"] == "portrait_injured"

    hub.update_hp("123", info(0, 20))                           # 0 HP → dying, not dead
    assert json.loads(get(base + "/api/123")[2])["state"] == "dying"
    hub.update_hp("123", info(0, 20, fail=3))
    assert json.loads(get(base + "/api/123")[2])["state"] == "dead"

    hub.set_live("npc0a1b2c3d", True)
    hub.update_hp("npc0a1b2c3d", info(0, 7, npc=True))           # NPC at 0 → dead
    assert json.loads(get(base + "/api/npc0a1b2c3d")[2])["state"] == "dead"

    party = json.loads(get(base + "/api/party/abcd1234")[2])
    assert [c["cid"] for c in party["characters"]] == ["123", "npc0a1b2c3d"]


def test_palette_reaches_overlay(served):
    hb, base = served
    hb.overlay.HUB.set_live("123", True)
    hb.overlay.HUB.update_hp("123", info(20, 20))
    assert json.loads(get(base + "/api/123")[2])["color"] == "#00e676"
    hb.config.apply_settings({"palette": "colorblind"})
    assert json.loads(get(base + "/api/123")[2])["color"] == "#1e88e5"


def test_portrait_png_is_transparent_and_scoped(served):
    hb, base = served
    status, ctype, body = get(base + "/portrait/123/portrait_injured")
    img = Image.open(io.BytesIO(body))
    assert status == 200 and ctype == "image/png" and img.size == (560, 560)
    assert img.getpixel((5, 280))[3] == 0
    for bad in ("/portrait/123/portrait_dead", "/portrait/123/../../x", "/api/999",
                "/api/party/ffff", "/api/__palette__", "/nope"):
        assert get(base + bad)[0] == 404


def test_server_sent_events_push_changes(served):
    hb, base = served
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

    assert next_event()["characters"][0]["live"] is False
    hb.overlay.HUB.set_live("123", True)
    threading.Timer(0.2, lambda: hb.overlay.HUB.update_hp("123", info(5, 20))).start()
    deadline = time.time() + 5
    while time.time() < deadline:
        ev = next_event()["characters"][0]
        if ev["loaded"]:
            assert ev["cur"] == 5
            break
    else:
        pytest.fail("no update event")
    conn.close()


def test_second_instance_detected_and_port_exclusive(hb):
    port = free_port()
    assert not hb.overlay.app_already_running(port)
    assert hb.overlay.start_server(port) == port
    assert hb.overlay.app_already_running(port)
    assert hb.overlay.start_server(port) != port
