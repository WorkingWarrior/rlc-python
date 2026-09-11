"""Kepago semantic lowering to the RealLive encoder."""

import copy
import operator
import os

from .config import TargetPlatform
from .errors import RLCError
from .kepago_ast import Expr
from .kfn_data_structures import RLType
from .real_bytecode import (
    Entrypoint,
    Kidoku,
    Label,
    LabelRef,
    LineRef,
    Literal,
    Special,
    assignment,
    binary,
    build_avg2000,
    build_uncompressed,
    choose_overload,
    function,
    int32,
    opcode,
    parameters,
    variable,
)
from .string_lexer import StringLiteral

_BIN = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": lambda a, b: int(a / b),
    "%": operator.mod,
    "&": operator.and_,
    "|": operator.or_,
    "^": operator.xor,
    "<<": operator.lshift,
    ">>": operator.rshift,
    "==": lambda a, b: int(a == b),
    "!=": lambda a, b: int(a != b),
    "<": lambda a, b: int(a < b),
    "<=": lambda a, b: int(a <= b),
    ">": lambda a, b: int(a > b),
    ">=": lambda a, b: int(a >= b),
    "&&": lambda a, b: int(bool(a) and bool(b)),
    "||": lambda a, b: int(bool(a) or bool(b)),
}


class Compiler:
    def __init__(self, config):
        self.config = config
        self.constants = {}
        self.variables = {}
        self.array_lengths = {}
        self.inlines = {}
        self.resources = {}
        self.elements = []
        self.auto = 0
        self.return_value = None
        self.next_int = 0
        self.next_str = 1900
        self.val_0x2c = 0
        self.break_stack = []
        self.continue_stack = []

    def error(self, e, msg):
        raise RLCError(msg, e.location)

    def _const_string(self, literal):
        """Equivalent of StrTokens.to_string for compile-time strings."""
        out = []
        simple = {
            "dquote": '"',
            "llentic": "\u3010",
            "rlentic": "\u3011",
            "asterisk": "\uff0a",
            "percent": "\uff05",
            "hyphen": "-",
            "rcur": "}",
        }
        for token in literal.tokens:
            if token.kind == "text":
                out.append(str(token.value))
            elif token.kind == "space":
                out.append(" " * int(token.value))
            elif token.kind in simple:
                out.append(simple[token.kind])
            elif token.kind == "code":
                code, width, args = token.value
                if code not in ("i", "s") or len(args) != 1:
                    raise ValueError
                value = self.const(args[0])
                if code == "i":
                    if not isinstance(value, int):
                        raise ValueError
                    rendered = str(value)
                    if width is not None:
                        field = self.const(width)
                        if not isinstance(field, int):
                            raise ValueError
                        rendered = "0" * max(0, field - len(rendered)) + rendered
                    out.append(rendered)
                else:
                    if not isinstance(value, str):
                        raise ValueError
                    out.append(value)
            else:
                raise ValueError
        return "".join(out)

    def const(self, e):
        if e.kind == "int":
            return e.value
        if e.kind == "str":
            if isinstance(e.value, StringLiteral):
                return self._const_string(e.value)
            return e.value
        if e.kind == "res":
            if e.value not in self.resources:
                self.error(e, f"unable to find resource string <{e.value}>")
            return self._const_string(self.resources[e.value])
        if e.kind == "ident" and e.value in self.constants:
            value = self.constants[e.value]
            if isinstance(value, Expr):
                return self.const(value)
            return value
        if e.kind == "unary":
            v = self.const(e.args[0])
            return {"-": lambda: -v, "!": lambda: int(not v), "~": lambda: ~v}[e.value]()
        if e.kind == "bin" and e.value in _BIN:
            return _BIN[e.value](self.const(e.args[0]), self.const(e.args[1]))
        if e.kind == "call":
            name = e.value
            if name == "defined?":
                if not all(x.kind == "ident" for x in e.args):
                    self.error(e, "the `defined?' intrinsic must be passed only simple identifiers")
                return int(
                    all(x.value in self.constants or x.value in self.variables for x in e.args)
                )
            if name == "default":
                if len(e.args) != 2 or e.args[0].kind != "ident":
                    self.error(
                        e, "the `default' intrinsic must be passed a symbol and an expression"
                    )
                return self.const(
                    e.args[0]
                    if e.args[0].value in self.constants or e.args[0].value in self.variables
                    else e.args[1]
                )
            if name in ("constant?", "integer?"):
                try:
                    vals = [self.const(x) for x in e.args]
                    return int(all(isinstance(x, int) for x in vals)) if name == "integer?" else 1
                except (ValueError, KeyError, RLCError):
                    return 0
            if name == "array?":
                if not all(x.kind == "ident" for x in e.args):
                    self.error(e, "the `array?' intrinsic must be passed only simple identifiers")
                return int(all(self.array_lengths.get(x.value) is not None for x in e.args))
            if name == "length":
                if len(e.args) != 1 or e.args[0].kind != "ident":
                    self.error(e, "the `length' function must be passed a single array variable")
                length = self.array_lengths.get(e.args[0].value)
                if length is None:
                    self.error(e, f"`{e.args[0].value}' is not an array")
                return length
            if name == "__variable?":
                return int(
                    len(e.args) == 1
                    and e.args[0].kind in ("ident", "index")
                    and e.args[0].value in self.variables
                )
            if name in ("__empty_string?", "__equal_strings?"):
                wanted = 1 if name == "__empty_string?" else 2
                if len(e.args) != wanted:
                    self.error(
                        e,
                        f"the `{name}' intrinsic must be passed {'a single' if wanted == 1 else 'two'} string constant{'s' if wanted == 2 else ''}",
                    )
                try:
                    values = [self.const(x) for x in e.args]
                except ValueError:
                    self.error(e, f"the `{name}' intrinsic must be passed string constants")
                if not all(isinstance(x, str) for x in values):
                    self.error(e, f"the `{name}' intrinsic must be passed string constants")
                return int(values[0] == ("" if wanted == 1 else values[1]))
            if name == "gameexe":
                if not 1 <= len(e.args) <= 3:
                    self.error(e, "the `gameexe' intrinsic takes between one and three parameters")
                key = self.const(e.args[0])
                idx = self.const(e.args[1]) if len(e.args) > 1 else 0
                if not isinstance(key, str) or not key:
                    self.error(
                        e,
                        "the key passed to `gameexe' must evaluate to a non-empty string constant",
                    )
                if not isinstance(idx, int):
                    self.error(
                        e, "the index passed to `gameexe' must evaluate to an integer constant"
                    )
                key = key[1:] if key.startswith("#") else key
                values = self.config.gameexe_values.get(key.lower())
                if values is not None:
                    if idx < 0 or idx >= len(values):
                        self.error(
                            e, f"unable to return value {idx} from #{key}: index out of range"
                        )
                    value = values[idx]
                    if isinstance(value, bool):
                        return int(value)
                    if isinstance(value, (int, str)):
                        return value
                    self.error(e, f"unable to return non-scalar value {idx} from #{key}")
                # OCaml returns the third argument unchanged when a key is absent.
                if len(e.args) == 3:
                    return self.const(e.args[2])
                self.error(e, f"unable to find #{key} in GAMEEXE.INI, and no default was provided")
            if name in ("target_lt", "target_le", "target_gt", "target_ge"):
                if not 1 <= len(e.args) <= 4:
                    self.error(e, f"`{name}' must be passed between 1 and 4 parameters")
                try:
                    requested = tuple(self.const(x) for x in e.args)
                except ValueError:
                    self.error(e, f"the parameters to `{name}' must evaluate to integer constants")
                if not all(isinstance(x, int) for x in requested):
                    self.error(e, f"the parameters to `{name}' must evaluate to integer constants")
                requested = requested + (0,) * (4 - len(requested))
                current = self.config.target_version.to_tuple()
                return int(
                    {
                        "target_lt": operator.lt,
                        "target_le": operator.le,
                        "target_gt": operator.gt,
                        "target_ge": operator.ge,
                    }[name](current, requested)
                )
            if name == "kinetic?":
                if e.args:
                    self.error(e, "`kinetic?' takes no parameters")
                return int(self.config.target_platform is TargetPlatform.KINETIC)
            if name == "at":
                if len(e.args) != 3:
                    self.error(
                        e, "the `at' intrinsic function must be passed a location and an expression"
                    )
                self.const(e.args[0])
                self.const(e.args[1])
                return self.const(e.args[2])
            if name == "rlc_parse_string":
                if len(e.args) != 1:
                    self.error(
                        e,
                        "the `rlc_parse_string' intrinsic must be passed a single string constant",
                    )
                source = self.const(e.args[0])
                if not isinstance(source, str):
                    self.error(
                        e,
                        "the string passed to `rlc_parse_string' must be evaluable at compile-time",
                    )
                from .lexer import Lexer
                from .parser import Parser

                parser = Parser(
                    Lexer(
                        source,
                        e.location.file if e.location else None,
                        start_line=e.location.line if e.location else 1,
                    ).tokens()
                )
                value = parser.expr()
                if parser.t.type != "EOF":
                    self.error(e, "rlc_parse_string did not contain a single expression")
                return self.const(value)
            if name in self.inlines:
                params, body = self.inlines.pop(name)
                supplied = list(e.args)
                old_constants = dict(self.constants)
                old_return = self.return_value
                mark = len(self.elements)
                self.return_value = None
                try:
                    self.constants["__INLINE_CALL__"] = 1
                    self.constants["__CALLER_FILE__"] = (
                        e.location.file if e.location and e.location.file else ""
                    )
                    self.constants["__CALLER_LINE__"] = e.location.line if e.location else 0
                    for param, optional, default_value in params:
                        if supplied:
                            actual = supplied.pop(0)
                        elif default_value is not None:
                            actual = default_value
                        elif optional:
                            continue
                        else:
                            raise ValueError
                        try:
                            self.constants[param] = self.const(actual)
                        except ValueError:
                            self.constants[param] = actual
                    if supplied:
                        raise ValueError
                    self.statement(copy.deepcopy(body))
                    if self.return_value is None:
                        raise ValueError
                    return self.const(self.return_value)
                finally:
                    self.constants = old_constants
                    self.return_value = old_return
                    del self.elements[mark:]
                    self.inlines[name] = (params, body)
        raise ValueError

    def expr(self, e):
        # Inline calls may contain arbitrary runtime statements.  They are
        # evaluated speculatively only from explicit constant contexts
        # (#if/#const); doing so here recurses through wrappers such as the
        # textout `pause' inline before its hiding node can select the KFN.
        if not (e.kind == "call" and e.value in self.inlines):
            try:
                v = self.const(e)
                return Literal(v) if isinstance(v, str) else int32(v)
            except (ValueError, KeyError):
                pass
        if e.kind == "res":
            if e.value not in self.resources:
                self.error(e, f"unable to find resource string <{e.value}>")
            return Literal(self._const_string(self.resources[e.value]))
        if e.kind in ("ident", "index"):
            name = e.value
            if name in self.constants and isinstance(self.constants[name], Expr):
                return self.expr(self.constants[name])
            if name == "store":
                return b"$\xc8"
            if name in self.variables:
                space, base = self.variables[name]
                idx = (
                    int32(base)
                    if e.kind == "ident"
                    else binary(int32(base), "+", self.expr(e.args[0]))
                )
                if e.kind == "index":
                    try:
                        idx = int32(base + self.const(e.args[0]))
                    except ValueError:
                        idx = binary(int32(base), "+", self.expr(e.args[0]))
                return variable(space, idx)
            # Built-in arrays from keULexer.ml.
            spaces = {
                "intA": 0,
                "intB": 1,
                "intC": 2,
                "intD": 3,
                "intE": 4,
                "intF": 5,
                "intG": 6,
                "strK": 10,
                "intL": 11,
                "strM": 12,
                "strS": 18,
                "intZ": 25,
            }
            for suffix, offset in (("b", 26), ("2b", 52), ("4b", 78), ("8b", 104)):
                for index, letter in enumerate("ABCDEFG"):
                    spaces[f"int{letter}{suffix}"] = offset + index
                spaces[f"intZ{suffix}"] = offset + 25
            if name in spaces and e.kind == "index":
                return variable(spaces[name], self.expr(e.args[0]))
            if e.kind == "ident":
                try:
                    sigs = self.config.symbol_table.lookup_function(name)
                    compiled = self._compile_call(Expr("call", name, location=e.location))
                    if any("store" in sig.kfn_flags for sig in sigs):
                        self.elements.append(compiled)
                        return b"$\xc8"
                    return compiled
                except KeyError:
                    pass
            self.error(e, f"undeclared identifier `{name}'")
        if e.kind == "bin":
            op = e.value
            try:
                left_const = self.const(e.args[0])
            except ValueError:
                left_const = None
            try:
                right_const = self.const(e.args[1])
            except ValueError:
                right_const = None
            if op in ("/", "%") and right_const == 0:
                self.error(e, "division by zero")
            if (
                (op == "&" and right_const == -1)
                or (op in ("|", "^", "+", "-") and right_const == 0)
                or (op in ("*", "/") and right_const == 1)
            ):
                return self.expr(e.args[0])
            if (
                (op == "&" and left_const == -1)
                or (op in ("|", "^", "+") and left_const == 0)
                or (op == "*" and left_const == 1)
            ):
                return self.expr(e.args[1])
            if (op in ("&", "*") and (left_const == 0 or right_const == 0)) or (
                op in ("/", "%") and left_const == 0
            ):
                return int32(0)
            if self._same_expr(e.args[0], e.args[1]):
                if op in ("&", "|"):
                    return self.expr(e.args[0])
                if op in ("-", "^", "%"):
                    return int32(0)
                if op == "/":
                    return int32(1)
            if op in ("&&", "||"):
                # Each arm of AndOr is passed through conditional_unit;
                # therefore bare integer expressions become ``expr != 0``.
                left = self._condition(e.args[0])
                right = self._condition(e.args[1])
            else:
                left = self.expr(e.args[0])
                right = self.expr(e.args[1])
            # Kepago and RealLive bytecode do not share arithmetic operator
            # precedence.  Expr.traverse inserts parentheses using ``prec``
            # from expr.ml (add/sub=10, every other arithmetic op=20).
            arithmetic = {"+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"}

            def bytecode_precedence(operator):
                return 10 if operator in ("+", "-") else 20

            if op in arithmetic:
                if (
                    e.args[0].kind == "bin"
                    and e.args[0].value in arithmetic
                    and bytecode_precedence(e.args[0].value) < bytecode_precedence(op)
                ):
                    left = b"(" + left + b")"
                if (
                    e.args[1].kind == "bin"
                    and e.args[1].value in arithmetic
                    and bytecode_precedence(e.args[1].value) <= bytecode_precedence(op)
                ):
                    right = b"(" + right + b")"
            # RealLive gives && and || equal precedence.  Expr.transform adds
            # these parentheses when lowering Kepago's distinct precedences.
            if e.value == "||" and e.args[0].kind == "bin" and e.args[0].value == "&&":
                left = b"(" + left + b")"
            if e.value == "||" and e.args[1].kind == "bin" and e.args[1].value in ("&&", "||"):
                right = b"(" + right + b")"
            return binary(left, op, right)
        if e.kind == "unary":
            if e.value == "-":
                return b"\\\x01" + self.expr(e.args[0])
            if e.value == "!":
                return binary(self.expr(e.args[0]), "==", int32(0))
            if e.value == "~":
                return binary(self.expr(e.args[0]), "^", int32(-1))
        if e.kind == "call":
            if e.value == "at":
                if len(e.args) != 3:
                    self.error(
                        e, "the `at' intrinsic function must be passed a location and an expression"
                    )
                return self.expr(e.args[2])
            if e.value == "rlc_parse_string":
                if len(e.args) != 1:
                    self.error(
                        e,
                        "the `rlc_parse_string' intrinsic must be passed a single string constant",
                    )
                try:
                    source = self.const(e.args[0])
                except ValueError:
                    self.error(
                        e,
                        "the string passed to `rlc_parse_string' must be evaluable at compile-time",
                    )
                from .lexer import Lexer
                from .parser import Parser

                parser = Parser(
                    Lexer(
                        source,
                        e.location.file if e.location else None,
                        start_line=e.location.line if e.location else 1,
                    ).tokens()
                )
                value = parser.expr()
                if parser.t.type != "EOF":
                    self.error(e, "rlc_parse_string did not contain a single expression")
                return self.expr(value)
            if e.value in ("__deref", "__sderef"):
                if len(e.args) != 2:
                    self.error(
                        e,
                        f"the `{e.value}' intrinsic must be passed an integer constant and an expression",
                    )
                try:
                    space = self.const(e.args[0])
                except ValueError:
                    self.error(
                        e,
                        f"the `{e.value}' intrinsic must be passed an integer constant and an expression",
                    )
                if not isinstance(space, int):
                    self.error(
                        e,
                        f"the `{e.value}' intrinsic must be passed an integer constant and an expression",
                    )
                return variable(space, self.expr(e.args[1]))
            if e.value == "__addr":
                if len(e.args) != 1:
                    self.error(e, "the `__addr' intrinsic must be passed a single variable")
                arg = e.args[0]
                if arg.kind not in ("ident", "index") or arg.value not in self.variables:
                    self.error(e, "the `__addr' intrinsic must be passed a single variable")
                space, base = self.variables[arg.value]
                index = (
                    int32(base)
                    if arg.kind == "ident"
                    else binary(int32(base), "+", self.expr(arg.args[0]))
                )
                try:
                    if arg.kind == "index":
                        index = int32(base + self.const(arg.args[0]))
                except ValueError:
                    pass
                return binary(index, "|", binary(int32(space), "<<", int32(16)))
            if e.value in self.inlines:
                inline_name = e.value
                params, body = self.inlines.pop(inline_name)
                supplied = list(e.args)
                old = dict(self.constants)
                oldret = self.return_value
                self.return_value = None
                self.constants["__INLINE_CALL__"] = 1
                self.constants["__CALLER_FILE__"] = (
                    e.location.file if e.location and e.location.file else ""
                )
                self.constants["__CALLER_LINE__"] = e.location.line if e.location else 0
                for name, optional, default in params:
                    if supplied:
                        actual = supplied.pop(0)
                    elif default is not None:
                        actual = default
                    elif optional:
                        continue
                    else:
                        self.error(e, f"not enough parameters to inline `{e.value}'")
                    try:
                        self.constants[name] = self.const(actual)
                    except ValueError:
                        self.constants[name] = actual
                if supplied:
                    self.error(e, f"too many parameters to inline `{e.value}'")
                try:
                    self.statement(copy.deepcopy(body))
                    # Resolve the returned expression while the inline's
                    # scoped macros are still visible.  rlapi.kh commonly
                    # returns a local #sdefine such as __retval.
                    result = b"" if self.return_value is None else self.expr(self.return_value)
                finally:
                    self.constants = old
                    self.return_value = oldret
                    self.inlines[inline_name] = (params, body)
                return result
            compiled = self._compile_call(e)
            sigs = self.config.symbol_table.lookup_function(e.value)
            if any("store" in sig.kfn_flags for sig in sigs):
                self.elements.append(compiled)
                return b"$\xc8"
            return compiled
        if e.kind == "unknown_call":
            op_type, module, code, overload = e.value
            if isinstance(module, str):
                module = next(
                    (
                        ident
                        for ident, name in self.config.symbol_table.modules.items()
                        if name == module
                    ),
                    None,
                )
                if module is None:
                    self.error(e, f"undefined module `{e.value[1]}'")
            values = [self.expr(value) for value in e.args]
            return opcode(op_type, module, code, len(values), overload) + (
                b"(" + parameters(values) + b")" if values else b""
            )
        if e.kind == "complex":
            return tuple(self.expr(x) for x in e.args)
        self.error(e, "expression cannot be lowered to RealLive bytecode")

    def _expr_type(self, e):
        if e.kind in ("str", "res"):
            return "literal"
        if e.kind in ("int", "bin", "unary"):
            return "int_expr"
        if e.kind in ("ident", "index"):
            if e.kind == "ident" and e.value in self.constants:
                value = self.constants[e.value]
                if isinstance(value, Expr):
                    return self._expr_type(value)
                return "literal" if isinstance(value, str) else "int_expr"
            if e.value in self.variables:
                return "str_var" if self.variables[e.value][0] in (10, 12, 18) else "int_var"
            if e.value.startswith("str"):
                return "str_var"
            return "int_var"
        if e.kind == "complex":
            return "complex"
        if e.kind == "call":
            return "call"
        return "invalid"

    def _lower_parameter(self, e, p, funcname):
        actual = self._expr_type(e)
        typ = p.type
        if typ is RLType.SPECIAL:
            named = e.value if e.kind == "call" else None
            values = e.args if e.kind in ("call", "complex") else [e]
            choices = [
                d
                for d in p.special_params
                if (
                    (named and d.name == named)
                    or (not named and d.name is None and len(d.parameters) == len(values))
                )
            ]
            for choice in choices:
                encoded_defs = [
                    d for d in choice.parameters if not d.is_fake and not d.is_return_value
                ]
                minimum = sum(1 for d in encoded_defs if not d.is_optional and not d.is_repeated)
                maximum = None if any(d.is_repeated for d in encoded_defs) else len(encoded_defs)
                if len(values) < minimum or (maximum is not None and len(values) > maximum):
                    continue
                try:
                    lowered = []
                    for index, value in enumerate(values):
                        definition = encoded_defs[min(index, len(encoded_defs) - 1)]
                        lowered.append(self._lower_parameter(value, definition, funcname))
                    return Special(int(choice.id), tuple(lowered), "no_parens" in choice.flags)
                except ValueError:
                    pass
            raise ValueError(f"invalid special parameter to `{funcname}'")
        if typ is RLType.COMPLEX:
            if e.kind != "complex":
                raise ValueError(f"expected tuple in call to `{funcname}'")
            if len(e.args) != len(p.complex_params):
                raise ValueError(f"tuple has wrong length in call to `{funcname}'")
            return tuple(
                self._lower_parameter(v, d, funcname) for v, d in zip(e.args, p.complex_params)
            )
        if typ in (RLType.INT, RLType.INT_V) and actual != "int_var":
            raise ValueError(f"expected integer variable in call to `{funcname}'")
        if typ is RLType.INT_C and actual not in ("int_var", "int_expr"):
            raise ValueError(f"expected integer in call to `{funcname}'")
        if typ is RLType.STR and actual != "str_var":
            raise ValueError(f"expected string variable in call to `{funcname}'")
        if typ is RLType.STR_V and actual not in ("str_var", "literal"):
            raise ValueError(f"expected string in call to `{funcname}'")
        if typ in (RLType.STR_C, RLType.RES) and actual not in ("str_var", "literal"):
            raise ValueError(f"expected string in call to `{funcname}'")
        if typ in (RLType.STR_C, RLType.STR_V, RLType.RES) and actual == "literal":
            materialized = self._materialize_literal_parameter(e)
            if materialized is not None:
                return materialized
        return self.expr(e)

    def _materialize_literal_parameter(self, e):
        """Implement Function.handle_literal_in_strc for quote-containing literals.

        A source ``"`` inside a single-quoted Kepago string is not a bytecode
        string delimiter.  RLC obtains the full-width quote through zentohan
        and builds a temporary string before invoking the original function.
        """
        if e.kind != "str" or not isinstance(e.value, StringLiteral):
            return None
        tokens = e.value.tokens
        if not any(token.kind == "dquote" for token in tokens):
            return None
        allowed = {
            "text",
            "space",
            "dquote",
            "llentic",
            "rlentic",
            "asterisk",
            "percent",
            "hyphen",
            "rcur",
        }
        if any(token.kind not in allowed for token in tokens):
            return None
        accum = variable(18, int32(self.next_str))
        quote_temp = None
        chunk = []
        emitted = False

        def flush():
            nonlocal chunk, emitted
            if not chunk:
                return
            value = self._const_string(StringLiteral(tuple(chunk)))
            self.elements.append(
                self._named_call("strcat" if emitted else "strcpy", [accum, Literal(value)])
            )
            emitted = True
            chunk = []

        for token in tokens:
            if token.kind != "dquote":
                chunk.append(token)
                continue
            flush()
            if not emitted:
                self.elements.append(self._named_call("zentohan", [b"\x81\x68", accum], 1))
                emitted = True
            else:
                if quote_temp is None:
                    quote_temp = variable(18, int32(self.next_str + 1))
                    self.elements.append(self._named_call("zentohan", [b"\x81\x68", quote_temp], 1))
                self.elements.append(self._named_call("strcat", [accum, quote_temp]))
        flush()
        return accum

    def _compile_call(self, e, destination=None):
        sigs = self.config.symbol_table.lookup_function(e.value)
        last = None
        for sig in sigs:
            try:
                overload = choose_overload(sig, len(e.args))
                proto = sig.prototypes[overload]
                if proto is None:
                    return function(sig, [self.expr(x) for x in e.args], overload)
                defs = [p for p in proto if not p.is_return_value and not p.is_fake]
                lowered = []
                for i, arg in enumerate(e.args):
                    p = defs[min(i, len(defs) - 1)]
                    lowered.append(self._lower_parameter(arg, p, e.value))
                if destination is not None:
                    return_positions = [i for i, p in enumerate(proto) if p.is_return_value]
                    if not return_positions:
                        raise ValueError(
                            f"the function `{e.value}' has no explicit return parameter"
                        )
                    return_index = return_positions[0]
                    return_def = proto[return_index]
                    encoded_index = sum(1 for p in proto[:return_index] if not p.is_fake)
                    lowered.insert(
                        encoded_index, self._lower_parameter(destination, return_def, e.value)
                    )
                return function(sig, lowered, overload)
            except (ValueError, TypeError) as ex:
                last = ex
        self.error(e, str(last))

    def _select_text(self, e):
        literal = None
        if e.kind == "res":
            literal = self.resources.get(e.value)
            if literal is None:
                self.error(e, f"unable to find resource string <{e.value}>")
        elif e.kind == "str" and isinstance(e.value, StringLiteral):
            literal = e.value
        if literal is not None:
            tokens = list(literal.tokens)
            prefix = []
            if len(tokens) == 1 and tokens[0].kind == "code":
                code, width, args = tokens[0].value
                if code in ("s", "i") and width is None and len(args) == 1:
                    return b"###PRINT(" + self.expr(args[0]) + b")"
            if any(token.kind in ("dquote", "code") for token in tokens):
                out = bytearray()
                quoted = False

                def quote():
                    nonlocal quoted
                    if not quoted:
                        out.extend(b'"')
                        quoted = True

                def unquote():
                    nonlocal quoted
                    if quoted:
                        out.extend(b'"')
                        quoted = False

                def unquoted(char):
                    return (
                        "A" <= char <= "Z"
                        or "0" <= char <= "9"
                        or char in "_?"
                        or len(char.encode(self.config.output_encoding)) == 2
                    )

                simple = {
                    "llentic": "\u3010",
                    "rlentic": "\u3011",
                    "asterisk": "\uff0a",
                    "percent": "\uff05",
                    "hyphen": "-",
                    "rcur": "}",
                }
                for token in tokens:
                    if token.kind == "text":
                        value = str(token.value)
                        if not quoted and any(not unquoted(char) for char in value):
                            quote()
                        out.extend(value.encode(self.config.output_encoding))
                    elif token.kind == "space":
                        quote()
                        out.extend(b" " * int(token.value))
                    elif token.kind in simple:
                        out.extend(simple[token.kind].encode(self.config.output_encoding))
                    elif token.kind == "name":
                        scope, args = token.value
                        index = self.const(args[0])
                        out.extend(b"\x81\x93" if scope == "local" else b"\x81\x96")
                        out.extend(
                            bytes((0x82, index + 0x60))
                            if index < 26
                            else bytes((0x82, index // 26 + 0x5F, 0x82, index % 26 + 0x60))
                        )
                        if len(args) == 2:
                            out.extend(bytes((0x82, self.const(args[1]) + 0x4F)))
                    elif token.kind == "dquote":
                        unquote()
                        if self._select_quote_temp is None:
                            self._select_quote_temp = variable(18, int32(self.next_str))
                            self.elements.insert(
                                self._select_insert_pos,
                                self._named_call(
                                    "zentohan", [b"\x81\x68", self._select_quote_temp], 1
                                ),
                            )
                            self._select_insert_pos += 1
                        out.extend(b"###PRINT(" + self._select_quote_temp + b")")
                    elif token.kind == "code":
                        code, width, args = token.value
                        if code not in ("s", "i") or len(args) != 1:
                            self.error(e, f"expected one parameter for \\{code}")
                        unquote()
                        if width is not None:
                            self.error(e, "dynamic select width specifiers are not implemented yet")
                        out.extend(b"###PRINT(" + self.expr(args[0]) + b")")
                    else:
                        self.error(e, f"\\{token.kind} is invalid in select calls")
                unquote()
                return bytes(out) if out else b'""'

            def safely_unquoted(raw):
                i = 0
                while i < len(raw):
                    byte = raw[i]
                    if 0x81 <= byte <= 0x9F or 0xE0 <= byte <= 0xFC:
                        if i + 1 >= len(raw):
                            return False
                        i += 2
                        continue
                    if not (65 <= byte <= 90 or 48 <= byte <= 57 or byte in (ord("_"), ord("?"))):
                        return False
                    i += 1
                return True

            split = 0
            for split, token in enumerate(tokens):
                if token.kind != "text" or not safely_unquoted(
                    str(token.value).encode(self.config.output_encoding)
                ):
                    break
                prefix.append(str(token.value))
            else:
                return "".join(prefix).encode(self.config.output_encoding)
            remainder = StringLiteral(tuple(tokens[split:]))
            return (
                "".join(prefix).encode(self.config.output_encoding)
                + b'"'
                + self._const_string(remainder).encode(self.config.output_encoding)
                + b'"'
            )
        if e.kind != "str":
            compiled = self.expr(e)
            if isinstance(compiled, Literal):
                return compiled
            return b"###PRINT(" + compiled + b")"
        value = e.value
        if not isinstance(value, StringLiteral):
            return Literal(str(value))
        plain = value.plain()
        if plain is None:
            self.error(e, "dynamic select text is not implemented yet")
        return Literal(plain)

    def _compile_select(self, e, dest=None):
        name, op, window, params = e.value
        if window is not None and op == 13:
            self.error(e, f"select window specifiers are not valid in `{name}' (opcode {op}) calls")
        self._select_insert_pos = len(self.elements)
        self._select_quote_temp = None
        self.elements.extend((Kidoku(e.location.line), opcode(0, 2, op, len(params), 0)))
        if window is not None:
            self.elements.append(b"(" + self.expr(window) + b")")
        self.elements.extend((b"{", LineRef(e.location.line, True)))
        effects = {
            "colour": ord("0"),
            "title": ord("1"),
            "grey": ord("1"),
            "hide": ord("2"),
            "blank": ord("3"),
            "cursor": ord("4"),
        }
        for param in params:
            use_text = True
            if param[0] == "always":
                text = param[1]
            else:
                conditions, text = param[1], param[2]
                encoded = bytearray(b"(")
                for kind, n, arg, cond, loc in conditions:
                    if n not in effects:
                        raise RLCError(f"unknown effect `{n}' in select condition", loc)
                    marker = bytes((effects[n],))
                    if cond is not None:
                        encoded.extend(b"(" + self._condition(cond) + b")" + marker)
                    else:
                        encoded.extend(marker)
                    if kind == "value":
                        encoded.extend(self.expr(arg))
                    elif cond is None:
                        try:
                            use_text = self.const(text) != ""
                        except ValueError:
                            use_text = True
                encoded.extend(b")")
                self.elements.append(bytes(encoded))
            if use_text:
                rendered = self._select_text(text)
                self.elements.append(
                    rendered if isinstance(rendered, bytes) else parameters([rendered])
                )
            self.elements.append(LineRef(text.location.line, True))
        self.elements.append(b"}")
        if dest is not None:
            self.elements.append(assignment(self.expr(dest), "=", b"$\xc8"))

    def _new(self):
        self.auto += 1
        return f"__auto@_{self.auto}__"

    def _condition(self, e):
        """Normalise a condition like Expr.conditional_unit in expr.ml."""
        try:
            return int32(int(bool(self.const(e))))
        except ValueError:
            pass
        if e.kind == "bin" and e.value in ("==", "!=", "<=", "<", ">=", ">", "&&", "||"):
            return self.expr(e)
        if e.kind == "unary" and e.value == "!":
            # conditional_unit turns ``! value`` into ``value == 0``.  The
            # operand must not first be normalised to ``value != 0`` or the
            # emitted expression gains a second, observable comparison.
            return binary(self.expr(e.args[0]), "==", int32(0))
        return binary(self.expr(e), "!=", int32(0))

    def _named_call(self, name, values, overload=None):
        return function(self.config.symbol_table.lookup_function(name)[0], values, overload)

    def _is_string_lvalue(self, e):
        if e.kind in ("ident", "index"):
            if e.value in self.variables:
                return self.variables[e.value][0] in (10, 12, 18)
            return e.value.startswith("str")
        return False

    def _same_expr(self, left, right):
        if (
            left.kind != right.kind
            or left.value != right.value
            or len(left.args) != len(right.args)
        ):
            return False
        return all(self._same_expr(a, b) for a, b in zip(left.args, right.args))

    def _compile_quoted_string_assignment(self, lhs, rhs, append=False):
        """Handle DQuote tokens as function.handle_literal_in_strc does."""
        if rhs.kind != "str" or not isinstance(rhs.value, StringLiteral):
            return False
        tokens = rhs.value.tokens
        allowed = {
            "text",
            "space",
            "dquote",
            "llentic",
            "rlentic",
            "asterisk",
            "percent",
            "hyphen",
            "rcur",
        }
        if not any(t.kind == "dquote" for t in tokens) or any(
            t.kind not in allowed for t in tokens
        ):
            return False
        destination = self.expr(lhs)
        chunk = []
        emitted = append
        quote_temp = None

        def flush():
            nonlocal chunk, emitted
            if not chunk:
                return
            value = self._const_string(StringLiteral(tuple(chunk)))
            self.elements.append(
                self._named_call("strcat" if emitted else "strcpy", [destination, Literal(value)])
            )
            emitted = True
            chunk = []

        for token in tokens:
            if token.kind != "dquote":
                chunk.append(token)
                continue
            flush()
            if not emitted:
                # zentohan(0x8168) yields an ASCII double quote and may write
                # it directly to strcpy's destination.
                self.elements.append(self._named_call("zentohan", [b"\x81\x68", destination], 1))
                emitted = True
            else:
                if quote_temp is None:
                    quote_temp = variable(18, int32(self.next_str))
                    self.elements.append(self._named_call("zentohan", [b"\x81\x68", quote_temp], 1))
                self.elements.append(self._named_call("strcat", [destination, quote_temp]))
        flush()
        return True

    def _textout_stub(self, e, s):
        """Lower static text as Textout.compile_stub does."""
        literal = e.value
        if not isinstance(literal, StringLiteral):
            self.elements.extend(
                (
                    Kidoku(s.location.line),
                    b'"' + str(literal).encode(self.config.output_encoding) + b'"',
                )
            )
            return
        if any(t.kind == "delete" for t in literal.tokens):
            return
        self.elements.append(Kidoku(s.location.line))
        buf = bytearray()
        quoted = False
        in_name = False
        ignore_space = False

        def quote(on):
            nonlocal quoted
            if quoted != on:
                buf.extend(b'"')
                quoted = on

        def add_text(value):
            quote(True)
            buf.extend(value.encode(self.config.output_encoding))

        def flush():
            quote(False)
            if buf:
                self.elements.append(bytes(buf))
                buf.clear()

        # compile_stub opens a quoted segment before visiting the first token.
        # This matters for an empty string and for a leading speaker marker,
        # which deliberately produces an empty quoted segment first.
        quote(True)
        for token in literal.tokens:
            if ignore_space and token.kind != "space":
                ignore_space = False
            if token.kind == "text":
                add_text(token.value)
            elif token.kind == "space":
                count = token.value
                if ignore_space and count:
                    count -= 1
                    ignore_space = False
                # textout.ml writes spaces without changing quote state.  A
                # space immediately after a name token therefore precedes the
                # opening quote of the following text.
                if count:
                    buf.extend(b" " * count)
            elif token.kind == "dquote":
                quote(True)
                buf.extend(b'\\"')
            elif token.kind == "llentic":
                add_text("\u3010")
            elif token.kind == "rlentic":
                add_text("\u3011")
            elif token.kind == "asterisk":
                add_text("\uff0a")
            elif token.kind == "percent":
                add_text("\uff05")
            elif token.kind == "hyphen":
                add_text("-")
            elif token.kind == "speaker":
                if in_name:
                    raise RLCError("\\{} may not be nested", token.location)
                quote(False)
                buf.extend(b"\x81\x79")
                in_name = True
            elif token.kind == "rcur":
                quote(False)
                buf.extend(b"\x81\x7a")
                ignore_space = True
                in_name = False
            elif token.kind == "name":
                quote(False)
                scope, args = token.value
                try:
                    index = self.const(args[0])
                except ValueError:
                    raise RLCError("name index must be constant in static text", token.location)
                buf.extend(b"\x81\x93" if scope == "local" else b"\x81\x96")
                if index < 26:
                    buf.extend(bytes((0x82, index + 0x60)))
                else:
                    buf.extend(bytes((0x82, index // 26 + 0x5F, 0x82, index % 26 + 0x60)))
                if len(args) == 2:
                    buf.extend(bytes((0x82, self.const(args[1]) + 0x4F)))
            elif token.kind == "code":
                code, width, args = token.value
                if code == "i":
                    if len(args) != 1:
                        raise RLCError(
                            "the control code \\i{} must have one and only one parameter",
                            token.location,
                        )
                    value = self.const(args[0])
                    text = str(value)
                    if width is not None:
                        text = "0" * max(0, self.const(width) - len(text)) + text
                    add_text(text)
                else:
                    flush()
                    sigs = self.config.symbol_table.lookup_control_code(code)
                    last = None
                    for sig in sigs:
                        try:
                            self.elements.append(function(sig, [self.expr(a) for a in args]))
                            break
                        except ValueError as ex:
                            last = ex
                    else:
                        raise RLCError(str(last), token.location)
            elif token.kind in ("add", "resref", "rewrite"):
                raise RLCError(
                    f"\\{token.kind} resource semantics are not implemented yet", token.location
                )
        if in_name:
            raise RLCError("expected `}' to close name block", s.location)
        flush()

    def statement(self, s):
        if s.location:
            self.elements.append(LineRef(s.location.line))
        if s.kind == "label":
            self.elements.append(Label(s.value))
            return
        if s.kind == "block":
            for x in s.args:
                self.statement(x)
        elif s.kind == "expr":
            e = s.args[0]
            if e.kind == "str":
                self._textout_stub(e, s)
            elif e.kind == "res":
                if e.value not in self.resources:
                    self.error(e, f"unable to find resource string <{e.value}>")
                self._textout_stub(Expr("str", self.resources[e.value], location=e.location), s)
            elif e.kind == "label":
                self.elements.append(LabelRef(e.value))
            elif e.kind == "select":
                self._compile_select(e)
            elif e.kind == "call" and e.value in ("at", "rlc_parse_string"):
                if e.value == "at":
                    if len(e.args) != 3:
                        self.error(
                            e,
                            "the `at' intrinsic statement must be passed a location and a string to evaluate",
                        )
                    try:
                        filename = self.const(e.args[0])
                        line = self.const(e.args[1])
                        source = self.const(e.args[2])
                    except ValueError:
                        self.error(e, "the string passed to `at' must be evaluable at compile-time")
                else:
                    if len(e.args) != 1:
                        self.error(
                            e,
                            "the `rlc_parse_string' intrinsic must be passed a single string constant",
                        )
                    try:
                        source = self.const(e.args[0])
                    except ValueError:
                        self.error(
                            e,
                            "the string passed to `rlc_parse_string' must be evaluable at compile-time",
                        )
                    filename = e.location.file if e.location else None
                    line = e.location.line if e.location else 1
                if not isinstance(source, str):
                    self.error(
                        e, f"the string passed to `{e.value}' must be evaluable at compile-time"
                    )
                from .lexer import Lexer
                from .parser import Parser

                for child in (
                    Parser(Lexer(source, filename, start_line=line).tokens()).parse().statements
                ):
                    self.statement(child)
            elif e.kind == "call" and e.value not in self.inlines:
                self.elements.append(self._compile_call(e))
            elif e.kind == "call" and e.value in self.inlines:
                # Expanding an inline used as a statement may emit runtime
                # code, but its returned expression is deliberately ignored.
                # Appending it produced a stray ``store`` expression after
                # wrappers such as CallDLL().
                self.expr(e)
            elif e.kind == "ident":
                try:
                    self.elements.append(
                        function(self.config.symbol_table.lookup_function(e.value)[0], [])
                    )
                except KeyError:
                    self.expr(e)
            else:
                self.elements.append(self.expr(e))
        elif s.kind == "assign":
            rhs = s.args[1]
            direct_return = False
            callable_rhs = (
                rhs
                if rhs.kind == "call"
                else Expr("call", rhs.value, location=rhs.location)
                if rhs.kind == "ident"
                else None
            )
            if (
                s.value == "="
                and callable_rhs is not None
                and callable_rhs.value not in self.inlines
            ):
                try:
                    for signature in self.config.symbol_table.lookup_function(callable_rhs.value):
                        overload = choose_overload(signature, len(callable_rhs.args))
                        prototype = signature.prototypes[overload]
                        if prototype is not None and any(p.is_return_value for p in prototype):
                            self.elements.append(self._compile_call(callable_rhs, s.args[0]))
                            direct_return = True
                            break
                except (KeyError, ValueError):
                    pass
            if direct_return:
                pass
            elif s.value == "=" and rhs.kind == "select":
                self._compile_select(rhs, s.args[0])
            elif s.value == "=" and self._same_expr(s.args[0], rhs):
                pass
            elif (
                s.value == "="
                and not self._is_string_lvalue(s.args[0])
                and rhs.kind == "bin"
                and rhs.value in ("+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>")
                and self._same_expr(s.args[0], rhs.args[0])
            ):
                self.elements.append(
                    assignment(self.expr(s.args[0]), rhs.value + "=", self.expr(rhs.args[1]))
                )
            elif self._is_string_lvalue(s.args[0]):
                if s.value == "=":
                    if not self._compile_quoted_string_assignment(s.args[0], rhs):
                        self.elements.append(
                            self._named_call("strcpy", [self.expr(s.args[0]), self.expr(rhs)], 0)
                        )
                elif s.value == "+=":
                    if not self._compile_quoted_string_assignment(s.args[0], rhs, True):
                        self.elements.append(
                            self._named_call("strcat", [self.expr(s.args[0]), self.expr(rhs)], 0)
                        )
                else:
                    self.error(s, f"assignment operator `{s.value}' is not valid for strings")
            else:
                self.elements.append(assignment(self.expr(s.args[0]), s.value, self.expr(rhs)))
        elif s.kind == "goto_call":
            call, labels = s.value
            if call.kind == "ident":
                call = Expr("call", call.value, location=call.location)
            conditional = (
                call.value in ("goto_if", "goto_unless", "gosub_if", "gosub_unless")
                and len(call.args) == 1
            )
            folded = False
            if conditional:
                try:
                    condition = self.const(call.args[0])
                except ValueError:
                    pass
                else:
                    folded = True
                    jump = (condition != 0) if call.value.endswith("_if") else (condition == 0)
                    if jump:
                        direct = "gosub" if call.value.startswith("gosub") else "goto"
                        self.elements.append(
                            self._compile_call(Expr("call", direct, location=call.location))
                        )
                        self.elements.extend(LabelRef(label) for label in labels)
            if not folded:
                if conditional:
                    # The condition arguments of the four jump functions are
                    # handled by Goto.compile rather than ordinary FuncAsm
                    # parameter lowering.  In particular a bare integer must
                    # be encoded as ``integer != 0``.
                    sig = self.config.symbol_table.lookup_function(call.value)[0]
                    self.elements.append(function(sig, [self._condition(call.args[0])]))
                else:
                    self.elements.append(self._compile_call(call))
                self.elements.extend(LabelRef(label) for label in labels)
        elif s.kind == "goto_table":
            call, entries = s.value
            if len(call.args) != 1:
                self.error(call, f"`{call.value}' requires one selector expression")
            sig = self.config.symbol_table.lookup_function(call.value)[0]
            self.elements.extend(
                (
                    opcode(sig.opcode_type, sig.module_id or 0, sig.id or 0, len(entries), 0),
                    b"(" + self.expr(call.args[0]) + b")",
                    b"{",
                )
            )
            for match, label in entries:
                self.elements.append(b"()" if match is None else b"(" + self.expr(match) + b")")
                self.elements.append(LabelRef(label))
            self.elements.append(b"}")
        elif s.kind == "decl":
            typ, dirs, decls = s.value
            for name, size, init, addr, loc in decls:
                if size == "auto":
                    if not isinstance(init, list) or not init:
                        raise RLCError(
                            f"`{name}[]' must either be given an explicit length, or the initial value array must contain at least one element",
                            loc,
                        )
                    count = len(init)
                elif size is None:
                    count = 1
                else:
                    try:
                        count = self.const(size)
                    except ValueError:
                        raise RLCError(
                            f"array length for `{name}[]' must evaluate to a constant integer",
                            size.location,
                        )
                # Explicit zero-length arrays are accepted by variables.ml.
                # (Only an inferred [] array is rejected above.)  Some shipped
                # headers deliberately use them when GAMEEXE defines no windows.
                if addr:
                    try:
                        space = self.const(addr[0])
                        base = self.const(addr[2])
                    except ValueError:
                        raise RLCError("fixed address must be constant", loc)
                elif typ == "str":
                    space, base = 18, self.next_str
                    self.next_str += count
                else:
                    bits = int(typ)
                    underlying = self.next_int
                    # OCaml integer division truncates toward zero, unlike //.
                    blocks = int((count * bits - 1) / 32) + 1
                    self.next_int += blocks
                    space = 2 if bits == 32 else 2 + {1: 26, 2: 52, 4: 78, 8: 104}[bits]
                    base = underlying if bits == 32 else underlying * (32 // bits)
                self.variables[name] = (space, base)
                self.array_lengths[name] = count if size is not None else None
                first = variable(space, int32(base))
                last = variable(space, int32(base + count - 1))
                is_array = size is not None
                if isinstance(init, list):
                    if len(init) > count:
                        raise RLCError(f"too many values supplied to initialise {name}[]", loc)
                    if typ == "str":
                        for i, value in enumerate(init):
                            self.elements.append(
                                self._named_call(
                                    "strcpy",
                                    [variable(space, int32(base + i)), self.expr(value)],
                                    0,
                                )
                            )
                    elif init:
                        self.elements.append(
                            self._named_call(
                                "setarray", [first] + [self.expr(value) for value in init], 0
                            )
                        )
                    if "zero" in dirs and len(init) < count:
                        tail = variable(space, int32(base + len(init)))
                        self.elements.append(
                            self._named_call(
                                "strclear" if typ == "str" else "setrng",
                                [tail, last],
                                1 if typ == "str" else 0,
                            )
                        )
                elif init is not None:
                    if not is_array:
                        if typ == "str":
                            self.elements.append(
                                self._named_call("strcpy", [first, self.expr(init)], 0)
                            )
                        else:
                            self.elements.append(assignment(first, "=", self.expr(init)))
                    elif typ == "str":
                        for i in range(count):
                            self.elements.append(
                                self._named_call(
                                    "strcpy", [variable(space, int32(base + i)), self.expr(init)], 0
                                )
                            )
                    else:
                        self.elements.append(
                            self._named_call("setrng", [first, last, self.expr(init)], 1)
                        )
                elif "zero" in dirs:
                    if typ == "str":
                        self.elements.append(
                            self._named_call(
                                "strclear",
                                [first, last] if is_array else [first],
                                1 if is_array else 0,
                            )
                        )
                    elif is_array:
                        self.elements.append(self._named_call("setrng", [first, last], 0))
                    else:
                        self.elements.append(assignment(first, "=", int32(0)))
        elif s.kind == "if":
            cond, yes, no = s.args
            try:
                chosen = yes if self.const(cond) else no
                self.statement(chosen) if chosen else None
            except ValueError:
                els = self._new()
                end = els if no is None else self._new()
                self._goto("goto_unless", cond, els)
                self.statement(yes)
                if no:
                    self._goto("goto", None, end)
                    self.elements.append(Label(els))
                    self.statement(no)
                self.elements.append(Label(end))
        elif s.kind == "while":
            start, end = self._new(), self._new()
            self.elements.append(Label(start))
            self._goto("goto_unless", s.args[0], end)
            self.break_stack.append(end)
            self.continue_stack.append(start)
            try:
                self.statement(s.args[1])
            finally:
                self.break_stack.pop()
                self.continue_stack.pop()
            self._goto("goto", None, start)
            self.elements.append(Label(end))
        elif s.kind == "repeat":
            start, cont, end = self._new(), self._new(), self._new()
            self.elements.append(Label(start))
            self.break_stack.append(end)
            self.continue_stack.append(cont)
            try:
                for x in s.args[0]:
                    self.statement(x)
            finally:
                self.break_stack.pop()
                self.continue_stack.pop()
            self.elements.append(Label(cont))
            self._goto("goto_unless", s.args[1], start)
            self.elements.append(Label(end))
        elif s.kind == "case":
            value, cases, other = s.value
            try:
                selected = next(
                    (body for match, body in cases if self.const(match) == self.const(value)), other
                )
                for x in selected:
                    if x.kind == "break":
                        break
                    self.statement(x)
            except ValueError:
                end = self._new()
                self.break_stack.append(end)
                try:
                    for match, body in cases:
                        nxt = self._new()
                        self._goto(
                            "goto_unless", Expr("bin", "==", [value, match], s.location), nxt
                        )
                        for x in body:
                            self.statement(x)
                        self._goto("goto", None, end)
                        self.elements.append(Label(nxt))
                    for x in other:
                        self.statement(x)
                finally:
                    self.break_stack.pop()
                self.elements.append(Label(end))
        elif s.kind == "raw":
            out = bytearray()
            for tok in s.value:
                if tok.type == "IDENT" and str(tok.value).startswith("#"):
                    h = str(tok.value)[1:]
                    h = ("0" + h) if len(h) % 2 else h
                    try:
                        out.extend(bytes.fromhex(h))
                    except ValueError:
                        raise RLCError("syntax error in raw block: #... not hex", tok.location)
                elif tok.type == "INTEGER":
                    out.extend(int32(int(tok.value)))
                else:
                    out.extend(str(tok.value).encode(self.config.output_encoding))
            self.elements.append(bytes(out))
        elif s.kind == "definitions":
            mode, vals = s.value
            for name, op, e in vals:
                # directive.ml keeps #define/#sdefine/#redef as expression
                # macros.  In particular, definitions such as
                # ``#sdefine __retval = store`` must not be folded here.
                # #const and #set, on the other hand, use getconst and must be
                # evaluable during compilation.
                if mode in ("define", "sdefine", "bind", "ebind", "redef"):
                    val = e
                else:
                    value_expr = e
                    if op and op != "=":
                        if name not in self.constants:
                            self.error(e, f"cannot mutate undefined symbol `{name}'")
                        old = self.constants[name]
                        if not isinstance(old, Expr):
                            old = Expr(
                                "str" if isinstance(old, str) else "int", old, location=e.location
                            )
                        value_expr = Expr("bin", op[:-1], [old, e], e.location)
                    val = self.const(value_expr)
                self.constants[name] = val
        elif s.kind == "inline":
            name, params, body, _scoped = s.value
            self.inlines[name] = (params, body)
        elif s.kind == "hiding":
            name = s.value
            hidden_inline = self.inlines.pop(name, None)
            hidden_constant = self.constants.pop(name, None)
            old_markers = {
                key: self.constants.get(key)
                for key in ("__INLINE_CALL__", "__CALLER_FILE__", "__CALLER_LINE__")
            }
            had_markers = {key: key in self.constants for key in old_markers}
            self.constants["__INLINE_CALL__"] = 0
            self.constants["__CALLER_FILE__"] = (
                s.location.file if s.location and s.location.file else ""
            )
            self.constants["__CALLER_LINE__"] = s.location.line if s.location else 0
            try:
                self.statement(s.args[0])
            finally:
                if hidden_inline is not None:
                    self.inlines[name] = hidden_inline
                if hidden_constant is not None:
                    self.constants[name] = hidden_constant
                for key in old_markers:
                    if had_markers[key]:
                        self.constants[key] = old_markers[key]
                    else:
                        self.constants.pop(key, None)
        elif s.kind == "undef":
            for n in s.value:
                self.constants.pop(n, None)
        elif s.kind == "compile_if":
            k, cond = s.value
            if k in ("#ifdef", "#ifndef"):
                val = all(
                    x.kind == "ident" and (x.value in self.constants or x.value in self.variables)
                    for x in ([cond] if cond.kind != "bin" else cond.args)
                )
                val = not val if k == "#ifndef" else val
            else:
                val = bool(self.const(cond))
            for x in s.args[0 if val else 1]:
                self.statement(x)
        elif s.kind == "compile_for":
            name, first, last, body = s.value
            old = self.constants.get(name, None)
            had = name in self.constants
            for value in range(self.const(first), self.const(last) + 1):
                self.constants[name] = value
                self.statement(copy.deepcopy(body))
            if had:
                self.constants[name] = old
            else:
                self.constants.pop(name, None)
        elif s.kind == "directive":
            name, e = s.value
            if name == "entrypoint":
                self.elements.append(Entrypoint(self.const(e)))
            elif name == "val_0x2c":
                self.val_0x2c = self.const(e)
            elif name == "target":
                pass
            elif name == "load":
                path = str(self.const(e))
                candidates = [
                    path,
                    path + ".kh",
                    os.path.join("lib", path),
                    os.path.join("lib", path + ".kh"),
                ]
                if self.config.kfn_directory_path:
                    runtime_dir = (
                        self.config.kfn_directory_path
                        if os.path.isdir(self.config.kfn_directory_path)
                        else os.path.dirname(self.config.kfn_directory_path)
                    )
                    candidates.extend(
                        (os.path.join(runtime_dir, path), os.path.join(runtime_dir, path + ".kh"))
                    )
                found = next((p for p in candidates if os.path.isfile(p)), None)
                if not found:
                    raise RLCError(f"Cannot load `{path}'", s.location)
                from .lexer import Lexer
                from .parser import Parser

                with open(found, "rb") as source_file:
                    raw = source_file.read()
                try:
                    src = raw.decode(self.config.input_encoding)
                except UnicodeDecodeError:
                    src = raw.decode("utf-8")
                for child in Parser(Lexer(src, found).tokens()).parse().statements:
                    self.statement(child)
            elif name == "resource":
                path = str(self.const(e))
                base = os.path.dirname(s.location.file) if s.location and s.location.file else ""
                candidates = [path, os.path.join(base, path)]
                found = next((p for p in candidates if os.path.isfile(p)), None)
                if not found:
                    raise RLCError(f"Cannot load resource file `{path}'", s.location)
                with open(found, "rb") as resource_file:
                    raw = resource_file.read()
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = raw.decode(self.config.input_encoding)
                from .string_lexer import StringLexer

                pending_key = None
                pending_body = []

                def finish_resource():
                    if pending_key is None:
                        return
                    # Every physical resource line contributes its line
                    # ending.  lex_resstr later removes one final Space(1),
                    # so a deliberate blank line leaves exactly one space.
                    body = "\n".join(line.rstrip(" \t\u3000") for line in pending_body) + "\n"
                    literal, _, _, _ = StringLexer(body + "\0", 0, "\0", found, 1, 1).scan()
                    # lex_resstr drops exactly one trailing space token.  This
                    # is observable for intentionally split resource lines.
                    if (
                        literal.tokens
                        and literal.tokens[-1].kind == "space"
                        and literal.tokens[-1].value == 1
                    ):
                        literal = StringLiteral(literal.tokens[:-1])
                    self.resources[pending_key] = literal

                for line_number, resource_line in enumerate(text.splitlines(), 1):
                    stripped = resource_line.lstrip(" \t")
                    if stripped.startswith("<") and ">" in stripped:
                        finish_resource()
                        close = stripped.index(">")
                        pending_key = stripped[1:close]
                        pending_body = [stripped[close + 1 :].lstrip(" ")]
                    elif pending_key is not None:
                        # strLexer consumes whitespace on both sides of a
                        # physical newline and emits one Space token.
                        pending_body[-1] = pending_body[-1].rstrip(" \t\u3000")
                        pending_body.append(resource_line.lstrip(" \t\u3000"))
                finish_resource()
            elif name in ("file", "base_res", "character", "kidoku_type", "version", "exclude"):
                pass
            elif name in ("print", "warn"):
                pass
            elif name == "error":
                raise RLCError(str(self.const(e)), s.location)
            else:
                raise RLCError(f"#{name} is not implemented yet", s.location)
        elif s.kind == "return":
            self.return_value = s.args[0]
        elif s.kind == "halt":
            self.elements.append(b"\x00")
        elif s.kind == "break":
            if not self.break_stack:
                self.error(s, "break outside breakable structure")
            self._goto("goto", None, self.break_stack[-1])
        elif s.kind == "continue":
            if not self.continue_stack:
                self.error(s, "continue outside loop")
            self._goto("goto", None, self.continue_stack[-1])
        else:
            raise RLCError(f"{s.kind} is not implemented yet", s.location)

    def _goto(self, name, cond, label):
        if cond is not None and name in ("goto_if", "goto_unless", "gosub_if", "gosub_unless"):
            try:
                condition = self.const(cond)
            except ValueError:
                pass
            else:
                jump = (condition != 0) if name.endswith("_if") else (condition == 0)
                if jump:
                    direct = "gosub" if name.startswith("gosub") else "goto"
                    self.elements.extend(
                        (
                            function(self.config.symbol_table.lookup_function(direct)[0], []),
                            LabelRef(label),
                        )
                    )
                return
        sig = self.config.symbol_table.lookup_function(name)[0]
        vals = [] if cond is None else [self._condition(cond)]
        self.elements.extend((function(sig, vals), LabelRef(label)))

    def compile(self, program):
        # compilerFrame.ml unconditionally parses the installed system.kh
        # before the project/source AST.  Apart from defining the RTL macros,
        # this supplies the default #entrypoint 0 used by ordinary scenarios.
        if self.config.kfn_directory_path:
            libdir = (
                self.config.kfn_directory_path
                if os.path.isdir(self.config.kfn_directory_path)
                else os.path.dirname(self.config.kfn_directory_path)
            )
            system_header = os.path.join(libdir, "system.kh")
            if os.path.isfile(system_header):
                from .lexer import Lexer
                from .parser import Parser

                with open(system_header, "rb") as source_file:
                    raw = source_file.read()
                try:
                    source = raw.decode(self.config.input_encoding)
                except UnicodeDecodeError:
                    source = raw.decode("utf-8")
                for statement in Parser(Lexer(source, system_header).tokens()).parse().statements:
                    self.statement(statement)
        for s in program.statements:
            self.statement(s)
        # compilerFrame.ml always appends a script terminator, even when the
        # source already contains an explicit `halt`.
        self.elements.append(b"\x00")
        if self.config.target_platform is TargetPlatform.AVG2000:
            result = build_avg2000(
                self.elements, val_0x2c=self.val_0x2c, debug_info=self.config.include_debug_symbols
            )
            if self.config.compress_output:
                from .compression import mask_kp2k

                result = mask_kp2k(result)
            return result
        result = build_uncompressed(
            self.elements,
            compiler_version=self.config.compiler_version,
            val_0x2c=self.val_0x2c,
            version=self.config.target_version.to_tuple(),
            debug_info=self.config.include_debug_symbols,
        )
        if self.config.compress_output:
            from .compression import compress_kprl

            result = compress_kprl(result)
        return result
