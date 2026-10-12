"""Offline PDAF interface/capacity audit; never executes or modifies firmware."""
import argparse
import hashlib
import json
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile


VERSIONS = {
    "x2d-system-root": {
        "model": "X2D 100C first generation", "version": "4.2.0",
        "sha256": "feef8a8dc3a27395e47232c2b25a5da7a7ab335922fbb527e637c439e35bcec7",
        "functions": ["pdaf_type3_init_impl", "pdaf_type3_get_stat_cfg",
                      "pdaf_type3_statistics", "pdaf_type3_run",
                      "pdaf_type3_stats_lib_create", "pdaf_type3_stats_lib_calc",
                      "pdaf_type3_stats_lib_get_results", "process_configuration",
                      "process_scene_configuration", "calculate_pdaf_stat",
                      "allocate_pdaf_result", "get_sensor_specifics"],
    },
    "x2d2-system-root": {
        "model": "X2D II 100C", "version": "1.3.16.2",
        "sha256": "7d6164eccc734de7087bb778ee72f17a0b3ccf6c0d1f20092c7ebe74a86574ba",
        "functions": ["pdaf_type2_run", "pdaf_type2_statistics",
                      "pdaf_type2_get_stat_cfg", "_exec_pdaf_afs_process"],
    },
}


def inspect(root, output):
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"method": "offline static inspection, no camera access",
                "versions": {}, "capacity_scope": "one packed Type3 result interface, not advertised AF zones"}
    for folder, spec in VERSIONS.items():
        path = root / folder / "lib64/libaaa.so"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != spec["sha256"]:
            raise ValueError("Firmware input hash mismatch: " + folder)
        record = {"model": spec["model"], "version": spec["version"],
                  "sha256": digest, "functions": {}}
        with path.open("rb") as f:
            elf = ELFFile(f)
            symbols = list(elf.get_section_by_name(".dynsym").iter_symbols())
            lookup = {s.name: s for s in symbols}
            names = {s["st_value"]: s.name for s in symbols if s["st_value"]}
            plt = elf.get_section_by_name(".plt")
            for index, reloc in enumerate(elf.get_section_by_name(".rela.plt").iter_relocations()):
                names[plt["sh_addr"] + 32 + 16 * index] = symbols[reloc["r_info_sym"]].name
            section = elf.get_section_by_name(".text")
            base, data = section["sh_addr"], section.data()
            md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
            listing = []
            for name in spec["functions"]:
                sym = lookup[name]
                start, size = sym["st_value"], sym["st_size"]
                calls = []
                listing.append("\n" + name + " @ " + hex(start))
                for ins in md.disasm(data[start - base:start - base + size], start):
                    target_name = ""
                    if ins.mnemonic == "bl":
                        target = int(ins.op_str[1:], 16)
                        target_name = names.get(target, "")
                        calls.append({"at": hex(ins.address), "target": hex(target), "name": target_name})
                    listing.append(f"{ins.address:08x}  {ins.mnemonic:8s} {ins.op_str} {target_name}")
                record["functions"][name] = {"elf_va": hex(start), "size": size, "calls": calls}
            (output / (folder + "-disassembly.txt")).write_text("\n".join(listing) + "\n")
            if folder == "x2d-system-root":
                # Verify instructions underlying the fixed-size interface/capacity calculation.
                checked = {
                    0x8efec: ("cmp", "w8, #0x7d0"),
                    0x8f0b4: ("mov", "w2, #0x6ff"),
                    0x8d2d4: ("mov", "w2, #0x666"),
                    0x8d2f0: ("mov", "w2, #0x1f8"),
                    0xd9b2c: ("strb", "w10, [x19, #0x6fe]"),
                    0xd9b34: ("strb", "w10, [x19, #0x6fd]"),
                    0xd9b58: ("mov", "w14, #0xd"),
                    0xd9b84: ("stur", "w16, [x18, #0x97]"),
                }
                record["verified_instructions"] = {}
                for address, expected in checked.items():
                    ins = next(md.disasm(data[address - base:address - base + 4], address))
                    if (ins.mnemonic, ins.op_str) != expected:
                        raise ValueError("Unexpected instruction at " + hex(address))
                    record["verified_instructions"][hex(address)] = ins.mnemonic + " " + ins.op_str
        evidence["versions"][folder] = record
    evidence["packed_result"] = {
        "payload_bytes": 0x6ff, "record_start": 0x97, "record_stride": 13,
        "dimension_tail": 0x6fd, "slot_count": (0x6fd - 0x97) // 13,
        "history_record_bytes": 0x666, "temporary_float_array_bytes": 0x1f8,
        "hypothetical_sizes": {str(n): 0x97 + n * 13 + 2 for n in (126, 294, 425)},
        "warning": "126 is a capacity of this particular ABI. It is not the number of physical PDAF sites or marketed focus zones.",
    }
    config = root / "x2d2-system-root/etc/aaa/af/af_imx861.json"
    text = config.read_text()
    expected = "e4f965ed8634c0e14d418d4f57131243d7ea197b8abea2a84d9ee0f934d2ed9e"
    if hashlib.sha256(config.read_bytes()).hexdigest() != expected:
        raise ValueError("Second-generation configuration hash mismatch")
    evidence["x2d2_config"] = {
        "sha256": expected,
        "matched_lines": [{"line": i, "text": line.strip()} for i, line in enumerate(text.splitlines(), 1)
                          if any(key in line for key in ("pd_type :", "af_pdaf_type2_load_cfg_s",
                                                        "PDAF_TYPE_MODE_DSP_V3", "mesh_num_x", "mesh_num_y"))],
    }
    (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print("Verified both firmware baselines, fixed interface instructions and capacity arithmetic.")


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
