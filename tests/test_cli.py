import contextlib
import io
import pathlib
import tempfile
import unittest

from rlc import __version__
from rlc.main import main


class TestCli(unittest.TestCase):
    def test_version(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), f"rlc {__version__}\n")

    def test_original_output_suffixes_and_compression_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "input.ke"
            source.write_bytes(b"#entrypoint 0\npause()\n")
            common = [str(source), "-g", "--no-metadata", "-f", "1.4.0.5"]
            main(common + ["-u", "-o", str(root / "plain.ke")])
            main(common + ["-o", str(root / "packed.ke")])
            self.assertEqual((root / "plain.TXT.rl").read_bytes()[:4], b"KPRL")
            self.assertEqual(
                int.from_bytes((root / "packed.TXT").read_bytes()[:4], "little"), 0x1D0
            )


if __name__ == "__main__":
    unittest.main()
