from turbohtml.context import ParseContext, DocumentState, ContentState
from .handlers import *
from turbohtml.tokenizer import HTMLToken, HTMLTokenizer
from turbohtml import table_modes  # phase 1 extraction: table predicates
from turbohtml.adoption import AdoptionAgencyAlgorithm
from .fragment import parse_fragment
from turbohtml.node import Node
from .constants import (
    HEAD_ELEMENTS,
    FORMATTING_ELEMENTS,
    TABLE_ELEMENTS,
    RAWTEXT_ELEMENTS,
    VOID_ELEMENTS,
)
from typing import Optional


class TurboHTML:
    """
    Main parser interface.
    - Instantiation with an HTML string automatically triggers parsing.
    - Provides a root Node that represents the DOM tree.
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

        # Track token history for minimal contextual inferences (e.g. permitting a nested
        # <form> after an ignored premature </form> in table insertion modes). We keep only
        # the immediately previous token to avoid persistent parse-state flags.
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
        """Ensure html node is in the tree if it isn't already"""
        # Skip for fragment parsing
        if self.fragment_context:
            return
        if self.html_node not in self.root.children:
            self.root.append_child(self.html_node)

    # Head access helpers removed – handlers synthesize/locate head directly when necessary.


    def _get_body_node(self) -> Optional[Node]:  # retained minimal body lookup for handlers
        if self.fragment_context:
            return None
        if not self.html_node:
            return None
        for child in self.html_node.children:
            if child.tag_name == "body":
                return child
        return None

    def _has_root_frameset(self) -> bool:
        """Return True if a top-level <frameset> child exists under <html>."""
        if self.html_node is None:  # fragment mode
            return False
        for child in self.html_node.children:
            if child.tag_name == "frameset":
                return True
        return False

    def _ensure_body_node(self, context: ParseContext) -> Optional[Node]:
        """Get or create body node if not in frameset mode"""
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
        parent: Node = None,
        before: Node | None = None,
        tag_name_override: str = None,
        attributes_override: dict = None,
        preserve_attr_case: bool = False,
        push_override: bool
        | None = None,  # None => default semantics, True/False force push behavior for normal mode
    ) -> Node:
        """Create and insert an element for a start tag token and (optionally) update stacks.

        Modes:
          * normal    – Standard spec behavior: push non-void elements onto the open elements stack. 'enter' controls
                        whether the insertion point (current_parent) is moved to the new element (ignored for voids).
          * transient – Insert element, optionally enter it, but NEVER push it on the open elements stack. Used for
                        simplified / synthetic wrappers (e.g. table-ish constructs inside template content) that
                        should act as current insertion point without participating in scope/adoption algorithms.
          * void      – Force void semantics: element is inserted and never pushed nor entered regardless of tag.

        treat_as_void forces void classification within 'normal' or 'transient' modes (e.g. for caption/thead like
        wrappers we don't want on the stack). If mode=='void' this flag is ignored.

        Invariants preserved:
          * current_parent is only set to the new element if (mode in {normal, transient}) AND enter True AND element
            is not (actually or forced) void.
          * Elements on the open elements stack are always non-void and created in normal mode.

        Returns the newly created Node.
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
        parent: Node | None = None,
        before: Node | None = None,
        merge: bool = True,
        foster: bool = False,
        strip_replacement: bool = True,
    ) -> Node | None:
        """Insert character data into the tree with standardized merging / sanitation.

        This concentrates the low‑level mechanics that are repeated across handlers
        while deliberately excluding higher‑level heuristics (body promotion, template
        boundary routing, adoption‑driven reconstruction triggers, PRE first‑newline
        suppression, malformed <code> duplication, etc.). Those remain in the handlers
        so that this helper stays a predictable primitive and *never* drives parser
        state transitions or stack mutations.

        Responsibilities:
          * Optional foster parenting hand‑off (delegates to TextHandler logic)
          * Context‑sensitive U+FFFD stripping (mirrors TextHandler._append_text)
          * frameset_ok invalidation when meaningful characters appear
          * Merge with previous sibling text node (when merge=True and inserting
            at end of parent)
          * Insertion before an existing node when 'before' is supplied (attempting
            merge with the immediate previous sibling only)

        Returns the Node that now holds the text content, or None when the text
        is fully suppressed (e.g. becomes empty after stripping replacement chars).
        """
        if text == "":  # Fast path noop
            return None

        # Determine insertion parent
        target_parent = parent or context.current_parent
        # Option text recovery: if an <option> element is still open on the stack but the current
        # insertion point has drifted outside it (e.g. nested select handling closed outer select
        # and repositioned to its parent), route non‑whitespace character data back into the deepest
        # open <option>. Limited to normal HTML (not template content, not foreign math/svg, not RAWTEXT).
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
        if target_parent is None:  # Defensive; should not happen in normal flow
            return None

        # Foster parenting path delegates early (kept separate to avoid duplicating logic)

        # Decide insertion strategy
        if before is not None and before.parent is target_parent:
            # Insert before specific child; attempt merge with preceding sibling if text node
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
            # No merge possible – create fresh node and insert
            new_node = self.create_text_node(text)
            target_parent.insert_before(new_node, before)
            return new_node

        # Append path (potential merge with last child)
        if (
            merge
            and target_parent.children
            and target_parent.children[-1].tag_name == "#text"
        ):
            last = target_parent.children[-1]
            last.text_content += text
            return last

        # Fresh append
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
        """
        Main parsing loop using ParseContext and HTMLTokenizer.
        """
        if self.fragment_context:
            self._parse_fragment()
        else:
            self._parse_document()

    def _parse_fragment(self) -> None:
        parse_fragment(self)

    def _create_fragment_context(self) -> "ParseContext":
        """Create parsing context for fragment parsing"""
        from turbohtml.context import DocumentState

        # Create context based on the fragment context element
        if self.fragment_context == "template":
            # Special fragment parsing for templates: create a template/content container
            context = ParseContext(len(self.html), self.root, debug_callback=self.debug)
            context.transition_to_state(DocumentState.IN_BODY, self.root)
            template_node = Node("template")
            self.root.append_child(template_node)
            content_node = Node("content")
            template_node.append_child(content_node)
            context.move_to_element(content_node)
            return context

        if self.fragment_context in ("td", "th"):
            context = ParseContext(len(self.html), self.root, debug_callback=self.debug)
            context.transition_to_state(DocumentState.IN_CELL, self.root)
        elif self.fragment_context == "tr":
            context = ParseContext(len(self.html), self.root, debug_callback=self.debug)
            context.transition_to_state(DocumentState.IN_ROW, self.root)
        elif self.fragment_context in ("thead", "tbody", "tfoot"):
            context = ParseContext(len(self.html), self.root, debug_callback=self.debug)
            context.transition_to_state(DocumentState.IN_TABLE_BODY, self.root)
        elif self.fragment_context == "html":
            context = ParseContext(len(self.html), self.root, debug_callback=self.debug)
            # Remain at fragment root; children appended directly (no <html> wrapper node in output)
            context.transition_to_state(DocumentState.INITIAL, self.root)
        elif self.fragment_context in RAWTEXT_ELEMENTS:
            context = ParseContext(len(self.html), self.root, debug_callback=self.debug)
            context.transition_to_state(DocumentState.IN_BODY, self.root)
        else:
            context = ParseContext(len(self.html), self.root, debug_callback=self.debug)
            context.transition_to_state(DocumentState.IN_BODY, self.root)
        # Table fragment: treat insertion mode as IN_TABLE for correct section handling
        if self.fragment_context == "table":
            context.transition_to_state(DocumentState.IN_TABLE, self.root)

        # Set foreign context if fragment context is within a foreign element
        if self.fragment_context:
            if self.fragment_context in ("math", "svg"):
                # Simple foreign context (e.g., fragment_context="math")
                context.current_context = self.fragment_context
                self.debug(f"Set foreign context to {self.fragment_context}")
            elif " " in self.fragment_context:
                # Namespaced foreign element (e.g., fragment_context="math ms")
                namespace_elem = self.fragment_context.split(" ")[0]
                if namespace_elem in ("math", "svg"):
                    context.current_context = namespace_elem
                    self.debug(f"Set foreign context to {namespace_elem}")

        return context

    def _should_ignore_fragment_start_tag(
        self, tag_name: str, context: "ParseContext"
    ) -> bool:
        """Check if a start tag should be ignored in fragment parsing context"""
        # HTML5 Fragment parsing rules

        # In non-document fragment contexts, ignore document structure elements
        # (except allow <frameset> when fragment_context == 'html' so frameset handler can run).
        if (
            tag_name == "html"
            or (tag_name == "head" and self.fragment_context != "html")
            or (tag_name == "frameset" and self.fragment_context != "html")
        ):
            return True
        # Ignore <body> start tag in fragment parsing if a body element already exists in the fragment root.
        # Structural inference: if any child of fragment root (or its descendants) is a <body>, further <body>
        # tags should not be ignored (we allow flow content). We only skip the first redundant <body>.
        if tag_name == "body":
            # Walk fragment root children to detect existing body
            existing_body = None
            # Contexts always operate relative to parser root
            root = self.root
            # Direct children scan (fragment root holds parsed subtree)
            for ch in root.children:
                if ch.tag_name == "body":
                    existing_body = ch
                    break
            if not existing_body:
                return True  # Suppress first <body> in fragment context
            return False

        # In foreign contexts (MathML/SVG), let the foreign handlers manage everything
        # Fragment parsing is less relevant in foreign contexts
        if context.current_context in ("math", "svg"):
            return False

        # Special-case (html fragment only): once we enter frameset insertion modes, ignore any
        # non-frameset elements (only frame/frameset/noframes permitted). This mirrors document
        # parsing frameset insertion mode while suppressing stray flow content provided in the
        # fragment source after a root <frameset>.
        if self.fragment_context == "html":
            if context.document_state in (
                DocumentState.IN_FRAMESET,
                DocumentState.AFTER_FRAMESET,
            ) and tag_name not in ("frameset", "frame", "noframes"):
                return True
        # Select fragment: suppress disallowed interactive inputs (treated as parse errors, dropped)
        if self.fragment_context == "select" and tag_name in (
            "input",
            "keygen",
            "textarea",
        ):
            return True

        # Table fragment: ignore nested <table> start tags; treat its internal rows/sections directly
        if self.fragment_context == "table" and tag_name == "table":
            return True

        # Ignore the first start tag token whose name matches the fragment context element
        # for table-related contexts (sections, row, cell). After the first ignore we must
        # allow subsequent identical tags to be processed normally so that nested structure
        # (e.g. a <table><td> inside a td fragment) is constructed.
        if self.fragment_context in ("td", "th") and tag_name in ("td", "th"):
            # Only ignore if we're still at the fragment root insertion point so nested table
            # structures can create their own cells.
            at_fragment_root = context.current_parent is self.root or (
                context.current_parent and context.current_parent.tag_name == "document-fragment"
            )
            if not context.fragment_context_ignored and at_fragment_root:
                context.fragment_context_ignored = True
                return True
        elif self.fragment_context in ("thead", "tbody", "tfoot") and tag_name in (
            "thead",
            "tbody",
            "tfoot",
        ):
            at_fragment_root = context.current_parent is self.root or (
                context.current_parent and context.current_parent.tag_name == "document-fragment"
            )
            if not context.fragment_context_ignored and at_fragment_root:
                context.fragment_context_ignored = True
                return True
        elif self.fragment_context == "tr" and tag_name == "tr":
            at_fragment_root = context.current_parent is self.root or (
                context.current_parent and context.current_parent.tag_name == "document-fragment"
            )
            if not context.fragment_context_ignored and at_fragment_root:
                context.fragment_context_ignored = True
                return True
        elif self.fragment_context in ("td", "th") and tag_name == "tr":
            # Leading <tr> before any cell in td/th fragment (test expectation: drop it)
            at_fragment_root = context.current_parent is self.root or (
                context.current_parent and context.current_parent.tag_name == "document-fragment"
            )
            if not context.fragment_context_ignored and at_fragment_root:
                context.fragment_context_ignored = True
                return True

        # Non-table fragments: ignore stray table-structural tags so their contents flow to parent (prevents
        # spurious table construction inside phrasing contexts like <span> fragment when encountering <td><span>).
        if self.fragment_context not in (
            "table",
            "tr",
            "td",
            "th",
            "thead",
            "tbody",
            "tfoot",
        ) and tag_name in (
            "caption",
            "colgroup",
            "tbody",
            "thead",
            "tfoot",
            "tr",
            "td",
            "th",
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
        """Parse HTML as a full document (original logic)"""
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

            # Contextual malformed tag suppression: if a start tag token has a raw '<' in its tag name
            # (tokenizer tolerated malformed name) and the current insertion point is within a select/option/
            # optgroup subtree, drop it. Outside select-related subtrees we preserve literal malformed names
            # to match expected tree output for generic malformed constructs.
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
                # Dispatch to handlers (SpecialElementHandler now covers previous special-element logic)
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
                # Normalization handled by TextNormalizationHandler.

        # Structural synthesis and normalization moved to StructureSynthesisHandler.finalize()

    # Tag Handling Methods
    def _handle_start_tag(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> None:
        """Handle all opening HTML tags."""

        # RAWTEXT start tag suppression handled by RawtextStartTagIgnoreHandler early_start_preprocess

        # Rawtext elements (style/script) encountered while in table insertion mode should
        # become children of the current table element (before any row groups) rather than
        # being foster parented outside. Handle this directly here prior to generic handlers.
        if (
            tag_name in ("style", "script")
            and context.document_state == DocumentState.IN_TABLE
            and not in_template_content(context)
        ):
            # Let normal table handling place script/style (may end up inside row if appropriate)
            pass

        # Early start-tag preprocessing: give all handlers a chance to suppress/synthesize before dispatch.
        # Handlers that don't implement the hook inherit the no-op base method (no branching/try needed).
        for h in self.tag_handlers:
            if h.early_start_preprocess(token, context):  # type: ignore[attr-defined]
                return

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context):
                if handler.handle_start(token, context, not token.is_last_token):
                    # <listing> initial newline suppression handled structurally during character token stage
                    return

        # Default handling for unhandled tags
        self.debug(f"No handler found, using default handling for {tag_name}")

        new_node = Node(tag_name, token.attributes)
        # Do NOT prematurely unwind formatting elements when inserting a block-level element.
        # Current parent at this point may be a formatting element (e.g. <cite> inside <b>) and
        # per spec the block should become its child, not a sibling produced by popping the
        # formatting element. We therefore simply append without altering any formatting stack
        # beyond the normal open-elements push.
        context.current_parent.append_child(new_node)
        context.move_to_element(new_node)
        context.open_elements.push(new_node)
        # Execute deferred reconstruction inside the newly created block if flagged.
        if context._deferred_block_reconstruct:
            # Clear flag before running to avoid repeat on nested blocks
            context._deferred_block_reconstruct = False
            self.reconstruct_active_formatting_elements(context)
        # <listing> initial newline suppression handled structurally on character insertion

    def _handle_end_tag(
        self, token: HTMLToken, tag_name: str, context: ParseContext
    ) -> None:
        """Handle all closing HTML tags (spec-aligned, no auxiliary adoption flags)."""
        # Early end-tag preprocessing (mirrors start-tag early hook). Allows handlers to suppress or
        # synthesize behavior (e.g., stray </table> ignore) before generic parser logic.
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

        # In template content, perform a bounded default closure for simple end tags
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
        """Recursively merge adjacent text node children for cleaner DOM output.

        This is a post-processing normalization to align with HTML parsing conformance outputs
            where successive character insertions that are contiguous end up in a single
            text node. It is intentionally conservative: only merges direct siblings
            that are both '#text'.
        """
        if not node.children:
            return
        merged = []
        pending_text = None
        for child in node.children:
            if child.tag_name == "#text":
                if pending_text is None:
                    pending_text = child
                else:
                    # Merge into pending
                    pending_text.text_content += child.text_content
            else:
                if pending_text is not None:
                    merged.append(pending_text)
                    pending_text = None
                merged.append(child)
        if pending_text is not None:
            merged.append(pending_text)
        # Only replace if changed
        if len(merged) != len(node.children):
            node.children = merged
        # Recurse
        for child in node.children:
            if child.tag_name != "#text":
                self._merge_adjacent_text_nodes(child)




    def reconstruct_active_formatting_elements(self, context: "ParseContext") -> None:
        """
        Reconstruct active formatting elements inside the current parent.

        This implements the "reconstruct the active formatting elements"
        algorithm from the HTML5 specification. When a block element
        interrupts formatting elements, those formatting elements must
        be reconstructed inside the new block.
        """
        if context.active_formatting_elements.is_empty():
            return

        # Step 1: If there are no entries, return (already handled)
        afe_list = list(context.active_formatting_elements)
        if not afe_list:
            return

        # Step 2: If the last entry's element is already on the open elements stack, return
        # (Optimization: we detect earliest needing reconstruction below)

        # Forward scan (legacy implementation used by current handler logic): find earliest entry whose
        # element is missing from the open elements stack, then reconstruct from that point forward.
        index_to_reconstruct_from = None
        for i, entry in enumerate(afe_list):
            if entry.element is None:
                continue
            if not context.open_elements.contains(entry.element):
                index_to_reconstruct_from = i
                break
        if index_to_reconstruct_from is None:
            return

        afe_list = list(context.active_formatting_elements)
        if index_to_reconstruct_from is None:
            return

        for entry in afe_list[index_to_reconstruct_from:]:
            if entry.element is None:
                continue
            if context.open_elements.contains(entry.element):
                continue
            # Suppress redundant sibling <nobr> reconstruction at block/body level: when the current
            # insertion parent is a block container whose last child is already a <nobr>, skip cloning
            # another stale <nobr> here. This prevents creation of an empty peer wrapper immediately
            # before an incoming block element while leaving other formatting reconstruction unaffected.
            if (
                entry.element.tag_name == "nobr"
                and context.current_parent.tag_name
                in ("body", "div", "section", "article", "p")
                and context.current_parent.children
                and context.current_parent.children[-1].tag_name == "nobr"
            ):
                continue
            # NOTE: Intentionally do NOT suppress duplicate <b> cloning here; per spec each missing
            # formatting element entry must be reconstructed, producing nested <b> wrappers when
            # multiple <b> elements were active at the time a block element interrupted them.
            # Reuse existing current_parent if same tag and attribute set and still empty (prevents redundant wrapper)
            if (
                entry.element.tag_name
                == "nobr"  # Only reuse for <nobr>; other tags (e.g., <b>, <i>) must clone to preserve nesting depth
                and context.current_parent
                and context.current_parent.tag_name == entry.element.tag_name
                and context.current_parent.attributes == entry.element.attributes
                and not any(
                    ch.tag_name == "#text" for ch in context.current_parent.children
                )
            ):
                # Point active formatting entry at existing element instead of cloning a new one
                entry.element = context.current_parent
                context.open_elements.push(context.current_parent)
                if self.env_debug:
                    self.debug(
                        f"Reconstructed (reused) formatting element {context.current_parent.tag_name} (no clone)"
                    )
                continue
            clone = Node(entry.element.tag_name, entry.element.attributes.copy())
            if context.document_state in (
                DocumentState.IN_TABLE,
                DocumentState.IN_TABLE_BODY,
                DocumentState.IN_ROW,
            ):
                first_table_idx = None
                for idx, child in enumerate(context.current_parent.children):
                    if child.tag_name == "table":
                        first_table_idx = idx
                        break
                if first_table_idx is not None:
                    context.current_parent.children.insert(first_table_idx, clone)
                    clone.parent = context.current_parent
                else:
                    context.current_parent.append_child(clone)
            else:
                context.current_parent.append_child(clone)
            context.open_elements.push(clone)
            entry.element = clone
            context.move_to_element(clone)
            self.debug(f"Reconstructed formatting element {clone.tag_name}")
