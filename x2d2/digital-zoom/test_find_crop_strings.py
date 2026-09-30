"""The finder must hit a crop name and ignore unrelated text. No firmware fixture."""

import tempfile
import unittest
from pathlib import Path

from find_crop_strings import scan


class FindCropStringsTest(unittest.TestCase):
    def test_hits_crop_name_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ui.txt").write_bytes(b"prefix setCropRect(x,y,w,h) suffix\x00other")
            (root / "noise.txt").write_bytes(b"battery and shutter only")
            hits = scan(root)
        self.assertEqual(len(hits), 1)
        self.assertIn("setCropRect", hits[0][1])


if __name__ == "__main__":
    unittest.main()
