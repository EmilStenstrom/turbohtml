from enum import Enum, auto

from turbohtml.node import Node


class DocumentState(Enum):
    """
    Enumerates document parser states for clarity and safety (head, body...).
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
    IN_CAPTION = auto()
    IN_FRAMESET = auto()
    AFTER_FRAMESET = auto()
    AFTER_HTML = auto()


class ContentState(Enum):
    """
    Enumerates content parser states for clarity and safety (rawtext...).
    """
    NONE = auto()
    RAWTEXT = auto()
    PLAINTEXT = auto()


class ParseContext:
    """
    Holds parser state during the parsing process.
    """

    def __init__(
        self, length: int, body_node: "Node", html_node: "Node", debug_callback=None
    ):
        self.index = 0
        self.length = length
        self._current_parent = body_node
        self.current_context = None
        self.has_form = False
        self.in_rawtext = False
        self.rawtext_start = 0
        self.html_node = html_node
        self._document_state = DocumentState.INITIAL
        self._content_state = ContentState.NONE
        self.current_table = None
        self.active_block = None
        self._debug = debug_callback
        self.doctype_seen = False
        
        # Adoption Agency Algorithm data structures
        from turbohtml.adoption import ActiveFormattingElements, OpenElementsStack
        self.active_formatting_elements = ActiveFormattingElements()
        self.open_elements = OpenElementsStack()
        self.adoption_agency_counter = 0

    @property
    def current_parent(self) -> "Node":
        return self._current_parent

    @current_parent.setter
    def current_parent(self, new_parent: "Node") -> None:
        if new_parent is None:
            # This is a serious parsing error - we should never have a None parent
            error_msg = f"Attempt to set current_parent to None! Current state: {self}"
            if self._debug:
                self._debug(f"ERROR: {error_msg}")
            raise ValueError(error_msg)
        
        if new_parent != self._current_parent:
            if self._debug:
                old_name = self._current_parent.tag_name if self._current_parent else "None"
                new_name = new_parent.tag_name if new_parent else "None"
                self._debug(f"Parent change: {old_name} -> {new_name}")
        
        self._current_parent = new_parent

    @property
    def document_state(self) -> DocumentState:
        return self._document_state

    @document_state.setter
    def document_state(self, new_state: DocumentState) -> None:
        if new_state != self._document_state:
            if self._debug:
                self._debug(f"Document State change: {self._document_state} -> {new_state}")
            self._document_state = new_state

    @property
    def content_state(self) -> ContentState:
        return self._content_state

    @content_state.setter
    def content_state(self, new_state: ContentState) -> None:
        if new_state != self._content_state:
            if self._debug:
                self._debug(f"Content State change: {self._content_state} -> {new_state}")
            self._content_state = new_state

    def debug(self, message: str) -> None:
        if self._debug:
            self._debug(message)

    def __repr__(self):
        parent_name = self._current_parent.tag_name if self._current_parent else "None"
        return f"<ParseContext: doc_state={self.document_state.name}, content_state={self.content_state.name}, parent={parent_name}>"
