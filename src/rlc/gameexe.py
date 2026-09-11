"""GAMEEXE.INI reader corresponding to iniLexer.mll/iniParser.mly."""

import re


def _split_values(text):
    values = []
    token = []
    quoted = False
    depth = 0
    for char in text:
        if char == '"':
            quoted = not quoted
            token.append(char)
        elif not quoted and char == "(":
            if depth == 0 and "".join(token).strip():
                values.append("".join(token).strip())
                token = []
            depth += 1
            token.append(char)
        elif not quoted and char == ")":
            depth -= 1
            token.append(char)
        elif not quoted and depth == 0 and char in ",:=":
            if "".join(token).strip():
                values.append("".join(token).strip())
            token = []
        else:
            token.append(char)
    if "".join(token).strip():
        values.append("".join(token).strip())
    result = []
    for value in values:
        if value.startswith('"') and value.endswith('"'):
            result.append(value[1:-1])
        elif value == "U":
            result.append(True)
        elif value == "N":
            result.append(False)
        elif value.startswith("(") and value.endswith(")"):
            result.append([int(x.strip()) for x in value[1:-1].split(",") if x.strip()])
        else:
            try:
                result.append(int(value, 10))
            except ValueError:
                result.append(value)
    return result


def _normalise_key(key):
    parts = key.strip().split(".")
    return ".".join(f"{int(part):03d}" if part.isdigit() else part for part in parts).lower()


def parse_gameexe(source):
    """Return the case-insensitive definition table used by Ini.find."""
    definitions = {}
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or not line.startswith("#"):
            continue
        line = line[1:]
        if "=" not in line:
            continue
        lhs, rhs = line.split("=", 1)
        lhs = lhs.strip()
        # These records are explicitly ignored by iniParser.mly.
        if lhs in ("DSTRACK", "CDTRACK", "NAMAE"):
            continue
        ranged = re.fullmatch(r"([A-Z_0-9]+)\.(\d+):(\d+)\.([A-Z_0-9\[\]]+)", lhs)
        parsed = _split_values(rhs)
        if ranged:
            stem, first, last, tail = ranged.groups()
            for index in range(int(first), int(last) + 1):
                definitions[f"{stem}.{index:03d}.{tail}".lower()] = parsed
        else:
            definitions[_normalise_key(lhs)] = parsed
    return definitions


def load_gameexe(path, encoding="cp932"):
    with open(path, "rb") as stream:
        raw = stream.read()
    return parse_gameexe(raw.decode(encoding))
