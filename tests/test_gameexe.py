import os
import pathlib
import tempfile
import unittest

from rlc.gameexe import load_gameexe, parse_gameexe


class TestGameexe(unittest.TestCase):
    def test_load_utf8_when_cp932_decoding_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "Gameexe.ini"
            path.write_text('#CAPTION="RLC 😀"\n', encoding="utf-8")
            self.assertEqual(load_gameexe(path)["caption"], ["RLC 😀"])

    def test_original_definition_forms(self):
        values = parse_gameexe('#A=1:U:"x"\n#WINDOW.000:002.MOJI_CNT=30,3\n#DLL.0="rlBabel"\n')
        self.assertEqual(values["a"], [1, True, "x"])
        self.assertEqual(values["window.001.moji_cnt"], [30, 3])
        self.assertEqual(values["dll.000"], ["rlBabel"])

    @unittest.skipUnless(os.environ.get("RLC_GAMEEXE"), "set RLC_GAMEEXE to a CLANNAD Gameexe.ini")
    def test_real_clannad_gameexe(self):
        values = load_gameexe(os.environ["RLC_GAMEEXE"])
        self.assertEqual(values["screensize_mod"], [999, 1280, 960])
        self.assertEqual(values["dll.000"], ["RealLiveSteam"])
        self.assertEqual(values["window.000.moji_cnt"], [30, 3])


if __name__ == "__main__":
    unittest.main()
