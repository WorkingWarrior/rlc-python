import unittest

from rlc.kfn_lexer import KfnLexer
from rlc.kfn_parser import KfnParser
from rlc.runtime import default_kfn_path
from rlc.symbol_table import SymbolTable
from rlc.versioning import Version


class TestKfnCompatibility(unittest.TestCase):
    def parse(self, text, target="reallive"):
        st = SymbolTable()
        return st, KfnParser(KfnLexer(text, "test.kfn"), st, Version(1, 4, 0, 5), target).parse()

    def test_exact_grammar_features(self):
        src = """module 001 = Jmp
ver RealLive, >= 1.3
 fun foo bar {*=ctrl} (store if goto) <2:Jmp:00016, 1> (<'condition') ?
end
"""
        st, (_, fs) = self.parse(src)
        f = fs[0]
        self.assertEqual(
            (f.name, f.alias, f.opcode_type, f.module_id, f.id), ("foo", "bar", 2, 1, 16)
        )
        self.assertEqual(len(f.prototypes), 2)
        self.assertIsNone(f.prototypes[1])
        self.assertIn("line_break", f.kfn_flags)
        self.assertTrue(f.prototypes[0][0].is_uncounted)

    def test_target_classes_are_alternatives(self):
        src = "ver Avg2000, RealLive\n fun x <0:0:1, 0> ()\nend"
        self.assertEqual(len(self.parse(src, "reallive")[1][1]), 1)
        self.assertEqual(len(self.parse(src, "kinetic")[1][1]), 0)

    def test_distribution_kfn_parses(self):
        path = str(default_kfn_path())
        st = SymbolTable()
        with open(path, encoding="utf-8") as stream:
            source = stream.read()
        mods, fs = KfnParser(KfnLexer(source, path), st, Version(1, 4, 0, 5)).parse()
        self.assertEqual(len(mods), 23)
        self.assertGreater(len(fs), 5000)
        self.assertEqual(
            (st.lookup_function("goto")[0].module_id, st.lookup_function("goto")[0].id), (1, 0)
        )


if __name__ == "__main__":
    unittest.main()
