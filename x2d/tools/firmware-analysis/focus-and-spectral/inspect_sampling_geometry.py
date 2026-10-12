"""Read-only inspection of sampling descriptors, not a silicon pixel counter."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile
from inspect_pdaf import VERSIONS


def region(text, name, opening="{"):
    match = re.search(r"\b" + re.escape(name) + r"\s*:\s*" + re.escape(opening), text)
    if not match:
        raise ValueError("Configuration region missing: " + name)
    start = match.end() - 1
    closing = "}" if opening == "{" else "]"
    depth = 0
    for index in range(start, len(text)):
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if not depth:
                return text[start:index + 1]
    raise ValueError("Unterminated configuration region")


def inspect(root, output):
    output.mkdir(parents=True, exist_ok=True)
    result = {"method": "offline static descriptors and extraction instructions",
              "scope": "configured/compiled sampling geometry; physical silicon PDAF population remains unverified",
              "versions": {}}
    for folder, spec in VERSIONS.items():
        path = root / folder / "lib64/libaaa.so"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != spec["sha256"]:
            raise ValueError("Firmware baseline mismatch")
        record = {"model": spec["model"], "firmware": spec["version"], "sha256": digest}
        with path.open("rb") as f:
            elf = ELFFile(f)
            symbols = {s.name: s for s in elf.get_section_by_name(".dynsym").iter_symbols() if s["st_value"]}
            section = elf.get_section_by_name(".text")
            data, base = section.data(), section["sh_addr"]
            md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
            listing = []
            for name in ["get_sensor_specifics", "set_sensor_specifics", "extract_pdaf_pixels", "process_configuration"]:
                sym = symbols[name]
                address, size = sym["st_value"], sym["st_size"]
                listing.append("\n" + name + " @ " + hex(address))
                for ins in md.disasm(data[address - base:address - base + size], address):
                    listing.append(f"{ins.address:08x}  {ins.mnemonic:8s} {ins.op_str}")
            if folder == "x2d-system-root":
                start = 0x1b2a08
                for sec in elf.iter_sections():
                    if sec["sh_type"] != "SHT_NOBITS" and sec["sh_addr"] <= start < start + 252 <= sec["sh_addr"] + sec["sh_size"]:
                        table = sec.data()[start - sec["sh_addr"]:start - sec["sh_addr"] + 252]
                        break
                else:
                    raise ValueError("Sensor descriptor table not file-backed")
                modes = []
                for index in range(3):
                    raw = table[index * 84:(index + 1) * 84]
                    words = struct.unpack("<42H", raw)
                    lengths = struct.unpack_from("<4h", raw, 0x48)
                    offsets = [list(struct.unpack_from("<6h", raw, 0x18 + channel * 12)[:lengths[channel]])
                               for channel in range(4)]
                    cols, rows = words[7], words[8]
                    # Enumerate the address equations used by extract_pdaf_pixels.
                    addresses = set()
                    reads = 0
                    for y in range(rows):
                        raw_y = words[5] + y * words[6]
                        for x in range(cols):
                            raw_x = words[3] + x * words[4]
                            for channel_offsets in offsets:
                                for offset in channel_offsets:
                                    column = (raw_x + offset) & 0xffff
                                    if not (0 <= column < words[2] and 0 <= raw_y < words[1]):
                                        raise ValueError("Compiled sampling address outside descriptor frame")
                                    addresses.add(raw_y * words[2] + column)
                                    reads += 1
                    modes.append({"table_index": index, "elf_va": hex(start + index * 84),
                                  "raw_width": words[0], "raw_height": words[1], "raw_stride": words[2],
                                  "first_x": words[3], "x_step": words[4], "first_y": words[5], "y_step": words[6],
                                  "sample_columns": cols, "sample_rows": rows,
                                  "extraction_mode": struct.unpack_from("<I", raw, 0x14)[0],
                                  "channel_lengths": list(lengths), "channel_offsets": offsets,
                                  "groups": cols * rows, "scalar_reads_full_descriptor": reads,
                                  "unique_raw_addresses_full_descriptor": len(addresses),
                                  "warning": "Groups and scalar addresses are not counts of physically masked PDAF pixels; active ROI/mode was not measured."})
                if (modes[0]["sample_columns"], modes[0]["sample_rows"], modes[0]["y_step"]) != (970, 42, 210):
                    raise ValueError("Unexpected first-generation descriptor")
                record["compiled_type3_descriptors"] = modes
            (output / (folder + "-sampling.txt")).write_text("\n".join(listing) + "\n")
        result["versions"][folder] = record
    config = root / "x2d2-system-root/etc/aaa/af/af_imx861.json"
    raw = config.read_bytes()
    if hashlib.sha256(raw).hexdigest() != "e4f965ed8634c0e14d418d4f57131243d7ea197b8abea2a84d9ee0f934d2ed9e":
        raise ValueError("Second-generation configuration baseline mismatch")
    text = re.sub(r"//[^\n]*", "", raw.decode())
    pdaf_stats = region(text, "pdaf_stats")
    sensors = region(pdaf_stats, "sensor", "[")
    first = sensors[sensors.index("{"):]
    # First full-size/calibration descriptor; subsequent live-view entries are not conflated with it.
    depth = 0
    for i, char in enumerate(first):
        depth += (char == "{") - (char == "}")
        if depth == 0:
            first = first[:i + 1]
            break
    keys = ["sensor_width_pixels", "sensor_height_pixels", "pdaf_stats_width", "pdaf_stats_height",
            "pdaf_columns", "pdaf_rows", "pdaf_column_per_block", "pdaf_row_per_block",
            "pdaf_blocks_nx", "pdaf_blocks_ny", "pdaf_column_distance", "pdaf_row_distance",
            "pdaf_w_binning", "pdaf_h_binning", "pdaf_blk_avg_width", "pdaf_blk_avg_height"]
    descriptor = {key: int(re.search(r"\b" + key + r"\s*:\s*(\d+)", first).group(1)) for key in keys}
    descriptor["pdaf_len"] = [int(n) for n in re.findall(r"\d+", region(first, "pdaf_len", "["))]
    if (descriptor["pdaf_columns"], descriptor["pdaf_rows"]) != (1828, 485):
        raise ValueError("Unexpected second-generation descriptor")
    descriptor["configured_blocks"] = descriptor["pdaf_blocks_nx"] * descriptor["pdaf_blocks_ny"]
    descriptor["warning"] = "This is a configured Type2 full-size/calibration block layout, not a measured sensor-wide physical pixel count. Do not divide it by the Type3 averaged output size to claim a hardware ratio."
    result["second_generation_type2_descriptor"] = descriptor
    driver = root / "x2d2-system-root/lib64/libsensor_imx861.so"
    raw = driver.read_bytes()
    driver_hash = hashlib.sha256(raw).hexdigest()
    if driver_hash != "38648a00138f2f5315e857546f357f07da52a6d31c31fde7d39ac02a22641aaa":
        raise ValueError("Second-generation driver baseline mismatch")
    result["second_generation_driver"] = {
        "sha256": driver_hash,
        "pdaf_control_strings": [{"file_offset": hex(m.start()), "text": m.group().decode()}
                                 for m in re.finditer(rb"[\x20-\x7e]{6,}", raw)
                                 if b"pdaf again_reg" in m.group() or b"pdaf integration time" in m.group()],
        "limit": "Static driver diagnostic evidence; does not prove a particular camera mode enabled these controls.",
    }
    (output / "sampling-geometry-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Verified sampling tables, extraction address bounds and Type2 block configuration; no hardware total inferred.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("firmware_analysis_root", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new local output directory outside the input tree")
    args = parser.parse_args()
    source_root = args.firmware_analysis_root.resolve(strict=True)
    output_root = args.output.resolve()
    if output_root == source_root or source_root in output_root.parents:
        parser.error("output must be outside the read-only firmware input tree")
    if output_root.exists():
        parser.error("output must not already exist")
    inspect(args.firmware_analysis_root, args.output)
