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
    """Mutable parser state: stacks, modes, insertion point."""

    def __init__(self, length, initial_parent, debug_callback=None):
        # Input bounds
        self.index = 0
        self.length = length

        if initial_parent is None:
            raise ValueError("ParseContext requires a valid initial parent")
        self._current_parent = initial_parent
        self.current_context = None  # e.g. 'math' / 'svg'

        # States
        self._document_state = DocumentState.INITIAL
        self._content_state = ContentState.NONE
        self._debug = debug_callback
        self.doctype_seen = False
        self.frameset_ok = True  # Whether frameset still allowed

        # Adoption Agency data structures
        from turbohtml.adoption import ActiveFormattingElements, OpenElementsStack
        self.active_formatting_elements = ActiveFormattingElements()
        self.open_elements = OpenElementsStack()


    # --- Properties / helpers ---
    @property
    def current_parent(self):
        return self._current_parent

    def _set_current_parent(self, new_parent):
        if new_parent != self._current_parent:
            if self._debug:
                old_name = self._current_parent.tag_name if self._current_parent else "None"
                new_name = new_parent.tag_name if new_parent else "None"
                self._debug(f"Parent change: {old_name} -> {new_name}")
        self._current_parent = new_parent

    @property
    def document_state(self):
        return self._document_state

    @property
    def content_state(self):
        return self._content_state

    @content_state.setter
    def content_state(self, new_state):
        if new_state != self._content_state:
            if self._debug:
                self._debug(f"Content State change: {self._content_state} -> {new_state}")
            self._content_state = new_state

    def debug(self, message):
        if self._debug:
            self._debug(message)

    # --- State transitions ---
    def transition_to_state(self, new_state, new_parent=None):
        if new_parent is not None:
            self._set_current_parent(new_parent)
        if new_state != self._document_state:
            if self._debug:
                self._debug(f"Document State change: {self._document_state} -> {new_state}")
            self._document_state = new_state

    # --- Insertion point navigation ---
    def move_to_element(self, element):
        self._set_current_parent(element)

    def move_to_element_with_fallback(self, element, fallback):
        self._set_current_parent(element or fallback)

    def move_up_one_level(self):
        if self._current_parent.parent:
            self._set_current_parent(self._current_parent.parent)
            return True
        return False

    def move_to_ancestor_parent(self, ancestor):
        if ancestor and ancestor.parent:
            self._set_current_parent(ancestor.parent)
            return True
        return False

    def close_element_by_tag(self, tag_name, stop_at_boundary=False):
        ancestor = self._current_parent.find_ancestor(tag_name, stop_at_boundary=stop_at_boundary)
        if ancestor:
            self._set_current_parent(ancestor.parent or self._current_parent)
            return True
        return False

    def enter_element(self, element):
        self._set_current_parent(element)

    def __repr__(self):
        parent_name = self._current_parent.tag_name if self._current_parent else "None"
        return (
            f"<ParseContext: doc_state={self.document_state.name}, "
            f"content_state={self.content_state.name}, parent={parent_name}>"
        )
