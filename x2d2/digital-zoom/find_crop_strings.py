#!/usr/bin/env python3
"""Find the existing aspect-crop call in a local extract.

Digital zoom is not a new sensor mode. The body already records a rectangle
for 16:9, square and XPan. This only prints matching text from files you
already extracted. It does not unpack a CIM, write a file, or talk to a camera.

Run from this directory, pointing at your own extract, not at this repo:

    python3 find_crop_strings.py /path/to/local/extract
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

NEEDLES = (
    "setcrop",
    "croprect",
    "cropwindow",
    "croparea",
    "aspectratio",
    "imageaspect",
    "sensorcrop",
    "readoutwindow",
    "xpan",
)

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf",
    ".zip", ".gz", ".pyc", ".o", ".so", ".a",
}


def _strings(data: bytes) -> list[str]:
    out: list[str] = []
    start = None
    for index, byte in enumerate(data):
        if 32 <= byte < 127:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= 6:
                out.append(data[start:index].decode("ascii"))
            start = None
    if start is not None and len(data) - start >= 6:
        out.append(data[start:].decode("ascii"))
    return out


def scan(root: Path, needles: tuple[str, ...] = NEEDLES, limit: int = 40) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    files = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
    lowered = tuple(item.casefold() for item in needles)
    for path in files:
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for text in _strings(data):
            folded = text.casefold()
            if any(needle in folded for needle in lowered):
                hits.append((str(path), text[:160]))
                if len(hits) >= limit:
                    return hits
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extract", type=Path, help="file or directory you extracted locally")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    if not args.extract.exists():
        print(f"error: not found: {args.extract}", file=sys.stderr)
        return 1
    hits = scan(args.extract, limit=args.limit)
    if not hits:
        print("no crop or aspect strings")
        return 0
    for path, text in hits:
        print(f"{path}\n  {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
