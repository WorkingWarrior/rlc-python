"""RLC command-line entry point."""

import argparse
import logging
import os

from .compiler import Compiler
from .config import Config, TargetPlatform
from .lexer import Lexer
from .parser import Parser
from .runtime import default_kfn_path
from .versioning import parse_version_string


def compile_source(source: str, config: Config, filename="<string>") -> bytes:
    return Compiler(config).compile(
        Parser(Lexer(source, filename).tokens(), config.symbol_table).parse()
    )


def compile_file(filepath: str, config: Config):
    with open(filepath, "rb") as source_file:
        raw = source_file.read()
    try:
        source = raw.decode(config.input_encoding)
    except UnicodeDecodeError:
        source = raw.decode("utf-8")
    return compile_source(source, config, filepath)


def main(argv=None):
    p = argparse.ArgumentParser(prog="rlc", description="RealLive-compatible compiler")
    p.add_argument("filepath")
    p.add_argument("-o", "--output")
    p.add_argument("-d", "--outdir", default="")
    p.add_argument("-e", "--encoding", default="CP932")
    p.add_argument("-f", "--target-version", default="1.2.7.0")
    p.add_argument("-t", "--target", choices=["RealLive", "Kinetic", "AVG2000"], default="RealLive")
    p.add_argument("--kfn", default=str(default_kfn_path()))
    p.add_argument("-i", "--ini", dest="gameexe")
    p.add_argument("-g", "--no-debug", action="store_true")
    p.add_argument("-u", "--uncompressed", action="store_true")
    p.add_argument(
        "--no-metadata", action="store_true", help="accepted; metadata is not emitted yet"
    )
    p.add_argument("-c", "--compiler", type=int, default=10002)
    p.add_argument("-v", "--verbose", action="count", default=0)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO)
    platform = {
        "RealLive": TargetPlatform.GENERIC_REALLIVE,
        "Kinetic": TargetPlatform.KINETIC,
        "AVG2000": TargetPlatform.AVG2000,
    }[a.target]
    c = Config(
        target_platform=platform,
        target_version=parse_version_string(a.target_version),
        input_encoding=a.encoding,
        output_encoding="cp932",
        include_debug_symbols=not a.no_debug,
        kfn_directory_path=a.kfn,
        verbose=bool(a.verbose),
        compress_output=not a.uncompressed,
        compiler_version=a.compiler,
        gameexe_path=a.gameexe,
    )
    data = compile_file(a.filepath, c)
    base = os.path.splitext(a.output or os.path.basename(a.filepath))[0]
    dest = os.path.join(a.outdir, base + (".TXT.rl" if a.uncompressed else ".TXT"))
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as output_file:
        output_file.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
