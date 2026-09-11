"""Load RealLive function definitions from KFN files."""

import os

from .kfn_lexer import KfnLexer, KfnLexerError
from .kfn_parser import KfnParser, KfnParserError
from .symbol_table import SymbolTable
from .versioning import Version


def load_intrinsics(
    st: SymbolTable,
    kfn_directory: str,
    target_version: Version,
    verbose: bool = False,
    target_class: str = "reallive",
) -> None:
    """Load the selected KFN file into a symbol table."""
    if verbose:
        print(f"Loading function definitions from {kfn_directory} for {target_version}...")

    initial_function_count = len(st.get_all_functions())

    if os.path.isfile(kfn_directory):
        base_dir = os.path.dirname(kfn_directory) or "."
        filenames = [os.path.basename(kfn_directory)]
    elif not os.path.isdir(kfn_directory):
        print(f"Warning: KFN path does not exist: {kfn_directory}")
        return
    else:
        base_dir = kfn_directory
        # RLC accepts one --kfn file. When given an installed library directory,
        # select its default instead of merging incompatible databases.
        filenames = (
            ["reallive.kfn"]
            if os.path.isfile(os.path.join(base_dir, "reallive.kfn"))
            else sorted(os.listdir(base_dir))
        )

    for filename in filenames:
        if not filename.endswith(".kfn"):
            continue
        file_path = os.path.join(base_dir, filename)
        if verbose:
            print(f"  Parsing {file_path}")
        try:
            with open(file_path, encoding="cp932") as stream:
                content = stream.read()
            KfnParser(
                KfnLexer(content, file_path=file_path), st, target_version, target_class
            ).parse()
        except FileNotFoundError:
            print(f"  Error: KFN file not found: {file_path}")
        except (KfnLexerError, KfnParserError):
            # OCaml aborts on malformed KFN. Continuing could silently select
            # a missing or incorrect opcode definition.
            raise

    loaded_count = len(st.get_all_functions()) - initial_function_count
    if verbose:
        print(f"Loaded {loaded_count} function names ({len(st.get_all_functions())} total).")
