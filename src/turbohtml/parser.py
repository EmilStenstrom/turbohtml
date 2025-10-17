"""TurboHTML parser (type annotations removed)."""

from turbohtml.adoption import AdoptionAgencyAlgorithm
from turbohtml.constants import NUMERIC_ENTITY_INVALID_SENTINEL, VOID_ELEMENTS, TABLE_ELEMENTS_NO_FOSTER
from turbohtml.context import ContentState, DocumentState, FragmentContext, ParseContext, is_in_integration_point
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
        "Rust tokenizer not available. Please install with: cd rust_tokenizer && maturin develop --release",
    ) from err


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
            # Parse "namespace:tagname" format (e.g., "svg:path", "math:annotation-xml")
            # or plain tagname for HTML elements (e.g., "td", "table")
            if ":" in fragment_context:
                namespace, tag_name = fragment_context.split(":", 1)
                self.fragment_context = FragmentContext(tag_name, namespace)
            else:
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
                BlockFormattingReconstructionHandler,
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
        """Pre-compute per-tag dispatch tables for fast O(1) handler lookup.

        Builds direct tag->handlers list to replace linear scan over all handlers.
        """
        base_should_handle_start = TagHandler.should_handle_start
        base_should_handle_end = TagHandler.should_handle_end
        base_handle_end = TagHandler.handle_end
        base_should_handle_text = TagHandler.should_handle_text

        # Build ordered metadata (same as before, for compatibility with text handlers)
        self._start_handler_metadata = [
            (h, h.__class__.HANDLED_START_TAGS, h.should_handle_start.__func__ is not base_should_handle_start)
            for h in self.tag_handlers
            if h.__class__.HANDLED_START_TAGS is not None
            or h.should_handle_start.__func__ is not base_should_handle_start
        ]
        self._end_handler_metadata = [
            (h, h.__class__.HANDLED_END_TAGS, h.should_handle_end.__func__ is not base_should_handle_end)
            for h in self.tag_handlers
            if (
                h.__class__.HANDLED_END_TAGS is not None
                or h.should_handle_end.__func__ is not base_should_handle_end
                or h.handle_end.__func__ is not base_handle_end
            )
            and not isinstance(h, GenericEndTagHandler)
        ]
        self._text_handler_metadata = [
            (h, h.should_handle_text.__func__ is not base_should_handle_text)
            for h in self.tag_handlers
            if h.__class__.HANDLES_TEXT or h.should_handle_text.__func__ is not base_should_handle_text
        ]

        # Build per-tag dispatch: for each tag, pre-compute which handlers match
        self._start_dispatch = {}
        self._end_dispatch = {}

        # Collect all known tags from all handlers
        all_start_tags = set()
        all_end_tags = set()
        for h, handled_tags, _ in self._start_handler_metadata:
            if handled_tags is not None and hasattr(handled_tags, '__iter__'):
                # Skip ALL_TAGS sentinel (has __contains__ but don't iterate)
                if not hasattr(handled_tags, '__class__') or handled_tags.__class__.__name__ != '_AllTagsSentinel':
                    all_start_tags.update(handled_tags)
        for h, handled_tags, _ in self._end_handler_metadata:
            if handled_tags is not None and hasattr(handled_tags, '__iter__'):
                if not hasattr(handled_tags, '__class__') or handled_tags.__class__.__name__ != '_AllTagsSentinel':
                    all_end_tags.update(handled_tags)

        # Add high-frequency tags to ensure fast path (ALL_TAGS handlers will match these)
        common_tags = {
            # HTML structure
            'html', 'head', 'body', 'div', 'p', 'span', 'table', 'tbody', 'thead', 'tfoot',
            'tr', 'td', 'th', 'caption', 'colgroup', 'ul', 'ol', 'article', 'section',
            'nav', 'header', 'footer', 'aside', 'main', 'figure', 'figcaption',
            # SVG elements (high frequency in real web data)
            'svg', 'path', 'g', 'defs', 'use', 'symbol', 'rect', 'line', 'circle',
            'polygon', 'polyline', 'ellipse', 'lineargradient', 'radialgradient', 'stop',
            'clippath', 'filter', 'fecolormatrix', 'fegaussianblur', 'femerge', 'femergenode',
            'fecomposite', 'feflood', 'femorphology', 'foreignobject', 'text', 'tspan',
            'pattern', 'animatetransform',
            # Other common elements
            'option', 'picture', 'video', 'canvas', 'time', 'blockquote', 'pre', 'ins',
            'sup', 'details', 'summary', 'center', 'dl', 'fieldset', 'kbd', 'map',
            'address',
        }
        all_start_tags.update(common_tags)
        all_end_tags.update(common_tags)

        # For each known tag, build list of handlers that match it
        for tag in all_start_tags:
            handlers_for_tag = []
            for handler, handled_tags, has_custom in self._start_handler_metadata:
                # Check if this handler handles this tag
                if handled_tags is None or tag in handled_tags:
                    handlers_for_tag.append((handler, has_custom))
            if handlers_for_tag:
                self._start_dispatch[tag] = handlers_for_tag

        for tag in all_end_tags:
            handlers_for_tag = []
            for handler, handled_tags, has_custom in self._end_handler_metadata:
                if handled_tags is None or tag in handled_tags:
                    handlers_for_tag.append((handler, has_custom))
            if handlers_for_tag:
                self._end_dispatch[tag] = handlers_for_tag

        # Store generic end handler separately
        for h in self.tag_handlers:
            if isinstance(h, GenericEndTagHandler):
                self.generic_end_handler = h
                break

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
        # Cache frequently accessed attributes
        tag_name = tag_name_override or token.tag_name
        token_tag_name = token.tag_name
        is_self_closing = token.is_self_closing
        
        # Foster parenting: When inserting into default parent (parent=None) and in table context,
        # spec requires insertion before the table rather than inside it (unless in cell/caption).
        target_parent = parent or context.current_parent
        target_before = before

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
                    context.current_parent.find_first_ancestor_in_tags({"td", "th", "caption"}),
                )
                # Don't foster table-related elements or elements specifically allowed in tables (form)
                if not in_cell_or_caption and tag_name not in TABLE_ELEMENTS_NO_FOSTER:
                    target_parent, target_before = foster_parent(
                        context.current_parent,
                        context.open_elements,
                        self.root,
                        context.current_parent,
                        tag_name,
                    )

        # Guard: transient mode only allowed inside template content subtrees (content under a template)
        if mode == "transient":
            # Use context.in_template_content counter instead of walking parent chain
            # The counter is more reliable as it tracks template content depth regardless of
            # where the current insertion point is in the DOM (e.g., during foster parenting)
            if context.in_template_content == 0 and tag_name != "content":
                msg = f"insert_element: transient mode outside template content (tag={tag_name}) not permitted; current_parent={context.current_parent.tag_name}"
                raise ValueError(
                    msg,
                )
        attrs = attributes_override if attributes_override is not None else token.attributes
        new_node = Node(tag_name, attrs, preserve_attr_case=preserve_attr_case, namespace=namespace)
        if target_before and target_before.parent is target_parent:
            target_parent.insert_before(new_node, target_before)
        else:
            target_parent.append_child(new_node)
        
        # Determine effective voidness - mode "void" always results in void behavior
        # Otherwise check treat_as_void flag or if tag is in VOID_ELEMENTS set
        if mode == "void":
            is_void = True
        elif mode == "normal":
            is_void = treat_as_void or token_tag_name in VOID_ELEMENTS
            if not is_void:
                do_push = True if push_override is None else push_override
                if do_push:
                    context.open_elements.push(new_node)
            # Do not enter a node that the token marked self-closing even if not in VOID_ELEMENTS
            if enter and not is_void and not is_self_closing:
                context.enter_element(new_node)
        else:  # mode == "transient"
            is_void = treat_as_void or token_tag_name in VOID_ELEMENTS
            # Do not enter a node that the token marked self-closing even if not in VOID_ELEMENTS
            if enter and not is_void and not is_self_closing:
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
            if merge and prev_idx >= 0 and target_parent.children[prev_idx].tag_name == "#text":
                prev_node = target_parent.children[prev_idx]
                prev_node.text_content += text
                return prev_node
            new_node = Node("#text", text_content=text)
            target_parent.insert_before(new_node, before)
            return new_node

        if merge and target_parent.children and target_parent.children[-1].tag_name == "#text":
            last = target_parent.children[-1]
            if self._debug:
                self.debug(
                    f"[insert_text] merging into existing text node len_before={len(last.text_content)} add_len={len(text)}"
                )
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
        if not hasattr(self.tokenizer, "set_text_sink"):
            msg = "Rust tokenizer build missing required text sink support"
            raise RuntimeError(msg)

        text_sink_registered = False
        debug_enabled = self._debug
        debug_call = self.debug
        ensure_html_node = self.ensure_html_node
        dispatch_text = self._dispatch_text
        handle_start_tag = self.handle_start_tag
        handle_end_tag = self.handle_end_tag
        tag_handlers = self.tag_handlers

        def _text_sink(
            data,
            is_last,
            *,
            _ctx=context,
            _dispatch=dispatch_text,
            _ensure=ensure_html_node,
            _debug_enabled=debug_enabled,
            _debug=debug_call,
            _self=self,
        ):
            # Mirror token-loop semantics when Rust fast path short-circuits Character tokens
            _self._token_counter += 1
            if _debug_enabled:
                _debug(
                    f"_parse: Character(fast, len={len(data)}) context: {_ctx}",
                    indent=0,
                )
            _ensure()
            _dispatch(data, _ctx)
            return True

        self.tokenizer.set_text_sink(_text_sink)
        text_sink_registered = True

        tokens = self.tokenizer

        for token in tokens:
            # Increment token counter for deduplication tracking
            self._token_counter += 1

            if debug_enabled:
                debug_call(f"_parse: {token}, context: {context}", indent=0)

            if token.type == "DOCTYPE":
                # Handle DOCTYPE through the DoctypeHandler first
                for handler in tag_handlers:
                    if handler.should_handle_doctype(token.data, context):
                        if debug_enabled:
                            debug_call(f"{handler.__class__.__name__}: handling DOCTYPE")
                        if handler.handle_doctype(token.data, context):
                            break
                continue

            if token.type == "Comment":
                handled = False
                for handler in tag_handlers:
                    if handler.should_handle_comment(token.data, context) and handler.handle_comment(
                        token.data, context
                    ):
                        handled = True
                        break
                if not handled:
                    node = Node("#comment", text_content=token.data)
                    context.current_parent.append_child(node)
                continue

            # Ensure html node is in tree before processing any non-DOCTYPE/Comment token
            ensure_html_node()

            if token.type == "StartTag":
                handle_start_tag(token, context)

            elif token.type == "EndTag":
                # In template fragment context, ignore the context's own end tag
                if (
                    self.fragment_context
                    and self.fragment_context.tag_name == "template"
                    and not self.fragment_context.namespace
                    and token.tag_name == "template"
                ):
                    continue
                handle_end_tag(token, context)

            elif token.type == "Character":
                dispatch_text(token.data, context)

        # At EOF, handle any unclosed option elements for selectedcontent cloning
        # This is spec-compliant: selectedcontent mirrors the selected option's content
        for elem in reversed(list(context.open_elements)):
            if elem.tag_name == "option":
                # Find SelectTagHandler and call its cloning logic
                for handler in tag_handlers:
                    if handler.__class__.__name__ == "SelectTagHandler":
                        # Temporarily move to the option to clone its content
                        saved_parent = context.current_parent
                        context.move_to_element(elem)
                        handler.clone_option_to_selectedcontent(context)
                        context.move_to_element(saved_parent)
                        break
                break  # Only handle the first (innermost) option

        if text_sink_registered:
            self.tokenizer.set_text_sink(None)

    def _dispatch_text(self, data, context):
        if not data:
            return

        handlers = self._text_handler_metadata
        debug_enabled = self._debug
        debug_call = self.debug

        for handler, has_custom_should_handle in handlers:
            if has_custom_should_handle and not handler.should_handle_text(data, context):
                continue
            if debug_enabled:
                preview = data[:20]
                ellipsis = "..." if len(data) > 20 else ""
                debug_call(
                    f"{handler.__class__.__name__}: handling Character('{preview}{ellipsis}') context={context}",
                )
            if handler.handle_text(data, context):
                break

    def handle_start_tag(self, token, context):
        """Handle all opening HTML tags."""
        tag_name = token.tag_name

        # Malformed tag check: tags containing "<" are treated as normal elements per spec
        if "<" in tag_name:
            if self._debug:
                self.debug(f"Malformed tag detected: {tag_name}, inserting as normal element")
            # Ensure body exists for malformed tags (they're treated as content, not structure)
            from turbohtml.utils import ensure_body

            if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD, DocumentState.AFTER_HEAD):
                body = ensure_body(self.root, context.document_state, self.fragment_context)
                if body:
                    context.move_to_element(body)
                    context.transition_to_state(DocumentState.IN_BODY, body)
            self.insert_element(token, context, mode="normal")
            return

        # Short-circuit for PLAINTEXT mode: all tags become text (avoids dispatch entirely)
        if context.content_state == ContentState.PLAINTEXT:
            if self._debug:
                self.debug(f"PLAINTEXT mode: treating <{tag_name}> as text")
            from turbohtml.node import Node
            text_node = Node("#text", text_content=f"<{tag_name}>")
            context.current_parent.append_child(text_node)
            return

        # Inline frameset preprocessing (guards frameset_ok and consumes invalid tokens)
        if self.frameset_handler:
            if self.frameset_handler.preprocess_start(token, context):
                return

        # Inline formatting element reconstruction (must happen before handler dispatch)
        if self.formatting_handler:
            self.formatting_handler.preprocess_start(token, context)

        # Dispatch with O(1) per-tag lookup using pre-computed dispatch tables
        handlers = self._start_dispatch.get(tag_name)
        if handlers:
            # Fast path: known tag with pre-computed handler list (99.8% of real-world tags)
            for handler, has_custom_check in handlers:
                if has_custom_check:
                    if handler.should_handle_start(tag_name, context) and handler.handle_start(token, context):
                        return
                else:
                    if handler.handle_start(token, context):
                        return
        else:
            # Slow path: rare/unknown tags (0.2% of real-world tags)
            # Needed for custom elements and ALL_TAGS handlers with complex logic
            for handler, handled_tags, has_custom_check in self._start_handler_metadata:
                if handled_tags is not None and tag_name not in handled_tags:
                    continue
                if has_custom_check:
                    if handler.should_handle_start(tag_name, context) and handler.handle_start(token, context):
                        return
                else:
                    if handler.handle_start(token, context):
                        return

        # Fallback: if no handler claimed this start tag, insert it with default behavior.
        self.insert_element(token, context, mode="normal", enter=not token.is_self_closing)

    def handle_end_tag(self, token, context):
        """Handle all closing HTML tags using O(1) per-tag dispatch."""
        tag_name = token.tag_name

        # Dispatch with O(1) per-tag lookup using pre-computed dispatch tables
        handlers = self._end_dispatch.get(tag_name)
        if handlers:
            # Fast path: known tag with pre-computed handler list (99.7% of real-world tags)
            for handler, has_custom_check in handlers:
                if has_custom_check:
                    if handler.should_handle_end(tag_name, context) and handler.handle_end(token, context):
                        return
                else:
                    if handler.handle_end(token, context):
                        return
        else:
            # Slow path: rare/unknown tags (0.3% of real-world tags)
            # Needed for custom elements and ALL_TAGS handlers with complex logic
            for handler, handled_tags, has_custom_check in self._end_handler_metadata:
                if handled_tags is not None and tag_name not in handled_tags:
                    continue
                if has_custom_check:
                    if handler.should_handle_end(tag_name, context) and handler.handle_end(token, context):
                        return
                else:
                    if handler.handle_end(token, context):
                        return

        # Fallback: GenericEndTagHandler as last resort (spec "any other end tag")
        # No need for should_handle_end check since it always returns True
        if self.generic_end_handler:
            self.generic_end_handler.handle_end(token, context)
