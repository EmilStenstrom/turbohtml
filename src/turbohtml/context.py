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
        self, length: int, initial_parent: "Node", debug_callback=None
    ):
        # Basic indexing/state
        self.index = 0
        self.length = length

        # Validate and set initial parent
        if initial_parent is None:
            raise ValueError("ParseContext requires a valid initial parent")
        self._current_parent = initial_parent
        self.current_context = None

        # Core parser states
        self._document_state = DocumentState.INITIAL
        self._content_state = ContentState.NONE
        self._debug = debug_callback
        self.doctype_seen = False

        # Adoption Agency Algorithm data structures
        from turbohtml.adoption import ActiveFormattingElements, OpenElementsStack
        self.active_formatting_elements = ActiveFormattingElements()
        self.open_elements = OpenElementsStack()
        self.adoption_agency_counter = 0

        # Template content isolation depth (acts like a stack counter)
        self.template_content_depth = 0
        # Transparent template parsing depth (e.g., inside frameset, treat <template> as transparent)
        self.template_transparent_depth = 0

    @property
    def current_parent(self) -> "Node":
        """Read-only access to current parent. Use navigation methods to change."""
        return self._current_parent

    def _set_current_parent(self, new_parent: "Node") -> None:
        """Internal method to update current parent. Should only be called by navigation methods."""
        if new_parent != self._current_parent:
            if self._debug:
                old_name = self._current_parent.tag_name if self._current_parent else "None"
                new_name = new_parent.tag_name if new_parent else "None"
                self._debug(f"Parent change: {old_name} -> {new_name}")
        self._current_parent = new_parent

    @property
    def document_state(self) -> DocumentState:
        """Read-only access to document state. Use transition_to_state() to change."""
        return self._document_state

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

    # State transition methods
    def transition_to_state(self, new_state: DocumentState, new_parent: "Node" = None) -> None:
        """Transition to any document state, optionally updating current_parent"""
        if new_parent is not None:
            self._set_current_parent(new_parent)
        if new_state != self._document_state:
            if self._debug:
                self._debug(f"Document State change: {self._document_state} -> {new_state}")
            self._document_state = new_state

    # Navigation methods for current_parent
    def move_to_element(self, element: "Node") -> None:
        """Move current_parent to a specific element"""
        self._set_current_parent(element)

    def move_to_element_with_fallback(self, element: "Node", fallback: "Node") -> None:
        """Move current_parent to element, or fallback if element is None"""
        self._set_current_parent(element or fallback)

    def move_up_one_level(self) -> bool:
        """Move current_parent up one level to its parent. Returns True if successful."""
        if self._current_parent.parent:
            self._set_current_parent(self._current_parent.parent)
            return True
        return False

    def move_to_ancestor_parent(self, ancestor: "Node") -> bool:
        """Move current_parent to the parent of the given ancestor. Returns True if successful."""
        if ancestor and ancestor.parent:
            self._set_current_parent(ancestor.parent)
            return True
        return False

    def close_element_by_tag(self, tag_name: str, stop_at_boundary: bool = False) -> bool:
        """Find ancestor by tag name and move to its parent. Returns True if found."""
        ancestor = self._current_parent.find_ancestor(tag_name, stop_at_boundary=stop_at_boundary)
        if ancestor:
            self._set_current_parent(ancestor.parent or self._current_parent)
            return True
        return False

    def enter_element(self, element: "Node") -> None:
        """Enter a newly created element (set it as current_parent)"""
        self._set_current_parent(element)

    def __repr__(self):
        parent_name = self._current_parent.tag_name if self._current_parent else "None"
        return f"<ParseContext: doc_state={self.document_state.name}, content_state={self.content_state.name}, parent={parent_name}>"
