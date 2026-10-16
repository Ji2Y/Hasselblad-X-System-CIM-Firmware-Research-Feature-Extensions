"""X2D II 1.3.16.2 AF-S 路径离线审计；不连接或控制相机。

复用现有 ELF/APS2 读取器，显式覆盖机型哈希；不使用一代参数地址。
输入原厂 ELF 与配置文本未随研究仓库提供。配置是带枚举的文本，
不是严格 JSON；这里只校验全文哈希，不执行枚举或评估表达式。
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "x2d/CodeTests/pdaf-only-shadow"))
from native_afs_parameters import LockedElf

AAA_SHA256 = "7d6164eccc734de7087bb778ee72f17a0b3ccf6c0d1f20092c7ebe74a86574ba"
CONFIG_SHA256 = "e4f965ed8634c0e14d418d4f57131243d7ea197b8abea2a84d9ee0f934d2ed9e"

WORDS = {
    0x1ca448: 0x97fa0f52, 0x1ca44c: 0x39400001, 0x1ca454: 0x97fffd77,
    0x1c9a6c: 0x7100051f, 0x1c9a70: 0x540002e0,
    0x1c9ad8: 0xf9456508, 0x1c9ae0: 0xf9456929, 0x1c9ae4: 0xf9456d4a,
    0x1c9ae8: 0xf945716b, 0x1c9afc: 0xf9457508, 0x1c9b00: 0x9e670162,
    0x1c9b18: 0xf9457d08,
    0x1d4ee0: 0x97f9e9d0, 0x1d4ef4: 0x320003e1, 0x1d4efc: 0x97f9eb75,
    0x1d4f00: 0x72001c1f, 0x1d4f04: 0x54000120, 0x1d4f18: 0xb94102a8,
    0x1d4f1c: 0xb9402c09, 0x1d4f20: 0x6b08013f, 0x1d4f24: 0x540006ea,
    0x1d4fc8: 0x528000a1, 0x1d4fcc: 0x97f9eb41, 0x1d4fd4: 0x54000120,
    0x1d4ff8: 0x2a1f03e0,
    0x1d5418: 0x97f9ea2e, 0x1d5420: 0x54000d20, 0x1d5434: 0xb94102a8,
    0x1d5438: 0xb9402f29, 0x1d543c: 0x6b08013f, 0x1d5440: 0x54000c2b,
    0x185f24: 0x97fb3097, 0x186438: 0x97fffeb4, 0x186454: 0x0b140314,
    0x18659c: 0x97fb2f09, 0x1865c8: 0x1e610800, 0x1865cc: 0x1e682000,
    0x1865d0: 0x1a934113, 0x18666c: 0x97fb2edd, 0x186670: 0x71000e7f,
    0x186684: 0xb8a87928, 0x18668c: 0xd61f0100, 0x1868c4: 0x97fb20b3,
    0x1868d8: 0x97fb26a6, 0x186944: 0x97fb2e33, 0x186968: 0x97fb267e,
    0x1d9228: 0xb9415288, 0x1d9230: 0x54000641, 0x1d9524: 0x6b19011f,
    0x1d9584: 0x540000ab, 0x1d96ec: 0xb9409269, 0x1d96f4: 0x54fffe0c,
    0x1d96f8: 0x6b1a013f, 0x1d96fc: 0x54fffdcb,
    0x1da1bc: 0x97f9d519, 0x1da308: 0x3945a2a8, 0x1da3d8: 0xb94182a8,
    0x1da3e0: 0x6a09011f, 0x1da3e4: 0x540015c0,
    0x598078: 0x72003f1f, 0x598094: 0x6b08015f, 0x598098: 0x1a98b168,
    0x5980a0: 0x1a9f0118, 0x5980a4: 0x97eadd9f, 0x5980c4: 0x1e212000,
    0x5980c8: 0x540000ad, 0x5980fc: 0x7100091f, 0x598104: 0x1a893118,
    0x59811c: 0xb8bb7909, 0x598124: 0xd61f0100, 0x598200: 0x2a1f03f7,
    0x598208: 0xb942c6f7, 0x598210: 0xb942d2f7, 0x598218: 0xb942baf7,
    0x59826c: 0x97eae041, 0x598c98: 0x97eae8f6,
}

CALLBACKS = {
    0x719ac8: ("af_hybrid_hasselblad_policy_stage_goto_peak", 0x1da180, 1736),
    0x719ad0: ("af_hybrid_hasselblad_policy_stage_peak", 0x1d7840, 6568),
    0x719ad8: ("af_hybrid_hasselblad_policy_stage_end", 0x1da848, 128),
    0x719ae0: ("af_hybrid_hasselblad_policy_stage_start", 0x1d4eb0, 916),
    0x719ae8: ("af_hybrid_hasselblad_policy_stage_check_peak", 0x1d91e8, 1820),
    0x719af0: ("af_hybrid_hasselblad_policy_stage_dir", 0x1d5248, 9716),
    0x719af8: ("af_hybrid_hasselblad_policy_stage_idle", 0x1da8c8, 8),
}
JUMPS = {
    "pdaf_result": (0x6cb198, [0x186690, 0x186978, 0x1866c0, 0x186860]),
    "dtof_result": (0x6d223c, [0x598128, 0x598210, 0x598208, 0x598218]),
}


def audit(library, config):
    class X2D2Elf(LockedElf):
        EXPECTED_SHA256 = AAA_SHA256
    elf = X2D2Elf(library)
    if hashlib.sha256(config).hexdigest() != CONFIG_SHA256:
        raise ValueError("not the reviewed X2D II af_imx861 config")
    for address, expected in WORDS.items():
        if struct.unpack("<I", elf.read(address, 4))[0] != expected:
            raise ValueError(f"instruction mismatch at {address:#x}")
    symbols = {s["name"]: s for s in elf.dynamic if s["section"]}
    for address, (name, value, size) in CALLBACKS.items():
        symbol = symbols.get(name)
        if symbol is None or (symbol["value"], symbol["size"]) != (value, size):
            raise ValueError("policy callback symbol mismatch")
        elf.relocated_pointer(address, name, value, 1025)
    for name, (base, expected) in JUMPS.items():
        actual = [base + struct.unpack("<i", elf.read(base + i * 4, 4))[0]
                  for i in range(len(expected))]
        if actual != expected:
            raise ValueError(f"result dispatch mismatch: {name}")
    return {
        "model": "X2D II 100C", "firmware": "1.3.16.2",
        "verification": "static offline only", "device_access": False,
        "deployable": False, "library_sha256": AAA_SHA256,
        "config_sha256": CONFIG_SHA256, "instruction_count": len(WORDS),
        "policy_callback_count": len(CALLBACKS), "result_jump_table_count": len(JUMPS),
        "evidence": [{"va": hex(a), "word": hex(w)} for a, w in WORDS.items()],
        "config_review": {
            "hybrid_policy": 1, "enabled_algorithms": ["CDAF", "PDAF", "ToF"],
            "goto_refine_enabled": True, "goto_refine_algorithm_mask": 0,
            "pdaf_result_ok_peak_score": 80, "pdaf_result_super_ok_peak_score": 120,
            "tof_result_ok_peak_score": 80, "tof_result_super_ok_peak_score": 99,
            "live_overrides_read": False,
        },
        "conclusions": [
            "Policy 1 resolves to Hasselblad-specific stage callbacks.",
            "Start-stage PDAF validity/direction checks can succeed before checking ToF.",
            "PDAF AF-S consumes aligned lens position and temporal standard deviation.",
            "PDAF result 3 has a range-limited absolute lens-command branch.",
            "DTOF quality logic can downgrade/zero a result; classification is not an unconditional distance command.",
            "Goto refinement is separately mask-gated; all-off supplied config is not always-on CDAF refinement.",
        ],
        "limitations": [
            "The supplied config may be overridden at runtime.",
            "A hand over the window does not prove ToF's exact result or selected AF branch.",
            "No matched-scene X2D/X2D II sharpness or timing experiment was performed.",
            "No Kalman attribution or safe cross-generation binary port is established.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {args.library.resolve(), args.config.resolve()}:
        parser.error("output must not overwrite an input")
    report = audit(args.library.read_bytes(), args.config.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{report['instruction_count']} instructions, 7 callbacks, 2 dispatch tables checked; offline only")


if __name__ == "__main__":
    main()
