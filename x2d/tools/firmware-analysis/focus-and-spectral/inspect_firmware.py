"""Read-only ELF inspection. Does not connect to a camera or execute firmware."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile


EXPECTED = {
    "lib64/libaaa.so": "feef8a8dc3a27395e47232c2b25a5da7a7ab335922fbb527e637c439e35bcec7",
    "lib64/librcam.so": "72ebc8deebce4a29047c475e77ab4edbf2860abb1f572fea45260fe17ad0bda5",
    "lib64/libdcam_fcali.so": "d41917ed783bdf47b0da25b5a372a51050634a4c8ee42c90de1d175533a03e4c",
    "lib/modules/as7341.ko": "55945fc9d633ebf8a496026a35d78a8ca4038c520ef5b2ca677a0a4f8c1516e8",
    "bin/camera-system": "bf854a21881148565ff2cc00376426c37a2b82fed94c653abf024e23ed4ceda6",
}
FUNCTIONS = [
    "dji_awb_set_stat", "scene_awb_set_main_spec_info",
    "scene_awb_set_main_spec_sensor_calib_info", "scene_awb_lib_init",
    "scene_awb_lib_run", "awb_spec_main_cal_stat",
    "scene_awb_spec_sensor_init", "scene_awb_spec_sensor_calib_gain_calc",
    "scene_awb_spec_sensor_proc", "scene_awb_scene_proc",
    "scene_awb_scene_compute_spec_ct_weight",
    "scene_awb_scene_spec_ct_weight_ratio",
    "scene_awb_scene_spec_ct_weight_ct_dis",
]


def inspect(root, output):
    output.mkdir(parents=True, exist_ok=True)
    result = {"model": "X2D 100C first generation", "firmware": "4.2.0",
              "method": "offline static inspection; no runtime activation claim",
              "sha256": {}, "strings": {}, "functions": {}}
    for name, expected in EXPECTED.items():
        data = (root / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected:
            raise ValueError("Unexpected firmware input: " + name)
        result["sha256"][name] = digest
        if name.endswith(("librcam.so", "as7341.ko", "libdcam_fcali.so")):
            found = []
            for m in re.finditer(rb"[\x20-\x7e]{5,}", data):
                if re.search(rb"as7341|Set awb spec sensor calib|spectrum data:|spec_calib", m.group(), re.I):
                    found.append({"file_offset": hex(m.start()), "text": m.group().decode()})
            result["strings"][name] = found
    with (root / "lib64/libaaa.so").open("rb") as f:
        elf = ELFFile(f)
        symbols = list(elf.get_section_by_name(".dynsym").iter_symbols())
        names = {s["st_value"]: s.name for s in symbols if s["st_value"]}
        plt = elf.get_section_by_name(".plt")
        for i, reloc in enumerate(elf.get_section_by_name(".rela.plt").iter_relocations()):
            names[plt["sh_addr"] + 32 + 16 * i] = symbols[reloc["r_info_sym"]].name
        section = elf.get_section_by_name(".text")
        base, data = section["sh_addr"], section.data()
        md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        listing = []
        for name in FUNCTIONS:
            sym = next(s for s in symbols if s.name == name)
            address, size = sym["st_value"], sym["st_size"]
            calls = []
            listing.append("\n" + name + " @ " + hex(address))
            for ins in md.disasm(data[address - base:address - base + size], address):
                target_name = ""
                if ins.mnemonic == "bl":
                    target = int(ins.op_str[1:], 16)
                    target_name = names.get(target, "")
                    calls.append({"at": hex(ins.address), "target": hex(target), "name": target_name})
                listing.append(f"{ins.address:08x}  {ins.mnemonic:8s} {ins.op_str} {target_name}")
            result["functions"][name] = {"elf_va": hex(address), "size": size, "calls": calls}
        constants = {}
        for address, fmt in [(0x1a11a0, "d"), (0x1a11a8, "d"), (0x1a1374, "f"),
                             (0x1a1378, "f"), (0x1a137c, "f"), (0x1a1380, "f"),
                             (0x1a1364, "f"), (0x1a120c, "f")]:
            for sec in elf.iter_sections():
                if sec["sh_addr"] <= address < sec["sh_addr"] + sec["sh_size"]:
                    constants[hex(address)] = struct.unpack_from("<" + fmt, sec.data(), address - sec["sh_addr"])[0]
                    break
        result["spectral_cct_constants"] = constants
        (output / "awb-disassembly.txt").write_text("\n".join(listing) + "\n")
    expected_fields = {"chan_data": 0, "chan_data_size": 20, "chan_value_unit": 22,
                       "chan_data_valid": 24, "expo_time": 28, "a_gain": 32}
    with (root / "lib/modules/as7341.ko").open("rb") as f:
        dwarf = ELFFile(f).get_dwarf_info()
        verified = False
        for unit in dwarf.iter_CUs():
            for die in unit.iter_DIEs():
                name = die.attributes.get("DW_AT_name")
                if die.tag != "DW_TAG_structure_type" or not name or name.value != b"as7341_spectrum_stats":
                    continue
                size = die.attributes.get("DW_AT_byte_size")
                if not size:
                    continue
                fields = {}
                for child in die.iter_children():
                    if child.tag == "DW_TAG_member":
                        fields[child.attributes["DW_AT_name"].value.decode()] = child.attributes["DW_AT_data_member_location"].value
                if size.value != 36 or fields != expected_fields:
                    raise ValueError("Unexpected driver statistics layout")
                verified = True
                break
            if verified:
                break
        if not verified:
            raise ValueError("Driver statistics structure not found in DWARF")
    result["driver_stats_layout"] = {
        "source": "as7341.ko DWARF; as7341_spectrum_stats",
        "size_bytes": 36,
        "fields": expected_fields,
        "optical_channels": ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "Clear", "NIR"],
    }
    (output / "evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Verified firmware hashes and saved static evidence.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("firmware_root", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new local output directory outside the input tree")
    args = parser.parse_args()
    source_root = args.firmware_root.resolve(strict=True)
    output_root = args.output.resolve()
    if output_root == source_root or source_root in output_root.parents:
        parser.error("output must be outside the read-only firmware input tree")
    if output_root.exists():
        parser.error("output must not already exist")
    inspect(args.firmware_root, args.output)
