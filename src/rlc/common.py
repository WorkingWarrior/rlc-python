"""Shared source-location type."""

from dataclasses import dataclass


@dataclass
class Location:
    file: str | None
    line: int
    column: int

    def __str__(self) -> str:
        if self.file:
            return f"{self.file}:{self.line}:{self.column}"
        return f":{self.line}:{self.column}"
