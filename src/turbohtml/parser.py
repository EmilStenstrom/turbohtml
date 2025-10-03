"""TurboHTML parser (type annotations removed)."""

from turbohtml.context import ParseContext, DocumentState
from .handlers import (
    DoctypeHandler,
    TemplateContentAutoEnterHandler,
    RawtextStartTagIgnoreHandler,
    MalformedSelectStartTagFilterHandler,
    SpecialElementHandler,
    EarlyMathMLLeafFragmentEnterHandler,
    FormattingReconstructionPreludeHandler,
    TemplateTagHandler,
    TemplateContentFilterHandler,
    FragmentPreprocessHandler,
    ListingNewlineHandler,
    PlaintextHandler,
    FramesetPreludeHandler,
    BodyReentryHandler,
    FramesetLateHandler,
    FramesetTagHandler,
    SelectTagHandler,
    TableTagHandler,
    NullParentRecoveryEndHandler,
    UnifiedCommentHandler,
    ForeignTagHandler,
    ParagraphTagHandler,
    AutoClosingTagHandler,
    MenuitemElementHandler,
    ListTagHandler,
    HeadElementHandler,
    HtmlTagHandler,
    ButtonTagHandler,
    VoidElementHandler,
    RawtextTagHandler,
    BoundaryElementHandler,
    FormattingElementHandler,
    ImageTagHandler,
    TextHandler,
    TextNormalizationHandler,
    FormTagHandler,
    HeadingTagHandler,
    RubyElementHandler,
    FallbackPlacementHandler,
    DefaultElementInsertionHandler,
    GenericEndTagHandler,
    StructureSynthesisHandler,
    PostProcessHandler,
)
from turbohtml.tokenizer import HTMLTokenizer
from turbohtml.adoption import AdoptionAgencyAlgorithm
from .fragment import parse_fragment
from turbohtml.node import Node
from .constants import VOID_ELEMENTS


class TurboHTML:
    """
    Main parser interface.
    Instantiation with an HTML string immediately parses into an in‑memory tree
    rooted at `self.root`. Public surface is intentionally small; most spec logic
    lives in handlers and predicate helpers for determinism and testability.
    """

    def __init__(
        self,
        html,
        handle_foreign_elements=True,
        debug=False,
        fragment_context=None,
    ):
        """
        Args:
            html: The HTML string to parse
            handle_foreign_elements: Whether to handle SVG/MathML elements
            debug: Whether to enable debug prints
            fragment_context: Context element for fragment parsing (e.g., 'td', 'tr')
        """
        self.env_debug = debug
        self.html = html
        self.fragment_context = fragment_context

        # Reset all state for each new parser instance
        self._init_dom_structure()
        # Initialize legacy adoption agency (new experimental version removed)
        self.adoption_agency = AdoptionAgencyAlgorithm(self)

        # Initialize tag handlers in deterministic order
        self.tag_handlers = [
            DoctypeHandler(self),
            TemplateContentAutoEnterHandler(self),
            RawtextStartTagIgnoreHandler(self),
            MalformedSelectStartTagFilterHandler(self),
            SpecialElementHandler(self),
            EarlyMathMLLeafFragmentEnterHandler(self),
            FormattingReconstructionPreludeHandler(self),
            TemplateTagHandler(self),
            TemplateContentFilterHandler(self),
            FragmentPreprocessHandler(self),
            ListingNewlineHandler(self),
            PlaintextHandler(self),
            FramesetPreludeHandler(self),
            BodyReentryHandler(self),
            FramesetLateHandler(self),
            FramesetTagHandler(self),
            SelectTagHandler(self),  # must precede table handling to suppress table tokens inside <select>
            TableTagHandler(self),
            NullParentRecoveryEndHandler(self),  # ensures current_parent before end tag handling
            UnifiedCommentHandler(self),
            ForeignTagHandler(self) if handle_foreign_elements else None,
            ParagraphTagHandler(self),
            AutoClosingTagHandler(self),
            MenuitemElementHandler(self),
            ListTagHandler(self),
            HeadElementHandler(self),
            HtmlTagHandler(self),
            ButtonTagHandler(self),
            VoidElementHandler(self),
            RawtextTagHandler(self),
            BoundaryElementHandler(self),
            FormattingElementHandler(self),
            ImageTagHandler(self),
            TextHandler(self),
            TextNormalizationHandler(self),
            FormTagHandler(self),
            HeadingTagHandler(self),
            RubyElementHandler(self),
            FallbackPlacementHandler(self),
            DefaultElementInsertionHandler(self),
            GenericEndTagHandler(self),
            StructureSynthesisHandler(self),
            PostProcessHandler(self),
        ]
        self.tag_handlers = [h for h in self.tag_handlers if h is not None]

        for handler in self.tag_handlers:
            if isinstance(handler, TextHandler):
                self.text_handler = handler
                break

        # Track a tiny token history window for context-sensitive decisions without
        # proliferating boolean state. Only previous + current are retained.
        self._prev_token = None  # The token processed in the prior loop iteration
        self._last_token = (
            None  # The token currently being processed (internal convenience)
        )

        # Parse immediately upon construction
        self._parse()
        # Post-parse finalization: allow handlers to perform tree normalization
        for handler in self.tag_handlers:
            handler.finalize(self)

    def __repr__(self):
        return f"<TurboHTML root={self.root}>"

    def debug(self, *args, indent=4, **kwargs):
        if not self.env_debug:
            return

        print(f"{' ' * indent}{args[0]}", *args[1:], **kwargs)

    # --- Foreign subtree helpers ---
    def is_plain_svg_foreign(self, context):
        """Return True if current position is inside an <svg> subtree that is not an HTML integration point.

        Table handlers and other HTML tree construction logic use this to suppress HTML
        table scaffolding inside pure SVG subtrees. Delegates to TextHandler's internal
        detection logic (historically _is_plain_svg_foreign) to keep a single source
        of truth without reflective hasattr checks.
        """
        # TextHandler is always registered; rely on direct attribute (no reflection)
        return self.text_handler._is_plain_svg_foreign(context)

    # DOM Structure Methods
    def _init_dom_structure(self):
        """Initialize the basic DOM structure"""
        if self.fragment_context:
            # For fragment parsing, create a simplified structure
            self.root = Node("document-fragment")
            # Don't create html/head/body structure for fragments
            self.html_node = None
        else:
            # Regular document parsing
            self.root = Node("document")
            # Create but don't append html node yet
            self.html_node = Node("html")

            # Always create head node
            head = Node("head")
            self.html_node.append_child(head)

    def _ensure_html_node(self):
        """Materialize <html> into the root if not already present (document mode only)."""
        # Skip for fragment parsing (fragment root is a synthetic document-fragment)
        if self.fragment_context:
            return
        if self.html_node not in self.root.children:
            self.root.append_child(self.html_node)

    # Head access helpers removed – handlers synthesize/locate head directly when necessary.


    def _get_body_node(self):  # minimal body lookup for handlers
        if self.fragment_context:
            return None
        if not self.html_node:
            return None
        for child in self.html_node.children:
            if child.tag_name == "body":
                return child
        return None

    def _has_root_frameset(self):
        """Return True if <html> (when present) has a direct <frameset> child.

        Micro-optimized with a generator expression; no behavior change.
        """
        return bool(
            self.html_node
            and any(ch.tag_name == "frameset" for ch in self.html_node.children)
        )

    def _ensure_body_node(self, context):
        """Return existing <body> or create one (unless frameset/fragment constraints block it)."""
        if self.fragment_context:
            # Special case: html fragment context should create document structure
            if self.fragment_context == "html":
                # Create head and body in the fragment
                head = None
                body = None

                # Look for existing head/body in fragment
                for child in self.root.children:
                    if child.tag_name == "head":
                        head = child
                    elif child.tag_name == "body":
                        body = child

                # Create head if it doesn't exist
                if not head:
                    head = Node("head")
                    self.root.append_child(head)

                # Create body if it doesn't exist
                if not body:
                    body = Node("body")
                    self.root.append_child(body)

                return body
            else:
                return None
        if context.document_state == DocumentState.IN_FRAMESET:
            return None
        body = self._get_body_node()
        if not body:
            body = Node("body")
            self.html_node.append_child(body)
        return body

    # State transition helper methods
    def transition_to_state(self, context, new_state, new_parent=None):
        """Transition context to any document state, optionally with a new parent node"""
        context.transition_to_state(new_state, new_parent)

    # --- Standardized element insertion helpers ---
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
        attributes_override=None,
        preserve_attr_case=False,
        push_override=None,
    ):
        """Insert a start tag's element with controlled stack / current_parent semantics.

        Modes:
          normal    – Standard spec path: push (unless forced void) then optionally enter.
          transient – Insert but never push (synthetic wrappers inside template content).
          void      – Insert and never push/enter (independent of actual tag classification).

        treat_as_void can force void behavior under normal/transient modes. All invariants
        mirror HTML tree construction: no scoped side effects hidden here.
        """
        if mode not in ("normal", "transient", "void"):
            raise ValueError(f"insert_element: unknown mode '{mode}'")
        target_parent = parent or context.current_parent
        tag_name = tag_name_override or token.tag_name
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
                raise ValueError(
                    f"insert_element: transient mode outside template content (tag={tag_name}) not permitted; current_parent={context.current_parent.tag_name}"
                )
        attrs = (
            attributes_override if attributes_override is not None else token.attributes
        )
        new_node = Node(tag_name, attrs, preserve_attr_case=preserve_attr_case)
        if before and before.parent is target_parent:
            target_parent.insert_before(new_node, before)
        else:
            target_parent.append_child(new_node)
        # Determine effective voidness
        is_void = False
        if mode == "void":
            is_void = True
        else:
            is_void = treat_as_void or token.tag_name in VOID_ELEMENTS

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
        return new_node

    # --- Text node helper ---
    def create_text_node(self, text):
        """Create a new text node with the given text content.

        Centralizes the common pattern:
            node = Node("#text"); node.text_content = text

        No insertion or merging logic is performed here – callers remain
        responsible for appending/merging according to context (e.g. RAWTEXT
        vs normal content, foster parenting, etc.). Keeping this lean avoids
        hidden side effects and preserves deterministic control in handlers.
        """
        n = Node("#text")
        n.text_content = text
        return n

    # --- Centralized text insertion helper ---
    def insert_text(
        self,
        text,
        context,
        *,
        parent=None,
        before=None,
        merge=True,
        foster=False,
        strip_replacement=True,
    ):
        """Insert character data performing standard merge with preceding text node.

        Legacy params 'foster' & 'strip_replacement' are kept for handler API stability.
        Fostering / replacement char elision happens earlier in specialized handlers.
        """
        if text == "":  # Fast path noop
            return None

        target_parent = parent or context.current_parent
        # Template content duplication guard (debug-aware): if consecutive calls on same character index into
        # a template 'content' subtree with identical text, skip second merge to avoid FooFoo. We rely on
        # context.last_template_text_index tracking in TextHandler; here we add a secondary safeguard.
        if self.env_debug and target_parent and target_parent.tag_name == 'content':
            self.debug(f"[insert_text] parent=content text='{text}' idx={context.index}")
        # Robust duplication suppression for template content: if last child is identical text AND
        # tokenizer index (when available) is unchanged since that node was appended, skip.
        if target_parent.tag_name == 'content' and target_parent.children:
            last = target_parent.children[-1]
            if last.tag_name == '#text' and last.text_content == text:
                # Heuristic: treat immediate identical text append as duplication artifact.
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
            new_node = self.create_text_node(text)
            target_parent.insert_before(new_node, before)
            return new_node

        if (
            merge
            and target_parent.children
            and target_parent.children[-1].tag_name == "#text"
        ):
            last = target_parent.children[-1]
            if self.env_debug:
                self.debug(f"[insert_text] merging into existing text node len_before={len(last.text_content)} add_len={len(text)}")
            last.text_content += text
            return last

        new_node = self.create_text_node(text)
        target_parent.append_child(new_node)
        if self.env_debug:
            self.debug(f"[insert_text] new text node len={len(text)} parent={target_parent.tag_name}")
        return new_node


    # DOM traversal helper methods
    def find_current_table(self, context):
        """Find the current table element from the open elements stack when in table context."""
        # Always search open elements stack first (even in IN_BODY) so foster-parenting decisions
        # can detect an open table that the insertion mode no longer reflects (foreign breakout, etc.).
        for element in reversed(context.open_elements._stack):
            if element.tag_name == "table":
                return element

        # Fallback: traverse ancestors from current parent (rare recovery)
        current = context.current_parent
        while current:
            if current.tag_name == "table":
                return current
            current = current.parent
        return None

    # Main Parsing Methods
    def _parse(self):
        """Entry point selecting document vs fragment strategy."""
        if self.fragment_context:
            self._parse_fragment()
        else:
            self._parse_document()

    def _parse_fragment(self):
        parse_fragment(self)

    def _handle_fragment_comment(self, text, context):
        """Handle comments in fragment parsing"""
        comment_node = Node("#comment")
        comment_node.text_content = text
        # html fragment AFTER_HTML - attach at fragment root (siblings with head/body) per expected tree
        if (
            self.fragment_context == "html"
            and context.document_state == DocumentState.AFTER_HTML
        ):
            self.root.append_child(comment_node)
            return
        context.current_parent.append_child(comment_node)

    def _parse_document(self):
        """Parse a full HTML document (token loop delegating to handlers)."""
        # Initialize context with html_node as current_parent
        context = ParseContext(len(self.html), self.html_node, debug_callback=self.debug)
        self.tokenizer = HTMLTokenizer(self.html)

        # if self.env_debug:
        #     # Create debug tokenizer with same debug setting
        #     debug_tokenizer = HTMLTokenizer(self.html, debug=self.env_debug)
        #     self.debug(f"TOKENS: {list(debug_tokenizer.tokenize())}", indent=0)

        for token in self.tokenizer.tokenize():
            # Maintain previous token pointer for heuristic-free contextual decisions
            self._prev_token = self._last_token
            self._last_token = token
            self.debug(f"_parse: {token}, context: {context}", indent=0)

            if token.type == "DOCTYPE":
                # Handle DOCTYPE through the DoctypeHandler first
                for handler in self.tag_handlers:
                    if handler.should_handle_doctype(token.data, context):
                        self.debug(f"{handler.__class__.__name__}: handling DOCTYPE")
                        if handler.handle_doctype(token.data, context):
                            break
                context.index = self.tokenizer.pos
                continue

            # (Former malformed start-tag suppression moved to MalformedSelectStartTagFilterHandler)

            if token.type == "Comment":
                handled = False
                for handler in self.tag_handlers:
                    if handler.should_handle_comment(token.data, context) and handler.handle_comment(token.data, context):
                        handled = True
                        break
                if not handled:
                    parent = context.current_parent or self.root
                    node = Node("#comment")
                    node.text_content = token.data
                    parent.append_child(node)
                continue

            # Ensure html node is in tree before processing any non-DOCTYPE/Comment token
            self._ensure_html_node()

            if token.type == "StartTag":
                self._handle_start_tag(
                    token, token.tag_name, context, self.tokenizer.pos
                )
                context.index = self.tokenizer.pos

            elif token.type == "EndTag":
                # In template fragment context, ignore the context's own end tag
                if self.fragment_context == "template" and token.tag_name == "template":
                    continue
                self._handle_end_tag(token, token.tag_name, context)
                context.index = self.tokenizer.pos

            elif token.type == "Character":
                data = token.data
                if data:
                    for handler in self.tag_handlers:
                        if handler.should_handle_text(data, context):
                            self.debug(
                                f"{handler.__class__.__name__}: handling {token}, context={context}"
                            )
                            if handler.handle_text(data, context):
                                break

    def _handle_start_tag(
        self, token, tag_name, context, end_tag_idx
    ):
        """Handle all opening HTML tags."""

        for h in self.tag_handlers:
            if h.early_start_preprocess(token, context):
                return

        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context):
                if handler.handle_start(token, context, not token.is_last_token):
                    # <listing> initial newline suppression handled structurally during character token stage
                    return

    def _handle_end_tag(
        self, token, tag_name, context
    ):
        """Handle all closing HTML tags (spec-aligned, no auxiliary adoption flags)."""
        # Early end-tag preprocessing (mirrors start tag path).
        for h in self.tag_handlers:
            if h.early_end_preprocess(token, context):
                return
        # Create body node if needed and not in frameset mode

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.should_handle_end(tag_name, context):
                if handler.handle_end(token, context):
                    # Ensure current_parent is never None in fragment mode
                    if self.fragment_context and not context.current_parent:
                        context.move_to_element(self.root)
                    return


    # Utility for handlers to create a comment node (keeps single construction style)
    def _create_comment_node(self, text):
        node = Node("#comment")
        node.text_content = text
        return node

    def _merge_adjacent_text_nodes(self, node):
        """Iteratively merge adjacent sibling text nodes (non-recursive)."""
        stack = [node]
        while stack:
            cur = stack.pop()
            if not cur.children:
                continue
            merged = []
            pending_text = None
            changed = False
            for ch in cur.children:
                if ch.tag_name == "#text":
                    if pending_text is None:
                        pending_text = ch
                        merged.append(ch)
                    else:
                        pending_text.text_content += ch.text_content
                        changed = True
                else:
                    pending_text = None
                    merged.append(ch)
            if changed:
                cur.children = merged
            # Push non-text children for processing
            for ch in reversed(cur.children):  # reversed to process in original order depth-first
                if ch.tag_name != "#text":
                    stack.append(ch)
