"""Recursive-descent Kepago parser based on ``keAstParser.mly``."""

from .errors import RLCError
from .kepago_ast import Expr, Program, Statement

PREC = {
    "=": 1,
    "+=": 1,
    "-=": 1,
    "*=": 1,
    "/=": 1,
    "%=": 1,
    "&=": 1,
    "|=": 1,
    "^=": 1,
    "<<=": 1,
    ">>=": 1,
    "||": 2,
    "&&": 3,
    "==": 4,
    "!=": 4,
    "<=": 5,
    "<": 5,
    ">=": 5,
    ">": 5,
    "|": 6,
    "^": 6,
    "+": 6,
    "-": 6,
    "&": 7,
    "*": 7,
    "/": 7,
    "%": 7,
    "<<": 8,
    ">>": 8,
}


class Parser:
    def __init__(self, tokens, symbol_table=None):
        self.ts = list(tokens)
        self.i = 0
        self.symbol_table = symbol_table

    @property
    def t(self):
        return self.ts[self.i]

    def take(self, k=None):
        t = self.t
        if k and t.type != k:
            raise RLCError(f"expected {k}, found {t.type}", t.location)
        self.i += 1
        return t

    def accept(self, k):
        return self.take() if self.t.type == k else None

    def parse(self):
        out = []
        while self.t.type not in ("EOF", "eof"):
            out.append(self.statement())
        return Program(out)

    def statement(self):
        t = self.t
        if self.accept(","):
            return self.statement()
        if t.type == "LABEL":
            self.take()
            return Statement("label", t.value, location=t.location)
        if t.type in ("halt", "break", "continue"):
            self.take()
            return Statement(t.type, location=t.location)
        if t.type == "op":
            self.take()
            self.take("<")
            op_type = self.take("INTEGER").value
            self.take(":")
            module_token = self.take()
            if module_token.type not in ("INTEGER", "IDENT"):
                raise RLCError("expected module identifier", module_token.location)
            self.take(":")
            code = self.take("INTEGER").value
            self.take(",")
            overload = self.take("INTEGER").value
            self.take(">")
            args = []
            if self.accept("("):
                while self.t.type != ")":
                    args.append(self.expr())
                    if not self.accept(","):
                        break
                self.take(")")
            return Statement(
                "expr",
                args=[
                    Expr(
                        "unknown_call",
                        (op_type, module_token.value, code, overload),
                        args,
                        t.location,
                    )
                ],
                location=t.location,
            )
        if t.type in ("int", "str", "bit", "bit2", "bit4", "byte"):
            return self.declaration()
        if t.type.startswith("#"):
            return self.directive()
        if t.type == ":":
            return self.block()
        if t.type == "if":
            self.take()
            cond = self.expr()
            yes = self.statement()
            no = self.statement() if self.accept("else") else None
            return Statement("if", args=[cond, yes, no], location=t.location)
        if t.type == "while":
            self.take()
            return Statement("while", args=[self.expr(), self.statement()], location=t.location)
        if t.type == "repeat":
            self.take()
            body = []
            while self.t.type != "till":
                body.append(self.statement())
            self.take()
            return Statement("repeat", args=[body, self.expr()], location=t.location)
        if t.type == "case":
            self.take()
            value = self.expr()
            cases = []
            while self.accept("of"):
                match = self.expr()
                body = []
                while self.t.type not in ("of", "other", "ecase"):
                    body.append(self.statement())
                cases.append((match, body))
            other = []
            if self.accept("other"):
                while self.t.type != "ecase":
                    other.append(self.statement())
            self.take("ecase")
            return Statement("case", (value, cases, other), location=t.location)
        if t.type == "raw":
            self.take()
            values = []
            while self.t.type != "endraw":
                values.append(self.take())
            self.take("endraw")
            return Statement("raw", values, location=t.location)
        if t.type == "return":
            self.take()
            return Statement("return", args=[self.expr()], location=t.location)
        e = self.expr()
        if e.kind == "bin" and e.value in (
            "=",
            "+=",
            "-=",
            "*=",
            "/=",
            "%=",
            "&=",
            "|=",
            "^=",
            "<<=",
            ">>=",
        ):
            return Statement("assign", e.value, e.args, t.location)
        if e.kind == "call" and e.value in ("goto_on", "goto_case") and self.accept("{"):
            entries = []
            while self.t.type != "}":
                if e.value == "goto_on":
                    entries.append((None, self.take("LABEL").value))
                else:
                    if self.t.type == "IDENT" and self.t.value == "_":
                        self.take()
                        match = None
                    else:
                        match = self.expr()
                    self.take(":")
                    entries.append((match, self.take("LABEL").value))
                if not (self.accept(";") or self.accept(",")):
                    break
            self.take("}")
            return Statement("goto_table", (e, entries), location=t.location)
        if (
            e.kind in ("call", "ident")
            and e.value
            in ("goto", "goto_if", "goto_unless", "gosub", "gosub_with", "goto_on", "goto_case")
            and self.t.type == "LABEL"
        ):
            labels = [self.take("LABEL").value]
            while self.t.type == "," and self.ts[self.i + 1].type == "LABEL":
                self.take(",")
                labels.append(self.take("LABEL").value)
            return Statement("goto_call", (e, labels), location=t.location)
        return Statement("expr", args=[e], location=t.location)

    def select_expr(self, t):
        name, opcode = t.value
        window = None
        params = []
        if self.accept("["):
            window = self.expr()
            self.take("]")
        if self.accept("("):
            while self.t.type != ")":
                first = self.expr()
                if self.t.type in ("if", ";", ":"):
                    conditions = []
                    while True:
                        cond = None
                        if self.accept("if"):
                            cond = self.expr()
                        if first.kind == "ident":
                            conditions.append(("flag", first.value, None, cond, first.location))
                        elif first.kind == "call" and len(first.args) == 1:
                            conditions.append(
                                ("value", first.value, first.args[0], cond, first.location)
                            )
                        else:
                            raise RLCError("invalid select condition", first.location)
                        if not self.accept(";"):
                            break
                        first = self.expr()
                    self.take(":")
                    text = self.expr()
                    params.append(("special", conditions, text))
                else:
                    params.append(("always", first))
                if not self.accept(","):
                    break
            self.take(")")
        return Expr("select", (name, opcode, window, params), location=t.location)

    def block(self):
        t = self.take(":")
        out = []
        while self.t.type != ";":
            if self.t.type == "EOF":
                raise RLCError("expected ';'", self.t.location)
            out.append(self.statement())
        self.take(";")
        return Statement("block", args=out, location=t.location)

    def declaration(self):
        t = self.take()
        bits = {"int": 32, "str": "str", "bit": 1, "bit2": 2, "bit4": 4, "byte": 8}[t.type]
        decls = []
        dirs = []
        if self.accept("("):
            while self.t.type != ")":
                dirs.append(self.take("IDENT").value)
                self.accept(",")
            self.take(")")
        while True:
            n = self.take("IDENT")
            size = None
            init = None
            addr = None
            if self.accept("["):
                size = self.expr() if self.t.type != "]" else "auto"
                self.take("]")
            if self.accept("="):
                if self.accept("{"):
                    vals = []
                    while self.t.type != "}":
                        vals.append(self.expr())
                        self.accept(",")
                    self.take("}")
                    init = vals
                else:
                    init = self.expr(2)
            if self.accept("->"):
                addr = (self.expr(), self.take("."), self.expr())
            decls.append((n.value, size, init, addr, n.location))
            if not self.accept(","):
                break
        return Statement("decl", (bits, dirs, decls), location=t.location)

    def directive(self):
        t = self.take()
        k = t.type
        if k in ("#inline", "#sinline"):
            name = self.take("IDENT")
            self.take("(")
            params = []
            while self.t.type != ")":
                optional = bool(self.accept("["))
                p = self.take("IDENT")
                default = None
                if self.accept("="):
                    default = self.expr()
                if optional:
                    self.take("]")
                params.append((p.value, optional, default))
                if not self.accept(","):
                    break
            self.take(")")
            body = self.statement()
            return Statement(
                "inline", (name.value, params, body, k == "#sinline"), location=t.location
            )
        if k == "#hiding":
            name = self.take("IDENT")
            return Statement("hiding", name.value, [self.statement()], t.location)
        if k in (
            "#entrypoint",
            "#kidoku_type",
            "#val_0x2c",
            "#target",
            "#version",
            "#file",
            "#character",
            "#resource",
            "#base_res",
            "#print",
            "#warn",
            "#error",
            "#exclude",
            "#load",
        ):
            return Statement("directive", (k[1:], self.expr()), location=t.location)
        if k in ("#define", "#sdefine", "#const", "#bind", "#ebind", "#redef", "#set"):
            vals = []
            while True:
                name = self.take("IDENT")
                op = self.take().type if self.t.type in PREC and PREC[self.t.type] == 1 else None
                val = self.expr(2) if op else Expr("int", 1, location=name.location)
                vals.append((name.value, op, val))
                if not self.accept(","):
                    break
            return Statement("definitions", (k[1:], vals), location=t.location)
        if k == "#undef":
            names = [self.take("IDENT").value]
            while self.accept(","):
                names.append(self.take("IDENT").value)
            return Statement("undef", names, location=t.location)
        if k in ("#if", "#ifdef", "#ifndef"):
            cond = self.expr()
            yes = []
            while self.t.type not in ("#else", "#elseif", "#endif"):
                yes.append(self.statement())
            no = self._conditional_tail()
            return Statement("compile_if", (k, cond), [yes, no], t.location)
        if k == "#for":
            name = self.take("IDENT")
            self.take("=")
            first = self.expr()
            self.take(".")
            self.take(".")
            last = self.expr()
            body = self.statement()
            return Statement("compile_for", (name.value, first, last, body), location=t.location)
        raise RLCError(f"unsupported directive {k}", t.location)

    def _conditional_tail(self):
        if self.t.type == "#elseif":
            et = self.take()
            cond = self.expr()
            yes = []
            while self.t.type not in ("#else", "#elseif", "#endif"):
                yes.append(self.statement())
            return [
                Statement("compile_if", ("#if", cond), [yes, self._conditional_tail()], et.location)
            ]
        if self.accept("#else"):
            out = []
            while self.t.type != "#endif":
                out.append(self.statement())
            self.take("#endif")
            return out
        self.take("#endif")
        return []

    def expr(self, minp=0):
        t = self.take()
        if t.type == "INTEGER":
            left = Expr("int", t.value, location=t.location)
        elif t.type == "RESOURCE_REF":
            left = Expr("res", t.value, location=t.location)
        elif t.type == "SELECT":
            left = self.select_expr(t)
        elif t.type == "STRING":
            left = Expr("str", t.value, location=t.location)
        elif t.type == "LABEL":
            left = Expr("label", t.value, location=t.location)
        elif t.type in ("-", "!", "~"):
            left = Expr("unary", t.type, [self.expr(9)], t.location)
        elif t.type == "(":
            # keAstParser.mly deliberately discards source parentheses.  The
            # normaliser later reintroduces only those needed by RealLive's
            # different operator precedence.
            left = self.expr()
            self.take(")")
        elif t.type in ("IDENT", "store") or t.type.startswith("int") or t.type.startswith("str"):
            left = Expr("ident", t.value, location=t.location)
        else:
            raise RLCError("expected expression", t.location)
        while True:
            if self.accept("("):
                args = []
                while self.t.type != ")":
                    if self.accept("{"):
                        values = []
                        while self.t.type != "}":
                            values.append(self.expr())
                            if not self.accept(","):
                                break
                        self.take("}")
                        args.append(Expr("complex", args=values, location=self.t.location))
                    else:
                        args.append(self.expr())
                    if not self.accept(","):
                        break
                self.take(")")
                left = Expr("call", left.value, args, left.location)
                continue
            if self.accept("["):
                idx = self.expr()
                self.take("]")
                left = Expr("index", left.value, [idx], left.location)
                continue
            p = PREC.get(self.t.type, -1)
            if p < minp:
                break
            op = self.take()
            right = self.expr(p + 1)
            left = Expr("bin", op.type, [left, right], op.location)
        return left
