class Tag:
    __slots__ = ("attrs", "kind", "name", "self_closing")

    START = 0
    END = 1

    def __init__(self, kind, name, attrs, self_closing=False):
        self.kind = kind
        self.name = name
        self.attrs = attrs if attrs is not None else {}
        self.self_closing = bool(self_closing)

    def __repr__(self):
        if self.attrs:
            if isinstance(self.attrs, dict):
                parts = [f"{name}={value!r}" for name, value in self.attrs.items()]
            else:
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
        kind_str = "start" if self.kind == self.START else "end"
        return f"<{kind_str}:{self.name}{closing} {attrs}>"


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

    Continue = 0
    Plaintext = 1
    RawData = 2
    Script = 3


class Token:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data
