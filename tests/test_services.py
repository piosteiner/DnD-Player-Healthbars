"""Poller (shared session), updater, autostart, diagnostics."""
import hashlib
import json
import os
import sys
import threading
import time

import pytest
import requests

from conftest import raw_character


# ── Shared poller ───────────────────────────────────────────────────────────
def test_poller_shares_one_session(hb, monkeypatch):
    ddb = hb.ddb
    sessions, fetched = [], []
    monkeypatch.setattr(ddb, "make_session", lambda cid: sessions.append(cid) or object())
    monkeypatch.setattr(ddb, "get_character",
                        lambda s, cid: fetched.append(cid) or ddb.parse_character(raw_character()))
    hb.config.POLL_INTERVAL = 2
    got, statuses = {}, {}
    done = threading.Event()
    for cid in ("1", "2", "3"):
        ddb.POLLER.add(cid, lambda d, c=cid: (got.__setitem__(c, d), len(got) == 3 and done.set()),
                       lambda m, k, c=cid: statuses.__setitem__(c, (m, k)))
    assert done.wait(5)
    assert len(sessions) == 1                       # one Geo-cookie visit for everyone
    assert set(fetched) >= {"1", "2", "3"}
    assert all(k == "ok" for _, k in statuses.values())
    ddb.POLLER.remove("2")
    fetched.clear()
    ddb.POLLER.poll_now()
    time.sleep(0.5)
    assert "2" not in fetched and {"1", "3"} <= set(fetched)


def test_poller_reports_private_and_rate_limits(hb, monkeypatch):
    ddb = hb.ddb

    def http_error(code, headers=None):
        r = requests.Response()
        r.status_code = code
        r.headers.update(headers or {})
        return requests.exceptions.HTTPError(response=r)

    codes = {"priv": 403, "slow": 429}
    monkeypatch.setattr(ddb, "make_session", lambda cid: object())

    def fake_get(s, cid):
        raise http_error(codes[cid], {"Retry-After": "90"})
    monkeypatch.setattr(ddb, "get_character", fake_get)
    status = {}
    for cid in codes:
        ddb.POLLER.add(cid, lambda d: None, lambda m, k, c=cid: status.__setitem__(c, (m, k)))
    deadline = time.time() + 6
    while time.time() < deadline and not ("private" in status.get("priv", ("",))[0]
                                          and "slow down" in status.get("slow", ("",))[0]):
        time.sleep(0.1)
    assert status["priv"] == ("⚠ Character is private — make it public on D&D Beyond", "error")
    assert "retrying in 90s" in status["slow"][0]


# ── Diagnostics ─────────────────────────────────────────────────────────────
def test_diagnostics_report(hb, monkeypatch):
    ddb = hb.ddb
    raw = raw_character(conditions=[{"id": 11}],
                        modifiers={"feat": [{"type": "bonus", "subType": "hit-points-per-level", "value": 2}]})
    monkeypatch.setattr(ddb, "make_session", lambda cid: object())
    monkeypatch.setattr(ddb, "fetch_raw", lambda s, cid: raw)
    report = json.loads(ddb.diagnostics("42"))
    assert report["character_id"] == "42" and report["name"] == "Testy"
    assert report["classes"][0] == {"name": "Sorcerer", "level": 5}
    assert report["hp_modifiers"][0]["subType"] == "hit-points-per-level"
    assert report["avatar_url"].startswith("https://") and report["conditions"] == [{"id": 11}]
    assert report["result"]["mx"] == 56 + 16


# ── Updater ─────────────────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, payload=None, body=b""):
        self.payload, self.body = payload, body
    def raise_for_status(self): pass
    def json(self): return self.payload
    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_check_for_update(hb, monkeypatch):
    u = hb.updater
    rel = {"tag_name": "v99.0.0", "html_url": "https://github.com/x/y/releases/tag/v99.0.0",
           "assets": [{"name": u.ASSET_WINDOWS, "size": 3, "digest": "sha256:abc",
                       "browser_download_url": "https://github.com/x/y/releases/download/v99.0.0/a.exe"}]}
    monkeypatch.setattr(u.requests, "get", lambda *a, **k: FakeResp(rel))
    info = u.check_for_update()
    assert info["tag"] == "v99.0.0" and info["size"] == 3 and info["asset_url"].endswith("a.exe")
    monkeypatch.setattr(u.requests, "get", lambda *a, **k: FakeResp({**rel, "tag_name": "v0.1.0"}))
    assert u.check_for_update() is None


def test_download_verifies_size_digest_and_host(hb, monkeypatch, tmp_path):
    u = hb.updater
    body = b"new program bytes"
    monkeypatch.setattr(u.requests, "get", lambda *a, **k: FakeResp(body=body))
    good = {"asset_url": "https://github.com/x/y/releases/download/v9/a.exe", "size": len(body),
            "digest": "sha256:" + hashlib.sha256(body).hexdigest()}
    dest = str(tmp_path / "a.exe.new")
    seen = []
    assert u.download(good, dest, seen.append) == dest
    assert open(dest, "rb").read() == body and seen[-1] == 1.0
    for bad in ({**good, "digest": "sha256:" + "0" * 64}, {**good, "size": 999},
                {**good, "asset_url": "https://evil.example/a.exe"}):
        os.remove(dest) if os.path.exists(dest) else None
        with pytest.raises(ValueError):
            u.download(bad, dest)
        assert not os.path.exists(dest) and not os.path.exists(dest + ".part")


def test_update_helper_script(hb):
    path = hb.updater.write_helper()
    try:
        text = open(path, encoding="ascii").read()
        assert 'move /y "%NEW%" "%EXE%"' in text and "--after-update" in text
    finally:
        os.remove(path)
    assert hb.updater.can_self_update() is False          # not a frozen .exe in tests


# ── Autostart (Windows registry, own test value) ────────────────────────────
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_autostart_registry_roundtrip(hb):
    s = hb.system
    name = "DnD Health Bar TEST " + os.urandom(3).hex()
    try:
        assert s.get_autostart(name) is False
        s.set_autostart(True, name, command='"C:\\x\\app.exe" --minimized')
        assert s.get_autostart(name) is True
        s.set_autostart(False, name)
        assert s.get_autostart(name) is False
        s.set_autostart(False, name)                      # removing twice is fine
    finally:
        s.set_autostart(False, name)
