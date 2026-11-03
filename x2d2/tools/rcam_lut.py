#!/usr/bin/env python3
"""Offline codec and bake tool for DJI rcam 3D LUTs in X2D / X2D II IQ tables.

Layout (decoded from ``lookup_rgb_pixel_plt_fmt`` / ``set_rgb_pixel_to_plt_fmt_lut``
in X2D II 1.3.16.2 ``libduml_hal.so`` and checked against the IQ tables):
one table = 6144 little-endian uint32 words = three 2048-word planes (output
R, G, B). Inside a plane the node (r, g, b), each 0..15, is at word
``r*128 + g*8 + (b >> 1)``; even ``b`` uses bits 0..11, odd ``b`` bits 16..27.
Grid nodes sit at 0, 273, ..., 4095 (12-bit).

Subcommands (run from the repository root; nothing touches a camera):

    export SYSTEM --table main_3dlut --index N --out stock.cube
    bake   SYSTEM --look LOOK.cube --out-dir DIR [--tables ...] [--gamut all|srgb]

``bake`` writes DIR/<config>.bin with each selected table replaced by
``look(stock(x))`` and DIR/bake-manifest.json. The file size and every byte
outside the replaced tables stay the same. It refuses unknown inputs and
never overwrites. The output is an offline candidate, not an installer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cube_lut  # noqa: E402
from inspect_color_pipeline import load_fbs_json  # noqa: E402

WORDS = 6144
N = 16
TOP = 4095

# Exact inputs this tool was checked against. Table axes are first-axis-fastest.
KNOWN = {
    "ce58c7e668fd41af0547e0df7d8545159a3ab2619ad4eabb8931544dadb81436": {
        "model": "X2D II 100C 1.3.16.2", "json": "hb722_config.json",
        "json_sha256": "2a4fd76e5299937a6607da8454add17e9746347c54adcf5da1360799de634286",
        # main_3dlut: cc_color_temp(4) x color_gamut(2: sRGB, P3); index = ct + 4*gamut
        "p3_tables": {"main_3dlut": [4, 5, 6, 7]},
    },
    "ad416dccda717d2a196a859e664229c5f8e2665ecf65ab545603121a51451097": {
        "model": "X2D 100C 4.2.0", "json": "ec1706_config.json",
        "json_sha256": "b4dd1b02de7ce052cf4fd49806fabfb037f98aa0c6194aa28366b71791b545ad",
        "p3_tables": {},
    },
}
TABLE_FIELDS = {"main_3dlut": "lut_data", "lcdc_3dlut0": "tlut", "lcdc_3dlut1": "tlut"}
DEFAULT_TABLES = ("main_3dlut", "lcdc_3dlut0", "lcdc_3dlut1")


def word_index(plane: int, r: int, g: int, b: int) -> int:
    return plane * 2048 + r * 128 + g * 8 + (b >> 1)


def decode(words: list[int]) -> cube_lut.Lut3D:
    if len(words) != WORDS:
        raise ValueError(f"expected {WORDS} words, got {len(words)}")
    data = []
    for b in range(N):
        for g in range(N):
            for r in range(N):
                node = []
                for plane in range(3):
                    w = words[word_index(plane, r, g, b)]
                    node.append((((w >> 16) if b & 1 else w) & 0xFFF) / TOP)
                data.append(tuple(node))
    return cube_lut.Lut3D(N, data)


def encode(lut: cube_lut.Lut3D) -> list[int]:
    if lut.size != N:
        raise ValueError("rcam tables are 16^3")
    words = [0] * WORDS
    for b in range(N):
        for g in range(N):
            for r in range(N):
                node = lut.node(r, g, b)
                for plane in range(3):
                    code = min(max(int(round(node[plane] * TOP)), 0), TOP)
                    i = word_index(plane, r, g, b)
                    words[i] |= code << 16 if b & 1 else code
    return words


# Display P3 and sRGB share the sRGB transfer curve; D65 linear matrices.
_P3_TO_SRGB = ((1.2249401, -0.2249404, 0.0), (-0.0420569, 1.0420571, 0.0), (-0.0196376, -0.0786361, 1.0982735))
_SRGB_TO_P3 = ((0.8224621, 0.1775380, 0.0), (0.0331941, 0.9668058, 0.0), (0.0170827, 0.0723974, 0.9105199))


def _eotf(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _oetf(v: float) -> float:
    v = min(max(v, 0.0), 1.0)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _convert(rgb, matrix):
    lin = [_eotf(c) for c in rgb]
    return tuple(_oetf(sum(m * c for m, c in zip(row, lin))) for row in matrix)


def compose_table(stock: cube_lut.Lut3D, look: cube_lut.Lut3D, p3: bool) -> cube_lut.Lut3D:
    """look(stock(x)).

    P3 tables: the look (authored for sRGB) is applied as a delta,
    x + P3(look(s)) - P3(s) with s = sRGB(x) clipped, so colours outside
    sRGB keep their residual and an identity look leaves the table unchanged.
    """
    out = []
    for node in stock.data:
        if p3:
            s = _convert(node, _P3_TO_SRGB)
            looked = _convert(cube_lut.sample(look, s), _SRGB_TO_P3)
            base = _convert(s, _SRGB_TO_P3)
            out.append(tuple(min(max(x + a - b, 0.0), 1.0) for x, a, b in zip(node, looked, base)))
        else:
            out.append(cube_lut.sample(look, node))
    return cube_lut.Lut3D(N, out)


def _global_block(config: dict) -> dict:
    return next(b for b in config["iq_table"]["data"] if b.get("mod_iq_mode") == "global")


def load_inputs(system: Path) -> tuple[dict, bytes, dict, Path]:
    conf = json.loads((system / "etc/iq/dji_rcam.conf").read_text(encoding="utf-8"))
    bin_path = system / "etc/iq" / conf["module_config_table"][0]["config_name"]
    blob = bin_path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest not in KNOWN:
        raise SystemExit(f"error: {bin_path.name} sha256 {digest} is not a checked input")
    info = KNOWN[digest]
    json_path = bin_path.with_name(info["json"])
    if hashlib.sha256(json_path.read_bytes()).hexdigest() != info["json_sha256"]:
        raise SystemExit(f"error: {json_path.name} does not match {info['model']}")
    return info, blob, _global_block(load_fbs_json(json_path)), bin_path


def locate_all(blob: bytes, words: list[int]) -> list[int]:
    pattern = struct.pack("<%dI" % len(words), *words)
    found, start = [], 0
    while (pos := blob.find(pattern, start)) >= 0:
        found.append(pos)
        start = pos + 1
    return found


def _all_tables_with(block: dict, flat: list[int]) -> list[str]:
    return [name for name in TABLE_FIELDS if name in block and block[name][0][TABLE_FIELDS[name]] == flat]


def table_offsets(blob: bytes, block: dict) -> dict[str, list[int]]:
    """Byte offsets of each table array, ignoring matches that sit inside a
    longer table (X2D 4.2.0 LCD arrays start with a copy of main_3dlut)."""
    arrays = {name: block[name][0][TABLE_FIELDS[name]] for name in TABLE_FIELDS if name in block}
    found = {name: locate_all(blob, arr) for name, arr in arrays.items()}
    spans = [(pos, pos + 4 * len(arrays[name]), name) for name, poss in found.items() for pos in poss]
    result = {}
    for name, poss in found.items():
        size = 4 * len(arrays[name])
        result[name] = [pos for pos in poss
                        if not any(a <= pos and pos + size <= b and (b - a) > size for a, b, _ in spans)]
    return result


def stock_tables(block: dict, name: str) -> list[list[int]]:
    arr = block[name][0][TABLE_FIELDS[name]]
    if len(arr) % WORDS:
        raise SystemExit(f"error: {name} length {len(arr)} is not a multiple of {WORDS}")
    return [arr[i * WORDS:(i + 1) * WORDS] for i in range(len(arr) // WORDS)]


def _is_identity(words: list[int]) -> bool:
    ident = cube_lut.identity(N)
    return all(max(abs(a - b) for a, b in zip(x, y)) <= 2 / TOP for x, y in zip(decode(words).data, ident.data))


def bake(blob: bytes, block: dict, info: dict, look: cube_lut.Lut3D,
         tables: tuple[str, ...], gamut: str) -> tuple[bytes, list[dict]]:
    out = bytearray(blob)
    report = []
    done: set[int] = set()
    positions = table_offsets(blob, block)
    for name in tables:
        if name not in block:
            report.append({"table": name, "status": "absent"})
            continue
        group = stock_tables(block, name)
        flat = [w for t in group for w in t]
        offsets = positions[name]
        twins = _all_tables_with(block, flat)
        # Identical arrays (e.g. X2D II lcdc_3dlut0/1) share one byte pattern.
        # They get the same transform, so all copies are replaced together,
        # but only when every table with that content was requested.
        if len(offsets) != len(twins) or not set(twins) <= set(tables):
            raise SystemExit(f"error: {name} occurs {len(offsets)} times in the IQ binary; "
                             f"tables with identical content: {twins}. Request all of them together.")
        if offsets[0] in done:
            report.append({"table": name, "status": f"same content as {twins[0]}, replaced together"})
            continue
        p3_set = set(info["p3_tables"].get(name, []))
        new_words = []
        for i, words in enumerate(group):
            is_p3 = i in p3_set
            if _is_identity(words):
                status = "kept (identity table)"
                new = words
            elif is_p3 and gamut == "srgb":
                status = "kept (P3, --gamut srgb)"
                new = words
            else:
                new = encode(compose_table(decode(words), look, is_p3))
                status = "baked (P3 via sRGB)" if is_p3 else "baked"
            new_words.extend(new)
            report.append({"table": name, "index": i, "status": status})
        packed = struct.pack("<%dI" % len(new_words), *new_words)
        for offset in offsets:
            out[offset:offset + len(packed)] = packed
            done.add(offset)
    if len(out) != len(blob):
        raise AssertionError("size changed")
    return bytes(out), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_exp = sub.add_parser("export")
    p_exp.add_argument("system", type=Path)
    p_exp.add_argument("--table", default="main_3dlut", choices=sorted(TABLE_FIELDS))
    p_exp.add_argument("--index", type=int, default=0)
    p_exp.add_argument("--out", type=Path, required=True)
    p_bake = sub.add_parser("bake")
    p_bake.add_argument("system", type=Path)
    p_bake.add_argument("--look", type=Path, required=True)
    p_bake.add_argument("--out-dir", type=Path, required=True)
    p_bake.add_argument("--tables", default=",".join(DEFAULT_TABLES))
    p_bake.add_argument("--gamut", choices=("all", "srgb"), default="all")
    args = parser.parse_args(argv)

    info, blob, block, bin_path = load_inputs(args.system)
    if args.cmd == "export":
        group = stock_tables(block, args.table)
        if not 0 <= args.index < len(group):
            raise SystemExit(f"error: index must be 0..{len(group) - 1}")
        if args.out.exists():
            raise SystemExit(f"error: refusing to overwrite {args.out}")
        args.out.write_text(cube_lut.format_cube(decode(group[args.index]),
                                                 f"{info['model']} {args.table}[{args.index}]"), encoding="utf-8")
        print(f"wrote {args.out}")
        return 0

    look = cube_lut.parse_cube(args.look.read_text(encoding="utf-8"))
    tables = tuple(t for t in args.tables.split(",") if t)
    unknown = [t for t in tables if t not in TABLE_FIELDS]
    if unknown:
        raise SystemExit(f"error: unknown table {unknown}")
    out_bin = args.out_dir / bin_path.name
    manifest = args.out_dir / "bake-manifest.json"
    for path in (out_bin, manifest):
        if path.exists():
            raise SystemExit(f"error: refusing to overwrite {path}")
    new_blob, report = bake(blob, block, info, look, tables, args.gamut)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_bin.write_bytes(new_blob)
    changed = sum(1 for a, b in zip(blob, new_blob) if a != b)
    manifest.write_text(json.dumps({
        "model": info["model"], "input": bin_path.name,
        "input_sha256": hashlib.sha256(blob).hexdigest(),
        "output_sha256": hashlib.sha256(new_blob).hexdigest(),
        "look": args.look.name, "look_sha256": hashlib.sha256(args.look.read_bytes()).hexdigest(),
        "gamut": args.gamut, "changed_bytes": changed, "tables": report,
    }, indent=1), encoding="utf-8")
    print(f"wrote {out_bin} ({changed} bytes changed) and {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
