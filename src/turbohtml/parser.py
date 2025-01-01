
from turbohtml.context import ParseContext, ParserState
from turbohtml.handlers import (
    AnchorTagHandler,
    AutoClosingTagHandler,
    ButtonTagHandler,
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
)
from turbohtml.node import Node
from turbohtml.tokenizer import HTMLToken, HTMLTokenizer

from .constants import HEAD_ELEMENTS


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
            AnchorTagHandler(self),
            TableTagHandler(self),
            ListTagHandler(self),
            AutoClosingTagHandler(self),
            VoidElementHandler(self),
            RawtextTagHandler(self),
            FormattingElementHandler(self),
            TextHandler(self),
            SelectTagHandler(self),
            FormTagHandler(self),
            HeadingTagHandler(self),
            ParagraphTagHandler(self),
            ButtonTagHandler(self),
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
        """Initialize the basic DOM structure with document, html, head, and body nodes."""
        # Initialize basic DOM structure
        self.html_node = Node("html")
        self.head_node = Node("head")
        self.body_node = Node("body")
        self.root = Node("document")

        # Build the hierarchy
        self.html_node.children = [self.head_node, self.body_node]
        self.root.children = [self.html_node]

    # Main Parsing Methods
    def _parse(self) -> None:
        """
        Main parsing loop using ParseContext and HTMLTokenizer.
        """
        context = ParseContext(len(self.html), self.body_node, self.html_node)
        self.tokenizer = HTMLTokenizer(self.html)  # Store tokenizer instance

        if self.env_debug:
            self.debug(f"TOKENS: {list(HTMLTokenizer(self.html).tokenize())}", indent=0)

        for token in self.tokenizer.tokenize():
            self.debug(f"_parse: {token}, context: {context}", indent=0)
            if token.type == "Comment":
                self._handle_comment(token.data, context)

            # Handle DOCTYPE first since it doesn't have a tag_name
            if token.type == "DOCTYPE":
                self._handle_doctype(token)
                context.index = self.tokenizer.pos
                continue

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

    # Tag Handling Methods
    def _handle_start_tag(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> None:
        """Handle all opening HTML tags."""
        self.debug(
            f"_handle_start_tag: {tag_name}, current_parent={context.current_parent}"
        )

        if context.state == ParserState.RAWTEXT:
            self.debug("In rawtext mode, ignoring start tag")
            return

        # Try tag handlers first
        self.debug(f"Trying tag handlers for {tag_name}")
        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context):
                self.debug(
                    f"{handler.__class__.__name__}: handling {token}, context={context}"
                )
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
        self.debug(
            f"_handle_end_tag: {tag_name}, current_parent={context.current_parent}"
        )

        if not context.current_parent:
            context.current_parent = self.body_node

        # Try tag handlers first
        self.debug(f"Trying tag handlers for end tag {tag_name}")
        for handler in self.tag_handlers:
            if handler.should_handle_end(tag_name, context):
                self.debug(
                    f"{handler.__class__.__name__}: handling {token}, context={context}"
                )
                if handler.handle_end(token, context):
                    return

        # Default handling for unhandled tags
        self.debug(f"No end tag handler found, looking for matching tag {tag_name}")
        current = context.current_parent.find_ancestor(tag_name)
        if current:
            self.debug(f"Found matching tag {tag_name}, updating current_parent")
            context.current_parent = current.parent or self.body_node
            # Set state to after_body when body tag is closed
            if tag_name == "body":
                context.state = ParserState.AFTER_BODY

    def _handle_special_element(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> bool:
        """Handle html, head and body tags.
        Returns True if the tag was handled and should not be processed further."""
        if tag_name == "html":
            # Just update attributes, don't create a new node
            self.html_node.attributes.update(token.attributes)
            context.current_parent = self.html_node
            return True
        elif tag_name == "head":
            # Don't create duplicate head elements
            context.current_parent = self.head_node
            context.state = ParserState.IN_HEAD
            return True
        elif tag_name == "body":
            # Don't create duplicate body elements
            self.body_node.attributes.update(token.attributes)
            context.current_parent = self.body_node
            context.state = ParserState.IN_BODY
            return True
        elif tag_name not in HEAD_ELEMENTS:
            # Handle implicit head/body transitions
            if context.state == ParserState.INITIAL:
                self.debug("Implicitly closing head and switching to body")
                context.state = ParserState.IN_BODY
                if context.current_parent == self.head_node:
                    context.current_parent = self.body_node
            elif context.current_parent == self.head_node:
                self.debug("Closing head and switching to body")
                context.state = ParserState.IN_BODY
                context.current_parent = self.body_node
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
            return

        # Comments after </body> should go in html node
        if context.current_parent == self.body_node:
            self.html_node.append_child(comment_node)
            return

        context.current_parent.append_child(comment_node)

    def _handle_doctype(self, token: HTMLToken) -> None:
        """
        Handle DOCTYPE declarations by prepending them to the root's children.
        """
        doctype_node = Node("!doctype")
        self.root.children.insert(0, doctype_node)
