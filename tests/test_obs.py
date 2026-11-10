"""obs-websocket v5 client against a mock OBS that speaks the real protocol."""
import asyncio
import base64
import hashlib
import json
import threading
import time

import pytest

from conftest import free_port

websockets = pytest.importorskip("websockets")
pytest.importorskip("websocket")

PASSWORD, SALT, CHALLENGE = "s3cret", "c2FsdA==", "Y2hhbGxlbmdl"


class MockOBS:
    def __init__(self):
        self.scenes = ["Combat", "Exploration"]
        self.program = "Combat"
        self.inputs = {"Browser 2": {"kind": "browser_source", "settings": {}}}
        self.items = {"Combat": ["Browser 2"], "Exploration": []}
        self.transforms = {}

    def handle(self, rt, d):
        ok = lambda data=None: ({"result": True, "code": 100}, data or {})
        err = lambda code, c: ({"result": False, "code": code, "comment": c}, None)
        if rt == "GetSceneList":
            return ok({"scenes": [{"sceneName": n} for n in reversed(self.scenes)]})
        if rt == "GetCurrentProgramScene":
            return ok({"currentProgramSceneName": self.program})
        if rt == "GetInputList":
            return ok({"inputs": [{"inputName": n, "inputKind": v["kind"]} for n, v in self.inputs.items()]})
        if rt == "CreateInput":
            self.inputs[d["inputName"]] = {"kind": d["inputKind"], "settings": dict(d["inputSettings"])}
            self.items[d["sceneName"]].append(d["inputName"])
            return ok({"sceneItemId": len(self.items[d["sceneName"]])})
        if rt == "SetInputSettings":
            self.inputs[d["inputName"]]["settings"].update(d["inputSettings"])
            return ok()
        if rt == "GetSceneItemId":
            if d["sourceName"] in self.items[d["sceneName"]]:
                return ok({"sceneItemId": 1})
            return err(600, "not found")
        if rt == "CreateSceneItem":
            self.items[d["sceneName"]].append(d["sourceName"])
            return ok({"sceneItemId": len(self.items[d["sceneName"]])})
        if rt == "SetSceneItemTransform":
            self.transforms[(d["sceneName"], d["sceneItemId"])] = d["sceneItemTransform"]
            return ok()
        return err(204, "unknown")

    async def serve(self, ws):
        await ws.send(json.dumps({"op": 0, "d": {"rpcVersion": 1, "authentication":
                                                {"challenge": CHALLENGE, "salt": SALT}}}))
        try:
            ident = json.loads(await ws.recv())
        except websockets.ConnectionClosed:
            return
        secret = base64.b64encode(hashlib.sha256((PASSWORD + SALT).encode()).digest()).decode()
        good = base64.b64encode(hashlib.sha256((secret + CHALLENGE).encode()).digest()).decode()
        if ident["d"].get("authentication") != good:
            await ws.close(4009, "Authentication failed.")
            return
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        async for raw in ws:
            d = json.loads(raw)["d"]
            status, data = self.handle(d["requestType"], d.get("requestData", {}))
            await ws.send(json.dumps({"op": 5, "d": {"eventType": "Noise"}}))   # must be skipped
            await ws.send(json.dumps({"op": 7, "d": {"requestId": d["requestId"],
                                                     "requestStatus": status, "responseData": data}}))


@pytest.fixture
def obs():
    mock, port = MockOBS(), free_port()

    def run():
        async def main():
            async with websockets.serve(mock.serve, "127.0.0.1", port,
                                        subprotocols=["obswebsocket.json"]):
                await asyncio.Future()
        asyncio.run(main())

    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.5)
    return mock, {"host": "127.0.0.1", "port": port, "password": PASSWORD, "scene": ""}


def test_connection_errors_are_explained(hb, obs):
    _, cfg = obs
    for bad, expect in [({**cfg, "password": "nope"}, "password is wrong"),
                        ({**cfg, "password": ""}, "asks for a WebSocket password"),
                        ({**cfg, "port": free_port()}, "Can't reach OBS")]:
        with pytest.raises(hb.obs.OBSError, match=expect):
            hb.obs.list_scenes(bad)
    assert hb.obs.list_scenes(cfg) == ["Combat", "Exploration"]


def test_add_update_and_party(hb, obs):
    mock, cfg = obs
    hb.overlay.HUB.port = 7777
    game = {"id": "abcd1234", "name": "Camp", "characters": [
        {"name": "Abu", "character_id": "1"},
        {"name": "Ally", "character_id": "2", "show_hp_numbers": True}]}
    items = [hb.obs.character_item(c, i) for i, c in enumerate(game["characters"])]
    assert hb.obs.add_overlays(cfg, items) == ("Combat", 2, 0)
    assert mock.inputs["HP Overlay - Ally"]["settings"]["height"] == hb.theme.CARD_H_NUM
    assert mock.transforms[("Combat", 3)]["positionX"] == 320          # side by side
    assert hb.obs.add_overlays(cfg, items) == ("Combat", 0, 2)        # no duplicates
    assert mock.items["Combat"].count("HP Overlay - Abu") == 1
    assert hb.obs.add_overlays({**cfg, "scene": "Exploration"}, items) == ("Exploration", 0, 2)

    party = hb.obs.party_item(game)
    assert party["url"].endswith("/party/abcd1234") and party["width"] == 2 * 280 + 16
    hb.obs.add_overlays(cfg, [party])
    assert "HP Party - Camp" in mock.items["Combat"]
