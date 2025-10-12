from enum import Enum, auto

from turbohtml.adoption import ActiveFormattingElements, OpenElementsStack


class FragmentContext:
    """Structured fragment context for fragment parsing."""
    __slots__ = ["namespace", "tag_name"]

    def __init__(self, tag_name, namespace=None):
        self.tag_name = tag_name
        self.namespace = namespace  # None for HTML, "svg" or "math" for foreign

    def __repr__(self):
        if self.namespace:
            return f"FragmentContext({self.namespace}:{self.tag_name})"
        return f"FragmentContext({self.tag_name})"

    def __bool__(self):
        return True

    def __eq__(self, other):
        # Prevent accidental string comparisons (old code pattern)
        if isinstance(other, str):
            msg = (
                f"FragmentContext comparison with string '{other}' - "
                f"use fragment_context.tag_name == '{other}' instead"
            )
            raise TypeError(msg)
        if isinstance(other, FragmentContext):
            return self.tag_name == other.tag_name and self.namespace == other.namespace
        return False

    def __hash__(self):
        return hash((self.tag_name, self.namespace))

    def matches(self, tag_names):
        """Check if this is an HTML fragment context matching the given tag name(s).

        Args:
            tag_names: A single tag name string or iterable of tag name strings

        Returns:
            True if this is a non-namespaced (HTML) fragment with tag_name matching
            one of the given tag names, False otherwise (including for None context
            or foreign/namespaced fragments)

        Examples:
            fragment_context.matches("tr")
            fragment_context.matches(("tr", "td", "th"))
        """
        if self.namespace:
            return False
        if isinstance(tag_names, str):
            return self.tag_name == tag_names
        return self.tag_name in tag_names


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

    __slots__ = (
        "_content_state",
        "_current_parent",
        "_debug",
        "_document_state",
        "_ip_cache_node",
        "_ip_in_mathml_html",
        "_ip_in_mathml_text",
        "_ip_in_svg_html",
        "_select_cache_node",
        "_select_cached_value",
        "active_formatting_elements",
        "anchor_resume_element",
        "current_context",
        "doctype_seen",
        "form_element",
        "frameset_ok",
        "ignored_fragment_context_tag",
        "in_end_tag_dispatch",
        "in_template_content",
        "needs_reconstruction",
        "open_elements",
        "quirks_mode",
        "saw_body_start_tag",
        "saw_html_end_tag",
    )

    def __init__(self, initial_parent, debug_callback=None):
        if initial_parent is None:
            msg = "ParseContext requires a valid initial parent"
            raise ValueError(msg)
        self._current_parent = initial_parent
        self.current_context = None

        self._document_state = DocumentState.INITIAL
        self._content_state = ContentState.NONE
        self.in_template_content = 0  # Depth counter for nested template content
        self._ip_cache_node = None  # Integration point cache: which node is cached
        self._ip_in_svg_html = False  # In SVG HTML integration point (foreignObject/desc/title)
        self._ip_in_mathml_html = False  # In MathML HTML integration point (annotation-xml)
        self._ip_in_mathml_text = False  # In MathML text integration point (mi/mo/mn/ms/mtext)
        self._select_cache_node = None  # Select cache: which node is cached
        self._select_cached_value = False  # Cached result of is_inside_tag("select")
        self._debug = debug_callback
        self.doctype_seen = False
        self.quirks_mode = True  # Quirks mode (no DOCTYPE = quirks), set by DoctypeHandler
        self.frameset_ok = True

        self.active_formatting_elements = ActiveFormattingElements()
        self.open_elements = OpenElementsStack()

        self.form_element = None

        self.saw_html_end_tag = False

        self.saw_body_start_tag = False

        self.needs_reconstruction = False

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
            msg = "ParseContext requires a valid current_parent"
            raise ValueError(msg)

        if new_parent != self._current_parent:
            old_parent = self._current_parent
            # Invalidate integration point cache when parent changes
            self._ip_cache_node = None
            # Invalidate select cache when parent changes
            self._select_cache_node = None

            # Track template content depth for fast in_template_content checks
            # Exit: moving FROM a content node to a non-descendant
            if old_parent.tag_name == "content" and old_parent.parent and old_parent.parent.tag_name == "template":
                cur = new_parent.parent
                while cur:
                    if cur == old_parent:
                        break  # new_parent is descendant, staying inside
                    cur = cur.parent
                else:
                    # Exiting this content node
                    self.in_template_content -= 1

            # Enter: moving TO a content node (check if it's new)
            if new_parent.tag_name == "content" and new_parent.parent and new_parent.parent.tag_name == "template":
                # Only increment if we're not just returning to a content we're already inside
                cur = old_parent.parent
                while cur:
                    if cur == new_parent:
                        break  # was already inside this content
                    cur = cur.parent
                else:
                    # Entering new/different content
                    self.in_template_content += 1

            self._debug(f"Parent change: {old_parent.tag_name} -> {new_parent.tag_name}")
            self._current_parent = new_parent

    @property
    def in_select(self):
        """Fast cached check for is_inside_tag("select").

        Optimizes the very common pattern of checking if we're inside a select element.
        Cache is automatically invalidated when current_parent changes.
        ~4x faster than direct ancestry walk for repeated checks at same position.
        """
        if self._select_cache_node is not self._current_parent:
            # Cache miss - recalculate
            self._select_cache_node = self._current_parent
            self._select_cached_value = self._current_parent.is_inside_tag("select")
        return self._select_cached_value

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


def _update_integration_point_cache(context):
    """Update integration point cache for current_parent.

    Walks ancestors once and sets all three integration point flags.
    Called automatically by is_in_integration_point() when cache is stale.
    """
    node = context._current_parent

    # Cache hit - already computed for this node
    if context._ip_cache_node is node:
        return

    # Reset cache for new node
    context._ip_cache_node = node
    context._ip_in_svg_html = False
    context._ip_in_mathml_html = False
    context._ip_in_mathml_text = False

    # Walk ancestors once, setting all flags
    current = node
    while current:
        # SVG HTML integration point: foreignObject, desc, title
        if current.namespace == "svg" and current.tag_name in {"foreignObject", "desc", "title"}:
            context._ip_in_svg_html = True

        # MathML HTML integration point: annotation-xml with HTML encoding
        if current.namespace == "math" and current.tag_name == "annotation-xml":
            encoding = current.attributes.get("encoding", "").lower()
            if encoding in ("text/html", "application/xhtml+xml"):
                context._ip_in_mathml_html = True

        # MathML text integration point: mi, mo, mn, ms, mtext
        if current.namespace == "math" and current.tag_name in {"mi", "mo", "mn", "ms", "mtext"}:
            context._ip_in_mathml_text = True

        # Stop at SVG/MathML roots (don't walk into HTML)
        if (current.namespace == "svg" and current.tag_name == "svg") or \
           (current.namespace == "math" and current.tag_name == "math"):
            break

        current = current.parent


def is_in_integration_point(context, check="any"):
    """Check if current parse position is in an integration point.

    Integration points are locations where HTML parsing rules resume inside
    foreign (SVG/MathML) content.

    Args:
        context: ParseContext instance
        check: Type to check - "svg", "mathml", or "any" (default)

    Returns:
        bool: True if in the specified type of integration point
    """
    _update_integration_point_cache(context)

    if check == "svg":
        return context._ip_in_svg_html
    if check == "mathml":
        return context._ip_in_mathml_html or context._ip_in_mathml_text
    # "any"
    return context._ip_in_svg_html or context._ip_in_mathml_html or context._ip_in_mathml_text
