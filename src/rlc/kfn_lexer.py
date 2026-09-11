"""Lexer matching ``src/common/kfnLexer.mll``."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class KfnTokenType(Enum):
    EOF = auto()
    MODULE = auto()
    FUN = auto()
    VER = auto()
    END = auto()
    INT = auto()
    INTC = auto()
    INTV = auto()
    STR = auto()
    STRC = auto()
    STRV = auto()
    RES = auto()
    SPECIAL = auto()
    INT_CONST = auto()
    IDENT = auto()
    STRING = auto()
    EQUALS = auto()
    LANGLE = auto()
    RANGLE = auto()
    COMMA = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    QUESTION = auto()
    STAR = auto()
    PLUS = auto()
    COLON = auto()
    DOT = auto()
    HASH = auto()
    HYPHEN = auto()


@dataclass(frozen=True)
class KfnToken:
    type: KfnTokenType
    value: object
    line: int
    column: int

    def __str__(self):
        return f"KfnToken({self.type.name}, {self.value!r}, L{self.line}C{self.column})"


class KfnLexerError(Exception):
    def __init__(self, message, line, column):
        super().__init__(f"KfnLexerError: {message} at L{line}C{column}")
        self.line = line
        self.column = column


_KW = {
    "module": KfnTokenType.MODULE,
    "fun": KfnTokenType.FUN,
    "ver": KfnTokenType.VER,
    "end": KfnTokenType.END,
    "int": KfnTokenType.INT,
    "intC": KfnTokenType.INTC,
    "intV": KfnTokenType.INTV,
    "str": KfnTokenType.STR,
    "strC": KfnTokenType.STRC,
    "strV": KfnTokenType.STRV,
    "res": KfnTokenType.RES,
    "special": KfnTokenType.SPECIAL,
}
_P = {
    "=": KfnTokenType.EQUALS,
    "<": KfnTokenType.LANGLE,
    ">": KfnTokenType.RANGLE,
    ",": KfnTokenType.COMMA,
    "(": KfnTokenType.LPAREN,
    ")": KfnTokenType.RPAREN,
    "{": KfnTokenType.LBRACE,
    "}": KfnTokenType.RBRACE,
    "?": KfnTokenType.QUESTION,
    "*": KfnTokenType.STAR,
    "+": KfnTokenType.PLUS,
    ":": KfnTokenType.COLON,
    ".": KfnTokenType.DOT,
    "#": KfnTokenType.HASH,
    "-": KfnTokenType.HYPHEN,
}


class KfnLexer:
    def __init__(self, text: str, file_path: Optional[str] = None):
        self.text = text
        self.text_file_path = file_path or "<string>"
        self.pos = 0
        self.line = 1
        self.column = 1

    def _advance(self, n=1):
        for _ in range(n):
            ch = self.text[self.pos]
            self.pos += 1
            if ch == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1

    def get_next_token(self):
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in " \t\r\n":
                self._advance()
                continue
            if self.text.startswith("//", self.pos):
                while self.pos < len(self.text) and self.text[self.pos] != "\n":
                    self._advance()
                continue
            line, col = self.line, self.column
            if ch in _P:
                self._advance()
                return KfnToken(_P[ch], ch, line, col)
            if ch == "'":
                self._advance()
                start = self.pos
                while self.pos < len(self.text) and self.text[self.pos] != "'":
                    self._advance()
                if self.pos == len(self.text):
                    raise KfnLexerError("unterminated string", line, col)
                value = self.text[start : self.pos]
                self._advance()
                return KfnToken(KfnTokenType.STRING, value, line, col)
            if ch == "$":
                self._advance()
                start = self.pos
                while self.pos < len(self.text) and self.text[self.pos] in "0123456789abcdefABCDEF":
                    self._advance()
                if start == self.pos:
                    raise KfnLexerError("expected hexadecimal digits after '$'", line, col)
                return KfnToken(
                    KfnTokenType.INT_CONST, int(self.text[start : self.pos], 16), line, col
                )
            if ch.isdigit():
                start = self.pos
                while self.pos < len(self.text) and self.text[self.pos].isdigit():
                    self._advance()
                return KfnToken(KfnTokenType.INT_CONST, int(self.text[start : self.pos]), line, col)
            if ch.isalpha() or ch == "_":
                start = self.pos
                while self.pos < len(self.text) and (
                    self.text[self.pos].isalnum() or self.text[self.pos] in "_$?"
                ):
                    self._advance()
                value = self.text[start : self.pos]
                return KfnToken(_KW.get(value, KfnTokenType.IDENT), value, line, col)
            raise KfnLexerError(f"illegal character `{ch}' in reallive.kfn", line, col)
        return KfnToken(KfnTokenType.EOF, "", self.line, self.column)

    def tokenize_all(self):
        out = []
        while True:
            t = self.get_next_token()
            out.append(t)
            if t.type is KfnTokenType.EOF:
                return out
