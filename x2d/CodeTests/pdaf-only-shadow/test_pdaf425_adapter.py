"""Run the passive adapter's synthetic contract checks in a temporary directory."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class StreamAdapterTests(unittest.TestCase):
    def test_pass_through_snapshot_and_lifetime(self):
        compiler = shlex.split(os.environ.get('CC', 'clang'))
        if not compiler or not shutil.which(compiler[0]):
            self.skipTest('A C11 compiler is required for the adapter host check')
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'adapter-check'
            subprocess.run([
                *compiler, '-std=c11', '-O1', '-g', '-fsanitize=address,undefined',
                '-Wall', '-Wextra', '-Werror',
                *(str(HERE / name) for name in (
                    'pdaf425_core.c', 'pdaf425_capture.c',
                    'pdaf425_stream_adapter.c', 'test_pdaf425_stream_adapter.c')),
                '-o', str(target),
            ], check=True)
            result = subprocess.run([str(target)], check=True, capture_output=True, text=True)
            self.assertIn('7 original calls preserved', result.stdout)


if __name__ == '__main__':
    unittest.main()
