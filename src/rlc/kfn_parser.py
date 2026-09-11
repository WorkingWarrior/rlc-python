"""Recursive-descent transcription of ``src/common/kfnParser.mly``."""

from .kfn_data_structures import (
    FunctionSignature,
    Location,
    ParameterInfo,
    RLType,
    SpecialParameterDef,
)
from .kfn_lexer import KfnLexerError
from .kfn_lexer import KfnTokenType as T
from .versioning import is_version_compatible


class KfnParserError(Exception):
    def __init__(self, msg, tok=None):
        where = f" at line {tok.line}, column {tok.column}" if tok else ""
        super().__init__(f"Error: parsing reallive.kfn: {msg}{where}")
        self.line = getattr(tok, "line", None)
        self.column = getattr(tok, "column", None)


class KfnParser:
    def __init__(self, lexer, symbol_table, target_version, target_class="reallive"):
        self.lexer = lexer
        self.symbol_table = symbol_table
        self.target_version = target_version
        self.target_class = target_class.lower()
        self.parsed_modules = []
        self.parsed_functions = []
        self.modules_by_name = {}
        self.tok = lexer.get_next_token()

    def _next(self):
        old = self.tok
        try:
            self.tok = self.lexer.get_next_token()
        except KfnLexerError as e:
            raise KfnParserError(str(e), old) from e
        return old

    def _eat(self, t):
        if self.tok.type is not t:
            raise KfnParserError(f"expected {t.name}, found {self.tok.type.name}", self.tok)
        return self._next()

    def _accept(self, t):
        return self._next() if self.tok.type is t else None

    def _loc(self, t):
        return Location(self.lexer.text_file_path, t.line, t.column)

    def parse(self):
        while self.tok.type is not T.EOF:
            if self.tok.type is T.MODULE:
                self._module()
            elif self.tok.type is T.FUN:
                self._fun([])
            elif self.tok.type is T.VER:
                self._verblock()
            else:
                raise KfnParserError("syntax error", self.tok)
        for mid, name, loc in self.parsed_modules:
            self.symbol_table.define_module(mid, name, loc)
        compatible = []
        for f in self.parsed_functions:
            if is_version_compatible(f, self.target_version, self.target_class):
                f.module_name = self.symbol_table.lookup_module_name(f.module_id)
                self.symbol_table.define_function(f)
                compatible.append(f)
        return self.parsed_modules, compatible

    def _module(self):
        start = self._eat(T.MODULE)
        mid = int(self._eat(T.INT_CONST).value)
        if self._accept(T.EQUALS):
            name = str(self._eat(T.IDENT).value)
            self.modules_by_name[name] = mid
            self.parsed_modules.append((mid, name, self._loc(start)))

    def _vstamp(self):
        p = [str(self._eat(T.INT_CONST).value)]
        while self._accept(T.DOT):
            p.append(str(self._eat(T.INT_CONST).value))
        if len(p) > 4:
            raise KfnParserError("version has more than four components", self.tok)
        return ".".join(p)

    def _version(self):
        if self.tok.type is T.IDENT:
            return str(self._next().value).lower()
        if self.tok.type not in (T.LANGLE, T.RANGLE):
            raise KfnParserError("expected version constraint", self.tok)
        op = str(self._next().value)
        if self._accept(T.EQUALS):
            op += "="
        return op + self._vstamp()

    def _verblock(self):
        self._eat(T.VER)
        versions = [self._version()]
        while self._accept(T.COMMA):
            versions.append(self._version())
        while self.tok.type is T.FUN:
            self._fun(versions)
        self._eat(T.END)

    def _ccode(self):
        if not self._accept(T.LBRACE):
            return None, []
        flags = []
        if self._accept(T.RBRACE):
            return "", flags
        if self._accept(T.STAR):
            flags.append("textout")
        if self._accept(T.EQUALS):
            flags.append("no_braces")
            if "textout" in flags:
                flags.append("line_break")
        name = str(self._eat(T.IDENT).value)
        self._eat(T.RBRACE)
        return name, flags

    def _flags(self):
        if not self._accept(T.LPAREN):
            return []
        valid = {"store", "skip", "jump", "goto", "if", "neg", "cases", "gotos", "call", "ret"}
        out = []
        while self.tok.type is not T.RPAREN:
            flag = str(self._eat(T.IDENT).value).lower()
            if flag not in valid:
                raise KfnParserError(f"unknown flag {flag}", self.tok)
            out.append(flag)
        self._eat(T.RPAREN)
        return out

    def _fun(self, versions):
        start = self._eat(T.FUN)
        names = []
        if self.tok.type is T.END:
            names.append(str(self._next().value))
        while self.tok.type is T.IDENT and len(names) < 2:
            names.append(str(self._next().value))
        name = names[0] if names else ""
        alias = names[1] if len(names) > 1 else None
        ccode, ccflags = self._ccode()
        flags = self._flags()
        self._eat(T.LANGLE)
        typ = int(self._eat(T.INT_CONST).value)
        self._eat(T.COLON)
        if self.tok.type is T.INT_CONST:
            module = int(self._next().value)
        else:
            mt = self._eat(T.IDENT)
            if mt.value not in self.modules_by_name:
                raise KfnParserError(f"undeclared module {mt.value}", mt)
            module = self.modules_by_name[str(mt.value)]
        self._eat(T.COLON)
        opcode = int(self._eat(T.INT_CONST).value)
        self._eat(T.COMMA)
        overloads = int(self._eat(T.INT_CONST).value)
        self._eat(T.RANGLE)
        prototypes = []
        while self.tok.type in (T.QUESTION, T.LPAREN):
            prototypes.append(None if self._accept(T.QUESTION) else self._parameters())
        if len(prototypes) != overloads + 1:
            raise KfnParserError(f"incorrect overload count for {name}", start)
        first = next((x for x in prototypes if x is not None), [])
        self.parsed_functions.append(
            FunctionSignature(
                name=name,
                alias=alias,
                id=opcode,
                module_id=module,
                parameters=list(first),
                prototypes=prototypes,
                opcode_type=typ,
                overload_count=overloads,
                return_type=RLType.INT if "store" in flags else RLType.VOID,
                kfn_flags=ccflags + flags,
                kfn_ccode_name=(name if ccode == "" else ccode),
                kfn_ccode_flags=ccflags,
                location=self._loc(start),
                versions=list(versions),
                kfn_opcode_raw=f"<{typ}:{module}:{opcode},{overloads}>",
            )
        )

    def _parameters(self):
        self._eat(T.LPAREN)
        out = []
        if self._accept(T.RPAREN):
            return out
        while True:
            out.append(self._parameter())
            if not self._accept(T.COMMA):
                break
            # reallive.kfn 1.45 contains one historic trailing comma
            # (OBJFRONTCHILDSET_RECT).  Released rlc data must remain usable.
            if self.tok.type is T.RPAREN:
                break
        self._eat(T.RPAREN)
        return out

    def _parameter(self):
        flags = []
        fmap = {
            T.HASH: "text",
            T.QUESTION: "optional",
            T.LANGLE: "uncount",
            T.RANGLE: "return",
            T.EQUALS: "fake",
        }
        while self.tok.type in fmap:
            flags.append(fmap[self._next().type])
        p = (
            ParameterInfo(type=RLType.INT_C, tag=str(self._next().value))
            if self.tok.type is T.STRING
            else self._typedef()
        )
        while self.tok.type in (T.PLUS, T.STRING):
            if self._accept(T.PLUS):
                p.is_repeated = True
            else:
                p.tag = str(self._next().value)
        p.is_text_object = "text" in flags
        p.is_optional = "optional" in flags
        p.is_uncounted = "uncount" in flags
        p.is_return_value = "return" in flags
        p.is_fake = "fake" in flags
        return p

    def _typedef(self):
        m = {
            T.INT: RLType.INT,
            T.INTC: RLType.INT_C,
            T.INTV: RLType.INT_V,
            T.STR: RLType.STR,
            T.STRC: RLType.STR_C,
            T.STRV: RLType.STR_V,
            T.RES: RLType.RES,
        }
        if self.tok.type in m:
            return ParameterInfo(type=m[self._next().type])
        if self._accept(T.SPECIAL):
            p = ParameterInfo(type=RLType.SPECIAL)
            self._eat(T.LPAREN)
            while True:
                first = int(self._eat(T.INT_CONST).value)
                sid = (
                    ((first + 1) << 8) | int(self._eat(T.INT_CONST).value)
                    if self._accept(T.HYPHEN)
                    else first
                )
                self._eat(T.COLON)
                sf = []
                while self._accept(T.HASH):
                    sf.append("no_parens")
                if self._accept(T.LBRACE):
                    args = self._complex()
                    self._eat(T.RBRACE)
                    name = None
                else:
                    name = str(self._eat(T.IDENT).value)
                    args = self._parameters()
                p.special_params.append(SpecialParameterDef(sid, sf, name, args))
                if not self._accept(T.COMMA):
                    break
            self._eat(T.RPAREN)
            return p
        if self._accept(T.LPAREN):
            p = ParameterInfo(type=RLType.COMPLEX, complex_params=self._complex())
            self._eat(T.RPAREN)
            return p
        raise KfnParserError("expected parameter type", self.tok)

    def _complex(self):
        out = []
        while True:
            q = (
                ParameterInfo(type=RLType.INT_C, tag=str(self._next().value))
                if self.tok.type is T.STRING
                else self._typedef()
            )
            if self.tok.type is T.STRING:
                q.tag = str(self._next().value)
            out.append(q)
            if not self._accept(T.COMMA):
                return out
