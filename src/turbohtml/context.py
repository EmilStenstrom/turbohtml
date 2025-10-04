from enum import Enum, auto

from turbohtml.adoption import ActiveFormattingElements, OpenElementsStack


class DocumentState(Enum):
    """Enumerates document parser states for clarity and safety (head, body...)."""

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
    """Enumerates content parser states for clarity and safety (rawtext...)."""

    NONE = auto()
    RAWTEXT = auto()
    PLAINTEXT = auto()


class ParseContext:
    """Mutable parser state: stacks, modes, insertion point."""

    def __init__(self, initial_parent, debug_callback=None):
        if initial_parent is None:
            msg = "ParseContext requires a valid initial parent"
            raise ValueError(msg)
        self._current_parent = initial_parent
        self.current_context = None  # e.g. 'math' / 'svg'

        # States
        self._document_state = DocumentState.INITIAL
        self._content_state = ContentState.NONE
        self._debug = debug_callback
        self.doctype_seen = False
        self.frameset_ok = True

        # Tree construction algorithm stacks (HTML5 spec §13.2.4)
        self.active_formatting_elements = ActiveFormattingElements()
        self.open_elements = OpenElementsStack()

        # HTML Standard form element pointer (§4.10.3): tracks most recently opened <form>
        # outside templates. Additional <form> tags are ignored until pointer is cleared.
        self.form_element = None

        # Frameset-specific flag: Was </html> end tag explicit (vs. implied)?
        self.saw_html_end_tag = False

        # Body start tag tracking: whether literal <body> start tag appeared (affects comment placement)
        self.saw_body_start_tag = False

        # Adoption agency temporal signal: set when adoption restructures tree to trigger
        # active formatting element reconstruction before next character token (§13.2.6.4.8)
        self.needs_reconstruction = False

        # End tag processing gate: True during end-tag dispatch to prevent adoption agency
        # anchor segmentation (prevents infinite recursion in edge cases)
        self.in_end_tag_dispatch = False

        # Fragment parsing one-shot: tracks if first start tag matching fragment context
        # has been ignored (e.g., context='td' and first <td> token)
        self.ignored_fragment_context_tag = False

        # Anchor re-entry pointer: element to return to after structural element (e.g., table)
        # handling completes, if anchor is still in open elements stack
        self.anchor_resume_element = None

    # --- Properties / helpers ---
    @property
    def current_parent(self):
        return self._current_parent

    def _set_current_parent(self, new_parent):
        if new_parent is None:
            msg = "ParseContext requires a valid current parent"
            raise ValueError(msg)

        if new_parent != self._current_parent:
            self._debug(f"Parent change: {self._current_parent.tag_name} -> {new_parent.tag_name}")
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
            self._debug(f"Content State change: {self._content_state} -> {new_state}")
            self._content_state = new_state

    # --- State transitions ---
    def transition_to_state(self, new_state, new_parent=None):
        if new_parent is not None:
            self._set_current_parent(new_parent)
        if new_state != self._document_state:
            if self._debug:
                self._debug(
                    f"Document State change: {self._document_state} -> {new_state}",
                )
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

    def enter_element(self, element):
        self._set_current_parent(element)

    def __repr__(self):
        parent_name = self._current_parent.tag_name if self._current_parent else "None"
        return (
            f"<ParseContext: doc_state={self.document_state.name}, "
            f"content_state={self.content_state.name}, parent={parent_name}>"
        )
