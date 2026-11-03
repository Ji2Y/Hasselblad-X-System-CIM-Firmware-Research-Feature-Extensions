"""Offline checks for the color-pipeline inspector and cube_r helper.

Only synthetic inputs are used. No firmware, vendor LUT, or device is needed.
Run from this directory: python3 -m unittest test_color_pipeline_tools.py
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

import cube_lut
import inspect_color_pipeline as icp
import rcam_lut


def affine(size: int) -> cube_lut.Lut3D:
    """A LUT whose nodes follow an affine map, so trilinear lookup is exact."""
    step = 1.0 / (size - 1)
    data = []
    for b in range(size):
        for g in range(size):
            for r in range(size):
                x, y, z = r * step, g * step, b * step
                data.append((0.8 * x + 0.1 * y, 0.2 + 0.5 * y, 0.1 * x + 0.6 * z))
    return cube_lut.Lut3D(size, data)


class CubeTests(unittest.TestCase):
    def test_cube_roundtrip(self) -> None:
        lut = affine(5)
        again = cube_lut.parse_cube(cube_lut.format_cube(lut, "t"))
        self.assertEqual(again.size, 5)
        for a, b in zip(lut.data, again.data):
            for u, v in zip(a, b):
                self.assertAlmostEqual(u, v, places=6)

    def test_rejects_wrong_row_count(self) -> None:
        with self.assertRaises(ValueError):
            cube_lut.parse_cube("LUT_3D_SIZE 2\n0 0 0\n")

    def test_trilinear_exact_on_affine(self) -> None:
        lut = affine(4)
        x, y, z = 0.37, 0.81, 0.12
        expected = (0.8 * x + 0.1 * y, 0.2 + 0.5 * y, 0.1 * x + 0.6 * z)
        for got, want in zip(cube_lut.sample(lut, (x, y, z)), expected):
            self.assertAlmostEqual(got, want, places=9)

    def test_compose_with_identity_keeps_outer(self) -> None:
        outer = affine(6)
        result = cube_lut.compose(outer, cube_lut.identity(3))
        for a, b in zip(outer.data, result.data):
            for u, v in zip(a, b):
                self.assertAlmostEqual(u, v, places=9)

    def test_compose_order_is_outer_after_inner(self) -> None:
        # inner swaps red and blue; outer keeps only red. outer(inner(x)) = blue.
        n = 3
        step = 1.0 / (n - 1)
        swap = cube_lut.Lut3D(n, [(b * step, g * step, r * step)
                                  for b in range(n) for g in range(n) for r in range(n)])
        red_only = cube_lut.Lut3D(n, [(r * step, 0.0, 0.0)
                                      for b in range(n) for g in range(n) for r in range(n)])
        out = cube_lut.sample(cube_lut.compose(red_only, swap), (0.0, 0.0, 1.0))
        self.assertAlmostEqual(out[0], 1.0)

    def test_cube_r_layout_is_red_fastest_uint16(self) -> None:
        n, depth = 4, 10
        blob = cube_lut.write_cube_r([cube_lut.identity(n)], depth)
        self.assertEqual(len(blob), n ** 3 * 3 * 2)
        # node (r=1, g=0, b=0) is the second triplet; its red code is 1023/3.
        red, green, blue = struct.unpack_from("<3H", blob, 6)
        self.assertEqual((red, green, blue), (341, 0, 0))
        # node (r=0, g=0, b=1) starts after n*n triplets.
        self.assertEqual(struct.unpack_from("<3H", blob, n * n * 6), (0, 0, 341))
        back = cube_lut.read_cube_r(blob + blob, n, 2, depth)
        self.assertEqual(len(back), 2)
        self.assertAlmostEqual(back[1].node(3, 3, 3)[2], 1.0)

    def test_cli_compose_refuses_overwrite_and_same_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            desc = root / "cm_test.json"
            desc.write_text(json.dumps({"lut_format": "cube_r", "lut_data_type": "int", "lut_bit_depth": 10,
                                        "lut_width": 3, "lut_channels": 3, "param_count": 2,
                                        "param_list": [30, 1000], "param_name": "sdr_ref_white"}))
            (root / "cm_test.bin").write_bytes(cube_lut.write_cube_r([cube_lut.identity(3)] * 2, 10))
            look = root / "look.cube"
            look.write_text(cube_lut.format_cube(cube_lut.identity(2)))
            with self.assertRaises(SystemExit):
                cube_lut.main(["compose", str(desc), "--look", str(look), "--out-dir", str(root)])
            out = root / "out"
            self.assertEqual(cube_lut.main(["compose", str(desc), "--look", str(look), "--out-dir", str(out)]), 0)
            self.assertEqual((out / "cm_test.bin").read_bytes(), (root / "cm_test.bin").read_bytes())
            with self.assertRaises(SystemExit):
                cube_lut.main(["compose", str(desc), "--look", str(look), "--out-dir", str(out)])

    def test_cli_refuses_rcam_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            desc = Path(directory) / "cm_fast.json"
            desc.write_text(json.dumps({"lut_format": "rcam", "lut_width": 16}))
            with self.assertRaises(SystemExit):
                cube_lut.main(["export", str(desc), "--out", str(Path(directory) / "x.cube")])


SYNTHETIC_IQ = """{
    camera: {
        // comment with a colon: here
        local_lut3d_num: 5,
        lut3d : [ { lut3d: iq_lut3d_user, local_lut3d: 4 }, ],
    },
    topology: {
        modules: [
            { segment_name: "still_render", module: [MAIN_CCM, MAIN_3DLUT,], bypass: [MAIN_HNCS] },
            { segment_name: "no_color", module: [MAIN_BLC] },
        ],
        mode_map: [ { topo_name: "TPLG_X", mode: still0 } ],
    },
    iq_table: {
        module: { main_3dlut: { lut_data: { type: lerp_lut_mem_3d, group: global_frame, axis: [cc_color_temp] } } },
        data: [
            { mod_iq_mode: global, mode_axis: { cc_color_temp: [2400, 5500] },
              main_3dlut: [ { lut_data: [LUTDATA] } ] },
            { mod_iq_mode: still0, main_3dlut: [ { module_en_lut: [1], tlut_en: [0x1] } ] },
        ],
        color: { entry: [ { color_mode: IQ_COLOR_MODE_DEFAULT, ctrl: [] } ] },
    },
}"""


class InspectorTests(unittest.TestCase):
    def config(self) -> dict:
        text = SYNTHETIC_IQ.replace("LUTDATA", ",".join(["0"] * (2 * icp.LUT_WORDS)))
        return json.loads(icp.fbs_json_to_json(text))

    def test_lenient_parser(self) -> None:
        cfg = self.config()
        self.assertEqual(cfg["camera"]["lut3d"][0]["lut3d"], "iq_lut3d_user")
        self.assertEqual(cfg["iq_table"]["data"][1]["main_3dlut"][0]["tlut_en"], [1])

    def test_report_counts_luts_and_segments(self) -> None:
        report = icp.iq_report(self.config())
        lut = report["modules"]["main_3dlut"]
        self.assertEqual(lut["fields"]["lut_data"]["axis_len"], [2])
        self.assertEqual(lut["per_mode"]["global"]["lut_data"]["luts_of_6144_words"], 2)
        self.assertEqual(lut["per_mode"]["still0"]["module_en_lut"], [1])
        self.assertEqual(report["segments"], [{"segment": "still_render", "MAIN_HNCS": "bypass", "MAIN_3DLUT": "active"}])
        self.assertEqual(report["color_modes"], ["IQ_COLOR_MODE_DEFAULT"])

    def test_dispalgo_size_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cm_a.json").write_text(json.dumps({"lut_format": "cube_r", "lut_width": 2,
                                                        "param_count": 2, "lut_channels": 3}))
            (root / "cm_a.bin").write_bytes(bytes(2 ** 3 * 3 * 2 * 2))
            (root / "cm_b.json").write_text(json.dumps({"lut_format": "cube_r", "lut_width": 2}))
            (root / "cm_b.bin").write_bytes(bytes(10))
            rows = {row["descriptor"]: row["size_matches"] for row in icp.dispalgo_report(root)}
        self.assertEqual(rows, {"cm_a.json": True, "cm_b.json": False})


def _rcam_words(fn) -> list[int]:
    """Synthetic rcam table whose node (r, g, b) holds fn(r, g, b) codes."""
    words = [0] * rcam_lut.WORDS
    for r in range(16):
        for g in range(16):
            for b in range(16):
                for plane, code in enumerate(fn(r, g, b)):
                    i = rcam_lut.word_index(plane, r, g, b)
                    words[i] |= code << 16 if b & 1 else code
    return words


class RcamTests(unittest.TestCase):
    def test_layout_planes_and_halves(self) -> None:
        words = _rcam_words(lambda r, g, b: (r, g, b))
        # blue is the fastest index and shares one word between even and odd nodes
        self.assertEqual(words[rcam_lut.word_index(2, 0, 0, 0)], (1 << 16) | 0)
        self.assertEqual(words[rcam_lut.word_index(0, 5, 0, 0)], (5 << 16) | 5)
        self.assertEqual(rcam_lut.word_index(1, 0, 1, 0), 2048 + 8)
        self.assertEqual(rcam_lut.word_index(0, 1, 0, 0), 128)
        lut = rcam_lut.decode(words)
        self.assertAlmostEqual(lut.node(3, 7, 11)[1] * rcam_lut.TOP, 7)

    def test_identity_roundtrip(self) -> None:
        ident = _rcam_words(lambda r, g, b: tuple(round(v * 4095 / 15) for v in (r, g, b)))
        self.assertEqual(rcam_lut.encode(rcam_lut.decode(ident)), ident)

    def test_identity_look_keeps_srgb_and_p3_tables(self) -> None:
        stock = rcam_lut.decode(_rcam_words(lambda r, g, b: (min(4095, r * 300), g * 250, b * 200)))
        look = cube_lut.identity(9)
        for p3 in (False, True):
            self.assertEqual(rcam_lut.encode(rcam_lut.compose_table(stock, look, p3)), rcam_lut.encode(stock))

    def test_bake_replaces_only_tables_and_skips_nested_copy(self) -> None:
        main = _rcam_words(lambda r, g, b: (r * 273, g * 273, 4095 - b * 273))
        ident = _rcam_words(lambda r, g, b: tuple(v * 273 for v in (r, g, b)))
        lcdc = main + ident  # like X2D 4.2.0: the LCD array starts with a copy of main
        block = {"main_3dlut": [{"lut_data": main}], "lcdc_3dlut0": [{"tlut": lcdc}],
                 "lcdc_3dlut1": [{"tlut": lcdc}]}
        pack = lambda w: struct.pack("<%dI" % len(w), *w)  # noqa: E731
        blob = b"HEAD" + pack(main) + b"MID!" + pack(lcdc) + b"PAD." + pack(lcdc) + b"TAIL"
        info = {"p3_tables": {}}
        half = cube_lut.Lut3D(2, [tuple(0.5 * v for v in node) for node in cube_lut.identity(2).data])
        new, report = rcam_lut.bake(blob, block, info, half, rcam_lut.DEFAULT_TABLES, "all")
        self.assertEqual(len(new), len(blob))
        self.assertEqual(new[:4], b"HEAD")
        self.assertEqual(new[-4:], b"TAIL")
        statuses = [row["status"] for row in report]
        self.assertIn("kept (identity table)", statuses)
        self.assertIn("same content as lcdc_3dlut0, replaced together", statuses)
        baked_main = rcam_lut.decode(list(struct.unpack_from("<6144I", new, 4)))
        self.assertAlmostEqual(baked_main.node(15, 0, 0)[0], 0.5, places=3)
        with self.assertRaises(SystemExit):
            rcam_lut.bake(blob, block, info, half, ("lcdc_3dlut0",), "all")


if __name__ == "__main__":
    unittest.main()
