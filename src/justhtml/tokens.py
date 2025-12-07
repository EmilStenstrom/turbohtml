class Tag:
    __slots__ = ("attrs", "kind", "name", "self_closing")

    START = 0
    END = 1

    def __init__(self, kind, name, attrs, self_closing=False):
        self.kind = kind
        self.name = name
        self.attrs = attrs if attrs is not None else {}
        self.self_closing = bool(self_closing)


class CharacterTokens:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class CommentToken:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class Doctype:
    __slots__ = ("force_quirks", "name", "public_id", "system_id")

    def __init__(self, name=None, public_id=None, system_id=None, force_quirks=False):
        self.name = name
        self.public_id = public_id
        self.system_id = system_id
        self.force_quirks = bool(force_quirks)


class DoctypeToken:
    __slots__ = ("doctype",)

    def __init__(self, doctype):
        self.doctype = doctype


class EOFToken:
    __slots__ = ()


class TokenSinkResult:
    __slots__ = ()

    Continue = 0
    Plaintext = 1


class ParseError:
    """Represents a parse error with location information."""

    __slots__ = ("code", "column", "line", "message")

    def __init__(self, code, line=None, column=None, message=None):
        self.code = code
        self.line = line
        self.column = column
        self.message = message or code

    def __repr__(self):
        if self.line is not None and self.column is not None:
            return f"ParseError({self.code!r}, line={self.line}, column={self.column})"
        return f"ParseError({self.code!r})"

    def __str__(self):
        if self.line is not None and self.column is not None:
            if self.message != self.code:
                return f"({self.line},{self.column}): {self.code} - {self.message}"
            return f"({self.line},{self.column}): {self.code}"
        if self.message != self.code:
            return f"{self.code} - {self.message}"
        return self.code

    def __eq__(self, other):
        if not isinstance(other, ParseError):
            return NotImplemented
        return self.code == other.code and self.line == other.line and self.column == other.column

    __hash__ = None  # Unhashable since we define __eq__
    RawData = 2
