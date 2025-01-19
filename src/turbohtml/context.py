from enum import Enum, auto

from turbohtml.node import Node


class ParserState(Enum):
    """
    Enumerates parser states for clarity and safety.
    """

    INITIAL = auto()
    IN_HEAD = auto()
    AFTER_HEAD = auto()
    IN_BODY = auto()
    AFTER_BODY = auto()
    IN_TABLE = auto()
    IN_TABLE_BODY = auto()
    IN_ROW = auto()
    IN_CELL = auto()
    RAWTEXT = auto()
    IN_CAPTION = auto()
    IN_FRAMESET = auto()


class ParseContext:
    """
    Holds parser state during the parsing process.
    """

    def __init__(
        self, length: int, body_node: "Node", html_node: "Node", debug_callback=None
    ):
        self.index = 0
        self.length = length
        self.current_parent = body_node
        self.current_context = None
        self.has_form = False
        self.in_rawtext = False
        self.rawtext_start = 0
        self.html_node = html_node
        self._state = ParserState.INITIAL
        self.current_table = None
        self.active_block = None
        self._debug = debug_callback

    @property
    def state(self) -> ParserState:
        return self._state

    @state.setter
    def state(self, new_state: ParserState) -> None:
        if new_state != self._state:
            if self._debug:
                self._debug(f"State change: {self._state} -> {new_state}")
            self._state = new_state

    def debug(self, message: str) -> None:
        if self._debug:
            self._debug(message)

    def __repr__(self):
        parent_name = self.current_parent.tag_name if self.current_parent else "None"
        return f"<ParseContext: state={self.state.name}, parent={parent_name}>"
