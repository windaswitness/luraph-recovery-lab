"""Small, non-executing Lua/Luau lexer used by the recovery adapters.

Tokens retain the historical ``(kind, raw, character_offset)`` interface.
This is not a Lua parser. Interpolated strings are deliberately unsupported.
Offsets count Unicode characters, not UTF-8 bytes; lines/columns are one-based.
"""
from __future__ import annotations

import re

LONG = re.compile(r"\[(=*)\[")
IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_DEC = r"[0-9](?:_?[0-9])*"
_HEX = r"[0-9a-fA-F](?:_?[0-9a-fA-F])*"
NUMBER = re.compile(
    rf"(?:0[xX]{_HEX}(?:\.(?!\.)(?:{_HEX})?)?(?:[pP][+-]?{_DEC})?"
    rf"|0[bB][01](?:_?[01])*"
    rf"|(?:{_DEC}(?:\.(?!\.)(?:{_DEC})?)?|\.{_DEC})(?:[eE][+-]?{_DEC})?)"
)
_SPACE = " \t\r\n\v\f"
_OPS = ("...", "..=", "//=", "==", "~=", "<=", ">=", "+=", "-=", "*=",
        "/=", "%=", "^=", "..", "//", "::", "->")


def location(source: str, offset: int) -> tuple[int, int]:
    """Return a one-based line and column, treating CRLF as one newline."""
    prefix = source[:offset]
    endings = list(re.finditer(r"\r\n|\n\r|\r|\n", prefix))
    return len(endings) + 1, offset - (endings[-1].end() if endings else 0) + 1


class LuaLexError(ValueError):
    def __init__(self, message: str, source: str, offset: int = 0):
        self.message = message
        self.offset = offset
        self.line, self.column = location(source, offset)
        super().__init__(f"{message} at line {self.line}, column {self.column} (offset {offset})")


def decode(raw: str, *, permissive_unknown_escapes: bool = False) -> bytes:
    """Decode one literal without executing Lua.

    Unknown escapes are rejected by default. The explicit compatibility option
    only permits a backslash followed by an otherwise unknown character; it
    never relaxes malformed hexadecimal, Unicode, or decimal escapes.
    """
    if not isinstance(raw, str):
        raise TypeError("literal must be str")
    if raw.startswith("["):
        match = LONG.match(raw)
        if not match:
            raise LuaLexError("Invalid long-string opener", raw)
        close = "]" + match[1] + "]"
        end = raw.find(close, match.end())
        if end < 0:
            raise LuaLexError("Unterminated long string", raw)
        if end + len(close) != len(raw):
            raise LuaLexError("Trailing content after long string", raw, end + len(close))
        value = re.sub(r"\r\n|\n\r|\r|\n", "\n", raw[match.end():end])
        if value.startswith("\n"):
            value = value[1:]
        try:
            return value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise LuaLexError("Invalid Unicode scalar in string", raw, match.end() + exc.start) from exc
    if len(raw) < 2 or raw[0] not in "\"'" or raw[-1] != raw[0]:
        raise LuaLexError("Expected a complete quoted string", raw)
    out = bytearray()
    end = len(raw) - 1
    i = 1
    escapes = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11}
    while i < end:
        char = raw[i]
        if char != "\\":
            if char == raw[0]:
                raise LuaLexError("Unescaped quote inside string", raw, i)
            if char in "\r\n":
                raise LuaLexError("Unescaped newline in quoted string", raw, i)
            try:
                out.extend(char.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise LuaLexError("Invalid Unicode scalar in string", raw, i) from exc
            i += 1
            continue
        escape_at = i
        i += 1
        if i >= end:
            raise LuaLexError("Incomplete escape", raw, escape_at)
        char = raw[i]
        i += 1
        if char == "z":
            while i < end and raw[i] in _SPACE:
                i += 1
        elif char == "x":
            digits = raw[i:i + 2]
            if i + 2 > end or not re.fullmatch(r"[0-9a-fA-F]{2}", digits):
                raise LuaLexError("Hex escape needs exactly two hexadecimal digits", raw, escape_at)
            out.append(int(digits, 16))
            i += 2
        elif char == "u":
            close = raw.find("}", i, end)
            digits = raw[i + 1:close] if close >= 0 else ""
            if i >= end or raw[i] != "{" or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                raise LuaLexError("Unicode escape needs hexadecimal digits in braces", raw, escape_at)
            if len(digits) > 8:
                raise LuaLexError("Unicode escape is out of range", raw, escape_at)
            scalar = int(digits, 16)
            if scalar > 0x10FFFF or 0xD800 <= scalar <= 0xDFFF:
                raise LuaLexError("Unicode escape is not a Unicode scalar", raw, escape_at)
            out.extend(chr(scalar).encode("utf-8"))
            i = close + 1
        elif char in "0123456789":
            digits = char
            while len(digits) < 3 and i < end and raw[i] in "0123456789":
                digits += raw[i]
                i += 1
            value = int(digits)
            if value > 255:
                raise LuaLexError("Decimal byte escape exceeds 255", raw, escape_at)
            out.append(value)
        elif char in escapes:
            out.append(escapes[char])
        elif char in "\\\"'":
            out.append(ord(char))
        elif char in "\r\n":
            if i < end and raw[i] in "\r\n" and raw[i] != char:
                i += 1
            out.append(10)
        elif permissive_unknown_escapes:
            out.extend(char.encode("utf-8"))
        else:
            raise LuaLexError(f"Unknown escape \\{char}", raw, escape_at)
    return bytes(out)


def scan(src: str):
    """Yield tokens, validating strings and refusing ambiguous malformed numbers."""
    if not isinstance(src, str):
        raise TypeError("source must be str")
    i = 0
    while i < len(src):
        start = i
        char = src[i]
        if char in _SPACE:
            i += 1
            continue
        comment = src.startswith("--", i)
        long_match = LONG.match(src, i + 2 if comment else i)
        if long_match:
            close = "]" + long_match[1] + "]"
            end = src.find(close, long_match.end())
            if end < 0:
                raise LuaLexError("Unterminated long comment" if comment else "Unterminated long string", src, start)
            i = end + len(close)
            kind = "comment" if comment else "long"
        elif comment:
            match = re.search(r"[\r\n]", src[i:])
            i = i + match.start() if match else len(src)
            kind = "comment"
        elif char in "\"'":
            i += 1
            while i < len(src):
                if src[i] == char:
                    i += 1
                    break
                if src[i] == "\\":
                    i += 2
                else:
                    i += 1
            else:
                raise LuaLexError("Unterminated quoted string", src, start)
            kind = "string"
        elif char == "`":
            raise LuaLexError("Interpolated Luau strings are unsupported; refusing to rewrite", src, i)
        elif (match := NUMBER.match(src, i)):
            i = match.end()
            if i < len(src) and (src[i].isalnum() or src[i] == "_"):
                raise LuaLexError("Malformed numeric literal", src, start)
            kind = "number"
        elif (match := IDENT.match(src, i)):
            i = match.end()
            kind = "identifier"
        else:
            operator = next((op for op in _OPS if src.startswith(op, i)), char)
            i += len(operator)
            kind = "symbol"
        raw = src[start:i]
        if kind in ("string", "long"):
            try:
                decode(raw)
            except LuaLexError as exc:
                raise LuaLexError(exc.message, src, start + exc.offset) from exc
        yield kind, raw, start


def quote(value: bytes) -> str:
    """Render a lossless ASCII-only Lua byte-string literal."""
    if not isinstance(value, (bytes, bytearray)):
        raise TypeError("quote expects bytes or bytearray")
    return '"' + ''.join(
        chr(byte) if 32 <= byte <= 126 and byte not in (34, 92)
        else "\\" + chr(byte) if byte in (34, 92)
        else f"\\{byte:03d}" for byte in value
    ) + '"'


def normalize_number(raw: str) -> str:
    value = raw.replace("_", "")
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", value):
        return str(int(value, 16))
    if re.fullmatch(r"0[bB][01]+", value):
        return str(int(value, 2))
    return value
