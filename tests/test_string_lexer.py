import struct
import unittest

from rlc.config import Config
from rlc.lexer import Lexer
from rlc.main import compile_source
from rlc.parser import Parser
from rlc.runtime import default_kfn_path
from rlc.string_lexer import StringLiteral
from rlc.versioning import Version


class TestStringLexer(unittest.TestCase):
    def test_structured_tokens_and_width_expression(self):
        program = Parser(Lexer("'A\\_B\\i:3{7}\\name{N}'", "text.ke").tokens()).parse()
        literal = program.statements[0].args[0].value
        self.assertIsInstance(literal, StringLiteral)
        self.assertEqual(
            [t.kind for t in literal.tokens],
            ["text", "space", "text", "code", "speaker", "text", "rcur"],
        )
        code = literal.tokens[3].value
        self.assertEqual(code[0], "i")
        self.assertEqual(code[1].value, 3)
        self.assertEqual(code[2][0].value, 7)

    def test_plain_static_textout_matches_compile_stub_shape(self):
        config = Config(
            kfn_directory_path=str(default_kfn_path()),
            target_version=Version(1, 4, 0, 5),
            include_debug_symbols=False,
        )
        data = compile_source("'hello'", config, "text.ke")
        offset = struct.unpack_from("<I", data, 0x20)[0]
        self.assertEqual(data[offset:], b'!\x00\x00@\x01\x00"hello"\x00')

    def test_integer_control_code_constant_folds_into_text(self):
        config = Config(
            kfn_directory_path=str(default_kfn_path()),
            target_version=Version(1, 4, 0, 5),
            include_debug_symbols=False,
        )
        data = compile_source("'value=\\i:3{7}'", config, "text.ke")
        offset = struct.unpack_from("<I", data, 0x20)[0]
        self.assertEqual(data[offset:], b'!\x00\x00@\x01\x00"value=007"\x00')


if __name__ == "__main__":
    unittest.main()
