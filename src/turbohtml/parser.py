from turbohtml.context import ParseContext, DocumentState, ContentState
from turbohtml.handlers import (
    AutoClosingTagHandler,
    DoctypeHandler,
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
    BodyElementHandler,
    BoundaryElementHandler,
    ButtonTagHandler,
    PlaintextHandler,
    UnknownElementHandler,
    RubyElementHandler,
)
from turbohtml.node import Node
from turbohtml.tokenizer import HTMLToken, HTMLTokenizer
from turbohtml.adoption import AdoptionAgencyAlgorithm

from .constants import HEAD_ELEMENTS
from typing import Optional


class TurboHTML:
    """
    Main parser interface.
    - Instantiation with an HTML string automatically triggers parsing.
    - Provides a root Node that represents the DOM tree.
    """

    def __init__(self, html: str, handle_foreign_elements: bool = True, debug: bool = False, fragment_context: Optional[str] = None):
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
            PlaintextHandler(self),
            FramesetTagHandler(self),
            ForeignTagHandler(self) if handle_foreign_elements else None,  # Move before other handlers
            TableTagHandler(self),
            ParagraphTagHandler(self),  # Move before AutoClosingTagHandler for special button logic
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
            SelectTagHandler(self),
            FormTagHandler(self),
            HeadingTagHandler(self),
            RubyElementHandler(self),  # Handle ruby annotation elements
            UnknownElementHandler(self),  # Handle unknown/namespace elements
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
        return next((child for child in self.html_node.children if child.tag_name == "head"), None)

    def _get_body_node(self) -> Optional[Node]:
        """Get body node from tree, if it exists"""
        if self.fragment_context:
            return None
        return next((child for child in self.html_node.children if child.tag_name == "body"), None)

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

    def _ensure_body_node(self, context: ParseContext) -> Optional[Node]:
        """Get or create body node if not in frameset mode"""
        if self.fragment_context:
            return None
        if context.document_state == DocumentState.IN_FRAMESET:
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
        if self.fragment_context:
            self._parse_fragment()
        else:
            self._parse_document()

    def _parse_fragment(self) -> None:
        """Parse HTML as a document fragment in the given context"""
        self.debug(f"Parsing fragment in context: {self.fragment_context}")
        
        # Set up fragment context based on the context element
        context = self._create_fragment_context()
        
        # Special handling for RAWTEXT contexts - treat everything as text
        if self.fragment_context in self._get_rawtext_elements():
            text_node = Node("#text")
            text_node.text_content = self.html
            context.current_parent.append_child(text_node)
            self.debug(f"Fragment: Treated all content as raw text in {self.fragment_context} context")
            return
        
        self.tokenizer = HTMLTokenizer(self.html)

        for token in self.tokenizer.tokenize():
            self.debug(f"_parse_fragment: {token}, context: {context}", indent=0)

            # Skip DOCTYPE in fragments
            if token.type == "DOCTYPE":
                continue

            if token.type == "Comment":
                self._handle_fragment_comment(token.data, context)
                continue

            if token.type == "StartTag":
                # In fragment parsing, ignore certain start tags based on context
                if self._should_ignore_fragment_start_tag(token.tag_name, context):
                    self.debug(f"Fragment: Ignoring {token.tag_name} start tag in {self.fragment_context} context")
                    continue
                
                self._handle_start_tag(token, token.tag_name, context, self.tokenizer.pos)
                context.index = self.tokenizer.pos

            elif token.type == "EndTag":
                self._handle_end_tag(token, token.tag_name, context)
                context.index = self.tokenizer.pos

            elif token.type == "Character":
                for handler in self.tag_handlers:
                    if handler.should_handle_text(token.data, context):
                        self.debug(f"{handler.__class__.__name__}: handling {token}, context={context}")
                        if handler.handle_text(token.data, context):
                            break

    def _create_fragment_context(self) -> "ParseContext":
        """Create parsing context for fragment parsing"""
        from turbohtml.context import DocumentState, ContentState
        
        # Create context based on the fragment context element
        if self.fragment_context in ("td", "th"):
            # Fragment is parsed as if inside a table cell
            context = ParseContext(
                len(self.html),
                self.root,  # Fragment root
                None,  # No html node in fragments
                debug_callback=self.debug if self.env_debug else None,
            )
            context.document_state = DocumentState.IN_CELL
            context.current_parent = self.root
                
        elif self.fragment_context in ("tr",):
            context = ParseContext(
                len(self.html),
                self.root,
                None,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.document_state = DocumentState.IN_ROW
            context.current_parent = self.root
            
        elif self.fragment_context in ("thead", "tbody", "tfoot"):
            context = ParseContext(
                len(self.html),
                self.root,
                None,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.document_state = DocumentState.IN_TABLE_BODY
            context.current_parent = self.root
            
        elif self.fragment_context == "html":
            # HTML fragment context - allow document structure
            context = ParseContext(
                len(self.html),
                self.root,
                None,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.document_state = DocumentState.INITIAL
            context.current_parent = self.root
            
        elif self.fragment_context in self._get_rawtext_elements():
            # RAWTEXT fragment context - treat all content as raw text
            context = ParseContext(
                len(self.html),
                self.root,
                None,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.document_state = DocumentState.IN_BODY
            context.current_parent = self.root
            
        else:
            # Default fragment context (body-like)
            context = ParseContext(
                len(self.html),
                self.root,
                None,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.document_state = DocumentState.IN_BODY
            context.current_parent = self.root
            
        # Set foreign context if fragment context is within a foreign element
        if self.fragment_context and " " in self.fragment_context:
            namespace_elem = self.fragment_context.split(" ")[0]
            if namespace_elem in ("math", "svg"):
                context.current_context = namespace_elem
                self.debug(f"Set foreign context to {namespace_elem}")
            
        return context

    def _should_ignore_fragment_start_tag(self, tag_name: str, context: "ParseContext") -> bool:
        """Check if a start tag should be ignored in fragment parsing context"""
        # HTML5 Fragment parsing rules
        
        # In html context, allow document structure
        if self.fragment_context == "html":
            return False  # Don't ignore anything in html context
            
        # In non-document contexts, ignore document structure elements
        if tag_name in ("html", "head", "body", "frameset"):
            return True
        
        # Also ignore context element start tags
        if self.fragment_context == tag_name:
            return True
        elif self.fragment_context in ("td", "th") and tag_name in ("td", "th"):
            return True
        elif self.fragment_context in ("thead", "tbody", "tfoot") and tag_name in ("thead", "tbody", "tfoot"):
            return True
        
        return False

    def _handle_fragment_comment(self, text: str, context: "ParseContext") -> None:
        """Handle comments in fragment parsing"""
        comment_node = Node("#comment")
        comment_node.text_content = text
        context.current_parent.append_child(comment_node)

    def _parse_document(self) -> None:
        """Parse HTML as a full document (original logic)"""
        # Initialize context with html_node as current_parent
        context = ParseContext(
            len(self.html),
            self._get_body_node(),
            self.html_node,
            debug_callback=self.debug if self.env_debug else None,
        )
        self.tokenizer = HTMLTokenizer(self.html)

        # if self.env_debug:
        #     # Create debug tokenizer with same debug setting
        #     debug_tokenizer = HTMLTokenizer(self.html, debug=self.env_debug)
        #     self.debug(f"TOKENS: {list(debug_tokenizer.tokenize())}", indent=0)

        for token in self.tokenizer.tokenize():
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

            if token.type == "Comment":
                self._handle_comment(token.data, context)
                continue

            # Ensure html node is in tree before processing any non-DOCTYPE/Comment token
            self._ensure_html_node()

            if token.type == "StartTag":
                # Handle special elements and state transitions first
                if self._handle_special_element(token, token.tag_name, context, self.tokenizer.pos):
                    context.index = self.tokenizer.pos
                    continue

                # Then handle the actual tag
                self._handle_start_tag(token, token.tag_name, context, self.tokenizer.pos)
                context.index = self.tokenizer.pos

            elif token.type == "EndTag":
                self._handle_end_tag(token, token.tag_name, context)
                context.index = self.tokenizer.pos

            elif token.type == "Character":
                for handler in self.tag_handlers:
                    if handler.should_handle_text(token.data, context):
                        self.debug(f"{handler.__class__.__name__}: handling {token}, context={context}")
                        if handler.handle_text(token.data, context):
                            break

        # After all tokens are processed, ensure we have proper HTML structure if not in frameset mode
        if context.document_state != DocumentState.IN_FRAMESET:
            # Ensure HTML node is in the tree
            self._ensure_html_node()
            # Ensure head exists first
            self._ensure_head_node()
            # Then ensure body exists
            body = self._ensure_body_node(context)
            if body:
                context.document_state = DocumentState.IN_BODY

    # Tag Handling Methods
    def _handle_start_tag(self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int) -> None:
        """Handle all opening HTML tags."""

        # Skip implicit body creation for fragments
        if not self.fragment_context:
            # Create body node if we're implicitly switching to body mode
            # But don't do this if we're inside template content
            if (
                context.document_state == DocumentState.INITIAL or context.document_state == DocumentState.IN_HEAD
            ) and tag_name not in HEAD_ELEMENTS and tag_name != "html" and not (
                context.current_parent and context.current_parent.tag_name == "content"
            ):
                self.debug("Implicitly creating body node")
                if context.document_state != DocumentState.IN_FRAMESET:
                    body = self._ensure_body_node(context)
                    if body:
                        context.current_parent = body
                        context.document_state = DocumentState.IN_BODY

        if context.content_state == ContentState.RAWTEXT:
            self.debug("In rawtext mode, ignoring start tag")
            return

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context):
                if handler.handle_start(token, context, not token.is_last_token):
                    return

        # Default handling for unhandled tags
        self.debug(f"No handler found, using default handling for {tag_name}")
        
        # Check if we need table foster parenting (but not inside template content)
        if (context.document_state == DocumentState.IN_TABLE and 
            tag_name not in self._get_table_elements() and 
            tag_name not in self._get_head_elements() and
            not self._is_in_template_content(context)):
            self.debug(f"Foster parenting {tag_name} out of table")
            self._foster_parent_element(tag_name, token.attributes, context)
            return
            
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        
        # Add to open elements stack
        context.open_elements.push(new_node)

    def _handle_end_tag(self, token: HTMLToken, tag_name: str, context: ParseContext) -> None:
        """Handle all closing HTML tags."""

        # Create body node if needed and not in frameset mode
        if not context.current_parent and context.document_state != DocumentState.IN_FRAMESET:
            if self.fragment_context:
                # In fragment mode, restore current_parent to fragment root
                context.current_parent = self.root
            else:
                body = self._ensure_body_node(context)
                if body:
                    context.current_parent = body

        # Check if adoption agency algorithm should run
        if self.adoption_agency.should_run_adoption(tag_name, context):
            self.debug(f"Running adoption agency algorithm for {tag_name}")
            if self.adoption_agency.run_algorithm(tag_name, context):
                return

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.should_handle_end(tag_name, context):
                if handler.handle_end(token, context):
                    # Ensure current_parent is never None in fragment mode
                    if self.fragment_context and not context.current_parent:
                        context.current_parent = self.root
                    return

        # Default end tag handling - close matching element if found
        # self._handle_default_end_tag(tag_name, context)  # Temporarily disabled

    def _handle_default_end_tag(self, tag_name: str, context: "ParseContext") -> None:
        """Handle end tags that don't have specific handlers by finding and closing matching element"""
        if not context.current_parent:
            return
            
        # Only handle end tags for simple elements - avoid handling complex elements
        # that might have special semantics
        if tag_name in ("html", "head", "body", "table", "tr", "td", "th", "tbody", "thead", "tfoot"):
            self.debug(f"Default end tag: skipping complex element {tag_name}")
            return
            
        # Look for the matching element in current parent only (immediate closure)
        if context.current_parent.tag_name == tag_name:
            # Found matching element, set current_parent to its parent
            if context.current_parent.parent:
                old_parent = context.current_parent
                context.current_parent = context.current_parent.parent
                self.debug(f"Default end tag: closed {tag_name}, current_parent now: {context.current_parent.tag_name}")
            else:
                # At root level, restore to appropriate context
                if self.fragment_context:
                    context.current_parent = self.root
                else:
                    context.current_parent = self.body_node or self.html_node
                self.debug(f"Default end tag: closed {tag_name}, restored to root context")
        else:
            # If no immediate match, ignore the end tag (don't search ancestry)
            self.debug(f"Default end tag: no immediate match for {tag_name}, ignoring")

    def _handle_special_element(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> bool:
        """Handle html, head, body and frameset tags."""
        if tag_name == "html":
            # Just update attributes, don't create a new node
            self.html_node.attributes.update(token.attributes)
            context.current_parent = self.html_node
            
            # Don't immediately switch to IN_BODY - let the normal flow handle that
            # The HTML tag should not automatically transition states
            return True
        elif tag_name == "head":
            # Don't create duplicate head elements
            head = self._ensure_head_node()
            context.current_parent = head
            context.document_state = DocumentState.IN_HEAD

            # If we're not in frameset mode, ensure we have a body
            if context.document_state != DocumentState.IN_FRAMESET:
                body = self._ensure_body_node(context)
            return True
        elif tag_name == "body" and context.document_state != DocumentState.IN_FRAMESET:
            # Create body if needed
            body = self._ensure_body_node(context)
            if body:
                # Update attributes and switch to body mode
                body.attributes.update(token.attributes)
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY
            return True
        elif tag_name == "frameset" and context.document_state == DocumentState.INITIAL:
            # Let the frameset handler handle this
            return False
        elif tag_name not in HEAD_ELEMENTS and context.document_state != DocumentState.IN_FRAMESET:
            # Handle implicit head/body transitions (but not in frameset mode)
            if context.document_state == DocumentState.INITIAL:
                self.debug("Implicitly closing head and switching to body")
                context.document_state = DocumentState.IN_BODY
                body = self._ensure_body_node(context)
                if body:
                    context.current_parent = body
            elif context.current_parent == self._get_head_node():
                self.debug("Closing head and switching to body")
                context.document_state = DocumentState.IN_BODY
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
        # First check if any handler wants to process this comment (e.g., CDATA in foreign elements)
        for handler in self.tag_handlers:
            if hasattr(handler, 'should_handle_comment') and handler.should_handle_comment(text, context):
                if hasattr(handler, 'handle_comment') and handler.handle_comment(text, context):
                    self.debug(f"Comment '{text}' handled by {handler.__class__.__name__}")
                    return
        
        # Default comment handling
        comment_node = Node("#comment")
        comment_node.text_content = text
        self.debug(f"Handling comment '{text}' in document_state {context.document_state}")
        self.debug(f"Current parent: {context.current_parent}")

        # Handle comment placement based on parser state
        if context.document_state == DocumentState.INITIAL:
            # If we have a current parent (like html), add comment there
            if context.current_parent:
                self.debug(f"Adding comment to current parent {context.current_parent.tag_name} in initial state")
                # In INITIAL state, comments should come before head elements but after the html tag
                if context.current_parent.tag_name == "html":
                    # Find the position to insert - before the first non-comment element (like head)
                    insert_index = 0
                    for i, child in enumerate(context.current_parent.children):
                        if child.tag_name not in ("#comment", "#text"):
                            insert_index = i
                            break
                        else:
                            insert_index = i + 1
                    context.current_parent.insert_child_at(insert_index, comment_node)
                    self.debug(f"Inserted comment at index {insert_index}")
                else:
                    context.current_parent.append_child(comment_node)
            else:
                self.debug("Adding comment to root in initial state")
                self.root.append_child(comment_node)
                self._ensure_html_node()  # Make sure html node is in tree
                context.document_state = DocumentState.IN_BODY
                # Ensure body exists and set as current parent
                if context.document_state != DocumentState.IN_FRAMESET:
                    body = self._ensure_body_node(context)
                    if body:
                        context.current_parent = body
            self.debug(f"Root children after append: {[c.tag_name for c in self.root.children]}")
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
                self.debug(f"Inserted comment before body")
            else:
                # If no body found, just append
                self.html_node.append_child(comment_node)
                self.debug("No body found, appended comment to html")
            return

        # Comments after </body> should go in html node
        if context.document_state == DocumentState.AFTER_BODY:
            self.debug("Adding comment to html in after body state")
            self.html_node.append_child(comment_node)
            return

        # Comments in IN_BODY state should go as children of html, positioned before head
        if (context.document_state == DocumentState.IN_BODY
            and context.current_parent.tag_name == "html"):
            # If we're in body state but current parent is html, place comment before head
            self.debug(f"Adding comment to html in body state")
            # Find head element and insert comment before it
            head_node = None
            for child in context.current_parent.children:
                if child.tag_name == "head":
                    head_node = child
                    break

            if head_node:
                context.current_parent.insert_before(comment_node, head_node)
                self.debug(f"Inserted comment before head")
            else:
                # If no head found, just append
                context.current_parent.append_child(comment_node)
                self.debug("No head found, appended comment")

            self.debug(f"Current parent children: {[c.tag_name for c in context.current_parent.children]}")
            return

        # All other comments go in current parent
        self.debug(f"Adding comment to current parent: {context.current_parent}")
        context.current_parent.append_child(comment_node)
        self.debug(f"Current parent children: {[c.tag_name for c in context.current_parent.children]}")

    def _handle_doctype(self, token: HTMLToken) -> None:
        """
        Handle DOCTYPE declarations by appending them to the root's children.
        """
        doctype_node = Node("!doctype")
        doctype_node.text_content = token.data  # Store the DOCTYPE content
        self.root.append_child(doctype_node)

    def _get_table_elements(self):
        """Get list of elements allowed in tables"""
        from .constants import TABLE_ELEMENTS
        return TABLE_ELEMENTS
    
    def _get_head_elements(self):
        """Get list of head elements (templates can appear in tables)"""
        from .constants import HEAD_ELEMENTS  
        return HEAD_ELEMENTS
    
    def _get_rawtext_elements(self):
        """Get list of RAWTEXT elements"""
        from .constants import RAWTEXT_ELEMENTS
        return RAWTEXT_ELEMENTS
    
    def _foster_parent_element(self, tag_name: str, attributes: dict, context: "ParseContext"):
        """Foster parent an element outside of table context"""
        # Find the table
        table = context.current_parent.find_ancestor("table")
        if not table or not table.parent:
            # No table found, use default handling
            new_node = Node(tag_name, attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            return
            
        # Insert the element before the table
        foster_parent = table.parent
        table_index = foster_parent.children.index(table)
        
        new_node = Node(tag_name, attributes)
        foster_parent.children.insert(table_index, new_node)
        context.current_parent = new_node
        self.debug(f"Foster parented {tag_name} before table")

    def _is_in_template_content(self, context: "ParseContext") -> bool:
        """Check if we're inside actual template content (not just a user <content> tag)"""
        # Check if current parent is content node
        if (context.current_parent and 
            context.current_parent.tag_name == "content" and 
            context.current_parent.parent and 
            context.current_parent.parent.tag_name == "template"):
            return True
        
        # Check if any ancestor is template content
        current = context.current_parent
        while current:
            if (current.tag_name == "content" and 
                current.parent and 
                current.parent.tag_name == "template"):
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
            
        self.debug("Reconstructing active formatting elements")
        
        # Get all active formatting elements in order
        entries = list(context.active_formatting_elements)
        if not entries:
            return
            
        # Reconstruct each formatting element as nested children
        current_parent = context.current_parent
        
        for entry in entries:
            # Clone the formatting element
            clone = Node(entry.element.tag_name, entry.element.attributes.copy())
            
            # Add as child of current parent
            current_parent.append_child(clone)
            
            # Update current parent to be the clone for nesting
            current_parent = clone
            
            self.debug(f"Reconstructed {clone.tag_name} inside {clone.parent.tag_name}")
        
        # Update context's current parent to the innermost reconstructed element
        context.current_parent = current_parent
