import unittest

from rlc.errors import RLCError
from rlc.lexer import Lexer
from rlc.parser import Parser


class TestParser(unittest.TestCase):
    def parse(self, s):
        return Parser(Lexer(s, "test.ke").tokens()).parse()

    def test_kepago_declaration_and_expression_precedence(self):
        ast = self.parse("int x = 1 + 2 * 3")
        init = ast.statements[0].value[2][0][2]
        self.assertEqual(ast.statements[0].kind, "decl")
        self.assertEqual((init.kind, init.value), ("bin", "+"))
        self.assertEqual(init.args[1].value, "*")

    def test_control_structures_and_labels(self):
        ast = self.parse("@loop while intA[0] < 3: intA[0] += 1;")
        self.assertEqual([x.kind for x in ast.statements], ["label", "while"])
        self.assertEqual(ast.statements[1].args[1].kind, "block")

    def test_kepago_numbers(self):
        vals = self.parse("#const a=$ff, b=$#1010, c=$%17").statements[0].value[1]
        self.assertEqual([x[2].value for x in vals], [255, 10, 15])

    def test_invalid_syntax(self):
        with self.assertRaises(RLCError):
            self.parse("int x =")


if __name__ == "__main__":
    unittest.main()
