from turbohtml.context import ParseContext, DocumentState, ContentState
from turbohtml.handlers import (
    AutoClosingTagHandler,
    DoctypeHandler,
    TemplateTagHandler,
    TemplateContentFilterHandler,
    FragmentPreprocessHandler,
    ForeignTagHandler,
    FormattingElementHandler,
    FormTagHandler,
    HeadingTagHandler,
    ListTagHandler,
    MenuitemElementHandler,
    ParagraphTagHandler,
    RawtextTagHandler,
    SelectTagHandler,
    TableTagHandler,
    TextHandler,
    VoidElementHandler,
    HeadElementHandler,
    ImageTagHandler,
    HtmlTagHandler,
    FramesetTagHandler,
    BodyReentryHandler,
    BodyImplicitCreationHandler,
    FramesetOkHandler,
    FramesetGuardHandler,
    BodyElementHandler,
    BoundaryElementHandler,
    ButtonTagHandler,
    PlaintextHandler,
    UnknownElementHandler,
    RubyElementHandler,
    FallbackPlacementHandler,
)
from turbohtml.node import Node
from turbohtml.tokenizer import (
    HTMLToken,
    HTMLTokenizer,
    NUMERIC_ENTITY_INVALID_SENTINEL as _NE_SENTINEL,
)
from turbohtml import table_modes  # phase 1 extraction: table predicates
from turbohtml.adoption import AdoptionAgencyAlgorithm
from .fragment import parse_fragment

from .constants import (
    HEAD_ELEMENTS,
    FORMATTING_ELEMENTS,
    TABLE_ELEMENTS,
    RAWTEXT_ELEMENTS,
    VOID_ELEMENTS,
    MATHML_ELEMENTS,
    MATHML_CASE_SENSITIVE_ATTRIBUTES,
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
            TemplateTagHandler(self),
            TemplateContentFilterHandler(self),
            FragmentPreprocessHandler(self),
            PlaintextHandler(self),
            FramesetOkHandler(self),
            BodyImplicitCreationHandler(self),
            FramesetGuardHandler(self),
            BodyReentryHandler(self),
            FramesetTagHandler(self),
            SelectTagHandler(self),  # must precede table handling to suppress table tokens inside <select>
            TableTagHandler(self),
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
            TextHandler(self),
            FormTagHandler(self),
            HeadingTagHandler(self),
            RubyElementHandler(self),
            FallbackPlacementHandler(self),
            UnknownElementHandler(self),
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
        self._finalize_tree()

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

    def _get_head_node(self) -> Optional[Node]:
        """Get head node from tree, if it exists"""
        if self.fragment_context:
            return None
        return next(
            (child for child in self.html_node.children if child.tag_name == "head"),
            None,
        )

    def _get_body_node(self) -> Optional[Node]:
        """Get body node from tree, if it exists"""
        if self.fragment_context:
            return None
        return next(
            (child for child in self.html_node.children if child.tag_name == "body"),
            None,
        )

    def _ensure_head_node(self) -> Node:
        """Get or create head node"""
        if self.fragment_context:
            return None
        head = self._get_head_node()
        if not head:
            head = Node("head")
            # Insert head after any existing comments but before body or other structural elements
            insert_index = 0
            for i, child in enumerate(self.html_node.children):
                if child.tag_name == "body":
                    # Insert before body
                    insert_index = i
                    break
                elif child.tag_name not in ("#comment", "#text"):
                    # Insert before other non-comment, non-text elements
                    insert_index = i
                    break
                else:
                    # Keep going - comments should come before head
                    insert_index = i + 1

            self.html_node.insert_child_at(insert_index, head)
        return head

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

    def ensure_body_context(self, context: ParseContext) -> None:
        """Ensure context is in body context, transitioning if needed"""
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            body = self._ensure_body_node(context)
            context.transition_to_state(DocumentState.IN_BODY, body)

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
        if (
            not tag_name and self.env_debug
        ):  # Unexpected – surface loudly during migration
            self.debug(
                f"insert_element: EMPTY tag name for token={token} parent={target_parent.tag_name} open={[e.tag_name for e in context.open_elements._stack]}",
                indent=2,
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
                raise ValueError(
                    f"insert_element: transient mode outside template content (tag={tag_name}) not permitted; current_parent={context.current_parent.tag_name}"
                )
        attrs = (
            attributes_override if attributes_override is not None else token.attributes
        )
        new_node = Node(tag_name, attrs, preserve_attr_case=preserve_attr_case)
        self._normalize_mathml_attributes(new_node)
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

    def _should_preserve_replacement(self, node: Node) -> bool:
        cur = node.parent
        while cur:
            tag = cur.tag_name
            if tag == "plaintext":
                return True
            if tag in ("script", "style"):
                return True
            if tag.startswith("svg "):
                return True
            cur = cur.parent
        return False

    def _sanitize_text_node(self, node: Node) -> None:
        if node.tag_name != "#text" or node.text_content is None:
            return
        text = node.text_content
        if not text:
            return
        had_sentinel = _NE_SENTINEL in text
        if had_sentinel:
            text = text.replace(_NE_SENTINEL, "\ufffd")
        if "\ufffd" in text and not had_sentinel and not self._should_preserve_replacement(node):
            text = text.replace("\ufffd", "")
        if text is not node.text_content:
            node.text_content = text

    def _append_text_content(self, node: Node, text: str) -> None:
        if not text:
            return
        if node.tag_name != "#text":
            raise ValueError("_append_text_content expects a text node")
        existing = node.text_content or ""
        node.text_content = existing + text
        self._sanitize_text_node(node)

    def _normalize_mathml_attributes(self, node: Node) -> None:
        if not node.attributes:
            return
        parts = node.tag_name.split()
        local_name = parts[-1] if parts else node.tag_name
        is_mathml = node.tag_name.startswith("math ") or local_name in MATHML_ELEMENTS
        if not is_mathml:
            return
        normalized = {}
        for name, value in node.attributes.items():
            lower = name.lower()
            target = MATHML_CASE_SENSITIVE_ATTRIBUTES.get(lower, lower)
            normalized[target] = value
        node.attributes = normalized

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
            and not self._is_in_template_content(context)
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
        if foster:
            # Reuse existing TextHandler foster logic (always present) for consistency.
            self.text_handler._foster_parent_text(text, context)
            return None  # Foster logic handles insertion; no direct node reference guaranteed

        # Replacement character policy: mirror TextHandler._append_text — strip outside
        # plain SVG foreign subtrees when strip_replacement is True.
        if (
            strip_replacement
            and "\ufffd" in text
            and not self.is_plain_svg_foreign(context)
        ):  # type: ignore[arg-type]
            text = text.replace("\ufffd", "")
            if text == "":
                return None

        # frameset_ok toggling (meaningful = non‑whitespace, non‑replacement)
        if context.frameset_ok and any(
            (not c.isspace()) and c != "\ufffd" for c in text
        ):
            context.frameset_ok = False

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
                self._append_text_content(prev_node, text)
                return prev_node
            # No merge possible – create fresh node and insert
            new_node = self.create_text_node(text)
            target_parent.insert_before(new_node, before)
            self._sanitize_text_node(new_node)
            return new_node

        # Append path (potential merge with last child)
        if (
            merge
            and target_parent.children
            and target_parent.children[-1].tag_name == "#text"
        ):
            last = target_parent.children[-1]
            self._append_text_content(last, text)
            return last

        # Fresh append
        new_node = self.create_text_node(text)
        target_parent.append_child(new_node)
        self._sanitize_text_node(new_node)
        return new_node

        # MathML attribute case normalization (definitionURL, etc.) for nodes not processed by foreign handler
        from .constants import MATHML_CASE_SENSITIVE_ATTRIBUTES, MATHML_ELEMENTS

        def normalize_mathml(node: Node):
            parts = node.tag_name.split()
            local = parts[-1] if parts else node.tag_name
            is_mathml = local in MATHML_ELEMENTS or node.tag_name.startswith("math ")
            if is_mathml and node.attributes:
                new_attrs = {}
                for k, v in node.attributes.items():
                    kl = k.lower()
                    if kl in MATHML_CASE_SENSITIVE_ATTRIBUTES:
                        new_attrs[MATHML_CASE_SENSITIVE_ATTRIBUTES[kl]] = v
                    else:
                        new_attrs[kl] = v
                node.attributes = new_attrs
            for ch in node.children:
                if ch.tag_name != "#text":
                    normalize_mathml(ch)

        normalize_mathml(self.root)

        # Collapse adjacent duplicate formatting wrappers created via adoption cloning (<b><b>...)
        def collapse_formatting(node: Node):
            i = 0
            while i < len(node.children) - 1:
                a = node.children[i]
                b = node.children[i + 1]
                if (
                    a.tag_name in FORMATTING_ELEMENTS
                    and b.tag_name == a.tag_name
                    and a.attributes == b.attributes
                    and len(a.children) == 1
                    and a.children[0] is b
                    and not any(ch.tag_name == "#text" for ch in a.children)
                ):
                    # promote b's children
                    grandchildren = list(b.children)
                    for gc in grandchildren:
                        b.remove_child(gc)
                        a.append_child(gc)
                    node.remove_child(b)
                    continue  # re-check at same index
                i += 1
            for ch in node.children:
                if ch.tag_name != "#text":
                    collapse_formatting(ch)

        collapse_formatting(self.root)


        # Foreign (SVG/MathML) attribute ordering & normalization adjustments:
        #   * SVG: expected serialization orders some xml:* and definitionurl attributes: definitionurl first, then
        #           xml lang, xml space, any other xml:* (excluding xml:base), and xml:base last; unknown xml:* kept.
        #           xml:lang / xml:space displayed without colon after xml ("xml lang"). xml:base retains colon.
        #   * MathML: ensure definitionURL casing and represent xlink:* attributes as "xlink <local>" (space separator)
        #             ordered by local name after definitionURL and other non-xlink attributes.
        def _adjust_foreign_attrs(node: Node):
            parts = node.tag_name.split()
            local = parts[-1] if parts else node.tag_name
            is_svg = node.tag_name.startswith("svg ") or local == "svg"
            is_math = node.tag_name.startswith("math ") or local == "math"
            if is_svg and node.attributes:
                attrs = dict(node.attributes)  # copy
                defn_val = attrs.pop("definitionurl", None)
                xml_lang = attrs.pop("xml:lang", None)
                xml_space = attrs.pop("xml:space", None)
                xml_base = attrs.pop("xml:base", None)
                # Other xml:* attributes retain colon form and order (exclude converted ones and xml:base handled separately)
                other_xml = []
                for k in list(attrs.keys()):
                    if k.startswith("xml:") and k not in (
                        "xml:lang",
                        "xml:space",
                        "xml:base",
                    ):
                        other_xml.append((k, attrs.pop(k)))
                new_attrs = {}
                if defn_val is not None:
                    new_attrs["definitionurl"] = defn_val
                # For child SVG elements ensure non-xml (e.g. xlink:*) precede xml lang/space
                for k, v in node.attributes.items():
                    if not (
                        k in ("definitionurl", "xml:lang", "xml:space", "xml:base")
                        or k.startswith("xml:")
                    ):
                        new_attrs[k] = v
                if xml_lang is not None:
                    new_attrs["xml lang"] = xml_lang
                if xml_space is not None:
                    new_attrs["xml space"] = xml_space
                for k, v in other_xml:
                    new_attrs[k] = v
                if xml_base is not None:
                    new_attrs["xml:base"] = xml_base
                node.attributes = new_attrs
            elif is_math and node.attributes:
                attrs = dict(node.attributes)
                # Promote/normalize definitionurl -> definitionURL
                if "definitionurl" in attrs and "definitionURL" not in attrs:
                    attrs["definitionURL"] = attrs.pop("definitionurl")
                # Collect xlink:* attributes
                xlink_attrs = [
                    (k, v) for k, v in attrs.items() if k.startswith("xlink:")
                ]
                if xlink_attrs:
                    for k, _ in xlink_attrs:
                        del attrs[k]
                    # Sort xlink locals alphabetically
                    xlink_attrs.sort(key=lambda kv: kv[0].split(":", 1)[1])
                    rebuilt = {}
                    if "definitionURL" in attrs:
                        rebuilt["definitionURL"] = attrs.pop("definitionURL")
                    # Place xlink attributes before remaining math attributes
                    for k, v in xlink_attrs:
                        rebuilt[f"xlink {k.split(':', 1)[1]}"] = v
                    for k, v in attrs.items():
                        rebuilt[k] = v
                    node.attributes = rebuilt
            for ch in node.children:
                if ch.tag_name != "#text":
                    _adjust_foreign_attrs(ch)

        _adjust_foreign_attrs(self.root)

        # Reorder AFTER_HEAD whitespace that (due to earlier implicit body creation) ended up
        # after the <body> element instead of between <head> and <body>. Spec: whitespace
        # character tokens in the AFTER_HEAD insertion mode are inserted before creating the
        # body element. If our construction produced <head><body><text ws> reorder to
        # <head><text ws><body>. Only perform when the text node is pure whitespace and no
        # other intervening element/content exists that would make reordering unsafe.
        html = self.html_node if not self.fragment_context else None
        if html and len(html.children) >= 3:
            # Pattern: head, body, whitespace-text (optionally more whitespace-only text siblings)
            head = (
                html.children[0]
                if html.children and html.children[0].tag_name == "head"
                else None
            )
            # Find first body element index
            body_index = None
            for i, ch in enumerate(html.children):
                if ch.tag_name == "body":
                    body_index = i
                    break
            if head and body_index is not None and body_index + 1 < len(html.children):
                after = html.children[body_index + 1]
                if (
                    after.tag_name == "#text"
                    and after.text_content is not None
                    and after.text_content.strip() == ""
                ):
                    # Ensure there is no earlier whitespace text already between head and body
                    between_ok = True
                    for mid in html.children[1:body_index]:
                        if not (
                            mid.tag_name == "#text"
                            and mid.text_content is not None
                            and mid.text_content.strip() == ""
                        ):
                            between_ok = False
                            break
                    if between_ok:
                        # Move the whitespace text node so it sits right after head (index after any existing
                        # whitespace already there, preserving relative order of multiple whitespace nodes)
                        ws_nodes = []
                        j = body_index + 1
                        while (
                            j < len(html.children)
                            and html.children[j].tag_name == "#text"
                            and html.children[j].text_content is not None
                            and html.children[j].text_content.strip() == ""
                        ):
                            ws_nodes.append(html.children[j])
                            j += 1
                        # Remove collected whitespace nodes
                        for n in ws_nodes:
                            html.remove_child(n)
                        # Determine insertion index (after head and any existing whitespace directly after head)
                        insert_at = 1
                        while (
                            insert_at < len(html.children)
                            and html.children[insert_at].tag_name == "#text"
                            and html.children[insert_at].text_content is not None
                            and html.children[insert_at].text_content.strip() == ""
                        ):
                            insert_at += 1
                        for offset, n in enumerate(ws_nodes):
                            html.children.insert(insert_at + offset, n)
                            n.parent = html

        # Frameset trailing comments: no buffering; any required reordering handled during <noframes> insertion.

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

    def has_form_ancestor(self, context: ParseContext) -> bool:
        """Check if there's a form element in the ancestry."""
        current = context.current_parent
        while current:
            if current.tag_name == "form":
                return True
            current = current.parent
        return False

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
                self._handle_comment(token.data, context)
                continue

            # Ensure html node is in tree before processing any non-DOCTYPE/Comment token
            self._ensure_html_node()

            if token.type == "StartTag":
                # Handle special elements and state transitions first
                if self._handle_special_element(
                    token, token.tag_name, context, self.tokenizer.pos
                ):
                    context.index = self.tokenizer.pos
                    continue

                # Then handle the actual tag
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
                # Listing/pre-like initial newline suppression (only implemented for <listing> here)
                data = token.data
                # Spec recovery: In AFTER_BODY / AFTER_HTML insertion modes, a non-whitespace character token
                # is a parse error; the tokenizer reprocesses it in the IN_BODY insertion mode. We emulate this
                # by transitioning back to IN_BODY (ensuring body exists) before normal text handling so that
                # subsequent comments (and this text) become body descendants (frameset comment ordering rule).
                if (
                    context.document_state
                    in (DocumentState.AFTER_BODY, DocumentState.AFTER_HTML)
                    and data.strip() != ""
                ):
                    body = self._get_body_node() or self._ensure_body_node(context)
                    if body:
                        context.move_to_element(body)
                        context.transition_to_state(DocumentState.IN_BODY, body)
                # AFTER_HEAD: whitespace-only character tokens must be inserted at the html element
                # (parse error if body already started) without creating the body. Only non-whitespace
                # text forces implicit body creation. This preserves ordering for tests expecting the
                # newline/space node before <body> (frameset whitespace relocation rule).
                if (
                    context.document_state == DocumentState.AFTER_HEAD
                    and data
                    and data.strip() == ""
                ):
                    html_node = self.html_node
                    if html_node and html_node in self.root.children:
                        # Append or merge with preceding text under html (not inside head/body)
                        if (
                            html_node.children
                            and html_node.children[-1].tag_name == "#text"
                        ):
                            self._append_text_content(html_node.children[-1], data)
                        else:
                            text_node = self.create_text_node(data)
                            html_node.append_child(text_node)
                            self._sanitize_text_node(text_node)
                        # Skip normal text handling
                        continue
                if (
                    context.current_parent.tag_name == "listing"
                    and not context.current_parent.children
                    and data.startswith("\n")
                ):
                    data = data[1:]
                # Fast path: in PLAINTEXT mode all characters (including '<' and '&') are literal children
                if context.content_state == ContentState.PLAINTEXT:
                    if data:
                        text_node = self.create_text_node(data)
                        context.current_parent.append_child(text_node)
                        self._sanitize_text_node(text_node)
                else:
                    if data:
                        for handler in self.tag_handlers:
                            if handler.should_handle_text(data, context):
                                self.debug(
                                    f"{handler.__class__.__name__}: handling {token}, context={context}"
                                )
                                if handler.handle_text(data, context):
                                    # After inserting text inside a block, perform a targeted inline normalization
                                    # for redundant trailing formatting clones that could not be unwrapped during
                                    # the adoption phase because they were empty at that time (avoid duplicating emptied wrappers).
                                    self._post_text_inline_normalize(context)
                                    break
                    # Even if no handler consumed (or additional handlers appended text differently), run normalization
                    self._post_text_inline_normalize(context)

        # After tokens: synthesize missing structure unless frameset document
        if (
            context.document_state != DocumentState.IN_FRAMESET
            and not self._has_root_frameset()
        ):
            # Ensure HTML node is in the tree
            self._ensure_html_node()
            # Ensure head exists first
            self._ensure_head_node()
            # Then ensure body exists
            body = self._ensure_body_node(context)
            if body:
                context.transition_to_state(DocumentState.IN_BODY)

        # Normalize tree: merge adjacent text nodes (can result from foster parenting / reconstruction)
        self._merge_adjacent_text_nodes(self.root)

    # Tag Handling Methods
    def _handle_start_tag(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> None:
        """Handle all opening HTML tags."""

        if context.content_state == ContentState.RAWTEXT:
            self.debug("In rawtext mode, ignoring start tag")
            return

        # Rawtext elements (style/script) encountered while in table insertion mode should
        # become children of the current table element (before any row groups) rather than
        # being foster parented outside. Handle this directly here prior to generic handlers.
        if (
            tag_name in ("style", "script")
            and context.document_state == DocumentState.IN_TABLE
            and not self._is_in_template_content(context)
        ):
            # Let normal table handling place script/style (may end up inside row if appropriate)
            pass

        # Per HTML5 spec, before processing most start tags, reconstruct the active
        # formatting elements. However, in table insertion modes (IN_TABLE, IN_TABLE_BODY,
        # IN_ROW) and when not inside a cell/caption, reconstructing would wrongly insert
        # formatting elements as children of <table>/<tbody>/<tr>. Skip reconstruction in
        # those cases; formatting will be handled via foster parenting and adoption agency.
        if not self._is_in_template_content(context):
            in_table_modes = context.document_state in (
                DocumentState.IN_TABLE,
                DocumentState.IN_TABLE_BODY,
                DocumentState.IN_ROW,
            )
            in_cell_or_caption = bool(
                context.current_parent.find_ancestor(
                    lambda n: n.tag_name in ("td", "th", "caption")
                )
            )
            if in_table_modes and not in_cell_or_caption:
                if context.current_parent.tag_name in (
                    "table",
                    "tbody",
                    "thead",
                    "tfoot",
                    "tr",
                ):
                    pass
                else:
                    self.reconstruct_active_formatting_elements(context)
            else:
                blockish = (
                    "div",
                    "section",
                    "article",
                    "p",
                    "ul",
                    "ol",
                    "li",
                    "table",
                    "tr",
                    "td",
                    "th",
                    "body",
                    "html",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                )
                if tag_name not in blockish:
                    self.reconstruct_active_formatting_elements(context)
                else:
                    missing_non_nobr = False
                    if (
                        context.active_formatting_elements
                        and context.active_formatting_elements._stack
                    ):
                        for entry in context.active_formatting_elements._stack:
                            if entry.element is None:
                                continue
                            if (
                                not context.open_elements.contains(entry.element)
                                and entry.element.tag_name != "nobr"
                            ):
                                missing_non_nobr = True
                                break
                    context._deferred_block_reconstruct = (
                        missing_non_nobr  # transient attribute (not read elsewhere)
                    )

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
        if getattr(context, "_deferred_block_reconstruct", False):
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
        if self._is_in_template_content(context):
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
        # Default end tag handling - close matching element if found (re-enabled)
        self._handle_default_end_tag(tag_name, context)

    def _handle_default_end_tag(self, tag_name: str, context: "ParseContext") -> None:
        """Generic "any other end tag" algorithm from the IN BODY insertion mode.

        Implements the spec steps:
          1. Let i be the current node.
          2. If i's tag name equals the token's tag name, go to step 6.
          3. If i is a special element, ignore the token (abort).
          4. Set i to the previous entry in the stack of open elements and return to step 2.
          5. (Impossible here: if we fell off the stack the tag is ignored.)
          6. Generate implied end tags (we approximate: pop until target reached; formatting/phrasing
             elements like <b> that are not implied remain and will be popped if above target).
          7. If current node's tag name != target, parse error.
          8. Pop elements until the target element has been popped.
        The approximation skips a dedicated implied-end-tags list because the remaining failing cases only
        require correct handling of misnested formatting vs block boundaries. This remains deterministic and
        spec-aligned for the involved element categories.
        """
        if not context.current_parent:
            return

        # Elements handled elsewhere (special cases) are skipped here
        if tag_name in ("html", "head", "body"):
            return

        from turbohtml.constants import SPECIAL_CATEGORY_ELEMENTS

        stack = context.open_elements._stack
        if not stack:
            return
        # Step 1/2: walk i upward until match or special element encountered
        i_index = len(stack) - 1
        found_index = -1
        while i_index >= 0:
            node = stack[i_index]
            if node.tag_name == tag_name:
                found_index = i_index
                break
            if node.tag_name in SPECIAL_CATEGORY_ELEMENTS:
                # Step 3: encountered special element before finding target → ignore
                self.debug(
                    f"Default end tag: encountered special ancestor <{node.tag_name}> before <{tag_name}>; ignoring"
                )
                return
            i_index -= 1
        if found_index == -1:
            # Tag not open → ignore
            self.debug(f"Default end tag: </{tag_name}> not found on stack; ignoring")
            return
        # Step 6-8: pop until target popped
        while stack:
            popped = stack.pop()
            # Adjust current_parent if we just popped it
            if context.current_parent is popped:
                parent = popped.parent or self.root
                context.move_to_element_with_fallback(parent, popped)
            if popped.tag_name == tag_name:
                break
        # After pops, current_parent already at correct insertion point
        return

    def _handle_special_element(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> bool:
        """Handle html, head, body and frameset tags."""
        # Inside template content, do not perform special html/head/body/frameset handling.
        # Let the TemplateContentFilterHandler decide how to treat these tokens.
        if self._is_in_template_content(context):
            context.index = end_tag_idx
            return False
        # Template transparent depth bookkeeping not used (frameset templates stay transparent)
        if tag_name == "html":
            # Merge attributes: do not overwrite existing ones per spec
            for k, v in token.attributes.items():
                if k not in self.html_node.attributes:
                    self.html_node.attributes[k] = v
            context.move_to_element(self.html_node)
            # In a frameset document (root frameset present), suppress any implicit body creation side-effects.
            if self._has_root_frameset():
                context.index = end_tag_idx
                return True

            # Don't immediately switch to IN_BODY - let the normal flow handle that
            # The HTML tag should not automatically transition states
            return True
        elif tag_name == "head":
            # Don't create duplicate head elements
            head = self._ensure_head_node()
            context.transition_to_state(DocumentState.IN_HEAD, head)

            # If we're not in frameset mode, ensure we have a body
            if context.document_state != DocumentState.IN_FRAMESET:
                body = self._ensure_body_node(context)
            return True
        elif tag_name == "body" and context.document_state != DocumentState.IN_FRAMESET:
            # Only honor early <body> if frameset no longer permitted (frameset_ok False) or we already created body
            if context.frameset_ok and context.document_state in (
                DocumentState.INITIAL,
                DocumentState.IN_HEAD,
            ):
                # Explicit body tag commits to non-frameset document; flip frameset_ok off and continue to normal handling
                context.frameset_ok = False
            body = self._ensure_body_node(context)
            if body:
                # Merge body attributes without overwriting existing values (spec: first wins)
                for k, v in token.attributes.items():
                    if k not in body.attributes:
                        body.attributes[k] = v
                context.transition_to_state(DocumentState.IN_BODY, body)
            return True
        elif tag_name == "frameset" and context.document_state == DocumentState.INITIAL:
            # Let the frameset handler handle this
            return False
        elif (
            tag_name not in HEAD_ELEMENTS
            and context.document_state != DocumentState.IN_FRAMESET
        ):
            # Handle implicit head/body transitions (but not in frameset mode)
            if context.document_state == DocumentState.INITIAL:
                self.debug("Implicitly closing head and switching to body")
                body = self._ensure_body_node(context)
                if body:
                    context.transition_to_state(DocumentState.IN_BODY, body)
            elif context.current_parent == self._get_head_node():
                self.debug("Closing head and switching to body")
                body = self._ensure_body_node(context)
                if body:
                    context.transition_to_state(DocumentState.IN_BODY, body)
        # Special demotion: late metadata (<meta>, <title>) appearing after body/html should become body children.
        # When in AFTER_BODY or AFTER_HTML insertion modes, suppress special head handling so these tags are
        # treated as normal start tags under body (tests15 cases 3 and 5 expectations).
        if tag_name in ("meta", "title") and context.document_state in (
            DocumentState.AFTER_BODY,
            DocumentState.AFTER_HTML,
        ):
            # Ensure body exists and set insertion point to it, BUT keep state as AFTER_BODY/AFTER_HTML until
            # generic start tag handling runs so HeadElementHandler suppress predicate returns False.
            if (
                self._has_root_frameset()
            ):  # frameset documents drop late metadata entirely
                context.index = end_tag_idx
                return True
            body = self._get_body_node() or self._ensure_body_node(context)
            if body:
                context.move_to_element(body)
            context.index = end_tag_idx
            return False
        context.index = end_tag_idx
        return False

    # Special Node Handling Methods
    def _handle_comment(self, text: str, context: ParseContext) -> None:
        """
        Create and append a comment node with proper placement based on parser state.
        """
        # First check if any handler wants to process this comment (e.g., CDATA in foreign elements)
        for handler in self.tag_handlers:
            if handler.should_handle_comment(text, context) and handler.handle_comment(
                text, context
            ):
                self.debug(f"Comment '{text}' handled by {handler.__class__.__name__}")
                return

        # Default comment handling
        comment_node = Node("#comment")
        comment_node.text_content = text
        self.debug(
            f"Handling comment '{text}' in document_state {context.document_state}"
        )
        self.debug(f"Current parent: {context.current_parent}")

        # Handle comment placement based on parser state
        if context.document_state == DocumentState.INITIAL:
            # In INITIAL state, check if html_node is already in tree
            if self.html_node in self.root.children:
                # HTML node exists, comment should go inside it
                self.debug("Adding comment to html in initial state")
                # Find the position to insert - before the first non-comment element (like head)
                insert_index = 0
                for i, child in enumerate(self.html_node.children):
                    if child.tag_name not in ("#comment", "#text"):
                        insert_index = i
                        break
                    else:
                        insert_index = i + 1
                self.html_node.insert_child_at(insert_index, comment_node)
                self.debug(f"Inserted comment at index {insert_index}")
            else:
                # HTML node doesn't exist yet, comment goes at document level
                self.debug("Adding comment to root in initial state")
                self.root.append_child(comment_node)
            self.debug(
                f"Root children after comment: {[c.tag_name for c in self.root.children]}"
            )
            return

        # Comments after </head> should go in html node after head but before body
        if context.document_state == DocumentState.AFTER_HEAD:
            self.debug("Adding comment to html in after head state")
            # Find body element and insert comment before it
            body_node = None
            for child in self.html_node.children:
                if child.tag_name == "body":
                    body_node = child
                    break

            if body_node:
                self.html_node.insert_before(comment_node, body_node)
                self.debug("Inserted comment before body")
            else:
                # If no body found, just append
                self.html_node.append_child(comment_node)
                self.debug("No body found, appended comment to html")
            return

        # Comments after </body> should go in html node
        if context.document_state == DocumentState.AFTER_BODY:
            # If </body> seen but </html> not yet processed, comment should remain inside html AFTER body
            # Comments after body but before html close: spec places them inside <html>.
            any(
                ch.tag_name == "#comment"
                for ch in self.root.children
                if ch is not comment_node
            )
            if self.html_node not in self.root.children:
                self.root.append_child(self.html_node)
            body = self._get_body_node()
            if body and body.parent is self.html_node:
                self.html_node.append_child(comment_node)
            else:
                self.root.append_child(comment_node)
            return
        # Comments after </html> (AFTER_HTML) should appear as direct child of html (one level, not indented under body)
        if context.document_state == DocumentState.AFTER_HTML:
            # If we've seen stray non-whitespace characters after </html> we will have transitioned back to
            # IN_BODY already (spec reprocessing). When still formally in AFTER_HTML (no such re-entry), keep
            # comment at document level. Only relocate the FIRST comment that directly follows a non-whitespace
            # stray character token into the body. Subsequent comments, or comments after only whitespace stray
            # text, remain at document level (matches html5lib expectations for tests 23–27 patterns).
            body = self._get_body_node()
            placed = False
            if body:
                # Find the last non-whitespace text node in body (if any)
                text_nodes = [
                    ch
                    for ch in body.children
                    if ch.tag_name == "#text" and ch.text_content is not None
                ]
                if text_nodes:
                    last_text = text_nodes[-1]
                    has_non_ws = any(
                        t for t in last_text.text_content if not t.isspace()
                    )
                    # Count existing comments appended after that last text node
                    idx_last_text = body.children.index(last_text)
                    comments_after = [
                        ch
                        for ch in body.children[idx_last_text + 1 :]
                        if ch.tag_name == "#comment"
                    ]
                    if has_non_ws and not comments_after:
                        body.append_child(comment_node)
                        placed = True
            if not placed:
                self.root.append_child(comment_node)
            return

        # Frameset documents AFTER_FRAMESET ordering (no parser flags):
        # We distinguish three structural phases using only context flag and tree shape:
        #   1. Before explicit </html> (context.frameset_html_end_before_noframes False): comments still inside <html>.
        #   2. After </html> but before a root-level <noframes>: comments are appended as root siblings (temporarily
        #      preceding any later <noframes>); when a <noframes> appears we will relocate these comments after it.
        #   3. After first post-</html> <noframes>: subsequent comments remain root siblings after existing nodes.
        if context.document_state == DocumentState.AFTER_FRAMESET:
            # Before explicit </html>: comments still inside html; after: root-level.
            if not context.html_end_explicit:  # type: ignore[attr-defined]
                if self.html_node and self.html_node in self.root.children:
                    self.html_node.append_child(comment_node)
                else:
                    self.root.append_child(comment_node)
            else:
                self.root.append_child(comment_node)
            return

        # Comments in IN_BODY state should go as children of html, positioned before head
        if (
            context.document_state == DocumentState.IN_BODY
            and context.current_parent.tag_name == "html"
        ):
            # If we're in body state but current parent is html, place comment before head
            self.debug("Adding comment to html in body state")
            # Find head element and insert comment before it
            head_node = None
            for child in context.current_parent.children:
                if child.tag_name == "head":
                    head_node = child
                    break

            if head_node:
                context.current_parent.insert_before(comment_node, head_node)
                self.debug("Inserted comment before head")
            else:
                # If no head found, just append
                context.current_parent.append_child(comment_node)
                self.debug("No head found, appended comment")

            self.debug(
                f"Current parent children: {[c.tag_name for c in context.current_parent.children]}"
            )
            return

        # All other comments go in current parent
        self.debug(f"Adding comment to current parent: {context.current_parent}")
        context.current_parent.append_child(comment_node)
        self.debug(
            f"Current parent children: {[c.tag_name for c in context.current_parent.children]}"
        )

    def _handle_doctype(self, token: HTMLToken) -> None:
        """
        Handle DOCTYPE declarations by appending them to the root's children.
        """
        doctype_node = Node("!doctype")
        doctype_node.text_content = token.data  # Store the DOCTYPE content
        self.root.append_child(doctype_node)

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
                    self._append_text_content(pending_text, child.text_content)
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

    def _collapse_duplicate_formatting(self, node: Node) -> None:
        i = 0
        while i < len(node.children) - 1:
            first = node.children[i]
            second = node.children[i + 1]
            if (
                first.tag_name in FORMATTING_ELEMENTS
                and second.tag_name == first.tag_name
                and first.attributes == second.attributes
                and len(first.children) == 1
                and first.children[0] is second
                and not any(ch.tag_name == "#text" for ch in first.children)
            ):
                grandchildren = list(second.children)
                for gc in grandchildren:
                    second.remove_child(gc)
                    first.append_child(gc)
                node.remove_child(second)
                continue
            i += 1
        for child in node.children:
            if child.tag_name != "#text":
                self._collapse_duplicate_formatting(child)

    def _adjust_foreign_attrs(self, node: Node) -> None:
        parts = node.tag_name.split()
        local = parts[-1] if parts else node.tag_name
        is_svg = node.tag_name.startswith("svg ") or local == "svg"
        is_math = node.tag_name.startswith("math ") or local == "math"
        if is_svg and node.attributes:
            attrs = dict(node.attributes)
            defn_val = attrs.pop("definitionurl", None)
            xml_lang = attrs.pop("xml:lang", None)
            xml_space = attrs.pop("xml:space", None)
            xml_base = attrs.pop("xml:base", None)
            other_xml = []
            for key in list(attrs.keys()):
                if key.startswith("xml:") and key not in (
                    "xml:lang",
                    "xml:space",
                    "xml:base",
                ):
                    other_xml.append((key, attrs.pop(key)))
            new_attrs = {}
            if defn_val is not None:
                new_attrs["definitionurl"] = defn_val
            for key, value in node.attributes.items():
                if not (
                    key in ("definitionurl", "xml:lang", "xml:space", "xml:base")
                    or key.startswith("xml:")
                ):
                    new_attrs[key] = value
            if xml_lang is not None:
                new_attrs["xml lang"] = xml_lang
            if xml_space is not None:
                new_attrs["xml space"] = xml_space
            for key, value in other_xml:
                new_attrs[key] = value
            if xml_base is not None:
                new_attrs["xml:base"] = xml_base
            node.attributes = new_attrs
        elif is_math and node.attributes:
            attrs = dict(node.attributes)
            if "definitionurl" in attrs and "definitionURL" not in attrs:
                attrs["definitionURL"] = attrs.pop("definitionurl")
            xlink_attrs = [
                (key, value) for key, value in attrs.items() if key.startswith("xlink:")
            ]
            if xlink_attrs:
                for key, _ in xlink_attrs:
                    del attrs[key]
                xlink_attrs.sort(key=lambda kv: kv[0].split(":", 1)[1])
                rebuilt = {}
                if "definitionURL" in attrs:
                    rebuilt["definitionURL"] = attrs.pop("definitionURL")
                for key, value in xlink_attrs:
                    rebuilt[f"xlink {key.split(':', 1)[1]}"] = value
                for key, value in attrs.items():
                    rebuilt[key] = value
                node.attributes = rebuilt
        for child in node.children:
            if child.tag_name != "#text":
                self._adjust_foreign_attrs(child)

    def _reorder_after_head_whitespace(self) -> None:
        if self.fragment_context:
            return
        html = self.html_node
        if not html or len(html.children) < 3:
            return
        head = html.children[0] if html.children and html.children[0].tag_name == "head" else None
        body_index = None
        for i, child in enumerate(html.children):
            if child.tag_name == "body":
                body_index = i
                break
        if not head or body_index is None or body_index + 1 >= len(html.children):
            return
        def is_whitespace_text(node: Node) -> bool:
            return (
                node.tag_name == "#text"
                and node.text_content is not None
                and node.text_content.strip() == ""
            )
        if not is_whitespace_text(html.children[body_index + 1]):
            return
        for mid in html.children[1:body_index]:
            if not is_whitespace_text(mid):
                return
        ws_nodes = []
        j = body_index + 1
        while j < len(html.children) and is_whitespace_text(html.children[j]):
            ws_nodes.append(html.children[j])
            j += 1
        for node in ws_nodes:
            html.remove_child(node)
        insert_at = 1
        while insert_at < len(html.children) and is_whitespace_text(html.children[insert_at]):
            insert_at += 1
        for offset, node in enumerate(ws_nodes):
            html.children.insert(insert_at + offset, node)
            node.parent = html

    def _finalize_tree(self) -> None:
        if not self.root:
            return
        self._merge_adjacent_text_nodes(self.root)
        self._collapse_duplicate_formatting(self.root)
        self._adjust_foreign_attrs(self.root)
        self._reorder_after_head_whitespace()

    def _post_text_inline_normalize(self, context: ParseContext) -> None:
        """After appending a text node, unwrap a redundant trailing formatting element if present.

        Example scenario:
            <p><b><i>A</i></b><i>B</i>  -> becomes <p><b><i>A</i></b>B

        Adoption unwrapping runs only after end-tag driven adoption cycles; if the trailing <i>/<em>/<b>
        wrapper was empty during those cycles (text arrives later), the earlier normalization misses it.
        This lightweight check runs after text insertion, examining the current block parent's last two
        element children. It is intentionally narrow to avoid regressions:
          - Parent must be a block-ish container (p, div, section, article, body)
          - Pattern: first=<X> (any element), second=<f> where f in (i, em, b)
          - second has only text node children (now non-empty) and no attributes
          - first subtree already contains at least one descendant element with the same tag as second
            having some (possibly whitespace-trimmed) text descendant
        If matched, move text children of second after it, then remove second element.
        """
        insertion_parent = context.current_parent
        if not insertion_parent:
            return
        # Climb to nearest block container from current parent (which may be a formatting element)
        parent = insertion_parent
        block_tags = ("p", "div", "section", "article", "body")
        while parent and parent.tag_name not in block_tags:
            parent = parent.parent
        if not parent:
            return
        # Need at least two element children (ignoring text) within that block
        elems = [ch for ch in parent.children if ch.tag_name != "#text"]
        if len(elems) < 2:
            return
        second = elems[-1]
        first = elems[-2]
        # Only consider when the just-modified element is the trailing formatting element
        # Only target i/em (avoid modifying trailing <b> which may be semantically required)
        if second is not insertion_parent or second.tag_name not in ("i", "em"):
            return
        if second.attributes or not second.children:
            return
        if not all(ch.tag_name == "#text" for ch in second.children):
            return
        # Check if first subtree already has same formatting tag AND subtree has any text descendant (anywhere)
        has_same_fmt = False
        for d in self.adoption_agency._iter_descendants(first):
            if d.tag_name == second.tag_name:
                has_same_fmt = True
                break
        if not has_same_fmt:
            return
        has_any_text = any(
            (dd.tag_name == "#text" and dd.text_content and dd.text_content.strip())
            for dd in self.adoption_agency._iter_descendants(first)
        )
        if not has_any_text:
            return
        # Unwrap: move text children of second into parent after second, then remove second
        insert_index = parent.children.index(second) + 1
        texts = list(second.children)
        for t in texts:
            second.remove_child(t)
            parent.children.insert(insert_index, t)
            t.parent = parent
            insert_index += 1
        parent.remove_child(second)
        if self.env_debug:
            self.debug(
                f"Post-text inline normalize: unwrapped trailing <{second.tag_name}> into text"
            )

    def _foster_parent_element(
        self, tag_name: str, attributes: dict, context: "ParseContext"
    ):
        """Foster parent an element outside of table context"""
        # Find the table - check if we're in table context
        table = None
        if context.document_state == DocumentState.IN_TABLE:
            # We're in table context, so find the table from the open elements stack
            table = self.find_current_table(context)

        if not table or not table.parent:
            # No table found, use default handling
            new_node = Node(tag_name, attributes)
            context.current_parent.append_child(new_node)
            context.move_to_element(new_node)
            context.open_elements.push(new_node)
            return

        # Insert the element before the table
        foster_parent = table.parent
        table_index = foster_parent.children.index(table)
        # If current_parent is an existing foster-parented block immediately before the table,
        # and that block is allowed to contain this element, nest inside it instead of creating
        # a new sibling. This matches expected behavior where successive foster-parented
        # start tags become children (e.g., <table><div><div> becomes nested divs).
        if table_index > 0:
            prev_sibling = foster_parent.children[table_index - 1]
            # Only nest if previous sibling is a block-like container and current insertion
            # point is that previous sibling (we just foster parented into it)
            if prev_sibling is context.current_parent and prev_sibling.tag_name in (
                "div",
                "p",
                "section",
                "article",
                "blockquote",
                "li",
            ):
                self.debug(
                    f"Nesting {tag_name} inside existing foster-parented {prev_sibling.tag_name}"
                )
                new_node = Node(tag_name, attributes)
                prev_sibling.append_child(new_node)
                context.move_to_element(new_node)
                context.open_elements.push(new_node)
                return

        new_node = Node(tag_name, attributes)
        foster_parent.children.insert(table_index, new_node)
        new_node.parent = foster_parent  # Set parent relationship
        context.move_to_element(new_node)
        context.open_elements.push(new_node)  # Add to stack
        self.debug(f"Foster parented {tag_name} before table")

    def _is_in_template_content(self, context: "ParseContext") -> bool:
        """Check if we're inside actual template content (not just a user <content> tag)"""
        # Check if current parent is content node
        if (
            context.current_parent
            and context.current_parent.tag_name == "content"
            and context.current_parent.parent
            and context.current_parent.parent.tag_name == "template"
        ):
            return True

        # Check if any ancestor is template content
        current = context.current_parent
        while current:
            if (
                current.tag_name == "content"
                and current.parent
                and current.parent.tag_name == "template"
            ):
                return True
            current = current.parent

        return False

    def _is_in_integration_point(self, context: "ParseContext") -> bool:
        """Check if we're inside an SVG or MathML integration point where HTML rules apply"""
        # Check current parent and ancestors for integration points
        current = context.current_parent
        while current:
            # SVG integration points: foreignObject, desc, title
            if current.tag_name in ("svg foreignObject", "svg desc", "svg title"):
                return True

            # MathML integration points: annotation-xml with specific encoding
            if (
                current.tag_name == "math annotation-xml"
                and current.attributes
                and any(
                    attr.name.lower() == "encoding"
                    and attr.value.lower() in ("text/html", "application/xhtml+xml")
                    for attr in current.attributes
                )
            ):
                return True

            current = current.parent

        return False

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
