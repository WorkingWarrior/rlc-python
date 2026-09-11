"""AST closely mirroring the variants in ``keAst.ml``."""

from dataclasses import dataclass, field
from typing import Any, Optional

from .common import Location


@dataclass
class Expr:
    kind: str
    value: Any = None
    args: list["Expr"] = field(default_factory=list)
    location: Optional[Location] = None


@dataclass
class Statement:
    kind: str
    value: Any = None
    args: list[Any] = field(default_factory=list)
    location: Optional[Location] = None


@dataclass
class Program:
    statements: list[Statement]
