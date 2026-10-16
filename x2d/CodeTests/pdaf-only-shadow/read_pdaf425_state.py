"""Take up to eight bounded, read-only snapshots of the stock PDAF state."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

from device_readonly_probe import check_stock_afs
from pdaf425_readonly_usb import ReadOnlyCamera, ReadOnlyUsbError


LIBRARY_SHA256 = "feef8a8dc3a27395e47232c2b25a5da7a7ab335922fbb527e637c439e35bcec7"


class LockedLibrary:
    """Read file-backed AArch64 addresses from one exact stock library."""

    def __init__(self, data: bytes):
        if hashlib.sha256(data).hexdigest() != LIBRARY_SHA256:
            raise ValueError("input is not the checked X2D 4.2.0 libaaa.so")
        if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
            raise ValueError("expected a little-endian AArch64 ELF64 library")
        phoff = struct.unpack_from("<Q", data, 32)[0]
        phentsize, phnum = struct.unpack_from("<HH", data, 54)
        if phentsize < 56 or not 1 <= phnum <= 4096 or phoff + phentsize * phnum > len(data):
            raise ValueError("invalid ELF program header table")
        self.data = data
        self.loads = []
        for index in range(phnum):
            values = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phentsize)
            kind, _flags, offset, address, _physical, file_size, mem_size, _align = values
            if kind == 1:
                if offset + file_size > len(data) or file_size > mem_size:
                    raise ValueError("invalid ELF load segment")
                self.loads.append((address, address + file_size, offset))

    def read(self, address: int, length: int) -> bytes:
        if address < 0 or length < 0:
            raise ValueError("invalid library read range")
        for start, end, offset in self.loads:
            if start <= address and address + length <= end:
                file_offset = offset + address - start
                return self.data[file_offset:file_offset + length]
        raise ValueError("requested library range is not file-backed")


def collect(reader: ReadOnlyCamera, library: LockedLibrary, samples: int) -> dict:
    if type(samples) is not int or not 1 <= samples <= 8:
        raise ValueError("samples must be between 1 and 8")
    state = check_stock_afs(reader)
    pid = state["pid"]
    bias = state["load_bias"]
    contracts = ((0x8E618, 596), (0xD93C0, 1528), (0xD99B8, 1092), (0xCADA0, 840))
    for address, size in contracts:
        expected = hashlib.sha256(library.read(address, size)).hexdigest()
        if reader.memory_hash(pid, bias + address, size) != expected:
            raise ReadOnlyUsbError("live PDAF calculation code differs from the checked library")

    result = {"model": "X2D 100C first generation", "firmware": "4.2.0", "lens": "55V",
              "focus_mode": "AF-S", "observations": [], "context_table_stable": None,
              "atomic_snapshot": False, "candidate_installed": False,
              "raw_frame_acquired": False, "parameter_writes": False,
              "motor_commands": False, "device_files_written": False}
    for sample in range(samples):
        if sample:
            time.sleep(0.5)
        table_address = bias + 0xA6B5E8
        table_bytes = reader.read_memory(pid, table_address, 32 * 8)
        table = struct.unpack("<32Q", table_bytes)
        slots = []
        for index, pointer in enumerate(table):
            if not pointer:
                continue
            item = {"index": index, "segments": []}
            for segment, offset in ((1, 0), (2, 0xC938)):
                header = reader.read_memory(pid, pointer + offset + 0xA8, 64)
                descriptor_pointer = struct.unpack(
                    "<Q", reader.read_memory(pid, pointer + offset + 0x1C8, 8)
                )[0]
                info = {"segment": segment,
                        "local_count": struct.unpack_from("<I", header)[0],
                        "crop_sample_bounds": list(struct.unpack_from("<4I", header, 0xD4 - 0xA8))}
                if descriptor_pointer:
                    delta = descriptor_pointer - bias - 0x1B2A08
                    if delta not in (0, 84, 168):
                        raise ReadOnlyUsbError("unrecognized stock sampling descriptor")
                    spec = reader.read_memory(pid, descriptor_pointer, 84)
                    if spec != library.read(0x1B2A08 + delta, 84):
                        raise ReadOnlyUsbError("live sampling descriptor differs from the checked library")
                    info.update(descriptor_index=delta // 84,
                                sensor_fields=list(struct.unpack_from("<9H", spec)),
                                extract_mode=struct.unpack_from("<I", spec, 0x14)[0])
                else:
                    info["descriptor_index"] = None
                item["segments"].append(info)
            slots.append(item)
        after = reader.read_memory(pid, table_address, 32 * 8)
        result["observations"].append({"sample": sample,
                                       "context_table_stable": table_bytes == after,
                                       "slots": slots})

    result["context_table_stable"] = all(row["context_table_stable"]
                                          for row in result["observations"])
    if reader.identity(pid) != state["process_identity"]:
        raise ReadOnlyUsbError("camera service changed during the observation")
    if reader.read_parameter(2, sequence=4).value != b"i1":
        raise ReadOnlyUsbError("camera left AF-S during the observation")
    result["final_validation_complete"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path,
                        help="operator-supplied, hash-locked X2D 4.2.0 libaaa.so")
    parser.add_argument("--output", required=True, type=Path,
                        help="private local JSON output; sanitize before sharing")
    parser.add_argument("--samples", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.samples <= 8:
        parser.error("--samples must be between 1 and 8")
    try:
        library = LockedLibrary(args.library.read_bytes())
        with ReadOnlyCamera() as reader:
            result = collect(reader, library, args.samples)
    except (OSError, ValueError, ReadOnlyUsbError) as error:
        parser.exit(2, f"observation stopped safely: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({"saved": True, "observations": len(result["observations"]),
                      "final_validation_complete": result["final_validation_complete"],
                      "device_identity_fields": "omitted"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
