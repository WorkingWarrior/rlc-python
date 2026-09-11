import os
import tempfile
import unittest

from rlc.intrinsics_loader import load_intrinsics
from rlc.symbol_table import SymbolTable
from rlc.versioning import Version


class TestIntrinsicsLoader(unittest.TestCase):
    def setUp(self):
        """Set up a temporary directory with mock .kfn files."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = self.temp_dir.name

        with open(os.path.join(self.test_dir, "valid.kfn"), "w") as f:
            f.write("module 0 = Test\n")
            f.write("fun func_one <0:0:1, 0> ()\n")

        with open(os.path.join(self.test_dir, "versioned.kfn"), "w") as f:
            f.write("ver >=1.5.0.0\nfun func_new <0:0:2, 0> ()\nend\n")
            f.write("ver <1.5.0.0\nfun func_old <0:0:3, 0> ()\nend\n")

        with open(os.path.join(self.test_dir, "invalid.kfn"), "w") as f:
            f.write("module 1 = Bad @#$%\n")

        with open(os.path.join(self.test_dir, "ignored.txt"), "w") as f:
            f.write("some text")

        self.symbol_table = SymbolTable()
        self.target_version = Version(1, 4, 0, 0)

    def tearDown(self):
        """Remove the temporary directory."""
        self.temp_dir.cleanup()

    def test_load_intrinsics(self):
        """Test the main loader functionality."""
        os.remove(os.path.join(self.test_dir, "invalid.kfn"))
        load_intrinsics(self.symbol_table, self.test_dir, self.target_version, verbose=False)

        self.assertEqual(self.symbol_table.lookup_module_name(0), "Test")

        try:
            self.symbol_table.lookup_function("func_one")
        except KeyError:
            self.fail("Function 'func_one' was not loaded from valid.kfn")

        with self.assertRaises(KeyError):
            self.symbol_table.lookup_function("func_new")

        try:
            self.symbol_table.lookup_function("func_old")
        except KeyError:
            self.fail("Function 'func_old' was not loaded from versioned.kfn")

        # Malformed KFN data is fatal in the original compiler.
        with open(os.path.join(self.test_dir, "invalid.kfn"), "w") as f:
            f.write("module 1 = Bad @#$%\n")
        with self.assertRaises(Exception):
            load_intrinsics(SymbolTable(), self.test_dir, self.target_version)

    def test_loader_with_nonexistent_dir(self):
        """Test that the loader handles a non-existent directory gracefully."""
        st = SymbolTable()
        load_intrinsics(st, "non_existent_dir_xyz", self.target_version)
        self.assertEqual(len(st.get_all_functions()), 0)


if __name__ == "__main__":
    unittest.main()
