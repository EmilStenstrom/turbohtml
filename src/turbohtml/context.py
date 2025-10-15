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
        "_ip_svg_node",
        "_ip_mathml_node",
        "_svg_ancestor",
        "_math_ancestor",
        "_select_cache_node",
        "_select_cached_value",
        "_table_cache_node",
        "_table_cached_value",
        "active_formatting_elements",
        "anchor_resume_element",
        "current_context",
        "doctype_seen",
        "form_element",
        "frameset_ok",
        "has_foreign_content",  # Track if any SVG/MathML seen - enables integration point fast-path
        "ignored_fragment_context_tag",
        "in_end_tag_dispatch",
        "in_template_content",
        "needs_reconstruction",
        "open_elements",
        "quirks_mode",
        "saw_body_start_tag",
        "saw_html_end_tag",
        "_button_cache_node",
        "_button_cached_value",
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
        self._ip_svg_node = None  # Cached SVG integration point node
        self._ip_mathml_node = None  # Cached MathML integration point node
        self._svg_ancestor = None  # Cached SVG namespace ancestor (any SVG element)
        self._math_ancestor = None  # Cached MathML namespace ancestor (any MathML element)
        self._select_cache_node = None  # Select cache: which node is cached
        self._select_cached_value = False  # Cached result of is_inside_tag("select")
        self._button_cache_node = None  # Button cache: which node is cached
        self._button_cached_value = False  # Cached result of is_inside_tag("button")
        self._table_cache_node = None  # Table cache: which node is cached
        self._table_cached_value = None  # Cached result of find_current_table()
        self._debug = debug_callback
        self.doctype_seen = False
        self.quirks_mode = True  # Quirks mode (no DOCTYPE = quirks), set by DoctypeHandler
        self.frameset_ok = True
        self.has_foreign_content = False  # Set to True when first SVG/MathML element seen

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

    def _update_integration_point_cache_incremental(self, old_parent, new_parent):
        """Incrementally update integration point cache when moving to new parent.
        
        This is much faster than walking the entire tree every time. We leverage the
        fact that when moving from old_parent to new_parent:
        1. If new_parent is a child of old_parent, we just need to check the parent itself
        2. If moving up or sideways, we walk from new_parent (but cache is still valid)
        3. Most common case: moving to a child node (forward progress through tree)
        
        NOTE: Only called when has_foreign_content is True.
        """
        # Check if moving to a child (most common case - forward progress)
        if new_parent.parent == old_parent:
            # Moving down to a child - check if new_parent is an integration point or foreign ancestor
            # Check new_parent node itself for integration point properties
            self._check_node_for_integration_point(new_parent)
            
            # If new_parent has a parent, inherit foreign ancestors from parent chain
            if new_parent.parent:
                self._inherit_foreign_ancestors_from_parent(new_parent)
        else:
            # Moving up or sideways - need to walk from new_parent
            # This is less common (closing tags, adoption agency, etc)
            self._reset_integration_point_cache()
            self._walk_ancestors_for_integration_points(new_parent)
    
    def _reset_integration_point_cache(self):
        """Reset integration point cache to default values."""
        self._ip_in_svg_html = False
        self._ip_in_mathml_html = False
        self._ip_in_mathml_text = False
        self._ip_svg_node = None
        self._ip_mathml_node = None
        self._svg_ancestor = None
        self._math_ancestor = None
    
    def _check_node_for_integration_point(self, node):
        """Check if a single node is an integration point or foreign ancestor."""
        # SVG namespace ancestor
        if node.namespace == "svg":
            if self._svg_ancestor is None:
                self._svg_ancestor = node
            
            # SVG HTML integration point: foreignObject, desc, title
            if node.tag_name in {"foreignObject", "desc", "title"}:
                self._ip_in_svg_html = True
                if self._ip_svg_node is None:
                    self._ip_svg_node = node
        
        # MathML namespace ancestor
        elif node.namespace == "math":
            if self._math_ancestor is None:
                self._math_ancestor = node
            
            # MathML HTML integration point: annotation-xml with HTML encoding
            if node.tag_name == "annotation-xml":
                encoding = node.attributes.get("encoding", "").lower()
                if encoding in ("text/html", "application/xhtml+xml"):
                    self._ip_in_mathml_html = True
                    if self._ip_mathml_node is None:
                        self._ip_mathml_node = node
            
            # MathML text integration point: mi, mo, mn, ms, mtext
            elif node.tag_name in {"mi", "mo", "mn", "ms", "mtext"}:
                self._ip_in_mathml_text = True
                if self._ip_mathml_node is None:
                    self._ip_mathml_node = node
    
    def _inherit_foreign_ancestors_from_parent(self, node):
        """Walk up from node to find foreign ancestors."""
        current = node.parent
        while current:
            if current.namespace == "svg" and self._svg_ancestor is None:
                self._svg_ancestor = current
            if current.namespace == "math" and self._math_ancestor is None:
                self._math_ancestor = current
            
            # Check for integration points
            if current.namespace == "svg" and current.tag_name in {"foreignObject", "desc", "title"}:
                if not self._ip_in_svg_html:
                    self._ip_in_svg_html = True
                    if self._ip_svg_node is None:
                        self._ip_svg_node = current
            
            if current.namespace == "math":
                if current.tag_name == "annotation-xml":
                    encoding = current.attributes.get("encoding", "").lower()
                    if encoding in ("text/html", "application/xhtml+xml"):
                        if not self._ip_in_mathml_html:
                            self._ip_in_mathml_html = True
                            if self._ip_mathml_node is None:
                                self._ip_mathml_node = current
                
                if current.tag_name in {"mi", "mo", "mn", "ms", "mtext"}:
                    if not self._ip_in_mathml_text:
                        self._ip_in_mathml_text = True
                        if self._ip_mathml_node is None:
                            self._ip_mathml_node = current
            
            current = current.parent
    
    def _walk_ancestors_for_integration_points(self, node):
        """Walk ancestors to find all integration points and foreign ancestors."""
        current = node
        while current:
            self._check_node_for_integration_point(current)
            current = current.parent

    def _set_current_parent(self, new_parent):
        if new_parent is None:
            msg = "ParseContext requires a valid current_parent"
            raise ValueError(msg)

        if new_parent != self._current_parent:
            old_parent = self._current_parent
            
            # Invalidate other caches when parent changes
            self._select_cache_node = None
            self._button_cache_node = None
            self._table_cache_node = None

            # Update integration point cache
            # Fast path: if no foreign content, just mark as cached without any work
            self._ip_cache_node = new_parent
            if self.has_foreign_content:
                self._update_integration_point_cache_incremental(old_parent, new_parent)

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
    def in_button(self):
        """Fast cached check for is_inside_tag("button").

        Optimizes button scope checks by caching ancestry walk.
        Cache is automatically invalidated when current_parent changes.
        Used by paragraph handler to determine button scope boundaries.
        """
        if self._button_cache_node is not self._current_parent:
            # Cache miss - recalculate
            self._button_cache_node = self._current_parent
            self._button_cached_value = self._current_parent.is_inside_tag("button")
        return self._button_cached_value

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

    With incremental updates in _set_current_parent, this is now mostly a no-op
    unless the cache is explicitly invalidated or uninitialized.
    """
    node = context._current_parent

    # Cache hit - already computed for this node
    if context._ip_cache_node is node:
        return

    # Cache miss - need to compute from scratch
    # This should be rare with incremental updates
    context._ip_cache_node = node
    context._reset_integration_point_cache()
    
    # Fast path: no foreign content means no integration points
    if not context.has_foreign_content:
        return
    
    # Walk ancestors to populate cache
    context._walk_ancestors_for_integration_points(node)


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
    # Fast path: If we've never seen foreign content, we can't be in an integration point.
    # This eliminates ~1M function calls on typical HTML pages with no SVG/MathML (5% of time).
    if not context.has_foreign_content:
        return False

    _update_integration_point_cache(context)

    if check == "svg":
        return context._ip_in_svg_html
    if check == "mathml":
        return context._ip_in_mathml_html or context._ip_in_mathml_text

    return context._ip_in_svg_html or context._ip_in_mathml_html or context._ip_in_mathml_text


def get_integration_point_node(context, check="any"):
    """Get the cached integration point node.

    Returns the actual integration point node found during cache update,
    eliminating need for redundant tree walks.

    Args:
        context: ParseContext instance
        check: Type to get - "svg", "mathml", or "any" (default)

    Returns:
        Node or None: The integration point node, or None if not in one
    """
    # Fast path: no foreign content means no integration points
    if not context.has_foreign_content:
        return None

    _update_integration_point_cache(context)

    if check == "svg":
        return context._ip_svg_node if context._ip_in_svg_html else None
    if check == "mathml":
        return context._ip_mathml_node if (context._ip_in_mathml_html or context._ip_in_mathml_text) else None
    # "any" - return first available
    if context._ip_svg_node:
        return context._ip_svg_node
    return context._ip_mathml_node


def get_svg_ancestor(context):
    """Get the cached SVG namespace ancestor.

    Returns the nearest SVG namespace ancestor (any SVG element),
    or None if not inside SVG content. Uses cached result for O(1) performance.

    Args:
        context: ParseContext instance

    Returns:
        Node or None: The SVG ancestor, or None if not in SVG
    """
    # Fast path: no foreign content means no SVG ancestor
    if not context.has_foreign_content:
        return None

    _update_integration_point_cache(context)
    return context._svg_ancestor


def get_math_ancestor(context):
    """Get the cached MathML namespace ancestor.

    Returns the nearest MathML namespace ancestor (any MathML element),
    or None if not inside MathML content. Uses cached result for O(1) performance.

    Args:
        context: ParseContext instance

    Returns:
        Node or None: The MathML ancestor, or None if not in MathML
    """
    # Fast path: no foreign content means no MathML ancestor
    if not context.has_foreign_content:
        return None

    _update_integration_point_cache(context)
    return context._math_ancestor


def get_foreign_object_ancestor(context):
    """Get the cached foreignObject ancestor.

    Returns the nearest SVG foreignObject ancestor, or None if not inside one.
    Uses cached result for O(1) performance by checking if the SVG integration
    point is specifically a foreignObject.

    Args:
        context: ParseContext instance

    Returns:
        Node or None: The foreignObject ancestor, or None if not in one
    """
    # Fast path: no foreign content means no foreignObject
    if not context.has_foreign_content:
        return None

    _update_integration_point_cache(context)
    # Check if the cached SVG integration point is a foreignObject
    if context._ip_svg_node and context._ip_svg_node.tag_name == "foreignObject":
        return context._ip_svg_node
    return None


def get_foreign_namespace_ancestor(context):
    """Get the cached foreign namespace ancestor (SVG or MathML).

    Returns the nearest foreign namespace ancestor. If both SVG and MathML
    ancestors exist, returns whichever is closer to current_parent.
    Uses cached results for O(1) performance.

    Args:
        context: ParseContext instance

    Returns:
        Node or None: The foreign ancestor (SVG or MathML), or None if not in foreign content
    """
    # Fast path: no foreign content means no foreign ancestor
    if not context.has_foreign_content:
        return None

    _update_integration_point_cache(context)

    # If we only have one, return it
    if context._svg_ancestor and not context._math_ancestor:
        return context._svg_ancestor
    if context._math_ancestor and not context._svg_ancestor:
        return context._math_ancestor
    if not context._svg_ancestor and not context._math_ancestor:
        return None

    # Both exist - find which is nearest by walking from current_parent
    current = context._current_parent
    while current:
        if current is context._svg_ancestor:
            return context._svg_ancestor
        if current is context._math_ancestor:
            return context._math_ancestor
        current = current.parent

    # Fallback (shouldn't reach here if cache is correct)
    return context._svg_ancestor


def get_current_table(context):
    """Find the current table element from the open elements stack when in table context.

    Cached for O(1) performance. Walks ancestors once on cache miss and stores result.
    Cache invalidated automatically when current_parent changes.

    Args:
        context: ParseContext instance

    Returns:
        Node or None: The current table element, or None if not in table context
    """
    # Cache hit - already computed for this node
    if context._table_cache_node is context._current_parent:
        return context._table_cached_value

    # Reset cache for new node
    context._table_cache_node = context._current_parent
    context._table_cached_value = None

    # Always search open elements stack first (even in IN_BODY) so foster-parenting decisions
    # can detect an open table that the insertion mode no longer reflects (foreign breakout, etc.).
    for element in reversed(context.open_elements):
        if element.tag_name == "table":
            context._table_cached_value = element
            return element

    # Fallback: traverse ancestors from current parent (rare recovery)
    current = context._current_parent
    while current:
        if current.tag_name == "table":
            context._table_cached_value = current
            return current
        current = current.parent

    return None
