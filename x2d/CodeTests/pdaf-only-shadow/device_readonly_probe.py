"""Preflight and bounded stock AF-S/PDAF log reads for X2D 4.2.0 / 55V."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from pdaf425_readonly_usb import ReadOnlyCamera, ReadOnlyUsbError
from sanitize_pdaf_records import sanitize_lines


EXPECTED_DEVICE = "eagle2_ec1706_native"
EXPECTED_LIBRARY = "feef8a8dc3a27395e47232c2b25a5da7a7ab335922fbb527e637c439e35bcec7"
AFS_ENTRY = 0x90128
AFS_LENGTH = 1872
AFS_SHA256 = "042cc441a57fa5004b53f1f69a260799b4bb53768b311cf7d357d382ccce096d"
LENS_CONTEXT_VA = 0xA2F2F0
LENS_PRODUCT_OFFSET = 0x30
LENS_PRODUCT_55V = 81470


def _u64(raw: bytes) -> int:
    if len(raw) != 8:
        raise ReadOnlyUsbError("incomplete pointer read")
    return int.from_bytes(raw, "little")


def check_stock_afs(reader: ReadOnlyCamera) -> dict:
    """Prove the expected stock path before collecting any observation."""
    version = reader.read_parameter(27, sequence=1).value
    mode = reader.read_parameter(2, sequence=2).value
    runtime_flag = reader.read_parameter(28, sequence=3).value
    if version not in (b"S5,4.2.0", b"S6,v4.2.0") or mode != b"i1" or runtime_flag != b"i1":
        raise ReadOnlyUsbError("requires stock X2D 4.2.0 in AF-S")
    if reader.device_model() != EXPECTED_DEVICE:
        raise ReadOnlyUsbError("camera model does not match the recorded first-generation body")
    if reader.device_library_hash() != EXPECTED_LIBRARY:
        raise ReadOnlyUsbError("stock AF library version does not match the recorded build")

    pid = reader.camera_pid()
    before = reader.identity(pid)
    maps = reader.library_maps(pid)
    executable = [(start, end) for start, end, perm in maps if perm == "r-xp"]
    if len(executable) != 1:
        raise ReadOnlyUsbError("stock AF executable mapping is ambiguous")
    begin, end = executable[0]
    bias = begin - 0x1000
    function = bias + AFS_ENTRY
    if bias <= 0 or not begin <= function < function + AFS_LENGTH <= end:
        raise ReadOnlyUsbError("stock AF function is outside the executable mapping")
    if reader.memory_hash(pid, function, AFS_LENGTH) != AFS_SHA256:
        raise ReadOnlyUsbError("live AF-S function does not match the stock baseline")

    context = _u64(reader.read_memory(pid, bias + LENS_CONTEXT_VA, 8))
    if context <= 0:
        raise ReadOnlyUsbError("lens context was not available")
    product = int.from_bytes(reader.read_memory(pid, context + LENS_PRODUCT_OFFSET, 4), "little")
    if product != LENS_PRODUCT_55V:
        raise ReadOnlyUsbError("the attached lens is not the verified 55V profile")
    if reader.identity(pid) != before:
        raise ReadOnlyUsbError("camera service changed during the stock-path check")

    return {"model": "X2D 100C first generation", "firmware": "4.2.0",
            "lens": "55V", "focus_mode": "AF-S", "stock_verified": True,
            "pid": pid, "process_identity": before, "load_bias": bias}


def _public_metadata(state: dict) -> dict:
    public_fields = ("model", "firmware", "lens", "focus_mode", "stock_verified")
    return {key: state[key] for key in public_fields if key in state}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("mark", "read"))
    parser.add_argument("--since", type=float, help="private device-clock marker from mark mode")
    parser.add_argument("--kind", choices=("all", "state", "target", "zone"), default="all")
    parser.add_argument("--output", type=Path, help="write sanitized JSON locally")
    args = parser.parse_args()
    if args.mode == "read" and (args.since is None or args.since <= 0):
        parser.error("read mode requires --since from an earlier mark")

    try:
        with ReadOnlyCamera() as reader:
            state = check_stock_afs(reader)
            if args.mode == "mark":
                marker = reader.timestamp()
                payload = {**_public_metadata(state), "device_clock_marker": marker,
                           "instruction": "perform the manually controlled AF-S observation now"}
            else:
                raw = reader.recent_logs(state["pid"], args.kind)
                records = sanitize_lines(
                    [line for line in raw.splitlines()
                     if not (match := re.match(r"^\s*(\d{10}(?:\.\d+)?)\s", line))
                     or float(match.group(1)) >= args.since],
                    args.since,
                )
                payload = {**_public_metadata(state), "log_kind": args.kind,
                           "matched_records": len(records), "records": records,
                           "sensor_frame_coverage": "unknown"}
    except ReadOnlyUsbError as error:
        parser.exit(2, f"preflight or read stopped safely: {error}\n")

    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
