import pathlib
import tempfile
import unittest

from rlc.main import main


class TestCli(unittest.TestCase):
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
