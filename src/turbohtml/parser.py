from turbohtml.context import ParseContext, ParserState
from turbohtml.handlers import (
    AutoClosingTagHandler,
    DoctypeHandler,
    ForeignTagHandler,
    FormattingElementHandler,
    FormTagHandler,
    HeadingTagHandler,
    ListTagHandler,
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
    BodyElementHandler,
    BoundaryElementHandler,
    PlaintextHandler,
)
from turbohtml.node import Node
from turbohtml.tokenizer import HTMLToken, HTMLTokenizer

from .constants import HEAD_ELEMENTS
from typing import Optional


class TurboHTML:
    """
    Main parser interface.
    - Instantiation with an HTML string automatically triggers parsing.
    - Provides a root Node that represents the DOM tree.
    """

    def __init__(
        self, html: str, handle_foreign_elements: bool = True, debug: bool = False
    ):
        """
        Args:
            html: The HTML string to parse
            handle_foreign_elements: Whether to handle SVG/MathML elements
            debug: Whether to enable debug prints
        """
        self.env_debug = debug
        self.html = html

        # Reset all state for each new parser instance
        self.state = ParserState.INITIAL
        self._init_dom_structure()

        # Initialize tag handlers in deterministic order
        self.tag_handlers = [
            DoctypeHandler(self),
            PlaintextHandler(self),
            FramesetTagHandler(self),
            TableTagHandler(self),
            ListTagHandler(self),
            HeadElementHandler(self),
            BodyElementHandler(self),
            HtmlTagHandler(self),
            AutoClosingTagHandler(self),
            VoidElementHandler(self),
            RawtextTagHandler(self),
            BoundaryElementHandler(self),
            FormattingElementHandler(self),
            ImageTagHandler(self),
            TextHandler(self),
            SelectTagHandler(self),
            FormTagHandler(self),
            HeadingTagHandler(self),
            ParagraphTagHandler(self),
            ForeignTagHandler(self) if handle_foreign_elements else None,
        ]
        self.tag_handlers = [h for h in self.tag_handlers if h is not None]

        # Trigger parsing
        self._parse()

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"

    def debug(self, *args, indent=4, **kwargs) -> None:
        if not self.env_debug:
            return

        print(f"{' ' * indent}{args[0]}", *args[1:], **kwargs)

    # DOM Structure Methods
    def _init_dom_structure(self) -> None:
        """Initialize the basic DOM structure"""
        self.root = Node("document")
        self.html_node = Node("html")
        self.root.append_child(self.html_node)
        
        # Always create head node during initialization
        head = Node("head")
        self.html_node.append_child(head)
        
    def _get_head_node(self) -> Optional[Node]:
        """Get head node from tree, if it exists"""
        return next((child for child in self.html_node.children if child.tag_name == "head"), None)
        
    def _get_body_node(self) -> Optional[Node]:
        """Get body node from tree, if it exists"""
        return next((child for child in self.html_node.children if child.tag_name == "body"), None)
        
    def _ensure_head_node(self) -> Node:
        """Get or create head node"""
        head = self._get_head_node()
        if not head:
            head = Node("head")
            self.html_node.append_child(head)
        return head
        
    def _ensure_body_node(self, context: ParseContext) -> Optional[Node]:
        """Get or create body node if not in frameset mode"""
        if context.state == ParserState.IN_FRAMESET:
            return None
        body = self._get_body_node()
        if not body:
            body = Node("body")
            self.html_node.append_child(body)
        return body

    # Main Parsing Methods
    def _parse(self) -> None:
        """
        Main parsing loop using ParseContext and HTMLTokenizer.
        """
        # Initialize context with html_node as current_parent
        context = ParseContext(len(self.html), self.html_node, self.html_node)
        self.tokenizer = HTMLTokenizer(self.html)

        # if self.env_debug:
        #     # Create debug tokenizer with same debug setting
        #     debug_tokenizer = HTMLTokenizer(self.html, debug=self.env_debug)
        #     self.debug(f"TOKENS: {list(debug_tokenizer.tokenize())}", indent=0)

        for token in self.tokenizer.tokenize():
            self.debug(f"_parse: {token}, context: {context}", indent=0)
            if token.type == "Comment":
                self._handle_comment(token.data, context)

            # Handle DOCTYPE through the DoctypeHandler
            elif token.type == "DOCTYPE":
                for handler in self.tag_handlers:
                    if handler.should_handle_doctype(token.data, context):
                        self.debug(f"{handler.__class__.__name__}: handling DOCTYPE")
                        if handler.handle_doctype(token.data, context):
                            break
                context.index = self.tokenizer.pos
                continue

            elif token.type == "StartTag":
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

            if token.type == "EndTag":
                self._handle_end_tag(token, token.tag_name, context)
                context.index = self.tokenizer.pos

            elif token.type == "Character":
                for handler in self.tag_handlers:
                    if handler.should_handle_text(token.data, context):
                        self.debug(
                            f"{handler.__class__.__name__}: handling {token}, context={context}"
                        )
                        if handler.handle_text(token.data, context):
                            break

        # After all tokens are processed, ensure we have a body if not in frameset mode
        if context.state != ParserState.IN_FRAMESET:
            body = self._ensure_body_node(context)
            if body:
                context.state = ParserState.IN_BODY

    # Tag Handling Methods
    def _handle_start_tag(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> None:
        """Handle all opening HTML tags."""

        # Create body node if we're implicitly switching to body mode
        if (context.state == ParserState.INITIAL or 
            context.state == ParserState.IN_HEAD) and tag_name not in HEAD_ELEMENTS:
            self.debug("Implicitly creating body node")
            if context.state != ParserState.IN_FRAMESET:
                body = self._ensure_body_node(context)
                if body:
                    context.current_parent = body
                    context.state = ParserState.IN_BODY

        if context.state == ParserState.RAWTEXT:
            self.debug("In rawtext mode, ignoring start tag")
            return

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context):
                if handler.handle_start(token, context, not token.is_last_token):
                    return

        # Default handling for unhandled tags
        self.debug(f"No handler found, using default handling for {tag_name}")
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node

    def _handle_end_tag(
        self, token: HTMLToken, tag_name: str, context: ParseContext
    ) -> None:
        """Handle all closing HTML tags."""

        # Create body node if needed and not in frameset mode
        if not context.current_parent and context.state != ParserState.IN_FRAMESET:
            body = self._ensure_body_node(context)
            if body:
                context.current_parent = body

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.should_handle_end(tag_name, context):
                if handler.handle_end(token, context):
                    return

    def _handle_special_element(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> bool:
        """Handle html, head, body and frameset tags."""
        if tag_name == "html":
            # Just update attributes, don't create a new node
            self.html_node.attributes.update(token.attributes)
            context.current_parent = self.html_node
            
            # If we're not in frameset mode, ensure we have a body
            if context.state != ParserState.IN_FRAMESET:
                body = self._ensure_body_node(context)
                if body:
                    context.state = ParserState.IN_BODY
            return True
        elif tag_name == "head":
            # Don't create duplicate head elements
            head = self._ensure_head_node()
            context.current_parent = head
            context.state = ParserState.IN_HEAD
            
            # If we're not in frameset mode, ensure we have a body
            if context.state != ParserState.IN_FRAMESET:
                body = self._ensure_body_node(context)
            return True
        elif tag_name == "body" and context.state != ParserState.IN_FRAMESET:
            # Create body if needed
            body = self._ensure_body_node(context)
            if body:
                # Update attributes and switch to body mode
                body.attributes.update(token.attributes)
                context.current_parent = body
                context.state = ParserState.IN_BODY
            return True
        elif tag_name == "frameset" and context.state == ParserState.INITIAL:
            # Let the frameset handler handle this
            return False
        elif tag_name not in HEAD_ELEMENTS and context.state != ParserState.IN_FRAMESET:
            # Handle implicit head/body transitions (but not in frameset mode)
            if context.state == ParserState.INITIAL:
                self.debug("Implicitly closing head and switching to body")
                context.state = ParserState.IN_BODY
                body = self._ensure_body_node(context)
                if body:
                    context.current_parent = body
            elif context.current_parent == self._get_head_node():
                self.debug("Closing head and switching to body")
                context.state = ParserState.IN_BODY
                body = self._ensure_body_node(context)
                if body:
                    context.current_parent = body
        context.index = end_tag_idx
        return False

    # Special Node Handling Methods
    def _handle_comment(self, text: str, context: ParseContext) -> None:
        """
        Create and append a comment node with proper placement based on parser state.
        """
        comment_node = Node("#comment")
        comment_node.text_content = text

        # First comment should go in root if we're still in initial state
        if context.state == ParserState.INITIAL:
            self.root.children.insert(0, comment_node)
            context.state = ParserState.IN_BODY
            # Ensure body exists and set as current parent
            if context.state != ParserState.IN_FRAMESET:
                body = self._ensure_body_node(context)
                if body:
                    context.current_parent = body
            return

        # Comments after </body> should go in html node
        if context.current_parent == self._get_body_node():
            self.html_node.append_child(comment_node)
            return

        context.current_parent.append_child(comment_node)

    def _handle_doctype(self, token: HTMLToken) -> None:
        """
        Handle DOCTYPE declarations by prepending them to the root's children.
        """
        doctype_node = Node("!doctype")
        self.root.children.insert(0, doctype_node)
