import unittest

from rlc.kfn_data_structures import FunctionSignature
from rlc.versioning import (
    Version,
    is_version_compatible,
    parse_condition_string,
    parse_version_string,
)


class TestVersioning(unittest.TestCase):
    def test_version_parsing(self):
        """Test parsing of version strings."""
        self.assertEqual(parse_version_string("1.2.3.4"), Version(1, 2, 3, 4))
        self.assertEqual(parse_version_string("1.2.3"), Version(1, 2, 3, 0))
        self.assertEqual(parse_version_string("1.2"), Version(1, 2, 0, 0))
        self.assertEqual(parse_version_string("1"), Version(1, 0, 0, 0))
        with self.assertRaises(ValueError):
            parse_version_string("1.2.3.4.5")
        with self.assertRaises(ValueError):
            parse_version_string("a.b.c.d")

    def test_version_comparison(self):
        """Test comparison operators for the Version class."""
        v1 = Version(1, 2, 3, 4)
        v2 = Version(1, 2, 3, 5)
        v3 = Version(1, 3, 0, 0)
        v4 = Version(1, 2, 3, 4)

        self.assertTrue(v1 < v2)
        self.assertTrue(v1 < v3)
        self.assertTrue(v2 < v3)
        self.assertFalse(v1 > v2)
        self.assertEqual(v1, v4)
        self.assertNotEqual(v1, v2)
        self.assertTrue(v1 <= v4)
        self.assertTrue(v3 >= v1)

    def test_condition_parsing(self):
        """Test parsing of version condition strings."""
        target_v = Version(1, 5, 0, 0)

        cond_ge = parse_condition_string(">=1.4.0.0")
        self.assertIsNotNone(cond_ge)
        self.assertTrue(cond_ge.check(target_v))

        cond_lt = parse_condition_string("<1.4.0.0")
        self.assertIsNotNone(cond_lt)
        self.assertFalse(cond_lt.check(target_v))

        cond_eq = parse_condition_string("==1.5.0.0")
        self.assertIsNotNone(cond_eq)
        self.assertTrue(cond_eq.check(target_v))

        cond_named = parse_condition_string("reallive")
        self.assertIsNone(cond_named)

        with self.assertRaises(ValueError):
            parse_condition_string("!>1.0.0.0")

    def test_is_version_compatible(self):
        """Test the main compatibility checking function."""
        target_version = Version(1, 3, 5, 0)

        sig1 = FunctionSignature(name="func1", versions=[])
        self.assertTrue(is_version_compatible(sig1, target_version))

        sig2 = FunctionSignature(name="func2", versions=[">=1.3.0.0"])
        self.assertTrue(is_version_compatible(sig2, target_version))

        sig3 = FunctionSignature(name="func3", versions=["<1.3.0.0"])
        self.assertFalse(is_version_compatible(sig3, target_version))

        sig4 = FunctionSignature(name="func4", versions=[">=1.0.0.0", "<2.0.0.0"])
        self.assertTrue(is_version_compatible(sig4, target_version))

        sig5 = FunctionSignature(name="func5", versions=[">=1.0.0.0", "<1.2.0.0"])
        self.assertFalse(is_version_compatible(sig5, target_version))

        sig6 = FunctionSignature(name="func6", versions=["reallive", ">=1.3.0.0"])
        self.assertTrue(is_version_compatible(sig6, target_version))


if __name__ == "__main__":
    unittest.main()
