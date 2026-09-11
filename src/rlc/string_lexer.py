"""String tokeniser corresponding to ``src/rlc/strLexer.ml``.

It preserves control codes as structured tokens; strings are not flattened
before textout/type checking.
"""

from dataclasses import dataclass

from .common import Location
from .errors import RLCError


@dataclass(frozen=True)
class StringToken:
    kind: str
    value: object = None
    location: Location = None


@dataclass(frozen=True)
class StringLiteral:
    tokens: tuple[StringToken, ...]

    def plain(self):
        out = []
        for token in self.tokens:
            if token.kind == "text":
                out.append(str(token.value))
            elif token.kind == "space":
                out.append(" " * int(token.value))
            elif token.kind == "dquote":
                out.append('"')
            elif token.kind == "llentic":
                out.append("\u3010")
            elif token.kind == "rlentic":
                out.append("\u3011")
            elif token.kind == "asterisk":
                out.append("\uff0a")
            elif token.kind == "percent":
                out.append("\uff05")
            elif token.kind == "hyphen":
                out.append("-")
            else:
                return None
        return "".join(out)


class StringLexer:
    def __init__(self, source, start, quote, filename, line, column):
        self.source = source
        self.pos = start
        self.quote = quote
        self.filename = filename
        self.line = line
        self.column = column

    def loc(self):
        return Location(self.filename, self.line, self.column)

    def advance(self, n=1):
        for _ in range(n):
            c = self.source[self.pos]
            self.pos += 1
            if c == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1

    def _closed(self):
        depth = 0
        start = self.pos
        while self.pos < len(self.source):
            c = self.source[self.pos]
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    fragment = self.source[start : self.pos]
                    self.advance()
                    return fragment
                depth -= 1
            self.advance()
        raise RLCError("unterminated string: expected `}' in control code", self.loc())

    def _arguments(self, text, location):
        if not text.strip():
            return ()
        from .lexer import Lexer
        from .parser import Parser

        parser = Parser(Lexer(text, self.filename, start_line=location.line).tokens())
        values = []
        while parser.t.type != "EOF":
            values.append(parser.expr())
            if not parser.accept(","):
                break
        if parser.t.type != "EOF":
            raise RLCError("expected expression", parser.t.location)
        return tuple(values)

    def scan(self):
        tokens = []
        text = []
        textloc = self.loc()

        def flush():
            nonlocal text, textloc
            if text:
                tokens.append(StringToken("text", "".join(text), textloc))
                text = []

        while self.pos < len(self.source):
            loc = self.loc()
            c = self.source[self.pos]
            if c == self.quote:
                flush()
                self.advance()
                return StringLiteral(tuple(tokens)), self.pos, self.line, self.column
            if c == "\r":
                self.advance()
                continue
            if c == "\n":
                flush()
                self.advance()
                tokens.append(StringToken("space", 1, self.loc()))
                textloc = self.loc()
                continue
            if c in " \t\u3000":
                flush()
                width = 0
                while self.pos < len(self.source) and self.source[self.pos] in " \t\u3000":
                    width += 2 if self.source[self.pos] in "\t\u3000" else 1
                    self.advance()
                tokens.append(StringToken("space", width, loc))
                textloc = self.loc()
                continue
            if c == '"':
                # A double quote terminates only a double-quoted Kepago
                # literal.  In single-quoted and resource strings strLexer.ml
                # emits DQuote so textout can escape it in bytecode.
                flush()
                self.advance()
                tokens.append(StringToken("dquote", None, loc))
                textloc = self.loc()
                continue
            if c != "\\":
                # In resource strings a single quote is not a terminator, but
                # strLexer returns it as its own Text token.  Token boundaries
                # affect selective quoting in function/select parameters.
                if c == "'" and self.quote == "\0":
                    flush()
                    self.advance()
                    tokens.append(StringToken("text", "'", loc))
                    textloc = self.loc()
                    continue
                if c == "}":
                    flush()
                    self.advance()
                    tokens.append(StringToken("rcur", None, loc))
                    textloc = self.loc()
                    continue
                special = {
                    "\u3010": "llentic",
                    "\u3011": "rlentic",
                    "\uff0a": "asterisk",
                    "\uff05": "percent",
                    "-": "hyphen",
                }.get(c)
                if special:
                    flush()
                    self.advance()
                    tokens.append(StringToken(special, None, loc))
                    textloc = self.loc()
                else:
                    text.append(c)
                    self.advance()
                continue
            flush()
            self.advance()
            if self.pos >= len(self.source):
                raise RLCError("unterminated string", loc)
            if self.source[self.pos] == "\n":
                self.advance()
                textloc = self.loc()
                continue
            if self.source.startswith("name", self.pos) or self.source[self.pos] == "{":
                if self.source[self.pos] == "{":
                    self.advance()
                else:
                    self.advance(4)
                    while self.pos < len(self.source) and self.source[self.pos].isspace():
                        self.advance()
                    if self.pos >= len(self.source) or self.source[self.pos] != "{":
                        raise RLCError("expected `{' after \\name", loc)
                    self.advance()
                tokens.append(StringToken("speaker", None, loc))
                textloc = self.loc()
                continue
            if self.source[self.pos] == "_":
                self.advance()
                tokens.append(StringToken("space", 1, loc))
                textloc = self.loc()
                continue
            if self.source[self.pos] == '"':
                self.advance()
                tokens.append(StringToken("dquote", None, loc))
                textloc = self.loc()
                continue
            start = self.pos
            start_column = self.column
            while self.pos < len(self.source) and (
                (self.source[self.pos].isascii() and self.source[self.pos].isalpha())
                or self.source[self.pos] == "_"
            ):
                self.advance()
            code = self.source[start : self.pos]
            if not code:
                text.append(self.source[self.pos])
                self.advance()
                textloc = loc
                continue
            probe = self.pos
            while probe < len(self.source) and self.source[probe] in " \t\u3000":
                probe += 1
            if len(code) > 1 and (probe >= len(self.source) or self.source[probe] not in ":{"):
                # The single-letter no-argument rule precedes the named-code
                # rule in strLexer.mll: ``\pRight`` is code p plus "Right".
                code = code[0]
                self.pos = start + 1
                self.column = start_column + 1
            if len(code) == 1 and (probe >= len(self.source) or self.source[probe] not in ":{"):
                # The one-letter rule consumes only ``\\x``.  Whitespace
                # following a no-braces code remains a Space token.
                tokens.append(StringToken("code", (code, None, ()), loc))
                textloc = self.loc()
                continue
            while self.pos < len(self.source) and self.source[self.pos] in " \t\u3000":
                self.advance()
            if code == "d":
                if self.source.startswith("{}", self.pos):
                    self.advance(2)
                tokens.append(StringToken("delete", None, loc))
                textloc = self.loc()
                continue
            if code == "a" and (self.pos >= len(self.source) or self.source[self.pos] != "{"):
                tokens.append(StringToken("add", "", loc))
                textloc = self.loc()
                continue
            opt = None
            if self.pos < len(self.source) and self.source[self.pos] == ":":
                self.advance()
                optstart = self.pos
                parens = 0
                while self.pos < len(self.source):
                    ch = self.source[self.pos]
                    if ch == "(":
                        parens += 1
                    elif ch == ")" and parens:
                        parens -= 1
                    elif ch == "{" and not parens:
                        break
                    if ch == "\n":
                        raise RLCError("unterminated string", loc)
                    self.advance()
                if self.pos == len(self.source):
                    raise RLCError("unterminated string", loc)
                parsed = self._arguments(self.source[optstart : self.pos], loc)
                if len(parsed) != 1:
                    raise RLCError("expected expression before control-code arguments", loc)
                opt = parsed[0]
            elif self.pos >= len(self.source) or self.source[self.pos] != "{":
                # strLexer accepts one-letter codes without braces.
                if len(code) == 1:
                    tokens.append(StringToken("code", (code, None, ()), loc))
                    textloc = self.loc()
                    continue
                raise RLCError(f"expected `{{' after \\{code}", loc)
            if self.pos < len(self.source) and self.source[self.pos] == "{":
                self.advance()
            argtext = self._closed()
            args = self._arguments(argtext, loc)
            if code in ("l", "m"):
                if not 1 <= len(args) <= 2:
                    raise RLCError(f"expected argument to control code \\{code}{{}}", loc)
                first = args[0]
                if first.kind == "ident" and 1 <= len(first.value) <= 2:

                    def letter_value(char):
                        if "a" <= char <= "z":
                            return ord(char) - ord("a")
                        if "A" <= char <= "Z":
                            return ord(char) - ord("A")
                        if "\uff21" <= char <= "\uff3a":
                            return ord(char) - ord("\uff21")
                        raise ValueError

                    try:
                        vals = [letter_value(char) for char in first.value]
                        index = vals[0] if len(vals) == 1 else (vals[0] + 1) * 26 + vals[1]
                        from .kepago_ast import Expr

                        args = (Expr("int", index, location=first.location),) + args[1:]
                    except ValueError:
                        pass
                tokens.append(
                    StringToken("name", ("local" if code == "l" else "global", args), loc)
                )
            else:
                tokens.append(StringToken("code", (code, opt, args), loc))
            textloc = self.loc()
        raise RLCError("unterminated string", self.loc())
