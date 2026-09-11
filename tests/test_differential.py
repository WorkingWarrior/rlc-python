"""Optional byte-for-byte checks against a built OCaml rlc.

Set ``RLC_OCAML`` to the executable path.  The test deliberately disables
compression, debug records, and metadata so that the result is deterministic.
"""

import os
import pathlib
import subprocess
import tempfile
import unittest

from rlc.config import Config
from rlc.main import compile_source
from rlc.runtime import default_kfn_path
from rlc.versioning import Version


class TestOcamlDifferential(unittest.TestCase):
    def assert_compilers_equal(
        self,
        source,
        name,
        compressed=False,
        target_version="1.4.0.5",
        gameexe_path=None,
        gameexe_source=None,
    ):
        with tempfile.TemporaryDirectory() as directory:
            src = pathlib.Path(directory) / (name + ".ke")
            src.write_bytes(source.encode("cp932"))
            if gameexe_source is not None:
                ini = pathlib.Path(directory) / "Gameexe.ini"
                ini.write_bytes(gameexe_source.encode("cp932"))
                gameexe_path = str(ini)
            command = [
                os.environ["RLC_OCAML"],
                "-g",
                "--no-metadata",
                "-c",
                "10002",
                "-e",
                "CP932",
                "-f",
                target_version,
                "-o",
                name + ".ke",
                str(src),
            ]
            if gameexe_path:
                command[1:1] = ["-i", gameexe_path]
            if not compressed:
                command.insert(1, "-u")
            subprocess.run(command, cwd=directory, check=True, capture_output=True)
            suffix = ".TXT" if compressed else ".TXT.rl"
            reference = (pathlib.Path(directory) / (name + suffix)).read_bytes()
            config = Config(
                target_version=Version(*(int(x) for x in target_version.split("."))),
                include_debug_symbols=False,
                kfn_directory_path=str(default_kfn_path()),
                compress_output=compressed,
                gameexe_path=gameexe_path,
            )
            result = compile_source(source, config)
        self.assertEqual(result, reference)

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_minimal_function_call(self):
        self.assert_compilers_equal("#entrypoint 0\npause()\n", "minimal")

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_select_forms(self):
        cases = {
            "select_basic": "#entrypoint 0\nselect('ONE','TWO')\n",
            "select_window": "#entrypoint 0\nselect_w2[3]('ONE', colour: 'Red')\n",
            "select_conditions": "#entrypoint 0\nselect(grey(2) if intA[0]: 'X', hide: '')\n",
            "select_result": "#entrypoint 0\nint choice\nchoice = select('ONE')\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self.assert_compilers_equal(source, name)

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_static_textout_forms(self):
        cases = {
            "text_plain": "#entrypoint 0\n'hello world'\n",
            "text_integer": "#entrypoint 0\n'value=\\i:3{7}'\n",
            "text_speaker": "#entrypoint 0\n'\\name{Bob} hello'\n",
            "text_empty": "#entrypoint 0\n''\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self.assert_compilers_equal(source, name)

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_variables_arrays_and_initialisers(self):
        cases = {
            "int_array": "#entrypoint 0\nint x[3] = {1,2,3}\nx[1] += 2\n",
            "auto_array": "#entrypoint 0\nint x[] = {1,2}\n",
            "filled_array": "#entrypoint 0\nint x[3] = 7\n",
            "string_array": "#entrypoint 0\nstr s[] = {'A','B'}\ns[1] += 'C'\n",
            "zero_arrays": "#entrypoint 0\nint(zero) x[3]\nstr(zero) s[2]\n",
            "store_result": "#entrypoint 0\nint result\nresult = strlen('ABC')\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self.assert_compilers_equal(source, name)

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_lz77_and_masked_output(self):
        cases = {
            "compressed_tiny": "#entrypoint 0\npause()\n",
            "compressed_select": "#entrypoint 0\nselect('ONE','TWO','THREE')\n",
            "compressed_repetition": "#entrypoint 0\n'" + ("abcde " * 200) + "'\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self.assert_compilers_equal(source, name, compressed=True)

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_compile_time_intrinsics(self):
        source = """#entrypoint 0
#if target_lt(2)
pause()
#endif
#const key = 'DLL.\\i:3{2}', fallback = gameexe(key, 0, 7)
#if __equal_strings?(key, 'DLL.002') && fallback == 7
pause()
#endif
int values[3]
#if array?(values) && length(values) == 3
pause()
#endif
"""
        self.assert_compilers_equal(source, "compile_time_intrinsics")

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_scoped_inline_return_macros(self):
        cases = {
            # rlapi.kh implements these wrappers with
            # ``#sdefine __retval = store`` followed by ``return __retval``.
            "inline_calldll_statement": "#entrypoint 0\nCallDLL(0)\n",
            "inline_max_expression": "#entrypoint 0\nint x\nx = max(intA[0],intA[1])\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self.assert_compilers_equal(source, name)

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_corpus_discovered_expression_and_funcasm_cases(self):
        cases = {
            "condition_arms": "#entrypoint 0\ngoto_unless(intD[0] || intD[1] && intD[2]) @done\n@done\n",
            "bytecode_precedence": "#entrypoint 0\nintA[0] = (intA[0] + 1) % 2\n",
            "bare_return_function": "#entrypoint 0\nstrS[0] = Lowercase\n",
            "string_self_assignment": "#entrypoint 0\nstrS[0] = strS[0]\n",
            "dynamic_quote_parameter": "#entrypoint 0\nintA[0] = strpos(strS[0], '\"Fuko User')\n",
            "special_parameter_arity": "#entrypoint 0\ngrpMulti('KURO', 4, area('A', 0, 0, 10, 10, 0, 0, 255))\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self.assert_compilers_equal(source, name)

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_goto_case(self):
        source = """#entrypoint 0
goto_case(intA[0]){0:@one; 2:@two; _:@end}
@one
pause()
@two
pause()
@end
"""
        self.assert_compilers_equal(source, "goto_case")

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_real_runtime_headers(self):
        cases = (
            ("header_compat", "#load 'compat'\npause()\n", "1.4.0.5"),
            ("header_rlapi", "#load 'rlapi'\npause()\n", "1.4.0.5"),
            ("header_system", "#load 'system'\npause()\n", "1.4.0.5"),
            (
                "header_textout",
                "#define __DynamicLineation__\n#load 'system'\npause()\n",
                "1.4.0.5",
            ),
            ("header_rlbabel", "#load 'rlBabel'\n", "1.2.4.0"),
        )
        for name, source, version in cases:
            with self.subTest(name=name):
                self.assert_compilers_equal(source, name, target_version=version)

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_rlbabel_with_gameexe(self):
        self.assert_compilers_equal(
            "#load 'rlBabel'\n", "header_rlbabel_modern", gameexe_source='#DLL.000="rlBabel"\n'
        )

    @unittest.skipUnless(os.environ.get("RLC_OCAML"), "set RLC_OCAML to a built OCaml compiler")
    def test_clannad_gameexe_excerpt(self):
        source = """#if gameexe('SCREENSIZE_MOD',1)==1280 && __equal_strings?(gameexe('DLL.000'),'RealLiveSteam')
pause()
#endif
"""
        self.assert_compilers_equal(
            source,
            "clannad_gameexe",
            gameexe_source='#SCREENSIZE_MOD=999,1280,960\n#DLL.000="RealLiveSteam"\n',
        )

    @unittest.skipUnless(
        os.environ.get("RLC_OCAML") and os.environ.get("RLC_CLANNAD_CORPUS"),
        "set RLC_OCAML and RLC_CLANNAD_CORPUS",
    )
    def test_real_clannad_seens(self):
        base = pathlib.Path(os.environ["RLC_CLANNAD_CORPUS"])
        paths = (
            "SEEN0xxx/SEEN0001.org",
            "SEEN4xxx/SEEN4427.org",
            "SEEN4xxx/SEEN4999.org",
            "SEEN1xxx/SEEN1001.org",
            "SEEN6xxx/SEEN6513.org",
        )
        for relative in paths:
            source_path = base / relative
            name = source_path.stem
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                command = [
                    os.environ["RLC_OCAML"],
                    "-u",
                    "-g",
                    "--no-metadata",
                    "-c",
                    "10002",
                    "-e",
                    "UTF-8",
                    "-f",
                    "1.4.0.5",
                    "-d",
                    directory,
                    "-o",
                    name + ".ke",
                    source_path.name,
                ]
                subprocess.run(command, cwd=source_path.parent, check=True, capture_output=True)
                reference = (pathlib.Path(directory) / (name + ".TXT.rl")).read_bytes()
                config = Config(
                    target_version=Version(1, 4, 0, 5),
                    include_debug_symbols=False,
                    kfn_directory_path=str(default_kfn_path()),
                )
                result = compile_source(source_path.read_text("utf-8"), config, str(source_path))
                self.assertEqual(result, reference)

    @unittest.skipUnless(
        os.environ.get("RLC_OCAML") and os.environ.get("RLC_CLANNAD_CORPUS"),
        "set RLC_OCAML and RLC_CLANNAD_CORPUS",
    )
    def test_real_clannad_seen0001_compressed(self):
        source_path = pathlib.Path(os.environ["RLC_CLANNAD_CORPUS"]) / "SEEN0xxx/SEEN0001.org"
        with tempfile.TemporaryDirectory() as directory:
            command = [
                os.environ["RLC_OCAML"],
                "-g",
                "--no-metadata",
                "-c",
                "10002",
                "-e",
                "UTF-8",
                "-f",
                "1.4.0.5",
                "-d",
                directory,
                "-o",
                "SEEN0001.ke",
                source_path.name,
            ]
            subprocess.run(command, cwd=source_path.parent, check=True, capture_output=True)
            reference = (pathlib.Path(directory) / "SEEN0001.TXT").read_bytes()
            config = Config(
                target_version=Version(1, 4, 0, 5),
                include_debug_symbols=False,
                kfn_directory_path=str(default_kfn_path()),
                compress_output=True,
            )
            result = compile_source(source_path.read_text("utf-8"), config, str(source_path))
            self.assertEqual(result, reference)
