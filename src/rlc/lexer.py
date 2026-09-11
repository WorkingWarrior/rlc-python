"""Unicode Kepago lexer, transcribed from ``keULexer.ml``."""

from dataclasses import dataclass

from .common import Location
from .errors import RLCError


@dataclass(frozen=True)
class Token:
    type: str
    value: object
    location: Location


KEYWORDS = {
    x.upper(): x
    for x in "eof halt op return if else while repeat till for case of other ecase break continue raw endraw int str bit bit2 bit4 byte".split()
}
SELECTS = {
    "select_w": 0,
    "select": 1,
    "select_s2": 2,
    "select_s": 3,
    "select_w2": 10,
    "select_msgcancel": 11,
    "select_btncancel": 12,
    "select_btnwkcancel": 13,
}
for x in "#file #resource #base_res #entrypoint #character #val_0x2c #kidoku_type #print #error #warn #exclude #hiding #define #sdefine #undef #redef #const #bind #ebind #set #target #version #inline #sinline #load #if #ifdef #ifndef #else #elseif #endif #for".split():
    KEYWORDS[x.upper()] = x
OPS = (
    "<<=",
    ">>=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "<<",
    ">>",
    "->",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    ":",
    ";",
    ",",
    ".",
    "=",
    "+",
    "-",
    "*",
    "/",
    "%",
    "&",
    "|",
    "^",
    "<",
    ">",
    "!",
    "~",
)


class Lexer:
    def __init__(self, source_code: str, filename=None, start_line=1):
        self.source_code = source_code
        self.filename = filename
        self.pos = 0
        self.line = start_line
        self.col = 1

    def _loc(self):
        return Location(self.filename, self.line, self.col)

    def _adv(self, n=1):
        for _ in range(n):
            c = self.source_code[self.pos]
            self.pos += 1
            if c == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1

    def tokens(self):
        s = self.source_code
        while self.pos < len(s):
            c = s[self.pos]
            if c.isspace():
                self._adv()
                continue
            if s.startswith("//", self.pos):
                while self.pos < len(s) and s[self.pos] != "\n":
                    self._adv()
                continue
            if s.startswith("{-", self.pos):
                loc = self._loc()
                self._adv(2)
                while self.pos < len(s) and not s.startswith("-}", self.pos):
                    self._adv()
                if self.pos == len(s):
                    raise RLCError("unterminated comment", loc)
                self._adv(2)
                continue
            loc = self._loc()
            if s.startswith("#res", self.pos):
                endword = self.pos + 4
                probe = endword
                while probe < len(s) and s[probe].isspace():
                    probe += 1
                if probe < len(s) and s[probe] == "<":
                    while self.pos <= probe:
                        self._adv()
                    start = self.pos
                    while self.pos < len(s) and s[self.pos] != ">":
                        self._adv()
                    if self.pos == len(s):
                        raise RLCError("unterminated #res<...> reference", loc)
                    key = s[start : self.pos].strip()
                    if not key:
                        raise RLCError(
                            "anonymous resource string references not permitted in #res references",
                            loc,
                        )
                    if key.isdecimal():
                        key = str(int(key))
                    self._adv()
                    yield Token("RESOURCE_REF", key, loc)
                    continue
            if c in "'\"":
                from .string_lexer import StringLexer

                quote = c
                self._adv()
                literal, self.pos, self.line, self.col = StringLexer(
                    s, self.pos, quote, self.filename, self.line, self.col
                ).scan()
                yield Token("STRING", literal, loc)
                continue
            if c == "@":
                self._adv()
                start = self.pos
                while self.pos < len(s) and (s[self.pos].isalnum() or s[self.pos] in "_?$#"):
                    self._adv()
                if start == self.pos:
                    raise RLCError("empty label", loc)
                yield Token("LABEL", s[start : self.pos], loc)
                continue
            if c.isdigit() or c == "$":
                start = self.pos
                if c == "$":
                    self._adv()
                    base = 16
                else:
                    base = 10
                if c == "$" and self.pos < len(s) and s[self.pos] in "#%":
                    base = 2 if s[self.pos] == "#" else 8
                    self._adv()
                while self.pos < len(s) and (s[self.pos].isalnum() or s[self.pos] == "_"):
                    self._adv()
                raw = s[start : self.pos].replace("_", "")
                raw = (
                    raw[2:]
                    if raw.startswith(("$#", "$%"))
                    else raw[1:]
                    if raw.startswith("$")
                    else raw
                )
                try:
                    value = int(raw, base)
                except ValueError:
                    raise RLCError("invalid integer literal", loc)
                if value >= 2**31:
                    value -= 2**32
                yield Token("INTEGER", value, loc)
                continue
            if c.isalpha() or c in "_?#$" or ord(c) > 127:
                start = self.pos
                self._adv()
                while self.pos < len(s) and (
                    s[self.pos].isalnum() or s[self.pos] in "_?#$" or ord(s[self.pos]) > 127
                ):
                    self._adv()
                val = s[start : self.pos]
                lower = val.lower()
                if lower in SELECTS:
                    yield Token("SELECT", (lower, SELECTS[lower]), loc)
                else:
                    yield Token(KEYWORDS.get(lower.upper(), "IDENT"), val, loc)
                continue
            matched = False
            for op in OPS:
                if s.startswith(op, self.pos):
                    self._adv(len(op))
                    yield Token(op, op, loc)
                    matched = True
                    break
            if matched:
                continue
            raise RLCError(f"invalid character 0x{ord(c):02x} in source file", loc)
        yield Token("EOF", "", Location(self.filename, self.line, self.col))
