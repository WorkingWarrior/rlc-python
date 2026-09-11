import datetime
import struct
import unittest

from rlc.kfn_data_structures import FunctionSignature, ParameterInfo, RLType
from rlc.real_bytecode import (
    Entrypoint,
    Kidoku,
    Label,
    LabelRef,
    LineRef,
    assignment,
    binary,
    build_avg2000,
    build_uncompressed,
    function,
    int32,
    opcode,
    variable,
)


class TestRealBytecode(unittest.TestCase):
    def test_codegen_ml_equations(self):
        one = int32(1)
        two = int32(2)
        self.assertEqual(one, b"$\xff\x01\x00\x00\x00")
        self.assertEqual(binary(one, "+", two), one + b"\\\x00" + two)
        var = variable(0, int32(3))
        self.assertEqual(assignment(var, "=", one), var + b"\\\x1e" + one)
        self.assertEqual(opcode(0, 1, 5, 0, 0), b"#\x00\x01\x05\x00\x00\x00\x00")

    def test_overload_and_uncounted_argc(self):
        p = ParameterInfo(type=RLType.INT_C, is_uncounted=True)
        sig = FunctionSignature(
            "goto_if", id=1, module_id=1, opcode_type=0, prototypes=[[p]], parameters=[p]
        )
        self.assertEqual(function(sig, [int32(1)]), opcode(0, 1, 1, 0, 0) + b"(" + int32(1) + b")")

    def test_file_layout_label_kidoku_entrypoint(self):
        data = build_uncompressed(
            [Entrypoint(2), LineRef(7), Kidoku(9), Label("x"), b"A", LabelRef("x")],
            version=(1, 4, 0, 5),
        )
        self.assertEqual(data[:4], b"KPRL")
        self.assertEqual(struct.unpack_from("<I", data, 0x0C)[0], 2)
        self.assertEqual(struct.unpack_from("<I", data, 0x34 + 8)[0], 0)
        off = struct.unpack_from("<I", data, 0x20)[0]
        self.assertEqual(data[off], ord("!"))
        self.assertEqual(struct.unpack_from("<I", data, len(data) - 4)[0], 9)

    def test_avg2000_layout_and_four_byte_markers(self):
        now = datetime.datetime(2010, 2, 3, 4, 5, 6)
        data = build_avg2000([Entrypoint(2), Kidoku(9), b"A"], now=now)
        self.assertEqual(data[:4], b"KP2K")
        self.assertEqual(struct.unpack_from("<I", data, 4)[0], 10002)
        self.assertEqual(struct.unpack_from("<7H", data, 8), (2010, 2, 3, 3, 5, 5, 6))
        off = 0x1CC + 8
        self.assertEqual(data[off : off + 5], b"@\x00\x00\x00\x00")

    def test_last_duplicate_entrypoint_wins(self):
        data = build_uncompressed([Entrypoint(1), b"A", Entrypoint(1)], debug_info=False)
        self.assertEqual(struct.unpack_from("<I", data, 0x0C)[0], 1)
        self.assertEqual(struct.unpack_from("<I", data, 0x34 + 4)[0], 1)


if __name__ == "__main__":
    unittest.main()
