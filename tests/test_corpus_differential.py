"""Byte-for-byte differential test over the supplied CLANNAD corpus."""

import os
import pathlib
import subprocess
import tempfile
import unittest

from rlc.config import Config
from rlc.main import compile_source
from rlc.runtime import default_kfn_path
from rlc.versioning import Version

CORPUS = (
    pathlib.Path(os.environ["RLC_CLANNAD_CORPUS"]) if os.environ.get("RLC_CLANNAD_CORPUS") else None
)


class TestClannadCorpusDifferential(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("RLC_OCAML") and CORPUS and CORPUS.is_dir(),
        "set RLC_OCAML and RLC_CLANNAD_CORPUS",
    )
    def test_all_ocaml_compilable_scenarios_are_identical(self):
        paths = sorted(CORPUS.rglob("*.org"))
        self.assertEqual(len(paths), 205)
        ocaml_failures = []
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            for source_path in paths:
                name = source_path.stem
                target = output / name
                target.mkdir()
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
                    str(target),
                    "-o",
                    name + ".ke",
                    source_path.name,
                ]
                reference_run = subprocess.run(command, cwd=source_path.parent, capture_output=True)
                config = Config(
                    target_version=Version(1, 4, 0, 5),
                    include_debug_symbols=False,
                    kfn_directory_path=str(default_kfn_path()),
                    compress_output=False,
                    compiler_version=10002,
                )
                if reference_run.returncode:
                    ocaml_failures.append(name)
                    with self.subTest(name=name):
                        with self.assertRaises(Exception):
                            compile_source(source_path.read_text("utf-8"), config, str(source_path))
                    continue
                reference = (target / (name + ".TXT.rl")).read_bytes()
                with self.subTest(name=name):
                    result = compile_source(
                        source_path.read_text("utf-8"), config, str(source_path)
                    )
                    self.assertEqual(result, reference)
        self.assertEqual(ocaml_failures, ["SEEN6430", "SEEN6801", "SEEN9802", "SEEN9820"])

    @unittest.skipUnless(
        os.environ.get("RLC_OCAML")
        and os.environ.get("RLC_COMPRESSED_CORPUS")
        and CORPUS
        and CORPUS.is_dir(),
        "set RLC_COMPRESSED_CORPUS=1 for the full compressed corpus",
    )
    def test_all_ocaml_compilable_scenarios_are_identical_compressed(self):
        paths = sorted(CORPUS.rglob("*.org"))
        ocaml_failures = []
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            for source_path in paths:
                name = source_path.stem
                target = output / name
                target.mkdir()
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
                    str(target),
                    "-o",
                    name + ".ke",
                    source_path.name,
                ]
                reference_run = subprocess.run(command, cwd=source_path.parent, capture_output=True)
                if reference_run.returncode:
                    ocaml_failures.append(name)
                    continue
                reference = (target / (name + ".TXT")).read_bytes()
                config = Config(
                    target_version=Version(1, 4, 0, 5),
                    include_debug_symbols=False,
                    kfn_directory_path=str(default_kfn_path()),
                    compress_output=True,
                    compiler_version=10002,
                )
                with self.subTest(name=name):
                    result = compile_source(
                        source_path.read_text("utf-8"), config, str(source_path)
                    )
                    self.assertEqual(result, reference)
        self.assertEqual(ocaml_failures, ["SEEN6430", "SEEN6801", "SEEN9802", "SEEN9820"])
