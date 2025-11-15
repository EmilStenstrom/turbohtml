class Tag:
    __slots__ = ("attrs", "kind", "name", "self_closing")

    START = "start"
    END = "end"

    def __init__(self, kind, name, attrs, self_closing=False):
        self.kind = kind
        self.name = name
        self.attrs = attrs
        self.self_closing = bool(self_closing)

    def __repr__(self):
        if self.attrs:
            parts = []
            attrs = self.attrs
            for index in range(0, len(attrs), 2):
                name = attrs[index]
                value = attrs[index + 1]
                parts.append(f"{name}={value!r}")
            attrs = " ".join(parts)
        else:
            attrs = ""
        closing = " /" if self.self_closing else ""
        return f"<{self.kind}:{self.name}{closing} {attrs}>"


class CharacterTokens:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class CommentToken:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class Doctype:
    __slots__ = ("name", "public_id", "system_id", "force_quirks")

    def __init__(self, name=None, public_id=None, system_id=None, force_quirks=False):
        self.name = name
        self.public_id = public_id
        self.system_id = system_id
        self.force_quirks = bool(force_quirks)


class DoctypeToken:
    __slots__ = ("doctype",)

    def __init__(self, doctype):
        self.doctype = doctype


class NullCharacterToken:
    __slots__ = ()


class EOFToken:
    __slots__ = ()


class ParseError:
    __slots__ = ("message",)

    def __init__(self, message):
        self.message = message


class TokenSinkResult:
    __slots__ = ()

    Continue = "continue"
    Plaintext = "plaintext"
    RawData = "raw-data"
    Script = "script"


class Token:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data
