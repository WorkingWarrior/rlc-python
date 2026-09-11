import unittest
from hashlib import sha256

from rlc.compression import apply_mask, lz77_compress


class TestCompression(unittest.TestCase):
    def test_mask_is_symmetric(self):
        data = bytes(range(256)) + b"KPRL"
        self.assertEqual(apply_mask(apply_mask(data)), data)

    def test_reallive_lz77_known_vectors(self):
        self.assertEqual(lz77_compress(b""), b"\x00")
        self.assertEqual(lz77_compress(b"abc"), b"\x07abc")
        # Eight literals cause the C++ Flush() implementation to append an
        # otherwise empty flag group.
        self.assertEqual(lz77_compress(b"abcdefgh"), b"\xffabcdefgh\x00")

    def test_end_of_buffer_chain_termination(self):
        # The reference stops searching its hash chain after a mismatch on the
        # final available input byte, even when an older candidate is longer.
        source = b"ABCDEQQQABCDXRRRABCDE"
        expected = bytes.fromhex("ff41424344455151515e820058525252820045")
        self.assertEqual(lz77_compress(source), expected)

    def test_historical_static_min_lookahead(self):
        # CInfoRealLive inherits a static MinLookahead() computed with the base
        # 258-byte MaxMatch, then clamps emitted matches to 17 bytes. This input
        # crosses the point where an apparently equivalent LZ77 loop diverges.
        prefix = bytes(range(1, 156))
        source = prefix + b"\xfe" + bytes(range(1, 25)) + b"\xfd\xfc" + prefix
        digest = "bc757fb3c0eab28168414fab5c2aa1a48c9d792ec75db816dfca25219f14b313"
        self.assertEqual(sha256(lz77_compress(source)).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
