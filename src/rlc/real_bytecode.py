"""Faithful low-level RealLive bytecode encoder.

Transcribes the pure encoding portions of ``codegen.ml``, ``funcAsm.ml`` and
``bytecodeGen.ml``.  Keeping this layer free of parser concerns makes its bytes
directly testable against the OCaml equations.
"""

import datetime
import struct
from dataclasses import dataclass
from typing import Optional

from .kfn_data_structures import FunctionSignature

OP_CODES = {
    "+": 0x00,
    "-": 0x01,
    "*": 0x02,
    "/": 0x03,
    "%": 0x04,
    "&": 0x05,
    "|": 0x06,
    "^": 0x07,
    "<<": 0x08,
    ">>": 0x09,
    "&&": 0x3C,
    "||": 0x3D,
    "==": 0x28,
    "!=": 0x29,
    "<=": 0x2A,
    "<": 0x2B,
    ">=": 0x2C,
    ">": 0x2D,
}
ASSIGN_CODES = {
    "+=": 0x14,
    "-=": 0x15,
    "*=": 0x16,
    "/=": 0x17,
    "%=": 0x18,
    "&=": 0x19,
    "|=": 0x1A,
    "^=": 0x1B,
    "<<=": 0x1C,
    ">>=": 0x1D,
    "=": 0x1E,
}


def int32(value: int) -> bytes:
    return b"$\xff" + struct.pack("<i", value)


def variable(space: int, index: bytes) -> bytes:
    return b"$" + bytes((space,)) + b"[" + index + b"]"


def binary(lhs: bytes, operator: str, rhs: bytes) -> bytes:
    return lhs + b"\\" + bytes((OP_CODES[operator],)) + rhs


def assignment(lhs: bytes, operator: str, rhs: bytes) -> bytes:
    return lhs + b"\\" + bytes((ASSIGN_CODES[operator],)) + rhs


def opcode(op_type: int, module: int, code: int, argc: int, overload: int) -> bytes:
    return (
        b"#"
        + bytes((op_type, module))
        + struct.pack("<H", code)
        + struct.pack("<H", argc)
        + bytes((overload,))
    )


@dataclass(frozen=True)
class Special:
    ident: int
    values: tuple[object, ...]
    no_parens: bool = False


@dataclass(frozen=True)
class Literal:
    value: str


def _parameter(value, previous=None) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, Literal):
        raw = value.value.encode("cp932")

        # StrTokens.unquoted_char operates on characters, not encoded bytes:
        # uppercase ASCII/digits/_/? and every character represented by two
        # output bytes are safe.  Inspecting CP932 bytes individually wrongly
        # treated an ASCII-valued trail byte as punctuation.
        def unquoted(char):
            return (
                "A" <= char <= "Z"
                or "0" <= char <= "9"
                or char in "_?"
                or len(char.encode("cp932")) == 2
            )

        needs = any(not unquoted(char) for char in value.value)
        return (b'"' + raw + b'"') if needs or not raw else raw
    if isinstance(value, str):
        return value.encode("cp932")
    if isinstance(value, int):
        return int32(value)
    if isinstance(value, (tuple, list)):
        return b"(" + parameters(value) + b")"
    if isinstance(value, Special):
        if value.ident > 255:
            prefix = (
                b"a" + bytes((value.ident & 255,)) + b"a" + bytes((((value.ident >> 8) & 255) - 1,))
            )
        else:
            prefix = b"a" + bytes((value.ident,))
        body = parameters(value.values)
        return prefix + body if value.no_parens else prefix + b"(" + body + b")"
    raise TypeError(f"unsupported RealLive parameter: {type(value).__name__}")


def parameters(values) -> bytes:
    out = bytearray()
    previous = None
    for value in values:
        encoded = _parameter(value, previous)
        # OCaml inserts separators only in the few ambiguous cases.  Literal
        # strings are represented as str here; raw expression bytes are not.
        if out and isinstance(value, Literal) and isinstance(previous, Literal):
            out.extend(b",")
        if (
            out
            and isinstance(value, bytes)
            and value.startswith(b"\\")
            and not isinstance(previous, (tuple, list))
        ):
            out.extend(b",")
        out.extend(encoded)
        previous = value
    return bytes(out)


def choose_overload(func: FunctionSignature, argc: int) -> int:
    arbitrary = -1
    for idx, proto in enumerate(func.prototypes):
        if proto is None:
            arbitrary = idx
            continue
        minimum = maximum = 0
        repeated = False
        for p in proto:
            if p.is_fake or p.is_return_value:
                continue
            if p.is_repeated:
                repeated = True
            else:
                maximum += 1
                if not p.is_optional:
                    minimum += 1
        if (repeated and argc >= minimum) or (not repeated and minimum <= argc <= maximum):
            return idx
    if arbitrary >= 0:
        return arbitrary
    raise ValueError(f"unable to find a prototype for `{func.name}' that matches these parameters")


def function(func: FunctionSignature, values, overload: Optional[int] = None) -> bytes:
    idx = choose_overload(func, len(values)) if overload is None else overload
    argc = len(values)
    if func.prototypes and func.prototypes[idx] is not None:
        argc -= sum(1 for p in func.prototypes[idx] if p.is_uncounted)
    head = opcode(func.opcode_type, func.module_id or 0, func.id or 0, argc, idx)
    return head + (b"(" + parameters(values) + b")" if values else b"")


@dataclass(frozen=True)
class Label:
    name: str


@dataclass(frozen=True)
class LabelRef:
    name: str


@dataclass(frozen=True)
class Kidoku:
    line: int


@dataclass(frozen=True)
class Entrypoint:
    index: int


@dataclass(frozen=True)
class LineRef:
    line: int
    force: bool = False


def build_uncompressed(
    elements, compiler_version=10002, debug_info=True, val_0x2c=0, version=(1, 2, 7, 0)
):
    # bytecodeGen.ml removes all but the last occurrence of each entrypoint.
    last_entries = {e.index: i for i, e in enumerate(elements) if isinstance(e, Entrypoint)}
    elements = [
        e
        for i, e in enumerate(elements)
        if not isinstance(e, Entrypoint) or last_entries[e.index] == i
    ]
    labels = {}
    pos = 0
    kidoku = []
    entries = [0] * 100
    for e in elements:
        if isinstance(e, bytes):
            pos += len(e)
        elif isinstance(e, Label):
            labels[e.name] = pos
        elif isinstance(e, LabelRef):
            pos += 4
        elif isinstance(e, (Kidoku, Entrypoint)):
            pos += 3
        elif isinstance(e, LineRef) and (debug_info or e.force):
            pos += 3
    code = bytearray()
    kidx = 0
    marker = ord("!") if version > (1, 2, 5, 0) else ord("@")
    for e in elements:
        if isinstance(e, bytes):
            code.extend(e)
        elif isinstance(e, Label):
            pass
        elif isinstance(e, LabelRef):
            if e.name not in labels:
                raise ValueError(f"reference to undefined label @{e.name}")
            code.extend(struct.pack("<I", labels[e.name]))
        elif isinstance(e, Kidoku):
            kidoku.append(e.line if debug_info else 0)
            code.extend(b"@" + struct.pack("<H", kidx))
            kidx += 1
        elif isinstance(e, Entrypoint):
            entries[e.index] = len(code)
            kidoku.append(e.index + 1_000_000)
            code.extend(bytes((marker,)) + struct.pack("<H", kidx))
            kidx += 1
        elif isinstance(e, LineRef) and (debug_info or e.force):
            code.extend(b"\x0a" + struct.pack("<H", e.line if debug_info else 0))
    header = bytearray(0x1D0)
    kidoku_bytes = b"".join(struct.pack("<I", x) for x in kidoku)
    offset = 0x1D0 + len(kidoku_bytes)
    header[0:4] = b"KPRL"
    struct.pack_into(
        "<12I",
        header,
        4,
        compiler_version,
        0x1D0,
        len(kidoku),
        len(kidoku_bytes),
        0x1D0 + len(kidoku_bytes),
        0,
        0,
        offset,
        len(code),
        len(code),
        val_0x2c,
        val_0x2c + 3,
    )
    struct.pack_into("<100I", header, 0x34, *entries)
    return bytes(header) + kidoku_bytes + bytes(code)


def build_avg2000(elements, debug_info=True, val_0x2c=0, now=None):
    """Build the uncompressed ``KP2K`` container from bytecodeGen.ml."""
    last_entries = {e.index: i for i, e in enumerate(elements) if isinstance(e, Entrypoint)}
    elements = [
        e
        for i, e in enumerate(elements)
        if not isinstance(e, Entrypoint) or last_entries[e.index] == i
    ]
    labels = {}
    pos = 0
    kidoku = []
    entries = [0] * 100
    for e in elements:
        if isinstance(e, bytes):
            pos += len(e)
        elif isinstance(e, Label):
            labels[e.name] = pos
        elif isinstance(e, LabelRef):
            pos += 4
        elif isinstance(e, (Kidoku, Entrypoint)):
            pos += 5
        elif isinstance(e, LineRef) and (debug_info or e.force):
            pos += 5
    code = bytearray()
    kidx = 0
    for e in elements:
        if isinstance(e, bytes):
            code.extend(e)
        elif isinstance(e, Label):
            pass
        elif isinstance(e, LabelRef):
            if e.name not in labels:
                raise ValueError(f"reference to undefined label @{e.name}")
            code.extend(struct.pack("<I", labels[e.name]))
        elif isinstance(e, Kidoku):
            kidoku.append(e.line if debug_info else 0)
            code.extend(b"@" + struct.pack("<I", kidx))
            kidx += 1
        elif isinstance(e, Entrypoint):
            entries[e.index] = len(code)
            kidoku.append(e.index + 1_000_000)
            code.extend(b"@" + struct.pack("<I", kidx))
            kidx += 1
        elif isinstance(e, LineRef) and (debug_info or e.force):
            code.extend(b"\x0a" + struct.pack("<I", e.line if debug_info else 0))
    header = bytearray(0x1CC)
    header[:4] = b"KP2K"
    struct.pack_into("<I", header, 4, 10002)
    current = now or datetime.datetime.now().astimezone()
    # OCaml's tm_wday uses Sunday=0; Python uses Monday=0.
    struct.pack_into(
        "<7H",
        header,
        8,
        current.year,
        current.month,
        (current.weekday() + 1) % 7,
        current.day,
        current.hour + 1,
        current.minute,
        current.second,
    )
    struct.pack_into("<4I", header, 0x20, len(kidoku), len(code), val_0x2c, val_0x2c + 5)
    struct.pack_into("<100I", header, 0x30, *entries)
    return bytes(header) + b"".join(struct.pack("<I", x) for x in kidoku) + bytes(code)
