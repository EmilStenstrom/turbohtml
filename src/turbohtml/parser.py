from __future__ import annotations

from typing import Optional

from turbohtml.context import ParseContext, DocumentState, ContentState
from .handlers import *  # noqa: F401,F403  (intentional: handler registration side-effects)
from turbohtml.tokenizer import HTMLToken, HTMLTokenizer
from turbohtml.adoption import AdoptionAgencyAlgorithm
from .fragment import parse_fragment
from turbohtml.node import Node
from .constants import (
    RAWTEXT_ELEMENTS,
    VOID_ELEMENTS,
)
from .formatting import reconstruct_active_formatting_elements as _reconstruct_fmt


class TurboHTML:
    """
    Main parser interface.
    Instantiation with an HTML string immediately parses into an in‑memory tree
    rooted at `self.root`. Public surface is intentionally small; most spec logic
    lives in handlers and predicate helpers for determinism and testability.
    """

    def __init__(
        self,
        html: str,
        handle_foreign_elements: bool = True,
        debug: bool = False,
        fragment_context: Optional[str] = None,
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
        # Initialize adoption agency algorithm
        self.adoption_agency = AdoptionAgencyAlgorithm(self)

        # Initialize tag handlers in deterministic order
        self.tag_handlers = [
            DoctypeHandler(self),
            RawtextStartTagIgnoreHandler(self),
            SpecialElementHandler(self),
            FormattingReconstructionPreludeHandler(self),
            TemplateTagHandler(self),
            TemplateContentFilterHandler(self),
            FragmentPreprocessHandler(self),
            ListingNewlineHandler(self),
            PlaintextHandler(self),
            FramesetPreludeHandler(self),
            BodyImplicitCreationHandler(self),
            BodyReentryHandler(self),
            FramesetLateHandler(self),
            FramesetTagHandler(self),
            SelectTagHandler(self),  # must precede table handling to suppress table tokens inside <select>
            TableTagHandler(self),
            InitialCommentHandler(self),
            AfterHeadCommentHandler(self),
            AfterHtmlCommentHandler(self),
            AfterFramesetCommentHandler(self),
            InBodyHtmlParentCommentHandler(self),
            CommentPlacementHandler(self),
            PostBodyCharacterHandler(self),
            AfterHeadWhitespaceHandler(self),
            ForeignTagHandler(self) if handle_foreign_elements else None,
            ParagraphTagHandler(self),
            AutoClosingTagHandler(self),
            MenuitemElementHandler(self),
            ListTagHandler(self),
            HeadElementHandler(self),
            BodyElementHandler(self),
            HtmlTagHandler(self),
            ButtonTagHandler(self),
            VoidElementHandler(self),
            RawtextTagHandler(self),
            BoundaryElementHandler(self),
            FormattingElementHandler(self),
            ImageTagHandler(self),
            RawtextTextHandler(self),
            TextHandler(self),
            TextNormalizationHandler(self),
            FormTagHandler(self),
            HeadingTagHandler(self),
            RubyElementHandler(self),
            FallbackPlacementHandler(self),
            UnknownElementHandler(self),
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

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"

    def debug(self, *args, indent=4, **kwargs) -> None:
        if not self.env_debug:
            return

        print(f"{' ' * indent}{args[0]}", *args[1:], **kwargs)

    # --- Foreign subtree helpers ---
    def is_plain_svg_foreign(self, context: ParseContext) -> bool:
        """Return True if current position is inside an <svg> subtree that is not an HTML integration point.

        Table handlers and other HTML tree construction logic use this to suppress HTML
        table scaffolding inside pure SVG subtrees. Delegates to TextHandler's internal
        detection logic (historically _is_plain_svg_foreign) to keep a single source
        of truth without reflective hasattr checks.
        """
        # TextHandler is always registered; rely on direct attribute (no reflection)
        return self.text_handler._is_plain_svg_foreign(context)  # type: ignore[attr-defined]

    # DOM Structure Methods
    def _init_dom_structure(self) -> None:
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

    def _ensure_html_node(self) -> None:
        """Materialize <html> into the root if not already present (document mode only)."""
        # Skip for fragment parsing (fragment root is a synthetic document-fragment)
        if self.fragment_context:
            return
        if self.html_node not in self.root.children:
            self.root.append_child(self.html_node)

    # Head access helpers removed – handlers synthesize/locate head directly when necessary.


    def _get_body_node(self) -> Optional[Node]:  # minimal body lookup for handlers
        if self.fragment_context:
            return None
        if not self.html_node:
            return None
        for child in self.html_node.children:
            if child.tag_name == "body":
                return child
        return None

    def _has_root_frameset(self) -> bool:
        """Return True if <html> (when present) has a direct <frameset> child.

        Micro-optimized with a generator expression; no behavior change.
        """
        return bool(
            self.html_node
            and any(ch.tag_name == "frameset" for ch in self.html_node.children)
        )

    def _ensure_body_node(self, context: ParseContext) -> Optional[Node]:
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
    def transition_to_state(
        self, context: ParseContext, new_state: DocumentState, new_parent: "Node" = None
    ) -> None:
        """Transition context to any document state, optionally with a new parent node"""
        context.transition_to_state(new_state, new_parent)

    # --- Standardized element insertion helpers ---
    def insert_element(
        self,
        token: HTMLToken,
        context: ParseContext,
        *,
        mode: str = "normal",  # 'normal' | 'transient' | 'void'
        enter: bool = True,
        treat_as_void: bool = False,  # force void semantics (ignored if mode == 'void')
        parent: Optional[Node] = None,
        before: Optional[Node] = None,
        tag_name_override: Optional[str] = None,
        attributes_override: Optional[dict] = None,
        preserve_attr_case: bool = False,
        push_override: Optional[bool] = None,  # None => default semantics; True/False force push
    ) -> Node:
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
    def create_text_node(self, text: str) -> Node:
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
        text: str,
        context: ParseContext,
        *,
        parent: Optional[Node] = None,
        before: Optional[Node] = None,
        merge: bool = True,
        foster: bool = False,  # retained for API compatibility (no-op)
        strip_replacement: bool = True,  # retained for API compatibility (no-op)
    ) -> Optional[Node]:
        """Insert character data performing standard merge with preceding text node.

        Legacy params 'foster' & 'strip_replacement' are kept for handler API stability.
        Fostering / replacement char elision happens earlier in specialized handlers.
        """
        if text == "":  # Fast path noop
            return None

        target_parent = parent or context.current_parent
        if (
            target_parent is not None
            and not in_template_content(context)
            and context.content_state != ContentState.RAWTEXT
            and context.current_context not in ("math", "svg")
            and any(not c.isspace() for c in text)
        ):
            deepest_option = None
            for el in reversed(context.open_elements._stack):
                if el.tag_name == "option":
                    deepest_option = el
                    break
            if (
                deepest_option is not None
                and target_parent is not deepest_option
                and not target_parent.find_ancestor(lambda n: n is deepest_option)
            ):
                target_parent = deepest_option
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
            last.text_content += text
            return last

        new_node = self.create_text_node(text)
        target_parent.append_child(new_node)
        return new_node


    # DOM traversal helper methods
    def find_current_table(self, context: ParseContext) -> Optional["Node"]:
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
    def _parse(self) -> None:
        """Entry point selecting document vs fragment strategy."""
        if self.fragment_context:
            self._parse_fragment()
        else:
            self._parse_document()

    def _parse_fragment(self) -> None:
        parse_fragment(self)

    def _create_fragment_context(self) -> "ParseContext":
        """Initialize a fragment ParseContext with state derived from the context element."""
        from turbohtml.context import DocumentState as _DS

        fc = self.fragment_context
        context = ParseContext(len(self.html), self.root, debug_callback=self.debug)

        if fc == "template":
            # Special template: synthesize template/content container then treat as IN_BODY inside content.
            context.transition_to_state(_DS.IN_BODY, self.root)
            template_node = Node("template")
            self.root.append_child(template_node)
            content_node = Node("content")
            template_node.append_child(content_node)
            context.move_to_element(content_node)
            return context

        # Map fragment context to initial DocumentState (default IN_BODY)
        state_map = {
            "td": _DS.IN_CELL,
            "th": _DS.IN_CELL,
            "tr": _DS.IN_ROW,
            "thead": _DS.IN_TABLE_BODY,
            "tbody": _DS.IN_TABLE_BODY,
            "tfoot": _DS.IN_TABLE_BODY,
            "html": _DS.INITIAL,
        }
        target_state = None
        if fc in state_map:
            target_state = state_map[fc]
        elif fc in RAWTEXT_ELEMENTS:
            target_state = _DS.IN_BODY
        else:
            target_state = _DS.IN_BODY
        context.transition_to_state(target_state, self.root)

        # Table fragment: adjust to IN_TABLE for section handling
        if fc == "table":
            context.transition_to_state(_DS.IN_TABLE, self.root)

        # Foreign context detection (math/svg + namespaced)
        if fc:
            if fc in ("math", "svg"):
                context.current_context = fc
                self.debug(f"Set foreign context to {fc}")
            elif " " in fc:  # namespaced
                namespace_elem = fc.split(" ")[0]
                if namespace_elem in ("math", "svg"):
                    context.current_context = namespace_elem
                    self.debug(f"Set foreign context to {namespace_elem}")

        return context

    def _should_ignore_fragment_start_tag(self, tag_name: str, context: "ParseContext") -> bool:
        """Return True if a start tag is ignored under fragment rules.

        Structural table/document suppression has migrated to fragment predicates.
        This residual path handles:
          * Redundant document wrappers (html/head/body/frameset) in non-html fragments.
          * First redundant context element tokens (legacy one-shot suppression).
          * Spec-less fragment contexts (fallback for stray table structure).
        """

        def _at_fragment_root() -> bool:
            cp = context.current_parent
            return cp is self.root or (cp and cp.tag_name == "document-fragment")

        # Ignore document structure elements outside an html fragment (frameset kept so frameset handler can run)
        if (
            tag_name == "html"
            or (tag_name == "head" and self.fragment_context != "html")
            or (tag_name == "frameset" and self.fragment_context != "html")
        ):
            return True
        # Ignore only the first <body>; subsequent bodies merge attributes/content per tests.
        if tag_name == "body":
            existing_body = None
            root = self.root
            for ch in root.children:
                if ch.tag_name == "body":
                    existing_body = ch
                    break
            if not existing_body:
                return True
            return False

        # In foreign contexts (MathML/SVG), let the foreign handlers manage everything
        if context.current_context in ("math", "svg"):
            return False

        # Once in frameset modes inside an html fragment, only frame/frameset/noframes allowed.
        if self.fragment_context == "html":
            if context.document_state in (
                DocumentState.IN_FRAMESET,
                DocumentState.AFTER_FRAMESET,
            ) and tag_name not in ("frameset", "frame", "noframes"):
                return True
        # Select fragment: suppress disallowed interactive inputs
        if self.fragment_context == "select" and tag_name in (
            "input",
            "keygen",
            "textarea",
        ):
            return True

        # Table fragment: ignore nested <table> start tags
        if self.fragment_context == "table" and tag_name == "table":
            return True

        # Context-matching first tag suppression (legacy one-shot) for table-related contexts
        if self.fragment_context in ("td", "th") and tag_name in ("td", "th"):
            if not context.fragment_context_ignored and _at_fragment_root():
                context.fragment_context_ignored = True
                return True
        elif self.fragment_context in ("thead", "tbody", "tfoot") and tag_name in ("thead", "tbody", "tfoot"):
            if not context.fragment_context_ignored and _at_fragment_root():
                context.fragment_context_ignored = True
                return True
        elif self.fragment_context == "tr" and tag_name == "tr":
            if not context.fragment_context_ignored and _at_fragment_root():
                context.fragment_context_ignored = True
                return True
        elif self.fragment_context in ("td", "th") and tag_name == "tr":
            if not context.fragment_context_ignored and _at_fragment_root():
                context.fragment_context_ignored = True
                return True

        # Fallback: for contexts without a FragmentSpec, preserve legacy suppression of stray table structure.
        if self.fragment_context not in (
            "table","tr","td","th","thead","tbody","tfoot"
        ):
            from turbohtml.fragment import FRAGMENT_SPECS as _FRAG_SPECS  # localized import
            if self.fragment_context not in _FRAG_SPECS and tag_name in (
                "caption","colgroup","tbody","thead","tfoot","tr","td","th"
            ):
                return True

        return False

    def _handle_fragment_comment(self, text: str, context: "ParseContext") -> None:
        """Handle comments in fragment parsing"""
        from turbohtml.context import DocumentState

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

    def _parse_document(self) -> None:
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

            # Contextual malformed tag suppression: drop malformed start tags containing '<' inside select subtree.
            if (
                token.type == "StartTag"
                and "<" in token.tag_name
                and context.current_parent
                and (
                    context.current_parent.tag_name in ("select", "option", "optgroup")
                    or context.current_parent.find_ancestor(
                        lambda n: n.tag_name in ("select", "option", "optgroup")
                    )
                )
            ):
                continue

            if token.type == "Comment":
                # Delegate comment handling directly to handlers (parser no longer owns placement logic)
                handled = False
                for handler in self.tag_handlers:
                    if handler.should_handle_comment(token.data, context) and handler.handle_comment(token.data, context):  # type: ignore[attr-defined]
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
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> None:
        """Handle all opening HTML tags."""

        for h in self.tag_handlers:
            if h.early_start_preprocess(token, context):  # type: ignore[attr-defined]
                return

        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context):
                if handler.handle_start(token, context, not token.is_last_token):
                    # <listing> initial newline suppression handled structurally during character token stage
                    return

        # Default handling for unhandled tags
        self.debug(f"No handler found, using default handling for {tag_name}")

        new_node = Node(tag_name, token.attributes)
        # Keep formatting elements on stack: block inside formatting becomes its child (spec behavior).
        context.current_parent.append_child(new_node)
        context.move_to_element(new_node)
        context.open_elements.push(new_node)
        # Perform formatting reconstruction inside newly created block if needed (deferred path without flag)
        from turbohtml.context import DocumentState as _DS  # localized to avoid top-level churn
        BLOCKISH = {"div","section","article","p","ul","ol","li","table","tr","td","th","body","html","h1","h2","h3","h4","h5","h6"}
        if (
            tag_name in BLOCKISH
            and not in_template_content(context)  # type: ignore[name-defined]
        ):
            in_table_modes = context.document_state in (_DS.IN_TABLE, _DS.IN_TABLE_BODY, _DS.IN_ROW)
            if not in_table_modes or context.current_parent.find_ancestor(lambda n: n.tag_name in ("td","th","caption")):
                # Detect missing non-nobr formatting elements (mirrors previous deferred logic)
                afe = context.active_formatting_elements
                missing = False
                if afe and getattr(afe, "_stack", None):  # type: ignore[attr-defined]
                    for entry in afe._stack:  # type: ignore[attr-defined]
                        if entry.element is None:
                            continue
                        if (not context.open_elements.contains(entry.element)) and entry.element.tag_name != "nobr":
                            missing = True
                            break
                if missing:
                    _reconstruct_fmt(self, context)
        # <listing> initial newline suppression handled structurally on character insertion

    def _handle_end_tag(
        self, token: HTMLToken, tag_name: str, context: ParseContext
    ) -> None:
        """Handle all closing HTML tags (spec-aligned, no auxiliary adoption flags)."""
        # Early end-tag preprocessing (mirrors start tag path).
        for h in self.tag_handlers:
            if h.early_end_preprocess(token, context):  # type: ignore[attr-defined]
                return
        # Create body node if needed and not in frameset mode
        if (
            not context.current_parent
            and context.document_state != DocumentState.IN_FRAMESET
        ):
            if self.fragment_context:
                # In fragment mode, restore current_parent to fragment root
                context.move_to_element(self.root)
            else:
                body = self._ensure_body_node(context)
                if body:
                    context.move_to_element(body)

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.should_handle_end(tag_name, context):
                if handler.handle_end(token, context):
                    # Ensure current_parent is never None in fragment mode
                    if self.fragment_context and not context.current_parent:
                        context.move_to_element(self.root)
                    return

        # Template content bounded default closure for simple end tags
        if in_template_content(context):
            # Find the nearest template content boundary
            boundary = None
            node = context.current_parent
            while node:
                if (
                    node.tag_name == "content"
                    and node.parent
                    and node.parent.tag_name == "template"
                ):
                    boundary = node
                    break
                node = node.parent
            # Walk up from current_parent until boundary to find matching tag
            cursor = context.current_parent
            while cursor and cursor is not boundary:
                if cursor.tag_name == tag_name:
                    # Move out of the matching element
                    if cursor.parent:
                        context.move_to_element(cursor.parent)
                    return
                cursor = cursor.parent
            # No match below boundary: ignore
            return


    # Special Node Handling Methods
    # _handle_comment removed: comment placement fully handled by comment handlers + inline fallback

    # Utility for handlers to create a comment node (keeps single construction style)
    def _create_comment_node(self, text: str) -> Node:  # type: ignore[name-defined]
        node = Node("#comment")
        node.text_content = text
        return node

    # _handle_doctype removed (handled entirely by DoctypeHandler)

    # Constants imported at module level for direct use

    def _merge_adjacent_text_nodes(self, node: Node) -> None:
        """Iteratively merge adjacent sibling text nodes (non-recursive)."""
        stack = [node]
        while stack:
            cur = stack.pop()
            if not cur.children:
                continue
            merged: list[Node] = []
            pending_text: Optional[Node] = None
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
