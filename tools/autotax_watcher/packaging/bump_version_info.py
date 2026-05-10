"""Patch version_info.txt + (opsiyonel) APP_VERSION inside autotax_watcher.py.

Build/release script'lerinden çağrılır:
    python packaging/bump_version_info.py 2.0.1
    python packaging/bump_version_info.py 2.0.1 --update-py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VERSION_INFO = HERE / "version_info.txt"
WATCHER_PY = ROOT / "autotax_watcher.py"


def _parse_version(s: str) -> tuple[int, int, int, int]:
    parts = re.split(r"[.\-]", s)
    nums = []
    for p in parts:
        if not p.isdigit():
            break
        nums.append(int(p))
    while len(nums) < 4:
        nums.append(0)
    if len(nums) > 4:
        nums = nums[:4]
    return tuple(nums)  # type: ignore[return-value]


def _patch_version_info(ver_tuple: tuple[int, int, int, int], dotted: str) -> None:
    if not VERSION_INFO.exists():
        print(f"ERROR: {VERSION_INFO} missing", file=sys.stderr)
        sys.exit(1)
    text = VERSION_INFO.read_text(encoding="utf-8")
    text = re.sub(r"filevers=\([^)]+\)", f"filevers={ver_tuple}", text)
    text = re.sub(r"prodvers=\([^)]+\)", f"prodvers={ver_tuple}", text)
    text = re.sub(r"u'FileVersion', u'[^']+'", f"u'FileVersion', u'{dotted}'", text)
    text = re.sub(r"u'ProductVersion', u'[^']+'", f"u'ProductVersion', u'{dotted}'", text)
    VERSION_INFO.write_text(text, encoding="utf-8")
    print(f"  patched {VERSION_INFO.name} -> {dotted}")


def _patch_app_version(dotted_short: str) -> None:
    """autotax_watcher.py içindeki APP_VERSION sabitini güncelle."""
    if not WATCHER_PY.exists():
        print(f"ERROR: {WATCHER_PY} missing", file=sys.stderr)
        sys.exit(1)
    text = WATCHER_PY.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'APP_VERSION\s*=\s*"[^"]+"',
        f'APP_VERSION = "{dotted_short}"',
        text,
        count=1,
    )
    if n == 0:
        print("ERROR: APP_VERSION not found in autotax_watcher.py", file=sys.stderr)
        sys.exit(1)
    WATCHER_PY.write_text(new_text, encoding="utf-8")
    print(f"  patched {WATCHER_PY.name} APP_VERSION -> {dotted_short}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("version", help="örn: 2.0.1")
    p.add_argument("--update-py", action="store_true", help="autotax_watcher.py içindeki APP_VERSION'u da güncelle")
    args = p.parse_args()

    short = args.version.strip()
    ver = _parse_version(short)
    dotted_4 = ".".join(str(x) for x in ver)
    _patch_version_info(ver, dotted_4)
    if args.update_py:
        _patch_app_version(short)


if __name__ == "__main__":
    main()
