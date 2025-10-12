"""TurboHTML parser (type annotations removed)."""

from turbohtml.adoption import AdoptionAgencyAlgorithm
from turbohtml.constants import NUMERIC_ENTITY_INVALID_SENTINEL, VOID_ELEMENTS
from turbohtml.context import ContentState, DocumentState, ParseContext, is_in_integration_point
from turbohtml.foster import foster_parent, needs_foster_parenting
from turbohtml.fragment import parse_fragment
from turbohtml.handlers import (
    BlockFormattingReconstructionHandler,
    ButtonTagHandler,
    DoctypeHandler,
    DocumentStructureHandler,
    ForeignTagHandler,
    FormattingTagHandler,
    FormTagHandler,
    FramesetTagHandler,
    GenericEndTagHandler,
    HeadingTagHandler,
    HeadTagHandler,
    ImageTagHandler,
    ListTagHandler,
    MarqueeTagHandler,
    MenuitemTagHandler,
    ParagraphTagHandler,
    PlaintextHandler,
    RawtextTagHandler,
    RubyTagHandler,
    SelectTagHandler,
    TableFosterHandler,
    TableTagHandler,
    TagHandler,
    TemplateContentFilterHandler,
    TemplateElementHandler,
    TextHandler,
    UnifiedCommentHandler,
    VoidTagHandler,
)
from turbohtml.node import Node

try:
    from rust_tokenizer import RustTokenizer
except ImportError as err:
    raise ImportError(
        "Rust tokenizer not available. Please install with: "
        "cd rust_tokenizer && maturin develop --release",
    ) from err


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


class TurboHTML:
    """Main parser interface.
    Instantiation with an HTML string immediately parses into an in-memory tree
    rooted at `self.root`. Public surface is intentionally small; most spec logic
    lives in handlers and predicate helpers for determinism and testability.
    """

    def __init__(
        self,
        html,
        debug=False,
        fragment_context=None,
        handlers=None,
    ):
        """Args:
        html: The HTML string to parse
        debug: Whether to enable debug prints
        fragment_context: Context element for fragment parsing. Can be:
            - A string tag name (e.g., 'td', 'tr') for HTML elements
            - A FragmentContext object (from test runner)
        handlers: Optional list of handler classes to use. If None, uses default set.

        """
        self._debug = debug

        # Convert string fragment_context to FragmentContext object for internal use
        if fragment_context and isinstance(fragment_context, str):
            self.fragment_context = FragmentContext(fragment_context)
        else:
            self.fragment_context = fragment_context

        self._init_dom_structure()
        self.adoption_agency = AdoptionAgencyAlgorithm(self)

        # Performance cache: track frameset presence to avoid repeated DOM walks
        self._has_frameset = False

        # Handler references initialized during registration
        self.text_handler = None
        self.foreign_handler = None

        # Initialize tag handlers in deterministic order
        if handlers is None:
            handlers = [
                DoctypeHandler,
                TemplateContentFilterHandler,  # must precede TemplateElementHandler
                TemplateElementHandler,
                DocumentStructureHandler,
                PlaintextHandler,
                FramesetTagHandler,
                SelectTagHandler,  # must precede table handling to suppress table tokens inside <select>
                TableTagHandler,
                UnifiedCommentHandler,
                ForeignTagHandler,
                ParagraphTagHandler,
                BlockFormattingReconstructionHandler,  # Renamed from AutoClosingTagHandler
                MenuitemTagHandler,
                ListTagHandler,
                HeadTagHandler,
                ButtonTagHandler,
                VoidTagHandler,
                RawtextTagHandler,
                MarqueeTagHandler,
                FormattingTagHandler,
                ImageTagHandler,
                TextHandler,
                FormTagHandler,
                HeadingTagHandler,
                RubyTagHandler,
                TableFosterHandler,
                GenericEndTagHandler,
            ]

        self.tag_handlers = [handler_class(self) for handler_class in handlers]

        # Store direct references to handlers that need special early processing
        self.text_handler = None
        self.foreign_handler = None
        self.formatting_handler = None
        self.frameset_handler = None
        self.generic_end_handler = None

        for handler in self.tag_handlers:
            if isinstance(handler, TextHandler):
                self.text_handler = handler
            elif isinstance(handler, ForeignTagHandler):
                self.foreign_handler = handler
            elif isinstance(handler, FormattingTagHandler):
                self.formatting_handler = handler
            elif isinstance(handler, FramesetTagHandler):
                self.frameset_handler = handler
            elif isinstance(handler, GenericEndTagHandler):
                self.generic_end_handler = handler

        if self.text_handler is None:
            msg = "TextHandler not found in tag_handlers"
            raise RuntimeError(msg)

        # Build optimized dispatch tables
        self._build_dispatch_tables()

        # Sequential token counter for deduplication guards (replaces tokenizer position)
        self._token_counter = 0

        # Parse immediately upon construction (html string only used during parsing)
        self._parse(html)

        # Post-parse processing
        for handler in self.tag_handlers:
            handler.postprocess(self)

    def _build_dispatch_tables(self):
        """Pre-filter handlers and build fast-path dispatch tables.

        This eliminates calling should_handle_* on handlers that use the base class
        implementation, and provides direct tag→handler lookups where possible.
        """
        base_should_handle_start = TagHandler.should_handle_start
        base_should_handle_end = TagHandler.should_handle_end
        base_should_handle_text = TagHandler.should_handle_text

        # Only include handlers that actually override the base class methods
        self._active_start_handlers = [
            h for h in self.tag_handlers
            if h.should_handle_start.__func__ is not base_should_handle_start
        ]
        # Exclude GenericEndTagHandler from normal dispatch (handled separately as fallback)
        self._active_end_handlers = [
            h for h in self.tag_handlers
            if h.should_handle_end.__func__ is not base_should_handle_end
            and not isinstance(h, GenericEndTagHandler)
        ]
        self._active_text_handlers = [
            h for h in self.tag_handlers
            if h.should_handle_text.__func__ is not base_should_handle_text
        ]

        # Pre-compute handler metadata to avoid hasattr checks in hot path
        # Store tuples of (handler, HANDLED_TAGS or None) to eliminate runtime hasattr
        self._start_handler_metadata = [
            (h, getattr(h, "HANDLED_TAGS", None))
            for h in self._active_start_handlers
        ]
        self._end_handler_metadata = [
            (h, getattr(h, "HANDLED_END_TAGS", None))
            for h in self._active_end_handlers
        ]

    def debug(self, *args, indent=4, **kwargs):
        # Early return before any string formatting - args aren't evaluated if debug is off
        if not self._debug:
            return
        print(f"{' ' * indent}{args[0]}", *args[1:], **kwargs)

    def _init_dom_structure(self):
        """Initialize minimal DOM structure (document root and html element placeholder).

        Full structure (head/body) is ensured during parsing and in postprocess().
        """
        if self.fragment_context:
            self.root = Node("document-fragment")
            self.html_node = None
        else:
            self.root = Node("document")
            self.html_node = Node("html")

    def ensure_html_node(self):
        """Materialize <html> into the root if not already present (document mode only)."""
        if self.fragment_context:
            return
        if self.html_node not in self.root.children:
            self.root.append_child(self.html_node)

    def insert_element(
        self,
        token,
        context,
        *,
        mode="normal",
        enter=True,
        treat_as_void=False,
        parent=None,
        before=None,
        tag_name_override=None,
        namespace=None,
        attributes_override=None,
        preserve_attr_case=False,
        push_override=None,
        auto_foster=True,
    ):
        """Insert a start tag's element with controlled stack / current_parent semantics.

        Modes:
          normal    - Standard spec path: push (unless forced void) then optionally enter.
          transient - Insert but never push (synthetic wrappers inside template content).
          void      - Insert and never push/enter (independent of actual tag classification).

        treat_as_void can force void behavior under normal/transient modes. All invariants
        mirror HTML tree construction: no scoped side effects hidden here.

        auto_foster: When True (default) and parent=None, automatically applies foster
        parenting if current_parent is in table context. Set to False to bypass.
        """
        if mode not in ("normal", "transient", "void"):
            msg = f"insert_element: unknown mode '{mode}'"
            raise ValueError(msg)

        # Foster parenting: When inserting into default parent (parent=None) and in table context,
        # spec requires insertion before the table rather than inside it (unless in cell/caption).
        target_parent = parent or context.current_parent
        target_before = before
        tag_name = tag_name_override or token.tag_name

        # Determine namespace: explicit parameter, or inherit from context
        # BUT: don't auto-namespace if we're in an integration point where HTML elements are HTML
        # ALSO: don't auto-namespace synthetic HTML elements at fragment root in foreign contexts
        if namespace is None and context.current_context in ("svg", "math"):
            # If at fragment root (document-fragment parent), don't auto-namespace
            if context.current_parent.tag_name == "document-fragment":
                pass  # Keep namespace=None (HTML)
            else:
                # Only auto-namespace if NOT in an integration point
                if not is_in_integration_point(context):
                    namespace = context.current_context

        if auto_foster and parent is None and before is None:
            if needs_foster_parenting(context.current_parent):
                # Check if we're inside a cell or caption (foster parenting doesn't apply there)
                in_cell_or_caption = bool(
                    context.current_parent.find_table_cell_ancestor(),
                )
                # Don't foster table-related elements or elements specifically allowed in tables (form)
                tableish = ("table","tbody","thead","tfoot","tr","td","th","caption","colgroup","col","form")
                if not in_cell_or_caption and tag_name not in tableish:
                    target_parent, target_before = foster_parent(
                        context.current_parent, context.open_elements, self.root, context.current_parent, tag_name,
                    )

        # Guard: transient mode only allowed inside template content subtrees (content under a template)
        if mode == "transient":
            cur = context.current_parent
            in_template_content = False
            while cur:
                if (
                    cur.tag_name == "content"
                    and cur.parent
                    and cur.parent.tag_name == "template"
                ):
                    in_template_content = True
                    break
                cur = cur.parent
            if not in_template_content and tag_name != "content":
                msg = f"insert_element: transient mode outside template content (tag={tag_name}) not permitted; current_parent={context.current_parent.tag_name}"
                raise ValueError(
                    msg,
                )
        attrs = (
            attributes_override if attributes_override is not None else token.attributes
        )
        new_node = Node(tag_name, attrs, preserve_attr_case=preserve_attr_case, namespace=namespace)
        if target_before and target_before.parent is target_parent:
            target_parent.insert_before(new_node, target_before)
        else:
            target_parent.append_child(new_node)
        # Determine effective voidness
        is_void = False
        is_void = True if mode == "void" else treat_as_void or token.tag_name in VOID_ELEMENTS

        if mode == "normal" and not is_void:
            do_push = True if push_override is None else push_override
            if do_push:
                context.open_elements.push(new_node)
        # Do not enter a node that the token marked self-closing (HTML void-like syntax) even if not in VOID_ELEMENTS
        if (
            enter
            and not is_void
            and mode in ("normal", "transient")
            and not token.is_self_closing
        ):
            context.enter_element(new_node)

        # Activate RAWTEXT mode if token requires it (deferred activation for elements like textarea)
        if token.needs_rawtext and self.tokenizer:
            context.content_state = ContentState.RAWTEXT
            self.tokenizer.start_rawtext(tag_name)

        # Activate PLAINTEXT mode for <plaintext> element (consumes all remaining input as text)
        # BUT NOT in foreign (SVG/MathML) context where plaintext is a regular element
        if tag_name == "plaintext" and namespace is None and self.tokenizer:
            context.content_state = ContentState.PLAINTEXT
            self.tokenizer.start_plaintext()

        # Exit RAWTEXT mode when inserting foreign content (math/svg elements)
        if namespace in ("svg", "math") and self.tokenizer and self.tokenizer.state == "RAWTEXT":
            self.tokenizer.state = "DATA"
            self.tokenizer.rawtext_tag = None

        return new_node

    def insert_text(
        self,
        text,
        context,
        *,
        parent=None,
        before=None,
        merge=True,
    ):
        """Insert character data performing standard merge with preceding text node."""

        # Entity finalization: convert sentinel and strip invalid U+FFFD inline during text insertion.
        had_sentinel = NUMERIC_ENTITY_INVALID_SENTINEL in text
        if had_sentinel:
            text = text.replace(NUMERIC_ENTITY_INVALID_SENTINEL, "\ufffd")

        # Strip U+FFFD from invalid codepoints (not from numeric entities) based on context
        if "\ufffd" in text and not had_sentinel:
            target_parent = parent or context.current_parent
            preserve = False

            # Always preserve in script/style/plaintext
            if target_parent.tag_name in {"script", "style", "plaintext"}:
                preserve = True
            else:
                for elem in context.open_elements:
                    if elem.tag_name in {"script", "style", "plaintext"}:
                        preserve = True
                        break

            # Preserve in SVG content (but NOT in HTML integration points)
            if (
                not preserve
                and target_parent.namespace == "svg"
                and target_parent.tag_name not in ("foreignObject", "desc", "title")
            ):
                preserve = True

            if not preserve:
                text = text.replace("\ufffd", "")

        if text == "":  # Fast path noop
            return None

        target_parent = parent or context.current_parent
        # Template content duplication suppression
        if target_parent.tag_name == "content" and target_parent.children:
            last = target_parent.children[-1]
            if last.tag_name == "#text" and last.text_content == text:
                return last
        if target_parent is None:
            return None

        if before is not None and before.parent is target_parent:
            idx = target_parent.children.index(before)
            prev_idx = idx - 1
            if (
                merge
                and prev_idx >= 0
                and target_parent.children[prev_idx].tag_name == "#text"
            ):
                prev_node = target_parent.children[prev_idx]
                prev_node.text_content += text
                return prev_node
            new_node = Node("#text", text_content=text)
            target_parent.insert_before(new_node, before)
            return new_node

        if (
            merge
            and target_parent.children
            and target_parent.children[-1].tag_name == "#text"
        ):
            last = target_parent.children[-1]
            if self._debug:
                self.debug(f"[insert_text] merging into existing text node len_before={len(last.text_content)} add_len={len(text)}")
            last.text_content += text
            return last

        new_node = Node("#text", text_content=text)
        target_parent.append_child(new_node)
        if self._debug:
            self.debug(f"[insert_text] new text node len={len(text)} parent={target_parent.tag_name}")
        return new_node

    def _parse(self, html):
        """Entry point selecting document vs fragment strategy."""
        if self.fragment_context:
            parse_fragment(self, html)
        else:
            self._parse_document(html)

    def handle_fragment_comment(self, text, context):
        """Handle comments in fragment parsing."""
        comment_node = Node("#comment", text_content=text)
        # html fragment AFTER_HTML - attach at fragment root (siblings with head/body) per expected tree
        if (
            self.fragment_context
            and self.fragment_context.tag_name == "html"
            and not self.fragment_context.namespace
            and context.document_state == DocumentState.AFTER_HTML
        ):
            self.root.append_child(comment_node)
            return
        context.current_parent.append_child(comment_node)

    def _parse_document(self, html):
        """Parse a full HTML document (token loop delegating to handlers)."""
        # Initialize context with html_node as current_parent
        context = ParseContext(self.html_node, debug_callback=self.debug)

        # Use Rust tokenizer
        self.tokenizer = RustTokenizer(html, debug=self._debug)
        tokens = self.tokenizer

        for token in tokens:
            # Increment token counter for deduplication tracking
            self._token_counter += 1

            if self._debug:
                self.debug(f"_parse: {token}, context: {context}", indent=0)

            if token.type == "DOCTYPE":
                # Handle DOCTYPE through the DoctypeHandler first
                for handler in self.tag_handlers:
                    if handler.should_handle_doctype(token.data, context):
                        if self._debug:
                            self.debug(f"{handler.__class__.__name__}: handling DOCTYPE")
                        if handler.handle_doctype(token.data, context):
                            break
                continue


            if token.type == "Comment":
                handled = False
                for handler in self.tag_handlers:
                    if handler.should_handle_comment(token.data, context) and handler.handle_comment(token.data, context):
                        handled = True
                        break
                if not handled:
                    node = Node("#comment", text_content=token.data)
                    context.current_parent.append_child(node)
                continue

            # Ensure html node is in tree before processing any non-DOCTYPE/Comment token
            self.ensure_html_node()

            if token.type == "StartTag":
                self.handle_start_tag(token, context)

            elif token.type == "EndTag":
                # In template fragment context, ignore the context's own end tag
                if (
                    self.fragment_context
                    and self.fragment_context.tag_name == "template"
                    and not self.fragment_context.namespace
                    and token.tag_name == "template"
                ):
                    continue
                self.handle_end_tag(token, context)

            elif token.type == "Character":
                data = token.data
                if data:
                    # Use pre-filtered list of text handlers
                    for handler in self._active_text_handlers:
                        if handler.should_handle_text(data, context):
                            if self._debug:
                                self.debug(
                                f"{handler.__class__.__name__}: handling {token}, context={context}",
                            )
                            if handler.handle_text(data, context):
                                break

        # At EOF, handle any unclosed option elements for selectedcontent cloning
        # This is spec-compliant: selectedcontent mirrors the selected option's content
        for elem in reversed(list(context.open_elements)):
            if elem.tag_name == "option":
                # Find SelectTagHandler and call its cloning logic
                for handler in self.tag_handlers:
                    if handler.__class__.__name__ == "SelectTagHandler":
                        # Temporarily move to the option to clone its content
                        saved_parent = context.current_parent
                        context.move_to_element(elem)
                        handler.clone_option_to_selectedcontent(context)
                        context.move_to_element(saved_parent)
                        break
                break  # Only handle the first (innermost) option

    def handle_start_tag(self, token, context):
        """Handle all opening HTML tags."""
        tag_name = token.tag_name

        # Inline frameset preprocessing (guards frameset_ok and consumes invalid tokens)
        if self.frameset_handler and self.frameset_handler.preprocess_start(token, context):
            return

        # Inline formatting element reconstruction (must happen before handler dispatch)
        if self.formatting_handler:
            self.formatting_handler.preprocess_start(token, context)

        # Dispatch with fast-path optimization using pre-computed handler metadata
        # This eliminates hasattr calls by checking pre-stored HANDLED_TAGS
        for handler, handled_tags in self._start_handler_metadata:
            # Fast-path: skip if handler declares HANDLED_TAGS and tag not in set
            if handled_tags is not None and tag_name not in handled_tags:
                continue
            # Handler either has no HANDLED_TAGS (fallback) or tag is in HANDLED_TAGS
            if handler.should_handle_start(tag_name, context) and handler.handle_start(token, context):
                return

        # Fallback: if no handler claimed this start tag, insert it with default behavior.
        self.insert_element(token, context, mode="normal", enter=not token.is_self_closing)

    def handle_end_tag(self, token, context):
        """Handle all closing HTML tags (spec-aligned, no auxiliary adoption flags)."""
        tag_name = token.tag_name

        # Inline frameset preprocessing (guards invalid end tags in frameset contexts)
        if self.frameset_handler and self.frameset_handler.preprocess_end(token, context):
            return

        # Dispatch with fast-path optimization using pre-computed handler metadata
        for handler, handled_end_tags in self._end_handler_metadata:
            # Fast-path: skip if handler declares HANDLED_END_TAGS and tag not in set
            if handled_end_tags is not None and tag_name not in handled_end_tags:
                continue
            # Handler either has no HANDLED_END_TAGS (fallback) or tag is in HANDLED_END_TAGS
            if handler.should_handle_end(tag_name, context) and handler.handle_end(token, context):
                return

        # Fallback: GenericEndTagHandler as last resort (spec "any other end tag")
        # No need for should_handle_end check since it always returns True
        if self.generic_end_handler:
            self.generic_end_handler.handle_end(token, context)
