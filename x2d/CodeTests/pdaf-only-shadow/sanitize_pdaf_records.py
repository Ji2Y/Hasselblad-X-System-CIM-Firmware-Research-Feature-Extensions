"""Remove local identity and absolute clock data before sharing PDAF records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


EPOCH = re.compile(r"^\s*(\d{10}(?:\.\d+)?)\s")
LABELED_EPOCH = re.compile(
    r"(?i)([\"']?(?:device_clock_marker|since|timestamp)[\"']?\s*:\s*)\d{10}(?:\.\d+)?"
)
REDACTIONS = (
    (re.compile(r"/tmp/pdafsh-[0-9a-fA-F]{8,16}"), "/tmp/<CAPTURE>"),
    (re.compile(r"(?i)(capture[_ -]?id[\"']?\s*[:=]\s*[\"']?)[0-9a-f]{8,16}\b"), r"\1<CAPTURE>"),
    (re.compile(r"/proc/[0-9]+"), "/proc/<PID>"),
    (re.compile(r"(?i)(--pid=)[0-9]+"), r"\1<PID>"),
    (re.compile(r"(?i)(pid|owner|process(?:_id)?)[\"']?\s*([=:])\s*[\"']?[0-9]+\b"), r"\1\2<PID>"),
    (re.compile(r"(?i)\b(?:serial(?:number)?|s/n|sn)[\"']?\s*[:=]\s*[\"']?[A-Z0-9-]{5,}\b"), "serial=<REDACTED>"),
    (re.compile(r"\bXT[0-9A-Z]{8,}\b"), "<DEVICE_SERIAL>"),
    (re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"), "<BOOT_ID>"),
    (re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"), "<MAC>"),
    (re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"), "<IP>"),
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "<EMAIL>"),
    (re.compile(r"/(?:Users|home)/[^/\s]+(?:/[^\s\"'<>]*)?"), "<LOCAL_PATH>"),
    (re.compile(r"/private/var/folders/[^\s\"'<>]+"), "<LOCAL_PATH>"),
    (re.compile(r"[A-Za-z]:\\Users\\[^\s\"'<>]+"), "<LOCAL_PATH>"),
)


def redact_text(value: str) -> str:
    result = value
    result = LABELED_EPOCH.sub(r"\1<RELATIVE_TIME_REQUIRED>", result)
    for pattern, replacement in REDACTIONS:
        result = pattern.sub(replacement, result)
    return result


def sanitize_lines(lines: list[str], since: float | None = None) -> list[str]:
    epochs = [float(match.group(1)) for line in lines if (match := EPOCH.match(line))]
    origin = since if since is not None else (epochs[0] if epochs else None)
    output = []
    for line in lines:
        match = EPOCH.match(line)
        if match and origin is not None:
            elapsed = max(0.0, float(match.group(1)) - origin)
            rest = line[match.end():]
            fields = rest.split(maxsplit=3)
            if len(fields) >= 3 and fields[0].isdigit() and fields[1].isdigit() and fields[2] in "VDIWEF":
                tail = fields[3] if len(fields) > 3 else ""
                rest = "<PID> <PID> " + fields[2] + (" " + tail if tail else "")
            line = f"t+{elapsed:.3f}s " + rest
        output.append(redact_text(line))
    return output


def sanitize_text(text: str, since: float | None = None) -> str:
    return "\n".join(sanitize_lines(text.splitlines(), since)) + ("\n" if text.endswith("\n") else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="private local text export")
    parser.add_argument("--output", required=True, type=Path, help="sanitized output path")
    parser.add_argument("--since", type=float, help="private device epoch marker; output uses relative time")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output must be different files")
    source = args.input.read_text(encoding="utf-8", errors="replace")
    clean = sanitize_text(source, args.since)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(clean, encoding="utf-8")
    print(json.dumps({"sanitized": True, "output_lines": len(clean.splitlines())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
