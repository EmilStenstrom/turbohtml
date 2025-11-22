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


class ParseError:
    __slots__ = ("message",)

    def __init__(self, message):
        self.message = message


class TokenSinkResult:
    __slots__ = ()

    Continue = 0
    Plaintext = 1
    RawData = 2
