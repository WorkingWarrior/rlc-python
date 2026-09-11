import contextlib
import io
import pathlib
import struct
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

    def test_utf8_output_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "input.ke"
            source.write_text("'Zażółć gęślą jaźń'\n", encoding="utf-8")
            main(
                [
                    str(source),
                    "-e",
                    "UTF-8",
                    "--output-encoding",
                    "UTF-8",
                    "-u",
                    "-g",
                    "--no-metadata",
                    "-o",
                    str(root / "utf8.ke"),
                ]
            )
            self.assertIn("Zażółć gęślą jaźń".encode(), (root / "utf8.TXT.rl").read_bytes())

    def test_archive_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "input.ke"
            source.write_bytes(b"#entrypoint 0\npause()\n")
            first = root / "SEEN0042.TXT"
            second = root / "SEEN0007.TXT"
            common = [str(source), "-g", "--no-metadata", "-f", "1.4.0.5"]
            main(common + ["-o", str(first.with_suffix(""))])
            main(common + ["-o", str(second.with_suffix(""))])

            archive = root / "Seen.txt"
            main(["-a", str(archive), str(first), str(second)])
            data = archive.read_bytes()
            offset_7, length_7 = struct.unpack_from("<II", data, 7 * 8)
            offset_42, length_42 = struct.unpack_from("<II", data, 42 * 8)
            self.assertEqual(offset_7, 80_000)
            self.assertEqual(offset_42, offset_7 + length_7)
            self.assertEqual(data[offset_7 : offset_7 + length_7], second.read_bytes())
            self.assertEqual(data[offset_42 : offset_42 + length_42], first.read_bytes())


if __name__ == "__main__":
    unittest.main()
