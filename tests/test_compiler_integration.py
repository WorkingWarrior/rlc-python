import os
import struct
import tempfile
import unittest
from pathlib import Path

from rlc.config import Config
from rlc.errors import RLCError
from rlc.main import compile_source
from rlc.real_bytecode import opcode
from rlc.runtime import default_kfn_path, runtime_directory
from rlc.versioning import Version


class TestCompilerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Config(
            kfn_directory_path=str(default_kfn_path()),
            target_version=Version(1, 4, 0, 5),
            include_debug_symbols=False,
        )

    def test_source_to_complete_kprl(self):
        data = compile_source("#entrypoint 0 pause()", self.config, "tiny.ke")
        off = struct.unpack_from("<I", data, 0x20)[0]
        pause = self.config.symbol_table.lookup_function("pause")[0]
        self.assertEqual(data[:4], b"KPRL")
        self.assertEqual(
            data[off:],
            b"!\x00\x00" + opcode(pause.opcode_type, pause.module_id, pause.id, 0, 0) + b"\x00",
        )
        self.assertEqual(struct.unpack_from("<I", data, 0x34)[0], 0)

    def test_declaration_and_assignment_to_bytecode(self):
        data = compile_source("int x = 2 x += 3", self.config, "vars.ke")
        off = struct.unpack_from("<I", data, 0x20)[0]
        self.assertIn(b"\\\x1e", data[off:])
        self.assertIn(b"\\\x14", data[off:])

    def test_project_runtime_headers_parse(self):
        from rlc.lexer import Lexer
        from rlc.parser import Parser

        for name in ("system.kh", "compat.kh", "rlapi.kh", "textout.kh", "rlBabel.kh"):
            path = runtime_directory() / name
            with open(path, "rb") as stream:
                source = stream.read().decode("cp932")
            self.assertTrue(Parser(Lexer(source, path).tokens()).parse().statements)

    def test_all_runtime_headers_compile_in_valid_contexts(self):
        cases = (
            "#load 'compat' pause()",
            "#load 'rlapi' pause()",
            "#load 'system' pause()",
            "#define __DynamicLineation__ #load 'system' pause()",
        )
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(compile_source(source, self.config)[:4], b"KPRL")
        old = Config(
            kfn_directory_path=str(default_kfn_path()),
            target_version=Version(1, 2, 4, 0),
            include_debug_symbols=False,
        )
        self.assertEqual(compile_source("#load 'rlBabel'", old)[:4], b"KPRL")

    def test_load_real_system_header_and_compile(self):
        data = compile_source("#load 'system' pause()", self.config, "with_system.ke")
        self.assertEqual(data[:4], b"KPRL")

    def test_dynamic_textout_header_compiles_through_system(self):
        data = compile_source(
            "#define __DynamicLineation__ #load 'system' pause()", self.config, "dynamic_system.ke"
        )
        self.assertEqual(data[:4], b"KPRL")

    def test_compile_time_intrinsics(self):
        source = """#const key='DLL.\\i:3{2}', fallback=gameexe(key,0,7)
int values[3]
#if target_lt(2) && __equal_strings?(key,'DLL.002') && array?(values) && length(values)==3 && fallback==7
pause()
#endif"""
        self.assertEqual(compile_source(source, self.config, "intrinsics.ke")[:4], b"KPRL")

    @unittest.skipUnless(
        os.environ.get("RLC_CLANNAD_CORPUS"),
        "set RLC_CLANNAD_CORPUS to the CLANNAD SEEN source directory",
    )
    def test_real_clannad_seens_compile(self):
        base = os.environ["RLC_CLANNAD_CORPUS"]
        for relative in (
            "SEEN0xxx/SEEN0001.org",
            "SEEN4xxx/SEEN4427.org",
            "SEEN4xxx/SEEN4999.org",
            "SEEN1xxx/SEEN1001.org",
            "SEEN6xxx/SEEN6513.org",
        ):
            path = os.path.join(base, relative)
            with self.subTest(path=relative), open(path, encoding="utf-8") as stream:
                source = stream.read()
            self.assertEqual(compile_source(source, self.config, path)[:4], b"KPRL")

    def test_halt_and_loop_control(self):
        halted = compile_source("halt", self.config, "halt.ke")
        off = struct.unpack_from("<I", halted, 0x20)[0]
        self.assertEqual(halted[off:], b"!\x00\x00\x00\x00")
        self.assertEqual(compile_source("while 1 : continue break ;", self.config)[:4], b"KPRL")
        with self.assertRaisesRegex(RLCError, "break outside breakable structure"):
            compile_source("break", self.config)

    def test_funcasm_variable_type_check_and_special_parameter(self):
        with self.assertRaisesRegex(RLCError, "expected integer variable"):
            compile_source("GetTextPos(1, 2)", self.config)
        typed = compile_source("int x, y GetTextPos(x, y)", self.config)
        self.assertEqual(typed[:4], b"KPRL")
        special = compile_source("gosub_with({1})", self.config)
        off = struct.unpack_from("<I", special, 0x20)[0]
        self.assertIn(b"a\x00$\xff\x01\x00\x00\x00", special[off:])

    def test_string_returning_calls_can_be_nested(self):
        source = """strout(strsub(GetName(1), 0, 1))
goto_unless(GetLocalName(0) == 'Nagisa') @done
@done"""
        self.assertEqual(compile_source(source, self.config, "strings.ke")[:4], b"KPRL")

    def test_numeric_resource_keys_ignore_leading_zeroes(self):
        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / "strings.utf"
            resource.write_text("<0142> resource text\n", encoding="utf-8")
            source = f"#resource '{resource}' #res<142>"
            self.assertEqual(compile_source(source, self.config, "resource.ke")[:4], b"KPRL")

    def test_select_variants_conditions_and_result_store(self):
        source = "int choice choice = select_w2[3]('ONE', colour: 'Red', grey(2) if intA[0]: 'X')"
        data = compile_source(source, self.config, "select.ke")
        off = struct.unpack_from("<I", data, 0x20)[0]
        code = data[off:]
        self.assertIn(opcode(0, 2, 10, 3, 0) + b"($\xff\x03\x00\x00\x00){\x0a\x00\x00", code)
        self.assertIn(b'ONE\x0a\x00\x00(0)"Red"\x0a\x00\x00', code)
        self.assertIn(
            b"(($\x00[$\xff\x00\x00\x00\x00]\\\x29$\xff\x00\x00\x00\x00)1$\xff\x02\x00\x00\x00)X\x0a\x00\x00}",
            code,
        )
        self.assertTrue(code.endswith(b"$\x02[$\xff\x00\x00\x00\x00]\\\x1e$\xc8\x00"))

    def test_select_rejects_window_only_for_opcode_13(self):
        with self.assertRaisesRegex(RLCError, "window specifiers are not valid"):
            compile_source("select_btnwkcancel[0]('x')", self.config, "select.ke")
        self.assertEqual(compile_source("select_s[0]('x')", self.config)[:4], b"KPRL")


if __name__ == "__main__":
    unittest.main()
