import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from healthbar import config, ddb, obs, overlay, system, theme, updater  # noqa: E402


@pytest.fixture
def hb(tmp_path):
    """The app's modules with fresh state and an empty data folder."""
    data = tmp_path / "data"
    data.mkdir()
    config.set_base_dir(str(data))
    config.SAVE_ERROR_HANDLER = None
    config.POLL_INTERVAL = config.DEFAULT_POLL_INTERVAL
    theme.set_palette("default")
    overlay.HUB.reset()
    ddb.POLLER.reset()
    yield SimpleNamespace(config=config, ddb=ddb, obs=obs, overlay=overlay, system=system,
                          theme=theme, updater=updater, data=data)
    ddb.POLLER.reset()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def raw_character(**over):
    """Minimal D&D Beyond character payload (max HP 56 with these stats)."""
    d = {
        "name": "Testy", "baseHitPoints": 40, "bonusHitPoints": 0, "overrideHitPoints": None,
        "removedHitPoints": 10, "temporaryHitPoints": 0,
        "classes": [{"level": 5, "classFeatures": [{"definition": {"id": 111}}],
                     "definition": {"name": "Sorcerer"}},
                    {"level": 3, "classFeatures": [], "definition": {"name": "Fighter"}}],
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
