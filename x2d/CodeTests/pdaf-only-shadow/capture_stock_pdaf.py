"""Bounded stock AF-S/PDAF log capture with exact temporary-file ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from device_readonly_probe import _public_metadata, check_stock_afs
from pdaf425_readonly_usb import ReadOnlyCamera, ReadOnlyUsbError
from sanitize_pdaf_records import sanitize_lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("start", help="start the bounded 30-second temporary logger")
    read = commands.add_parser("read", help="export a completed capture as sanitized records")
    read.add_argument("--capture-id", required=True)
    read.add_argument("--max-lines", type=int, default=2048)
    read.add_argument("--output", type=Path)
    cleanup = commands.add_parser("cleanup", help="remove only the selected owned temporary capture")
    cleanup.add_argument("--capture-id", required=True)
    args = parser.parse_args()

    if args.mode == "read" and not 1 <= args.max_lines <= 4096:
        parser.error("--max-lines must be between 1 and 4096")
    if args.mode in ("read", "cleanup") and len(args.capture_id) != 16:
        parser.error("--capture-id must be the 16-character ID printed by start")

    try:
        with ReadOnlyCamera() as reader:
            if args.mode == "start":
                state = check_stock_afs(reader)
                token = reader.start_capture(state["pid"])
                payload = {**_public_metadata(state), "capture_id": token,
                           "auto_stop_seconds": 30,
                           "instructions": "半按快门对准有纹理的目标约 20 秒，不要完全按下快门。时间标记保存在设备私有临时记录中。"}
            elif args.mode == "read":
                raw_lines, marker = reader.read_capture(args.capture_id, args.max_lines)
                records = sanitize_lines(raw_lines, marker)
                payload = {"model": "X2D 100C first generation", "firmware": "4.2.0",
                           "lens": "55V", "focus_mode": "AF-S",
                           "matched_records": len(records),
                           "records": records, "complete_file_export": True,
                           "sensor_frame_coverage": "unknown"}
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
            else:
                reader.cleanup_capture(args.capture_id)
                payload = {"cleanup_complete": True}
    except ReadOnlyUsbError as error:
        parser.exit(2, f"operation stopped safely: {error}\n")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
