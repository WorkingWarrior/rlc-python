import tempfile
import unittest
from pathlib import Path

from rlc.archive import pack_seen_archive, read_seen_archive


class ArchiveTests(unittest.TestCase):
    def test_rejects_uncompressed_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "SEEN0001.TXT"
            source.write_bytes(b"KPRLinvalid")
            with self.assertRaisesRegex(ValueError, "not compressed RealLive"):
                pack_seen_archive([source], Path(directory) / "Seen.txt")

    def test_rejects_duplicate_scenario_number(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "SEEN0001.TXT"
            second_dir = root / "other"
            second_dir.mkdir()
            second = second_dir / "seen0001.txt"
            first.write_bytes(b"\xd0\x01\x00\x00a")
            second.write_bytes(b"\xd0\x01\x00\x00b")
            with self.assertRaisesRegex(ValueError, "duplicate scenario"):
                pack_seen_archive([first, second], root / "Seen.txt")

    def test_updates_an_archive_without_dropping_existing_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "SEEN0001.TXT"
            second = root / "SEEN0002.TXT"
            replacement = root / "replacement" / "SEEN0001.TXT"
            replacement.parent.mkdir()
            first.write_bytes(b"\xd0\x01\x00\x00first")
            second.write_bytes(b"\xd0\x01\x00\x00second")
            replacement.write_bytes(b"\xd0\x01\x00\x00replacement")
            archive = root / "Seen.txt"

            pack_seen_archive([first, second], archive)
            count = pack_seen_archive([replacement], archive)

            self.assertEqual(count, 2)
            self.assertEqual(
                read_seen_archive(archive),
                {1: replacement.read_bytes(), 2: second.read_bytes()},
            )


if __name__ == "__main__":
    unittest.main()
