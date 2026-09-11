"""Version parsing and KFN target filtering."""

import operator
import re
from dataclasses import dataclass
from functools import total_ordering
from typing import Callable, Optional, Tuple

from .kfn_data_structures import FunctionSignature


@total_ordering
@dataclass(frozen=True)
class Version:
    """A four-component RealLive interpreter version."""

    major: int = 0
    minor: int = 0
    patch: int = 0
    build: int = 0

    def __post_init__(self):
        if not all(value >= 0 for value in self.to_tuple()):
            raise ValueError("Version components cannot be negative.")

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.major, self.minor, self.patch, self.build)

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self.to_tuple() < other.to_tuple()

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self.to_tuple() == other.to_tuple()

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}.{self.build}"


def parse_version_string(version_str: str) -> Version:
    """Parse one to four dot-separated integer components."""
    parts = list(map(int, version_str.split(".")))
    while len(parts) < 4:
        parts.append(0)
    if len(parts) > 4:
        raise ValueError(f"Invalid version: {version_str}")
    return Version(major=parts[0], minor=parts[1], patch=parts[2], build=parts[3])


@dataclass(frozen=True)
class VersionCondition:
    operator: Callable[[Version, Version], bool]
    version: Version
    condition_str: str

    def check(self, target_version: Version) -> bool:
        return self.operator(target_version, self.version)

    def __str__(self) -> str:
        return self.condition_str


OPERATOR_MAP = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "=": operator.eq,
    "==": operator.eq,
}

VERSION_CONDITION_RE = re.compile(r"([<>=]=?)\s*([\d\.]+)$")


def parse_condition_string(condition_str: str) -> Optional[VersionCondition]:
    """Parse a comparison, or return None for a target-class constraint."""
    match = VERSION_CONDITION_RE.match(condition_str)
    if not match:
        if not condition_str.replace(".", "").isalnum():
            raise ValueError(f"Invalid version condition: {condition_str}")
        return None

    op_str, version_str = match.groups()
    if op_str not in OPERATOR_MAP:
        raise ValueError(f"Unknown version operator: {op_str}")
    return VersionCondition(
        operator=OPERATOR_MAP[op_str],
        version=parse_version_string(version_str),
        condition_str=condition_str,
    )


def is_version_compatible(
    signature: FunctionSignature, target_version: Version, target_class: str = "reallive"
) -> bool:
    """Check all version comparisons and alternative target-class constraints."""
    if not signature.versions:
        return True

    class_constraints = []
    for condition_string in signature.versions:
        condition = parse_condition_string(condition_string)
        if condition and not condition.check(target_version):
            return False
        if condition is None:
            class_constraints.append(condition_string.lower())
    return not class_constraints or target_class.lower() in class_constraints
