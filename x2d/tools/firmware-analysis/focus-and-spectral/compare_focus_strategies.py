"""Static comparison of first/second-generation focus control dependencies."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile
from inspect_pdaf import VERSIONS


def compare(root, output):
    output.mkdir(parents=True, exist_ok=True)
    result = {"method": "static calls and configuration; no device access or covered-radar trace",
              "versions": {}}
    for folder, spec in VERSIONS.items():
        path = root / folder / "lib64/libaaa.so"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != spec["sha256"]:
            raise ValueError("Firmware baseline mismatch")
        record = {"model": spec["model"], "firmware": spec["version"],
                  "sha256": digest, "functions": {}, "absent_exports": []}
        with path.open("rb") as f:
            elf = ELFFile(f)
            symbols = list(elf.get_section_by_name(".dynsym").iter_symbols())
            lookup = {s.name: s for s in symbols if s["st_value"]}
            names = {s["st_value"]: s.name for s in symbols if s["st_value"]}
            plt = elf.get_section_by_name(".plt")
            for index, rel in enumerate(elf.get_section_by_name(".rela.plt").iter_relocations()):
                names[plt["sh_addr"] + 32 + 16 * index] = symbols[rel["r_info_sym"]].name
            section = elf.get_section_by_name(".text")
            data, base = section.data(), section["sh_addr"]
            md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
            listing = []

            def inspect(name, start, size):
                calls = []
                listing.append("\n" + name + " @ " + hex(start))
                for ins in md.disasm(data[start - base:start - base + size], start):
                    target_name = ""
                    if ins.mnemonic == "bl":
                        target = int(ins.op_str[1:], 16)
                        target_name = names.get(target, "")
                        calls.append({"at": hex(ins.address), "target": hex(target), "name": target_name})
                    listing.append(f"{ins.address:08x}  {ins.mnemonic:8s} {ins.op_str} {target_name}")
                record["functions"][name] = {"elf_va": hex(start), "size": size, "direct_calls": calls}

            for name in ["_exec_pdaf_afs_process", "_exec_pdaf_afc_process", "afc_process",
                         "afc_ctrl_process", "get_pdaf_type2_align_lens_pos"]:
                if name not in lookup:
                    record["absent_exports"].append(name)
                    continue
                s = lookup[name]
                inspect(name, s["st_value"], s["st_size"])
            if folder == "x2d2-system-root":
                inspect("local_align_position_helper", 0x185f08, 0x98)
                if not any(c["at"] == "0x185f24" and c["name"] == "get_pdaf_type2_align_lens_pos"
                           for c in record["functions"]["local_align_position_helper"]["direct_calls"]):
                    raise ValueError("Unexpected second-generation alignment helper")
            (output / (folder + "-focus-control.txt")).write_text("\n".join(listing) + "\n")
        result["versions"][folder] = record
    config = root / "x2d2-system-root/etc/aaa/af/af_imx861.json"
    raw = config.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != "e4f965ed8634c0e14d418d4f57131243d7ea197b8abea2a84d9ee0f934d2ed9e":
        raise ValueError("Configuration baseline mismatch")
    text = raw.decode()
    keys = ["enable_tof_tracking", "skip_wait_for_ae", "stats_frame_delay_vs_lens",
            "low_lattency_afc_enable", "afc_interval_time_ms", "fusion_enable",
            "master_algo_type", "slave_algo_type", "backup_algo_type",
            "pos_unit_in_fdelta_flag", "invalid_cnt_th", "keep_cnt_th"]
    result["second_generation_configuration"] = {
        "sha256": digest,
        "matched_lines": [{"line": i, "text": line.strip()} for i, line in enumerate(text.splitlines(), 1)
                          if any(re.match(r"\s*" + key + r"\s*:", line) for key in keys)],
        "afc_ctrl_alg_cfg": [1, 0, 0, 1],
        "afc_ctrl_alg_cfg_source_lines": [1589, 1594],
        "interpretation_limit": "Enabled configuration is not proof that ToF contributed to a particular focus event.",
    }
    block = re.search(r"afc_ctrl_alg_cfg\s*:\s*\[(.*?)\]", text, re.S).group(1)
    block = re.sub(r"//[^\n]*", "", block)
    if [int(n) for n in re.findall(r"\d+", block)] != [1, 0, 0, 1]:
        raise ValueError("Unexpected AFC algorithm selection")
    (output / "focus-strategy-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Verified both control call graphs, alignment dependency and second-generation fusion configuration.")


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
    compare(args.firmware_analysis_root, args.output)
