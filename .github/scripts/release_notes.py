"""Print the CHANGELOG.md section for a version plus download info.

Usage: python release_notes.py v2.2.0 > notes.md
"""
import re
import sys
from pathlib import Path

FOOTER = """
---
| OS      | File                       |
|---------|----------------------------|
| Windows | `DnD_HealthBar_Public.exe` |
| Linux   | `DnD_HealthBar_Public`     |

**First time?** Download and run — no installation, no Python needed.
**Updating?** Close the app and replace the old file. Your settings and portraits stay untouched.
"""


def section(changelog: str, version: str) -> str:
    version = version.lstrip("v")
    out, found = [], False
    for line in changelog.splitlines():
        if line.startswith("## "):
            if found:
                break
            found = re.search(rf"\b{re.escape(version)}\b", line) is not None
            continue
        if found:
            out.append(line)
    return "\n".join(out).strip()


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    text = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), sys.argv[1])
    sys.stdout.reconfigure(encoding="utf-8")
    print((text or "See CHANGELOG.md for details.") + "\n" + FOOTER)
