"""Host-only synthetic RAW regression checks; no photos or camera access.

The fixed sensor layout is represented with sparse files. Output geometry is
4x4 to exercise real parsing/processing without a full-resolution quality claim.
"""
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


class Result(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint) for name in ("width", "height", "channels", "frames")]
    _fields_ += [("bytes_written", ctypes.c_uint64), ("error", ctypes.c_char * 160)]


CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint)
RAW_WIDTH, RAW_HEIGHT = 11904, 8842
RAW_BYTES = RAW_WIDTH * RAW_HEIGHT * 2


def synthetic_raw(path, count, index, iso=100, compression=1):
    data = bytearray(16384)
    data[:8] = b"II\x2a\0" + struct.pack("<I", 8)
    next_data = 2048

    def entry(tag, kind, payload, length):
        nonlocal next_data
        if len(payload) <= 4:
            value = payload.ljust(4, b"\0")
        else:
            value = struct.pack("<I", next_data)
            data[next_data:next_data + len(payload)] = payload
            next_data += len(payload)
        return struct.pack("<HHI", tag, kind, length) + value

    def scalar(tag, value):
        return entry(tag, 4, struct.pack("<I", value), 1)

    def rational(tag, pairs, signed=False):
        return entry(tag, 10 if signed else 5,
                     b"".join(struct.pack("<ii" if signed else "<II", *pair) for pair in pairs), len(pairs))

    def ifd(offset, entries):
        table = struct.pack("<H", len(entries)) + b"".join(sorted(entries)) + b"\0" * 4
        data[offset:offset + len(table)] = table

    matrix = [(1 if index in (0, 4, 8) else 0, 1) for index in range(9)]
    ifd(8, [entry(271, 2, b"Hasselblad\0", 11), entry(272, 2, b"X2D 100C\0", 9),
            scalar(274, 1), scalar(330, 512), scalar(34665, 1024),
            rational(50721, matrix, True), rational(50728, [(1, 1)] * 3), scalar(50778, 21)])
    raw_tags = {256: RAW_WIDTH, 257: RAW_HEIGHT, 258: 16, 259: compression,
                262: 32803, 277: 1, 273: 16384, 279: RAW_BYTES, 50717: 65535}
    ifd(512, [scalar(tag, value) for tag, value in raw_tags.items()] + [rational(50714, [(0, 1)])])
    ifd(1024, [rational(33434, [(1, 100)]), rational(33437, [(4, 1)]), scalar(34855, iso),
               struct.pack("<HHII", 37500, 7, 64, 1536)])
    ifd(1536, [entry(33, 9, struct.pack("<4i", count, index, 0, 0), 4)])
    with path.open("wb") as stream:
        stream.write(data)
        stream.truncate(16384 + RAW_BYTES)
        # Only the rows used by the miniature merge contain synthetic samples.
        for row in range(90, 100):
            stream.seek(16384 + row * RAW_WIDTH * 2)
            stream.write(struct.pack("<H", 1000) * RAW_WIDTH)


def input_signature(path):
    stat = path.stat()
    with path.open("rb") as stream:
        head = stream.read(16384)
        stream.seek(16384 + 90 * RAW_WIDTH * 2)
        rows = stream.read(10 * RAW_WIDTH * 2)
    return stat.st_size, stat.st_mtime_ns, hashlib.sha256(head + rows).hexdigest()


class MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("host C compiler required")
        cls.build = tempfile.TemporaryDirectory(prefix="x2d-offline-merge-")
        native = Path(__file__).resolve().parents[1] / "native"
        library = Path(cls.build.name) / "merge-host.so"
        subprocess.run([compiler, "-std=c11", "-D_GNU_SOURCE", "-DMS_WIDTH=4", "-DMS_HEIGHT=4",
                        "-O1", "-Wall", "-Wextra", "-Wno-misleading-indentation", "-fPIC", "-shared",
                        str(native / "merge.c"), "-lm", "-o", str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.ms_merge.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.c_uint, ctypes.c_char_p,
                                    CALLBACK, ctypes.c_void_p, ctypes.POINTER(Result)]
        cls.lib.ms_merge.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="x2d-synthetic-raw-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def sequence(self, count=4):
        paths = [self.root / f"synthetic-{index}.3fr" for index in range(count)]
        for index, path in enumerate(paths):
            synthetic_raw(path, count, index)
        return paths

    def merge(self, paths, callback=None, count=None):
        array = (ctypes.c_char_p * len(paths))(*[os.fsencode(path) for path in paths])
        result = Result()
        progress = CALLBACK(callback or (lambda context, done, total: 0))
        ok = self.lib.ms_merge(array, count or len(paths), os.fsencode(self.root / "result.dng"),
                               progress, None, ctypes.byref(result))
        return ok, result

    def test_four_frame_rgb_and_sources_unchanged(self):
        paths = self.sequence()
        before = [input_signature(path) for path in paths]
        ok, result = self.merge(paths)
        self.assertEqual(ok, 1, result.error)
        self.assertEqual((result.width, result.height, result.channels, result.frames), (4, 4, 3, 4))
        output = (self.root / "result.dng").read_bytes()
        self.assertEqual(len(output), result.bytes_written)
        self.assertEqual(struct.unpack("<48H", output[4096:]), (1000,) * 48)
        self.assertEqual(before, [input_signature(path) for path in paths])

    def test_six_frame_constant_field(self):
        ok, result = self.merge(self.sequence(6))
        self.assertEqual(ok, 1, result.error)
        self.assertEqual(result.frames, 6)
        self.assertEqual(struct.unpack("<48H", (self.root / "result.dng").read_bytes()[4096:]), (1000,) * 48)

    def test_existing_output_not_overwritten(self):
        (self.root / "result.dng").write_bytes(b"existing-output")
        ok, result = self.merge(self.sequence())
        self.assertEqual(ok, 0)
        self.assertIn(b"output exists", result.error)
        self.assertEqual((self.root / "result.dng").read_bytes(), b"existing-output")

    def test_wrong_frame_order_rejected(self):
        paths = self.sequence()
        paths.reverse()
        ok, result = self.merge(paths)
        self.assertEqual(ok, 0)
        self.assertIn(b"order mismatch", result.error)

    def test_exposure_metadata_mismatch_rejected(self):
        paths = self.sequence()
        synthetic_raw(paths[1], 4, 1, iso=200)
        ok, result = self.merge(paths)
        self.assertEqual(ok, 0)
        self.assertIn(b"ISO mismatch", result.error)
        self.assertFalse((self.root / "result.dng").exists())

    def test_compressed_layout_rejected(self):
        paths = self.sequence()
        synthetic_raw(paths[0], 4, 0, compression=7)
        ok, result = self.merge(paths)
        self.assertEqual(ok, 0)
        self.assertIn(b"RAW tag 259", result.error)

    def test_truncated_source_rejected(self):
        paths = self.sequence()
        with paths[0].open("r+b") as stream:
            stream.truncate(100)
        ok, result = self.merge(paths)
        self.assertEqual(ok, 0)
        self.assertIn(b"truncated", result.error)

    def test_symbolic_link_source_rejected(self):
        paths = self.sequence()
        link = self.root / "linked.3fr"
        link.symlink_to(paths[0])
        paths[0] = link
        ok, result = self.merge(paths)
        self.assertEqual(ok, 0)
        self.assertIn(b"cannot open", result.error)

    def test_output_symlink_not_followed(self):
        target = self.root / "preserved.txt"
        target.write_bytes(b"preserved")
        (self.root / "result.dng").symlink_to(target)
        ok, _ = self.merge(self.sequence())
        self.assertEqual(ok, 0)
        self.assertEqual(target.read_bytes(), b"preserved")

    def test_cancel_before_output_preserves_sources(self):
        paths = self.sequence()
        before = [input_signature(path) for path in paths]
        ok, result = self.merge(paths, lambda context, done, total: 1)
        self.assertEqual(ok, 0)
        self.assertIn(b"cancelled", result.error)
        self.assertFalse((self.root / "result.dng").exists())
        self.assertEqual(before, [input_signature(path) for path in paths])

    def test_cancel_after_output_reports_failure(self):
        ok, result = self.merge(self.sequence(), lambda context, done, total: int(done == 1))
        self.assertEqual(ok, 0)
        self.assertIn(b"cancelled", result.error)
        self.assertGreater((self.root / "result.dng").stat().st_size, 0)
        self.assertEqual(result.bytes_written, 0)

    def test_source_mutation_during_merge_rejected(self):
        paths = self.sequence()
        changed = [False]

        def mutate(context, done, total):
            if done == 1 and not changed[0]:
                with paths[0].open("r+b") as stream:
                    stream.seek(16383)
                    stream.write(b"\x7f")
                changed[0] = True
            return 0

        ok, result = self.merge(paths, mutate)
        self.assertEqual(ok, 0)
        self.assertIn(b"source changed", result.error)

    def test_unsupported_frame_count_rejected(self):
        ok, result = self.merge([], count=16)
        self.assertEqual(ok, 0)
        self.assertIn(b"four or six", result.error)


if __name__ == "__main__":
    unittest.main()
