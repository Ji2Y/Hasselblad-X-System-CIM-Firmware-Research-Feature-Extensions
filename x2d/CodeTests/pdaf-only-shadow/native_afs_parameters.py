"""Version-locked offline audit of native X2D 4.2.0 AF-S parameters.

Standard library only. Reads an explicit local ELF, never loads firmware code
or opens USB. APS2 decoding follows Android bionic linker_reloc_iterators.h.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct


LIBRARY_SHA256 = "feef8a8dc3a27395e47232c2b25a5da7a7ab335922fbb527e637c439e35bcec7"
PRODUCT_VA = 0x1E22B0
PRODUCT_SIZE = 4032
PRIVATE_VA = 0x1E21C8
PARAM_POINTER_VA = 0xA2FA00
HYBRID_OFFSET = 0x18
CDAF_OFFSET = 0xD8
PDAF_OFFSET = 0x920
VDAF_OFFSET = 0xBF8
VDAF_SIZE = 0x68  # Next product substructure, ToF, begins at 0xc60.
SLOTS = ("CDAF", "PDAF", "BDAF", "VDAF", "LDAF", "ToF")
ALGORITHM_SLOTS = ("CDAF", "PDAF", "BDAF", "LDAF", "VDAF", "ToF")


def packed_rela(raw):
    """Decode Android APS2 RELA with signed LEB128 and bounded groups."""
    if raw[:4] != b"APS2":
        raise ValueError("expected Android APS2 relocations")
    cursor = 4

    def pop():
        nonlocal cursor
        value = shift = 0
        for _ in range(10):
            if cursor >= len(raw):
                raise ValueError("truncated SLEB128")
            byte = raw[cursor]
            cursor += 1
            value |= (byte & 127) << shift
            shift += 7
            if not byte & 128:
                return value - (1 << shift) if byte & 64 else value
        raise ValueError("oversized SLEB128")

    count, offset = pop(), pop()
    if not 0 <= count <= 1_000_000 or offset < 0:
        raise ValueError("invalid relocation header")
    info = addend = done = 0
    result = []
    while done < count:
        size, flags = pop(), pop()
        if not 0 < size <= count - done or flags < 0 or flags & ~15:
            raise ValueError("invalid relocation group")
        delta = pop() if flags & 2 else 0
        if flags & 1:
            info = pop()
        if flags & 12 == 12:
            addend += pop()
        elif not flags & 8:
            addend = 0
        for _ in range(size):
            offset += delta if flags & 2 else pop()
            if not flags & 1:
                info = pop()
            if flags & 12 == 8:
                addend += pop()
            if offset < 0 or info < 0:
                raise ValueError("invalid relocation entry")
            result.append((offset, info, addend))
        done += size
    # Android's section may reserve extra zero bytes after the encoded stream.
    if any(raw[cursor:]):
        raise ValueError("nonzero trailing packed relocation bytes")
    return result


class LockedElf:
    """Minimal file-backed ELF reader for one exact firmware library."""

    EXPECTED_SHA256 = LIBRARY_SHA256

    def __init__(self, data):
        if hashlib.sha256(data).hexdigest() != self.EXPECTED_SHA256:
            raise ValueError("not the checked X2D 4.2.0 ELF image")
        self.data = data
        if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
            raise ValueError("expected little-endian AArch64 ELF64")
        start = struct.unpack_from("<Q", data, 40)[0]
        size, count, names_index = struct.unpack_from("<HHH", data, 58)
        self.sections = [struct.unpack_from("<IIQQQQIIQQ", data, start + i * size)
                         for i in range(count)]
        names = self.section_data(self.sections[names_index])
        self.named = {self.string(names, s[0]): s for s in self.sections}
        self.dynamic = self.symbol_records(".dynsym")
        raw = self.section_data(self.named[".rela.dyn"])
        if raw[:4] == b"APS2":
            self.relocations = packed_rela(raw)
        else:
            if len(raw) % 24:
                raise ValueError("incomplete ELF64 RELA table")
            self.relocations = [struct.unpack_from("<QQq", raw, i)
                                for i in range(0, len(raw), 24)]

    def symbol_records(self, name):
        if name not in self.named:
            return []
        section = self.named[name]
        strings = self.section_data(self.sections[section[6]])
        raw = self.section_data(section)
        symbols = []
        for i in range(len(raw) // section[9]):
            name, info, other, ndx, value, length = struct.unpack_from("<IBBHQQ", raw, i * section[9])
            symbols.append({"name": self.string(strings, name), "value": value,
                            "size": length, "section": ndx, "type": info & 15})
        return symbols

    @staticmethod
    def string(raw, offset):
        return raw[offset:raw.index(b"\0", offset)].decode("utf-8")

    def section_data(self, section):
        return self.data[section[4]:section[4] + section[5]]

    def read(self, address, length):
        for s in self.sections:
            if s[1] != 8 and s[3] <= address and address + length <= s[3] + s[5]:
                offset = s[4] + address - s[3]
                return self.data[offset:offset + length]
        raise ValueError("requested range is not file-backed")

    def relocated_pointer(self, address, symbol, value, kind):
        matches = [r for r in self.relocations if r[0] == address]
        if len(matches) != 1:
            raise ValueError("expected exactly one pointer relocation")
        _, info, addend = matches[0]
        resolved = self.dynamic[info >> 32]
        if (info & 0xFFFFFFFF, resolved["name"], resolved["value"], addend) != (kind, symbol, value, 0):
            raise ValueError("pointer relocation does not match native parameter layout")


def decode_product(raw, private):
    if len(raw) != PRODUCT_SIZE or len(private) != 20:
        raise ValueError("incomplete native parameters")
    values = struct.unpack("<Iffff", private)
    if any(not math.isfinite(v) for v in values[1:]) or any(a > b for a, b in zip(values[1:], values[2:])):
        raise ValueError("invalid native confidence threshold table")
    vdaf = raw[VDAF_OFFSET:VDAF_OFFSET + VDAF_SIZE]
    return {
        "global_afs_enable_mask": struct.unpack_from("<I", raw, 8)[0],
        "global_mask_slots": {name: bool(raw[8] & (1 << i)) for i, name in enumerate(SLOTS)},
        "pdaf_private_type": values[0],
        "pdaf_zone_class_thresholds": {"class0": values[1], "class1": values[2],
                                       "class2": values[3], "class3": values[4]},
        "hybrid_peak_min_score": raw[HYBRID_OFFSET + 0x39],
        "hybrid_pdaf_class2_peak_mode_54": raw[HYBRID_OFFSET + 0x54],
        "bdaf_parameter_bytes": 0x110,
        "bdaf_parameters_all_zero": not any(raw[0xA30:0xB40]),
        "cdaf_nominal_peak_scores": {"mode0": raw[CDAF_OFFSET + 0x838],
                                     "mode1": raw[CDAF_OFFSET + 0x839]},
        "cdaf_score_adjustment_bytes": list(raw[CDAF_OFFSET + 0x83A:CDAF_OFFSET + 0x843]),
        "pdaf_peak_score_fields": {hex(i): raw[PDAF_OFFSET + i] for i in range(0x50, 0x5C)},
        "vdaf_parameter_bytes": len(vdaf), "vdaf_parameters_all_zero": not any(vdaf),
        "vdaf_configuration_word_04": struct.unpack_from("<I", vdaf, 4)[0],
        "vdaf_confidence_thresholds_u16": list(struct.unpack_from("<HHH", vdaf, 0x40)),
    }


def audit(data):
    elf = LockedElf(data)
    elf.relocated_pointer(0x1DC848, "p_af_params", PARAM_POINTER_VA, 1025)
    elf.relocated_pointer(PRODUCT_VA + PDAF_OFFSET + 0x48,
                          "af_x2d_pdaf_private_param", PRIVATE_VA, 257)
    for i, (name, address) in enumerate(zip(
            ("cdaf", "pdaf", "bdaf", "ldaf", "vdaf", "tof"),
            (0x4F4F0, 0x92EA0, 0x95250, 0x7D530, 0x84D70, 0x9D8F8))):
        elf.relocated_pointer(0x1DC530 + i * 8, name + "_manager_init", address, 257)
    instructions = {
        0xB0FDC: 0x91006000, 0xB0FF4: 0x91036000, 0xB107C: 0x91248000,
        0xB1104: 0x912FE000, 0xB1134: 0x91318000,
        0x8CEFC: 0xF9402408, 0x8CF00: 0xBD401100, 0x8CF20: 0xBD400D00,
        0x8CF40: 0xBD400900, 0x8CF60: 0xBD400500, 0x461C8: 0x3940E6BC,
        0x90554: 0x394166C3, 0x906B0: 0x39415AC3,
        0x416B8: 0x53030D08, 0x416BC: 0x39016268,
        0x416C4: 0x53041108, 0x416C8: 0x39012268,
        0x41408: 0x39016109, 0x41414: 0x3901210B,
        0x36738: 0x2A1F03E1, 0x36770: 0x97FFD808,
        0xA2934: 0xB9418109, 0xA2940: 0xB9418508,
        0x8DCC8: 0xB95F8688, 0x8DCCC: 0x71000D1F,
        0x8DD48: 0x97FE821A, 0x8DD50: 0x540004E0,
        0x8DDEC: 0x321F03E8, 0x8DDF0: 0xB91F8688,
        0x910CC: 0x91003261, 0x910D4: 0x97FE7807,
        0x8E094: 0x5283EF08, 0x8E09C: 0x3CE86A80, 0x8E0A0: 0x3D800120,
        0x901AC: 0xB9401A79, 0x90424: 0x0B080509, 0x9043C: 0x0B890949,
        0x90514: 0xB9406BF7, 0x905D8: 0x97FE776E,
    }
    for address, expected in instructions.items():
        if struct.unpack("<I", elf.read(address, 4))[0] != expected:
            raise ValueError("native parameter consumer instruction mismatch")
    jump_tables = {}
    for address, expected in ((0x1A13A8, (0x36734, 0x36734, 0x36768, 0x36844, 0x36740)),
                              (0x1A4A54, (0x903EC, 0x905E4, 0x90400, 0x90500))):
        destinations = tuple(address + delta for delta in
                             struct.unpack("<" + "i" * len(expected), elf.read(address, 4 * len(expected))))
        if destinations != expected:
            raise ValueError("native AF-S jump table mismatch")
        jump_tables[hex(address)] = [hex(value) for value in destinations]
    product, private = elf.read(PRODUCT_VA, PRODUCT_SIZE), elf.read(PRIVATE_VA, 20)
    report = decode_product(product, private)
    return {"model": "X2D 100C first generation", "firmware": "4.2.0",
            "library_sha256": LIBRARY_SHA256, "verification": "static offline firmware audit",
            "device_access": False, "parameter_writes": False,
            "checked_consumer_instructions": len(instructions),
            "checked_jump_tables": jump_tables,
            "packed_relocations_decoded": len(elf.relocations),
            "pdaf_zone_confidence_scale_constant": struct.unpack("<f", elf.read(0x1A1208, 4))[0],
            "static_parameters": report,
            "native_afs_control": {
                "body_mode1_sets_afc_switch": 0,
                "type3_class3_when_afc_invalid": 2,
                "type3_class_output_handle_offset": "0x18",
                "afs_class2_consumer_va": "0x90400",
                "afs_class3_consumer_va": "0x90500",
                "class2_target_formula_when_abs_defocus_gt9":
                    "current_position + trunc_toward_zero(3 * defocus / 4)",
                "class2_target_scope": "Diagnostic calculation; hybrid +0x54 selects the published peak and command path. "
                    "Mode1 publishes this intermediate target; default mode0 publishes native peak. "
                    "Neither implies actual lens movement or final focus.",
                "class3_action": "native peak position, bounded by lens focus range, absolute focus command",
                "historical_formula_matches": [
                    {"current_position": 979, "peak": 90, "calculated_target": 313, "logged_target": 313},
                    {"current_position": 110, "peak": 883, "calculated_target": 689, "logged_target": 689}],
                "scope": "Specific Type3 class3 path; not proof that every AF-S path forbids absolute focus."},
            "vdaf_statistics_tags": [hex(0x410501 + i) for i in range(4)],
            "limitations": ["Static defaults do not prove active camera values.",
                            "Zone classes, PDAF output conf and hybrid peak score are different fields.",
                            "Lowering a threshold can admit false focus; it does not create missing input.",
                            "The AF-S class3 downgrade is separate from the 4000 zone threshold.",
                            "The firmware does not establish whether this policy is defective or intentionally conservative.",
                            "No VDAF input producer or lens calibration has been validated."],
            "experiments": [
                {"name": "AF-S Type3 highest-class policy audit", "priority": 1, "deployable": False,
                 "requires": "AF-S-specific validity checks and calibrated peak verification before reusing class3; "
                             "do not globally enable AFC or equate class2 diagnostic targets with final focus"},
                {"name": "VDAF input audit", "enable_bit": 3, "algorithm_slot": 4, "stock_mask": 3,
                 "proposed_mask_if_inputs_valid": 11, "deployable": False,
                 "requires": "valid native mesh statistics and nonzero, lens-appropriate configuration"},
                {"name": "PDAF highest-class threshold sweep", "private_offset": "0x10",
                 "offline_hypotheses": [4000.0, 3000.0, 2000.0, 1000.0], "deployable": False,
                 "requires": "separate resolution of the AF-S class3 downgrade, per-zone metric and sharpness ground truth"},
                {"name": "CDAF failure audit", "deployable": False,
                 "requires": "failure logs separating curve validity, peak score and final image sharpness"}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[2] / "outputs/afs-native-55v/firmware-audit.json")
    args = parser.parse_args()
    if args.library.resolve() == args.output.resolve():
        parser.error("output must not overwrite firmware")
    report = audit(args.library.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
