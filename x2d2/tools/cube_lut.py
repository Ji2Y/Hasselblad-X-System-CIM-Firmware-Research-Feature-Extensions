#!/usr/bin/env python3
"""Offline .cube <-> X2D II ``cube_r`` display-LUT helper. No device access.

``cube_r`` is the layout named in X2D II 1.3.16.2 ``/etc/dispalgo/cm_*.json``:
``lut_width``^3 nodes, red index fastest, RGB triplets, unsigned 16-bit
little-endian containers holding ``lut_bit_depth``-bit codes, ``param_count``
tables back to back (one per ``sdr_ref_white`` step). The ISP-side ``rcam``
layout (``cm_*_lv_sdr_fastpre``, IQ ``tlut``/``lut_data``) is a different
planar layout handled by ``rcam_lut.py``; this tool refuses it.

Subcommands (run from the repository root; every output goes to a path you
name and existing files are never overwritten):

    info    LOOK.cube
    export  DESCRIPTOR.json --index N --out stock_N.cube
    compose DESCRIPTOR.json --look LOOK.cube --out-dir DIR

``compose`` writes DIR/<descriptor>.bin and .json where every table is
``stock_display(look(x))``: the look runs first, the stock panel mapping
stays last. It is an offline file builder, not an installer.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

RGB = tuple[float, float, float]


@dataclass
class Lut3D:
    size: int
    data: list[RGB]  # red fastest: index = r + size*g + size*size*b
    domain_min: RGB = (0.0, 0.0, 0.0)
    domain_max: RGB = (1.0, 1.0, 1.0)

    def node(self, r: int, g: int, b: int) -> RGB:
        n = self.size
        return self.data[r + n * g + n * n * b]


def identity(size: int) -> Lut3D:
    step = 1.0 / (size - 1)
    return Lut3D(size, [(r * step, g * step, b * step)
                        for b in range(size) for g in range(size) for r in range(size)])


def parse_cube(text: str) -> Lut3D:
    size = None
    dmin: RGB = (0.0, 0.0, 0.0)
    dmax: RGB = (1.0, 1.0, 1.0)
    rows: list[RGB] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key = line.split()[0].upper()
        if key == "TITLE":
            continue
        if key == "LUT_1D_SIZE":
            raise ValueError("1D LUT not supported; supply a 3D .cube")
        if key == "LUT_3D_SIZE":
            size = int(line.split()[1])
            continue
        if key in ("DOMAIN_MIN", "DOMAIN_MAX"):
            values = tuple(float(x) for x in line.split()[1:4])
            if key == "DOMAIN_MIN":
                dmin = values  # type: ignore[assignment]
            else:
                dmax = values  # type: ignore[assignment]
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"unexpected line: {raw!r}")
        rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
    if size is None or size < 2:
        raise ValueError("missing or invalid LUT_3D_SIZE")
    if len(rows) != size ** 3:
        raise ValueError(f"expected {size ** 3} rows, got {len(rows)}")
    return Lut3D(size, rows, dmin, dmax)


def format_cube(lut: Lut3D, title: str = "") -> str:
    lines = []
    if title:
        lines.append(f'TITLE "{title}"')
    lines.append(f"LUT_3D_SIZE {lut.size}")
    if lut.domain_min != (0.0, 0.0, 0.0) or lut.domain_max != (1.0, 1.0, 1.0):
        lines.append("DOMAIN_MIN %.6f %.6f %.6f" % lut.domain_min)
        lines.append("DOMAIN_MAX %.6f %.6f %.6f" % lut.domain_max)
    lines.extend("%.6f %.6f %.6f" % row for row in lut.data)
    return "\n".join(lines) + "\n"


def sample(lut: Lut3D, rgb: RGB) -> RGB:
    """Trilinear lookup; input clamped to the LUT domain."""
    n1 = lut.size - 1
    pos = []
    for value, lo, hi in zip(rgb, lut.domain_min, lut.domain_max):
        t = (value - lo) / (hi - lo) if hi != lo else 0.0
        pos.append(min(max(t, 0.0), 1.0) * n1)
    i0 = [min(int(p), n1 - 1) for p in pos]
    f = [p - i for p, i in zip(pos, i0)]
    out = [0.0, 0.0, 0.0]
    for db in (0, 1):
        wb = f[2] if db else 1.0 - f[2]
        for dg in (0, 1):
            wg = f[1] if dg else 1.0 - f[1]
            for dr in (0, 1):
                w = (f[0] if dr else 1.0 - f[0]) * wg * wb
                if w == 0.0:
                    continue
                node = lut.node(i0[0] + dr, i0[1] + dg, i0[2] + db)
                out[0] += w * node[0]
                out[1] += w * node[1]
                out[2] += w * node[2]
    return (out[0], out[1], out[2])


def compose(outer: Lut3D, inner: Lut3D) -> Lut3D:
    """outer(inner(x)) on the outer grid."""
    grid = identity(outer.size)
    span = [hi - lo for lo, hi in zip(outer.domain_min, outer.domain_max)]
    points = [tuple(lo + v * s for v, lo, s in zip(node, outer.domain_min, span)) for node in grid.data]
    return Lut3D(outer.size, [sample(outer, sample(inner, p)) for p in points],
                 outer.domain_min, outer.domain_max)


def read_cube_r(blob: bytes, width: int, count: int, bit_depth: int) -> list[Lut3D]:
    per = width ** 3 * 3
    if len(blob) != per * 2 * count:
        raise ValueError(f"size {len(blob)} != {width}^3*3*2*{count}")
    scale = float((1 << bit_depth) - 1)
    values = struct.unpack("<%dH" % (per * count), blob)
    luts = []
    for k in range(count):
        chunk = values[k * per:(k + 1) * per]
        luts.append(Lut3D(width, [(chunk[i] / scale, chunk[i + 1] / scale, chunk[i + 2] / scale)
                                  for i in range(0, per, 3)]))
    return luts


def write_cube_r(luts: list[Lut3D], bit_depth: int) -> bytes:
    top = (1 << bit_depth) - 1
    out = bytearray()
    for lut in luts:
        for node in lut.data:
            for value in node:
                out += struct.pack("<H", min(max(int(round(value * top)), 0), top))
    return bytes(out)


def _descriptor(path: Path) -> tuple[dict, Path]:
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("lut_format") != "cube_r":
        raise SystemExit(f"error: {path.name} is {meta.get('lut_format')!r}; only 'cube_r' is decoded")
    if int(meta.get("lut_channels", 3)) != 3 or meta.get("lut_data_type") != "int":
        raise SystemExit("error: only 3-channel int cube_r is supported")
    return meta, path.with_suffix(".bin")


def _refuse_existing(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            raise SystemExit(f"error: refusing to overwrite {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_info = sub.add_parser("info")
    p_info.add_argument("cube", type=Path)
    p_exp = sub.add_parser("export")
    p_exp.add_argument("descriptor", type=Path)
    p_exp.add_argument("--index", type=int, default=0)
    p_exp.add_argument("--out", type=Path, required=True)
    p_cmp = sub.add_parser("compose")
    p_cmp.add_argument("descriptor", type=Path)
    p_cmp.add_argument("--look", type=Path, required=True)
    p_cmp.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.cmd == "info":
        lut = parse_cube(args.cube.read_text(encoding="utf-8"))
        flat = [v for node in lut.data for v in node]
        print(json.dumps({"size": lut.size, "domain_min": lut.domain_min, "domain_max": lut.domain_max,
                          "min": min(flat), "max": max(flat)}))
        return 0

    meta, binary = _descriptor(args.descriptor)
    width, count, depth = int(meta["lut_width"]), int(meta.get("param_count", 1)), int(meta["lut_bit_depth"])
    luts = read_cube_r(binary.read_bytes(), width, count, depth)

    if args.cmd == "export":
        if not 0 <= args.index < count:
            raise SystemExit(f"error: index must be 0..{count - 1}")
        _refuse_existing(args.out)
        param = meta.get("param_list", [None] * count)[args.index]
        args.out.write_text(format_cube(luts[args.index], f"{args.descriptor.stem} {meta.get('param_name')}={param}"),
                            encoding="utf-8")
        print(f"wrote {args.out}")
        return 0

    look = parse_cube(args.look.read_text(encoding="utf-8"))
    if args.out_dir.resolve() == args.descriptor.parent.resolve():
        raise SystemExit("error: --out-dir must differ from the descriptor directory")
    out_bin = args.out_dir / binary.name
    out_json = args.out_dir / args.descriptor.name
    _refuse_existing(out_bin, out_json)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_bin.write_bytes(write_cube_r([compose(stock, look) for stock in luts], depth))
    out_json.write_text(args.descriptor.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"wrote {out_bin} and {out_json} ({count} tables, {width}^3, {depth}-bit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
