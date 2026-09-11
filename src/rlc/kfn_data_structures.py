"""Data structures produced by the KFN parser."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, List, Optional, Tuple, Union


@dataclass(frozen=True)
class Location:
    file: str
    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}"


class RLType(Enum):
    ANY = auto()
    INT = auto()
    INT_C = auto()
    INT_V = auto()
    STR = auto()
    STR_C = auto()
    STR_V = auto()
    RES = auto()
    SPECIAL = auto()
    COMPLEX = auto()
    VOID = auto()


@dataclass
class SpecialParameterDef:
    id: Union[int, Tuple[int, int]]
    flags: List[str] = field(default_factory=list)
    name: Optional[str] = None
    parameters: List["ParameterInfo"] = field(default_factory=list)


@dataclass
class ParameterInfo:
    name: Optional[str] = None
    type: RLType = RLType.ANY
    tag: Optional[str] = None
    is_optional: bool = False
    is_return_value: bool = False
    is_uncounted: bool = False
    is_fake: bool = False
    is_text_object: bool = False
    text_object_name: Optional[str] = None
    is_repeated: bool = False
    repeated_count_name: Optional[str] = None
    complex_params: List["ParameterInfo"] = field(default_factory=list)
    special_params: List[SpecialParameterDef] = field(default_factory=list)


@dataclass
class FunctionSignature:
    """A function definition selected from a KFN database."""

    name: str
    alias: Optional[str] = None
    id: Optional[int] = None
    module_id: Optional[int] = None
    module_name: Optional[str] = None
    parameters: List[ParameterInfo] = field(default_factory=list)
    prototypes: List[Optional[List[ParameterInfo]]] = field(default_factory=list)
    opcode_type: int = 0
    overload_count: int = 0
    return_type: RLType = RLType.VOID
    is_intrinsic: bool = False
    kfn_flags: List[str] = field(default_factory=list)
    kfn_ccode_name: Optional[str] = None
    kfn_ccode_flags: List[str] = field(default_factory=list)
    handler: Any = None
    location: Optional[Location] = None
    versions: List[str] = field(default_factory=list)
    documentation: Optional[str] = None
    is_overload_stub: bool = False
    raw_kfn_definition: Optional[str] = None
    kfn_opcode_raw: Optional[str] = None

    @property
    def arg_count(self) -> int:
        return len(
            [
                parameter
                for parameter in self.parameters
                if not parameter.is_return_value
                and not parameter.is_uncounted
                and not parameter.is_fake
            ]
        )

    @property
    def min_args(self) -> int:
        return sum(
            1
            for parameter in self.parameters
            if not parameter.is_return_value
            and not parameter.is_uncounted
            and not parameter.is_fake
            and not parameter.is_optional
        )

    @property
    def max_args(self) -> int:
        visible = [
            parameter
            for parameter in self.parameters
            if not parameter.is_return_value
            and not parameter.is_uncounted
            and not parameter.is_fake
        ]
        if any(parameter.is_repeated for parameter in visible):
            return float("inf")  # type: ignore[return-value]
        return len(visible)

    def __str__(self) -> str:
        param_strs = []
        for parameter in self.parameters:
            rendered = ""
            if parameter.is_return_value:
                rendered += ">"
            if parameter.is_uncounted:
                rendered += "<"
            if parameter.is_fake:
                rendered += "="
            if parameter.is_text_object:
                rendered += "#"
            if parameter.text_object_name:
                rendered += parameter.text_object_name
            rendered += parameter.type.name
            if parameter.tag:
                rendered += f" '{parameter.tag}'"
            if parameter.name:
                rendered += f" {parameter.name}"
            if parameter.is_optional:
                rendered += "?"
            if parameter.is_repeated:
                rendered += "+"
                if parameter.repeated_count_name:
                    rendered += parameter.repeated_count_name
            param_strs.append(rendered)

        return_type = f" -> {self.return_type.name}" if self.return_type != RLType.VOID else ""
        location = f" @ {self.location}" if self.location else ""
        intrinsic = " (intrinsic)" if self.is_intrinsic else ""
        kfn_id = ""
        if self.module_id is not None and self.id is not None:
            module = self.module_name if self.module_name else f"ModID({self.module_id})"
            kfn_id = f" (kfn: {module}:{self.id:03X})"
        elif self.id is not None:
            kfn_id = f" (kfn: ID {self.id:03X})"
        versions = f" versions: [{', '.join(self.versions)}]" if self.versions else ""
        flags = f" flags: [{', '.join(self.kfn_flags)}]" if self.kfn_flags else ""
        ccode = f" ccode: {self.kfn_ccode_name}" if self.kfn_ccode_name else ""
        return (
            f"{self.name}({', '.join(param_strs)}){return_type}{intrinsic}{kfn_id}"
            f"{location}{versions}{flags}{ccode}"
        )
