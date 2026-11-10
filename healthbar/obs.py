"""OBS WebSocket (v5 protocol, built into OBS 28+): create/update the
browser sources so nobody has to copy URLs or set sizes by hand."""
import base64
import hashlib
import json
import time

from . import overlay, theme

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False

DEFAULTS = {"host": "127.0.0.1", "port": 4455, "password": "", "scene": ""}


class OBSError(Exception):
    def __init__(self, msg: str, code=None):
        super().__init__(msg)
        self.code = code


class OBSClient:
    """Minimal synchronous obs-websocket v5 client. Use as a context manager."""

    def __init__(self, host="127.0.0.1", port=4455, password="", timeout=5.0):
        self.host, self.port, self.password, self.timeout = host, int(port), password, timeout
        self._ws  = None
        self._req = 0

    def __enter__(self):
        if not HAS_WEBSOCKET:
            raise OBSError("OBS support needs the 'websocket-client' package.")
        try:
            self._ws = websocket.create_connection(
                f"ws://{self.host}:{self.port}", timeout=self.timeout,
                subprotocols=["obswebsocket.json"])
        except Exception:
            raise OBSError(f"Can't reach OBS at {self.host}:{self.port}.\n\n"
                           "Is OBS running, and is the WebSocket server enabled?\n"
                           "(OBS → Tools → WebSocket Server Settings)")
        try:
            hello = self._recv_op(0)
            ident = {"rpcVersion": 1, "eventSubscriptions": 0}
            auth  = hello.get("authentication")
            if auth:
                if not self.password:
                    raise OBSError("OBS asks for a WebSocket password — enter it in the "
                                   "OBS settings of this app.")
                secret = base64.b64encode(hashlib.sha256(
                    (self.password + auth["salt"]).encode()).digest()).decode()
                ident["authentication"] = base64.b64encode(hashlib.sha256(
                    (secret + auth["challenge"]).encode()).digest()).decode()
            self._send(1, ident)
            try:
                self._recv_op(2)
            except OBSError:
                raise
            except Exception:
                raise OBSError("OBS refused the connection — the WebSocket password is wrong.")
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._ws:
            try: self._ws.close()
            except Exception: pass
            self._ws = None

    def _send(self, op: int, d: dict):
        self._ws.send(json.dumps({"op": op, "d": d}))

    def _recv_op(self, op: int) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            msg = json.loads(self._ws.recv())
            if msg.get("op") == op:
                return msg.get("d", {})
        raise OBSError("OBS did not answer in time.")

    def call(self, request_type: str, data: dict | None = None) -> dict:
        self._req += 1
        rid = str(self._req)
        self._send(6, {"requestType": request_type, "requestId": rid, "requestData": data or {}})
        while True:
            d = self._recv_op(7)
            if d.get("requestId") == rid:
                break
        status = d.get("requestStatus", {})
        if not status.get("result"):
            raise OBSError(f"OBS: {request_type} failed — "
                           f"{status.get('comment') or 'error ' + str(status.get('code'))}",
                           status.get("code"))
        return d.get("responseData") or {}


def settings(cfg: dict) -> dict:
    s = dict(DEFAULTS)
    s.update(cfg.get("obs") or {})
    return s


def list_scenes(obs: dict) -> list[str]:
    with OBSClient(obs["host"], obs["port"], obs["password"]) as c:
        return [s["sceneName"] for s in reversed(c.call("GetSceneList").get("scenes", []))]


def source_name(char_name: str) -> str:
    return f"HP Overlay - {char_name}"


def party_source_name(game_name: str) -> str:
    return f"HP Party - {game_name}"


def character_item(ch: dict, slot: int = 0) -> dict:
    return {"source": source_name(ch.get("name") or ch["character_id"]),
            "url": overlay.HUB.url_for(ch["character_id"]), "width": theme.OVL_W,
            "height": theme.CARD_H_NUM if ch.get("show_hp_numbers") else theme.CARD_H, "slot": slot}


def party_item(game: dict) -> dict:
    chars = game.get("characters", [])
    n     = max(1, len(chars))
    return {"source": party_source_name(game.get("name", "Party")),
            "url": overlay.HUB.party_url(game["id"]),
            "width": n * theme.OVL_W + (n - 1) * theme.PARTY_GAP,
            "height": theme.CARD_H_NUM if any(c.get("show_hp_numbers") for c in chars) else theme.CARD_H,
            "slot": 0}


def add_overlays(obs: dict, items: list[dict]) -> tuple[str, int, int]:
    """Create or update one browser source per item in the target scene.
    items: [{"source", "url", "width", "height", "slot"}]. New sources are
    placed side by side (by slot). Returns (scene, created, updated)."""
    with OBSClient(obs["host"], obs["port"], obs["password"]) as c:
        scene = obs.get("scene") or ""
        if not scene:
            cur   = c.call("GetCurrentProgramScene")
            scene = cur.get("currentProgramSceneName") or cur.get("sceneName")
        existing = {i["inputName"]: i.get("inputKind")
                    for i in c.call("GetInputList").get("inputs", [])}
        created = updated = 0
        for it in items:
            name     = it["source"]
            settings_ = {"url": it["url"], "width": it["width"], "height": it["height"],
                         "shutdown": False, "restart_when_active": False}
            new_item = None
            if name in existing:
                if existing[name] != "browser_source":
                    raise OBSError(f"OBS already has a non-browser source named '{name}'. "
                                   "Rename or delete it and try again.")
                c.call("SetInputSettings", {"inputName": name, "inputSettings": settings_,
                                            "overlay": True})
                try:
                    c.call("GetSceneItemId", {"sceneName": scene, "sourceName": name})
                except OBSError as e:
                    if e.code != 600:      # 600 = ResourceNotFound → not in this scene yet
                        raise
                    new_item = c.call("CreateSceneItem", {"sceneName": scene,
                                                          "sourceName": name})["sceneItemId"]
                updated += 1
            else:
                new_item = c.call("CreateInput", {
                    "sceneName": scene, "inputName": name, "inputKind": "browser_source",
                    "inputSettings": settings_, "sceneItemEnabled": True})["sceneItemId"]
                created += 1
            if new_item is not None:
                try:
                    c.call("SetSceneItemTransform", {
                        "sceneName": scene, "sceneItemId": new_item,
                        "sceneItemTransform": {"positionX": 20 + it.get("slot", 0) * 300,
                                               "positionY": 20}})
                except OBSError:
                    pass
        return scene, created, updated
