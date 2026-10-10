"""Offline checks for the proposed CFV JPEG monochrome pixel unit."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MonoNativeTests(unittest.TestCase):

    def test_converter_contract(self):
        compiler = shutil.which("clang") or shutil.which("cc")
        if compiler is None:
            self.skipTest("A C compiler is unavailable")
        with tempfile.TemporaryDirectory(prefix="cfv-mono-test-") as temp:
            executable = Path(temp) / "mono-test"
            command = [
                compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT / "native"),
                str(ROOT / "native/cfv_mono.c"),
                str(ROOT / "native/cfv_mono_jpeg.c"),
                str(ROOT / "native/cfv_mono_vmem.c"),
                str(ROOT / "tests/mono_native_test.c"),
                "-o", str(executable),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run([str(executable)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
