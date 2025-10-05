"""TurboHTML parser (type annotations removed)."""

from turbohtml.adoption import AdoptionAgencyAlgorithm
from turbohtml.constants import NUMERIC_ENTITY_INVALID_SENTINEL, VOID_ELEMENTS
from turbohtml.context import ContentState, DocumentState, ParseContext
from turbohtml.foster import foster_parent, needs_foster_parenting
from turbohtml.fragment import parse_fragment
from turbohtml.handlers import (
    AutoClosingTagHandler,
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
    TemplateContentFilterHandler,
    TemplateElementHandler,
    TextHandler,
    UnifiedCommentHandler,
    VoidTagHandler,
)
from turbohtml.node import Node
from turbohtml.tokenizer import HTMLTokenizer


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
    ):
        """Args:
        html: The HTML string to parse
        debug: Whether to enable debug prints
        fragment_context: Context element for fragment parsing (e.g., 'td', 'tr').

        """
        self.env_debug = debug
        self.fragment_context = fragment_context

        self._init_dom_structure()
        self.adoption_agency = AdoptionAgencyAlgorithm(self)

        # Initialize tag handlers in deterministic order
        self.tag_handlers = [
            DoctypeHandler(self),
            TemplateContentFilterHandler(self),  # must precede TemplateElementHandler
            TemplateElementHandler(self),
            DocumentStructureHandler(self),
            PlaintextHandler(self),
            FramesetTagHandler(self),
            SelectTagHandler(self),  # must precede table handling to suppress table tokens inside <select>
            TableTagHandler(self),
            UnifiedCommentHandler(self),
            ForeignTagHandler(self),
            ParagraphTagHandler(self),
            AutoClosingTagHandler(self),
            MenuitemTagHandler(self),
            ListTagHandler(self),
            HeadTagHandler(self),
            ButtonTagHandler(self),
            VoidTagHandler(self),
            RawtextTagHandler(self),
            MarqueeTagHandler(self),
            FormattingTagHandler(self),
            ImageTagHandler(self),
            TextHandler(self),
            FormTagHandler(self),
            HeadingTagHandler(self),
            RubyTagHandler(self),
            TableFosterHandler(self),
            GenericEndTagHandler(self),
        ]

        for handler in self.tag_handlers:
            if isinstance(handler, TextHandler):
                self.text_handler = handler
            elif isinstance(handler, ForeignTagHandler):
                self.foreign_handler = handler

        if not hasattr(self, "text_handler"):
            msg = "TextHandler not found in tag_handlers"
            raise RuntimeError(msg)
        if not hasattr(self, "foreign_handler"):
            msg = "ForeignTagHandler not found in tag_handlers"
            raise RuntimeError(msg)

        # Sequential token counter for deduplication guards (replaces tokenizer position)
        self._token_counter = 0

        # Parse immediately upon construction (html string only used during parsing)
        self._parse(html)

        # Post-parse processing
        for handler in self.tag_handlers:
            handler.postprocess(self)

    def __repr__(self):
        return f"<TurboHTML root={self.root}>"

    def debug(self, *args, indent=4, **kwargs):
        if not self.env_debug:
            return
        print(f"{' ' * indent}{args[0]}", *args[1:], **kwargs)


    def get_token_position(self):
        """Get current token counter (for deduplication guards)."""
        return self._token_counter

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

        if auto_foster and parent is None and before is None:
            if needs_foster_parenting(context.current_parent):
                # Check if we're inside a cell or caption (foster parenting doesn't apply there)
                in_cell_or_caption = bool(
                    context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th", "caption")),
                )
                # Don't foster table-related elements or elements specifically allowed in tables (form)
                tableish = {"table","tbody","thead","tfoot","tr","td","th","caption","colgroup","col","form"}
                if not in_cell_or_caption and tag_name not in tableish:
                    target_parent, target_before = foster_parent(
                        context.current_parent, context.open_elements, self.root,
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
        new_node = Node(tag_name, attrs, preserve_attr_case=preserve_attr_case)
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
        if hasattr(token, "needs_rawtext") and token.needs_rawtext and self.tokenizer:
            context.content_state = ContentState.RAWTEXT
            self.tokenizer.start_rawtext(tag_name)

        # Activate PLAINTEXT mode for <plaintext> element (consumes all remaining input as text)
        if tag_name == "plaintext" and self.tokenizer:
            context.content_state = ContentState.PLAINTEXT
            self.tokenizer.start_plaintext()

        # Exit RAWTEXT mode when inserting foreign content (math/svg elements)
        if tag_name.startswith(("math ", "svg ")) and self.tokenizer and self.tokenizer.state == "RAWTEXT":
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
            if target_parent.tag_name in ("script", "style", "plaintext"):
                preserve = True
            else:
                for elem in context.open_elements:
                    if elem.tag_name in ("script", "style", "plaintext"):
                        preserve = True
                        break

            # Preserve in SVG content (but NOT in HTML integration points)
            if (
                not preserve
                and target_parent.tag_name.startswith("svg ")
                and target_parent.tag_name not in ("svg foreignObject", "svg desc", "svg title")
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
            if self.env_debug:
                self.debug(f"[insert_text] merging into existing text node len_before={len(last.text_content)} add_len={len(text)}")
            last.text_content += text
            return last

        new_node = Node("#text", text_content=text)
        target_parent.append_child(new_node)
        if self.env_debug:
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
            self.fragment_context == "html"
            and context.document_state == DocumentState.AFTER_HTML
        ):
            self.root.append_child(comment_node)
            return
        context.current_parent.append_child(comment_node)

    def _parse_document(self, html):
        """Parse a full HTML document (token loop delegating to handlers)."""
        # Initialize context with html_node as current_parent
        context = ParseContext(self.html_node, debug_callback=self.debug)
        self.tokenizer = HTMLTokenizer(html)


        for token in self.tokenizer.tokenize():
            # Increment token counter for deduplication tracking
            self._token_counter += 1

            self.debug(f"_parse: {token}, context: {context}", indent=0)

            if token.type == "DOCTYPE":
                # Handle DOCTYPE through the DoctypeHandler first
                for handler in self.tag_handlers:
                    if handler.should_handle_doctype(token.data, context):
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
                if self.fragment_context == "template" and token.tag_name == "template":
                    continue
                self.handle_end_tag(token, context)

            elif token.type == "Character":
                data = token.data
                if data:
                    for handler in self.tag_handlers:
                        if handler.should_handle_text(data, context):
                            self.debug(
                                f"{handler.__class__.__name__}: handling {token}, context={context}",
                            )
                            if handler.handle_text(data, context):
                                break

    def handle_start_tag(self, token, context):
        """Handle all opening HTML tags."""
        tag_name = token.tag_name

        # Pre-dispatch preprocessing (guards and side effects)
        for h in self.tag_handlers:
            if h.preprocess_start(token, context):
                return

        # Dispatch to first matching handler
        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context) and handler.handle_start(token, context):
                return

        # Fallback: if no handler claimed this start tag, insert it with default behavior.
        self.insert_element(token, context, mode="normal", enter=not token.is_self_closing)

    def handle_end_tag(self, token, context):
        """Handle all closing HTML tags (spec-aligned, no auxiliary adoption flags)."""
        tag_name = token.tag_name

        # Pre-dispatch preprocessing (guards and side effects)
        for h in self.tag_handlers:
            if h.preprocess_end(token, context):
                return

        # Dispatch to first matching handler
        for handler in self.tag_handlers:
            if handler.should_handle_end(tag_name, context) and handler.handle_end(token, context):
                return
