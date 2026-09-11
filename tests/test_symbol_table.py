import unittest

from rlc.kfn_data_structures import FunctionSignature, Location, ParameterInfo, RLType
from rlc.symbol_table import SymbolTable


class TestSymbolTable(unittest.TestCase):
    def setUp(self):
        self.table = SymbolTable()
        self.loc = Location("test.kfn", 1, 1)

    def test_define_and_lookup_module(self):
        """Test defining and looking up a module."""
        self.table.define_module(0, "System", self.loc)
        self.assertEqual(self.table.lookup_module_name(0), "System")
        self.assertIsNone(self.table.lookup_module_name(1))
        self.table.define_module(0, "SystemCore", self.loc)
        self.assertEqual(self.table.lookup_module_name(0), "SystemCore")

    def test_define_and_lookup_function(self):
        """Test defining and looking up a function."""
        sig = FunctionSignature(name="my_func", id=1, module_id=0, location=self.loc)
        self.table.define_function(sig)

        found_sigs = self.table.lookup_function("my_func")
        self.assertEqual(len(found_sigs), 1)
        self.assertIs(found_sigs[0], sig)

        with self.assertRaises(KeyError):
            self.table.lookup_function("non_existent_func")

    def test_function_overloading(self):
        """Test defining multiple function signatures for the same name (overloading)."""
        sig1 = FunctionSignature(name="overload_func", parameters=[], location=self.loc)
        sig2 = FunctionSignature(
            name="overload_func",
            parameters=[ParameterInfo(name="p1", type=RLType.INT)],
            location=self.loc,
        )

        self.table.define_function(sig1)
        self.table.define_function(sig2)

        found_sigs = self.table.lookup_function("overload_func")
        self.assertEqual(len(found_sigs), 2)

        self.assertIs(self.table.get_function("overload_func", 0), sig1)
        self.assertIs(self.table.get_function("overload_func", 1), sig2)
        self.assertIsNone(self.table.get_function("overload_func", 2))

    def test_variable_scopes(self):
        """Test variable declaration and lookup across different scopes."""
        self.table.declare_variable("global_var", RLType.INT, self.loc)
        self.assertIsNotNone(self.table.lookup_variable("global_var"))

        self.table.enter_scope()
        self.assertEqual(self.table.current_scope_level, 1)

        self.table.declare_variable("local_var", RLType.STR, self.loc)

        self.assertIsNotNone(self.table.lookup_variable("local_var"))
        self.assertIsNotNone(self.table.lookup_variable("global_var"))

        self.table.declare_variable("global_var", RLType.STR, self.loc)
        shadowed_var = self.table.lookup_variable("global_var")
        self.assertEqual(shadowed_var.type, RLType.STR)
        self.assertEqual(shadowed_var.scope_level, 1)

        self.table.exit_scope()
        self.assertEqual(self.table.current_scope_level, 0)

        self.assertIsNone(self.table.lookup_variable("local_var"))
        original_global = self.table.lookup_variable("global_var")
        self.assertIsNotNone(original_global)
        self.assertEqual(original_global.type, RLType.INT)
        self.assertEqual(original_global.scope_level, 0)

    def test_label_handling(self):
        """Test adding and checking for labels."""
        self.table.add_label("my_label", self.loc)
        self.assertTrue(self.table.has_label("my_label"))
        self.assertEqual(self.table.get_label_location("my_label"), self.loc)

        replacement = Location("other.kfn", 10, 1)
        self.table.add_label("my_label", replacement)
        self.assertEqual(self.table.get_label_location("my_label"), replacement)


if __name__ == "__main__":
    unittest.main()
