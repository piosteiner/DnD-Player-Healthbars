import importlib.util
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_app(base_dir):
    """Fresh copy of the app module pointed at an empty data folder."""
    spec = importlib.util.spec_from_file_location("dnd_app", ROOT / "dnd_healthbar_public.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.set_base_dir(str(base_dir))
    return mod


@pytest.fixture
def app(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return load_app(data)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def raw_character(**over):
    """Minimal D&D Beyond character payload."""
    d = {
        "name": "Testy", "baseHitPoints": 40, "bonusHitPoints": 0, "overrideHitPoints": None,
        "removedHitPoints": 10, "temporaryHitPoints": 0,
        "classes": [{"level": 5, "classFeatures": [{"definition": {"id": 111}}]},
                    {"level": 3, "classFeatures": []}],
        "stats": [{"id": 3, "value": 14}], "bonusStats": [], "overrideStats": [],
        "modifiers": {},
        "decorations": {"avatarUrl": "https://www.dndbeyond.com/avatars/1/2/3.png"},
        "deathSaves": {"failCount": 0, "successCount": 0, "isStabilized": False},
        "conditions": [],
    }
    d.update(over)
    return d


def make_image(path, size=(100, 200), color="red"):
    from PIL import Image
    Image.new("RGB", size, color).save(path)
    return str(path)
