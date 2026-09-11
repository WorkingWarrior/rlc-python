"""Compiler configuration."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from .intrinsics_loader import load_intrinsics
from .symbol_table import SymbolTable
from .versioning import Version


class TargetPlatform(Enum):
    """Compilation target understood by the original RLC."""

    GENERIC_REALLIVE = auto()
    AVG2000 = auto()
    KINETIC = auto()
    CLANNAD = auto()
    LITTLE_BUSTERS = auto()
    TOMOYO_AFTER = auto()


@dataclass
class Config:
    """Configuration for one compiler invocation."""

    target_platform: TargetPlatform = TargetPlatform.GENERIC_REALLIVE
    target_version: Version = field(default_factory=lambda: Version(1, 4, 0, 1))
    input_encoding: str = "cp932"
    output_encoding: str = "cp932"
    include_debug_symbols: bool = True
    symbol_table: SymbolTable = field(init=False)
    kfn_directory_path: Optional[str] = None
    verbose: bool = False
    compress_output: bool = False
    compiler_version: int = 10002
    gameexe_path: Optional[str] = None
    gameexe_values: dict = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        """Load GAMEEXE values and opcode definitions selected by this config."""
        self.symbol_table = SymbolTable()
        if self.gameexe_path:
            from .gameexe import load_gameexe

            self.gameexe_values = load_gameexe(self.gameexe_path)

        if self.kfn_directory_path:
            load_intrinsics(
                st=self.symbol_table,
                kfn_directory=self.kfn_directory_path,
                target_version=self.target_version,
                verbose=self.verbose,
                target_class=(
                    "avg2000"
                    if self.target_platform is TargetPlatform.AVG2000
                    else "kinetic"
                    if self.target_platform is TargetPlatform.KINETIC
                    else "reallive"
                ),
            )
        elif self.verbose:
            print("Warning: no KFN path was supplied; engine functions are unavailable.")
