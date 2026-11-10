"""Update check and one-click self-update (Windows .exe).

A running .exe can't overwrite itself, so the new file is downloaded next to
it, a tiny helper script waits for the app to exit, swaps the files and
starts the new version.
"""
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

import requests

from . import APP_VERSION, GITHUB_REPO

log = logging.getLogger("dnd_healthbar")

ASSET_WINDOWS = "DnD_HealthBar_Public.exe"
UA = f"DnD-Health-Bar/{APP_VERSION}"


def parse_version(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3])


def check_for_update(timeout: float = 6) -> dict | None:
    """Info about a newer GitHub release, or None.
    {"tag", "url", "asset_url", "size", "digest"} (asset fields may be None)."""
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                     headers={"Accept": "application/vnd.github+json", "User-Agent": UA},
                     timeout=timeout)
    r.raise_for_status()
    rel = r.json()
    tag = rel.get("tag_name", "")
    if parse_version(tag) <= parse_version(APP_VERSION):
        return None
    asset = next((a for a in rel.get("assets", []) if a.get("name") == ASSET_WINDOWS), None)
    return {"tag": tag,
            "url": rel.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest",
            "asset_url": asset.get("browser_download_url") if asset else None,
            "size": asset.get("size") if asset else None,
            "digest": asset.get("digest") if asset else None}


def can_self_update(info: dict | None = None) -> bool:
    if not (getattr(sys, "frozen", False) and sys.platform == "win32"):
        return False
    if info is not None and not info.get("asset_url"):
        return False
    return os.access(os.path.dirname(sys.executable), os.W_OK)


def download(info: dict, dest: str, progress=None) -> str:
    """Download the release asset to `dest`, verifying size and (if GitHub
    provides it) the SHA-256 digest. progress(fraction) is called as it goes."""
    url = info["asset_url"]
    host = urllib.parse.urlsplit(url).hostname or ""
    if urllib.parse.urlsplit(url).scheme != "https" or host != "github.com":
        raise ValueError(f"Unexpected download location: {url}")
    expected = info.get("size") or 0
    sha = hashlib.sha256()
    done = 0
    tmp = dest + ".part"
    with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress and expected:
                    progress(min(1.0, done / expected))
    try:
        if expected and done != expected:
            raise ValueError(f"Download incomplete ({done} of {expected} bytes)")
        digest = info.get("digest") or ""
        if digest.startswith("sha256:") and digest[7:].lower() != sha.hexdigest():
            raise ValueError("Downloaded file is corrupted (checksum mismatch)")
        os.replace(tmp, dest)
    except Exception:
        try: os.remove(tmp)
        except OSError: pass
        raise
    return dest


HELPER_BAT = r"""@echo off
rem D&D Health Bar updater: wait for the app to exit, swap files, restart.
set "NEW=%~1"
set "EXE=%~2"
set /a tries=0
:retry
ping -n 2 127.0.0.1 >nul
move /y "%NEW%" "%EXE%" >nul 2>&1 && goto started
set /a tries+=1
if %tries% lss 60 goto retry
goto done
:started
start "" "%EXE%" --after-update
:done
del "%~f0"
"""


def write_helper() -> str:
    fd, path = tempfile.mkstemp(prefix="dnd_healthbar_update_", suffix=".bat")
    with os.fdopen(fd, "w", encoding="ascii", newline="\r\n") as f:
        f.write(HELPER_BAT)
    return path


def launch_replacer(new_file: str, exe_path: str):
    """Start the helper that replaces `exe_path` with `new_file` once this
    process has exited. The caller must exit promptly afterwards."""
    helper = write_helper()
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(["cmd", "/c", helper, new_file, exe_path], creationflags=flags,
                     close_fds=True, cwd=os.path.dirname(exe_path))
    log.info("Update helper started: %s → %s", new_file, exe_path)
