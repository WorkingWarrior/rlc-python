"""Symbols populated from KFN files."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .common import Location
from .errors import RLCError
from .kfn_data_structures import FunctionSignature, RLType


@dataclass
class VariableInfo:
    name: str
    type: RLType
    scope_level: int
    location: Location
    index: Optional[int] = None
    is_array: bool = False
    array_size: Optional[int] = None


class SymbolTable:
    """Scoped variables plus module and function definitions from KFN data."""

    def __init__(self, parent: Optional["SymbolTable"] = None) -> None:
        self.parent = parent
        self.labels: Dict[str, Location] = {}
        self.variables: Dict[Tuple[str, int], VariableInfo] = {}
        self.scope_stack: List[Dict[str, VariableInfo]] = [{}]
        self.current_scope_level = 0
        self._next_variable_index = 0
        self.functions: Dict[str, List[FunctionSignature]] = {}
        self.modules: Dict[int, str] = {}
        if parent is None:
            self._define_builtins()

    def _define_builtins(self) -> None:
        location = Location(file="<builtin>", line=0, column=0)
        for name in ("intF", "intA", "intG", "strS", "intZ"):
            self.declare_variable(
                name=name,
                var_type=RLType.ANY,
                location=location,
                is_array=True,
                array_size=4096,
            )

    def enter_scope(self) -> None:
        self.current_scope_level += 1
        self.scope_stack.append({})

    def exit_scope(self) -> None:
        if self.current_scope_level == 0:
            raise RLCError("Cannot exit the global scope.", Location(None, 0, 0))
        self.scope_stack.pop()
        self.current_scope_level -= 1

    def declare_variable(
        self,
        name: str,
        var_type: RLType,
        location: Location,
        is_array: bool = False,
        array_size: Optional[int] = None,
    ) -> VariableInfo:
        current_scope = self.scope_stack[-1]
        if name in current_scope:
            previous = current_scope[name].location
            raise RLCError(f"Variable '{name}' is already defined at {previous}.", location)

        variable = VariableInfo(
            name=name,
            type=var_type,
            scope_level=self.current_scope_level,
            location=location,
            index=self._next_variable_index,
            is_array=is_array,
            array_size=array_size,
        )
        self._next_variable_index += 1
        current_scope[name] = variable
        self.variables[(name, self.current_scope_level)] = variable
        return variable

    def lookup_variable(self, name: str) -> Optional[VariableInfo]:
        for scope_level in range(self.current_scope_level, -1, -1):
            variable = self.scope_stack[scope_level].get(name)
            if variable:
                return variable
        if self.parent:
            return self.parent.lookup_variable(name)
        return None

    def assign_variable_index(self, name: str, index: int, scope_level: int = -1) -> bool:
        if scope_level != -1:
            variable = self.scope_stack[scope_level].get(name)
        else:
            variable = self.lookup_variable(name)
        if variable is None:
            return False
        variable.index = index
        return True

    def add_label(self, name: str, location: Location) -> None:
        self.labels[name] = location

    def has_label(self, name: str) -> bool:
        return name in self.labels or bool(self.parent and self.parent.has_label(name))

    def get_label_location(self, name: str) -> Location | None:
        location = self.labels.get(name)
        if location:
            return location
        if self.parent:
            return self.parent.get_label_location(name)
        return None

    def define_module(
        self, module_id: int, module_name: str, location: Optional[Location] = None
    ) -> None:
        # OCaml Hashtbl.add permits duplicate numeric IDs and resolves the most
        # recent binding. Historical KFN databases rely on that behaviour.
        self.modules[module_id] = module_name

    def lookup_module_name(self, module_id: int) -> Optional[str]:
        name = self.modules.get(module_id)
        if name:
            return name
        if self.parent:
            return self.parent.lookup_module_name(module_id)
        return None

    def define_function(self, signature: FunctionSignature) -> None:
        # OCaml Hashtbl.add preserves same-name definitions used for overload
        # and target/type dispatch.
        self.functions.setdefault(signature.name, []).append(signature)

    def lookup_function(self, name: str) -> List[FunctionSignature]:
        if name in self.functions:
            return self.functions[name]
        if self.parent:
            return self.parent.lookup_function(name)
        raise KeyError(f"Function '{name}' is not defined.")

    def lookup_control_code(self, name: str) -> List[FunctionSignature]:
        matches = [
            signature
            for signatures in self.functions.values()
            for signature in signatures
            if signature.kfn_ccode_name == name
        ]
        if matches:
            return matches
        if self.parent:
            return self.parent.lookup_control_code(name)
        raise KeyError(f"Text control code '{name}' is not defined.")

    def add_function(self, signature: FunctionSignature) -> None:
        self.define_function(signature)

    def get_function(self, name: str, arg_count: int) -> Optional[FunctionSignature]:
        try:
            return next(
                (
                    signature
                    for signature in self.lookup_function(name)
                    if signature.arg_count == arg_count
                ),
                None,
            )
        except KeyError:
            return None

    def get_all_functions(self) -> Dict[str, List[FunctionSignature]]:
        all_functions = self.parent.get_all_functions() if self.parent else {}
        all_functions = {name: list(signatures) for name, signatures in all_functions.items()}
        for name, signatures in self.functions.items():
            all_functions.setdefault(name, []).extend(signatures)
        return all_functions
