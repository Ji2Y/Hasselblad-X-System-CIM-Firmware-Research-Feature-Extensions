#!/usr/bin/env python3
"""Offline color-pipeline and 3D LUT inspector for an extracted X2D / X2D II system tree.

Reads only files you already extracted from an official CIM (for example
``.../system``). It does not unpack firmware, write files, or contact a camera.
The JSON report goes to stdout.

What it reads:

* ``etc/iq/dji_rcam.conf`` -> the IQ table name for the main sensor;
* ``etc/iq/<name>_config.json`` -> FlatBuffers-style JSON (unquoted keys,
  ``//`` comments, hex literals). Parsed leniently, not with ``flatc``;
* ``etc/dispalgo/cm_*.json`` (X2D II only) -> display color-management LUT
  descriptors, checked against the size of the matching ``.bin``.

Run from the repository root:

    python3 x2d2/tools/inspect_color_pipeline.py /path/to/extract/system
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# Inputs whose reports are recorded in the research notes. Anything else is
# reported as "unknown input" and must not be read as the same firmware.
KNOWN_IQ_JSON = {
    "2a4fd76e5299937a6607da8454add17e9746347c54adcf5da1360799de634286": "X2D II 100C 1.3.16.2 hb722_config.json",
    "b4dd1b02de7ce052cf4fd49806fabfb037f98aa0c6194aa28366b71791b545ad": "X2D 100C 4.2.0 ec1706_config.json",
}

COLOR_MODULES = (
    "main_wbc", "main_ccm", "main_hncs", "main_gamma_normal", "main_3dlut",
    "main_gtm", "main_r2y", "pyra_3dlut0", "pyra_3dlut1", "pyra_3dlut2",
    "lcdc_3dlut0", "lcdc_3dlut1", "lcdc_lutctrl0", "lcdc_lutctrl1",
)
TRACKED_SEGMENT_MODULES = ("MAIN_HNCS", "MAIN_3DLUT", "PYRA_3DLUT0", "PYRA_3DLUT1", "PYRA_3DLUT2")
LUT_WORDS = 6144  # one hardware 3D LUT block in the tables seen so far

_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|0[xX][0-9a-fA-F]+|[A-Za-z_][A-Za-z0-9_]*', re.S)
_LITERALS = {"true", "false", "null"}


def fbs_json_to_json(text: str) -> str:
    """Turn FlatBuffers-style JSON into strict JSON text."""

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith('"'):
            return token
        if token.startswith(("//", "/*")):
            return ""
        if token[:2] in ("0x", "0X"):
            return str(int(token, 16))
        if token in _LITERALS:
            return token
        return '"' + token + '"'

    out = _TOKEN.sub(replace, text)
    return re.sub(r",(\s*[}\]])", r"\1", out)


def load_fbs_json(path: Path) -> dict:
    return json.loads(fbs_json_to_json(path.read_text(encoding="utf-8", errors="replace")))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _axis_len(axes: dict, axis: list[str] | None) -> list[int]:
    if not axis:
        return []
    return [len(axes.get(name, [])) for name in axis]


def _flat_len(value) -> int:
    if isinstance(value, list):
        return sum(_flat_len(item) for item in value) if value and isinstance(value[0], list) else len(value)
    return 1


def _first(entry):
    return entry[0] if isinstance(entry, list) and entry else entry


def iq_report(config: dict) -> dict:
    camera = config.get("camera", {})
    iq = config.get("iq_table", {})
    modules = iq.get("module", {})
    data = iq.get("data", [])
    # Interpolation axes live in each mode block's mode_axis; global-group
    # tables use the global block. Older tables keep them under camera.
    global_block = next((b for b in data if b.get("mod_iq_mode") == "global"), {})
    axes = {**camera, **global_block.get("mode_axis", {})}
    report: dict = {
        "local_lut3d_num": camera.get("local_lut3d_num"),
        "lut3d_slots": camera.get("lut3d", []),
        "dlog_num": camera.get("dlog_num"),
        "color_gamut_axis": axes.get("color_gamut"),
        "cc_color_temp_axis": axes.get("cc_color_temp"),
        "iq_modes": [block.get("mod_iq_mode") for block in data],
        "color_modes": [entry.get("color_mode") for entry in iq.get("color", {}).get("entry", [])],
        "modules": {},
    }
    for name in COLOR_MODULES:
        if name not in modules:
            continue
        fields = {}
        for field, desc in modules[name].items():
            if not isinstance(desc, dict):
                continue
            item = {"type": desc.get("type"), "group": desc.get("group")}
            if desc.get("axis"):
                item["axis"] = desc["axis"]
                item["axis_len"] = _axis_len(axes, desc["axis"])
            fields[field] = item
        per_mode = {}
        for block in data:
            entry = _first(block.get(name))
            if not isinstance(entry, dict):
                continue
            values = {}
            for field, value in entry.items():
                length = _flat_len(value)
                values[field] = value if length <= 8 else {"values": length}
                if field in ("lut_data", "tlut") and length % LUT_WORDS == 0:
                    values[field]["luts_of_6144_words"] = length // LUT_WORDS
            per_mode[block.get("mod_iq_mode")] = values
        report["modules"][name] = {"fields": fields, "per_mode": per_mode}

    segments = []
    for segment in config.get("topology", {}).get("modules", []):
        used = set(segment.get("module", []))
        bypass = set(segment.get("bypass", []))
        tracked = {
            mod: ("bypass" if mod in bypass else "active" if mod in used else None)
            for mod in TRACKED_SEGMENT_MODULES
        }
        tracked = {key: value for key, value in tracked.items() if value}
        if tracked:
            segments.append({"segment": segment.get("segment_name"), **tracked})
    report["segments"] = segments
    report["mode_map"] = [
        {"topo": item.get("topo_name"), "mode": item.get("mode"),
         "segments": [seg.get("segment_name") for seg in item.get("segment_map", [])]}
        for item in config.get("topology", {}).get("mode_map", [])
    ]
    return report


def dispalgo_report(directory: Path) -> list[dict]:
    rows = []
    for descriptor in sorted(directory.glob("cm_*.json")):
        meta = json.loads(descriptor.read_text(encoding="utf-8"))
        width = int(meta.get("lut_width", 0))
        count = int(meta.get("param_count", 1))
        channels = int(meta.get("lut_channels", 3))
        expected = width ** 3 * channels * 2 * count
        binary = descriptor.with_suffix(".bin")
        size = binary.stat().st_size if binary.exists() else None
        rows.append({
            "descriptor": descriptor.name,
            "lut_format": meta.get("lut_format"),
            "bit_depth": meta.get("lut_bit_depth"),
            "width": width,
            "param_name": meta.get("param_name"),
            "param_list": meta.get("param_list"),
            "bin_bytes": size,
            "expected_bytes_uint16": expected,
            "size_matches": size == expected,
        })
    return rows


def inspect(system: Path) -> dict:
    conf_path = system / "etc" / "iq" / "dji_rcam.conf"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    table = conf["module_config_table"][0]
    iq_json = system / "etc" / "iq" / Path(table["config_name"]).with_suffix(".json").name
    digest = _sha256(iq_json)
    report = {
        "sensor_module": table.get("module_name"),
        "iq_json": iq_json.name,
        "iq_json_sha256": digest,
        "known_input": KNOWN_IQ_JSON.get(digest, "unknown input"),
        "iq": iq_report(load_fbs_json(iq_json)),
    }
    dispalgo = system / "etc" / "dispalgo"
    report["dispalgo"] = dispalgo_report(dispalgo) if dispalgo.is_dir() else []
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("system", type=Path, help="extracted system partition root (contains etc/iq)")
    parser.add_argument("--segments-only", action="store_true", help="print only the segment table")
    args = parser.parse_args()
    if not (args.system / "etc" / "iq" / "dji_rcam.conf").is_file():
        print(f"error: {args.system}/etc/iq/dji_rcam.conf not found", file=sys.stderr)
        return 1
    report = inspect(args.system)
    if args.segments_only:
        report = report["iq"]["segments"]
    json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
