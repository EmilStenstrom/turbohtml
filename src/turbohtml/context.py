from enum import Enum, auto

from turbohtml.adoption import ActiveFormattingElements, OpenElementsStack


class DocumentState(Enum):
    """Enumerates document parser states for clarity and safety (head, body...).
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
    """Enumerates content parser states for clarity and safety (rawtext...).
    """

    NONE = auto()
    RAWTEXT = auto()
    PLAINTEXT = auto()


class ParseContext:
    """Mutable parser state: stacks, modes, insertion point."""

    def __init__(self, initial_parent, debug_callback=None):
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
        self.active_formatting_elements = ActiveFormattingElements()
        self.open_elements = OpenElementsStack()
        # Historical bit (single minimal flag): in a frameset document, did an explicit </html>
        # occur before the first <noframes>? Used only for trailing comment placement.
        self.frameset_html_end_before_noframes = False
        # Explicit </html> end tag encountered (distinguishes pre/post html end in frameset AFTER_FRAMESET mode)
        self.html_end_explicit = False
        # One-shot flag: set True by adoption algorithm when it performs a restructuring so that
        # the *next* character token in IN_BODY triggers active formatting elements reconstruction
        # before inserting text. Cleared immediately after consumption (see TextHandler).
        self.post_adoption_reconstruct_pending = False
        # Deferred wrapper for legacy formatting when adoption removes the element but upcoming tokens
        # should continue inside an equivalent container (e.g. fostered <font> around stray table content).
        self.pending_font_wrapper_parent = None
        # Fragment parsing: track whether we've already ignored the first start tag
        # matching the fragment context element (e.g., context='td' and first <td>). The
        # HTML fragment algorithm only skips the context element token itself; subsequent
        # identical tags nested inside the fragment should be processed normally. We keep
        # a simple boolean rather than counting since only the first occurrence is ignored.
        self.fragment_context_ignored = False
        # Anchor element to re-enter after structural element (e.g., table) handling if still open.
        self.resume_anchor_after_structure = None
        # Anchor reconstruction / suppression coordination flags (previously accessed via getattr)
        self.processing_end_tag = False  # True only during end-tag handler dispatch to gate adoption agency anchor segmentation
        self.anchor_last_reconstruct_index = None  # tokenizer position of last anchor reconstruction (duplicate suppression)
        self.explicit_body = False  # whether a literal <body> start tag appeared (affects comment placement)
        self.last_template_text_sig = None  # signature tuple (parent_id, index) of last template text append for duplication guard
        # HTML Standard form element pointer: tracks the most recently opened <form> outside templates
        # so additional <form> start tags can be ignored until the pointer is cleared.
        self.form_element = None

    # --- Properties / helpers ---
    @property
    def current_parent(self):
        return self._current_parent

    def _set_current_parent(self, new_parent):
        if new_parent != self._current_parent:
            if self._debug:
                old_name = (
                    self._current_parent.tag_name if self._current_parent else "None"
                )
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
                self._debug(
                    f"Content State change: {self._content_state} -> {new_state}",
                )
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
