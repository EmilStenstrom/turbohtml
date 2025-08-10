from turbohtml.context import ParseContext, DocumentState, ContentState
from turbohtml.handlers import (
    AutoClosingTagHandler,
    DoctypeHandler,
    TemplateTagHandler,
    TemplateContentFilterHandler,
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

from .constants import HEAD_ELEMENTS, FORMATTING_ELEMENTS
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
            TemplateTagHandler(self),
            TemplateContentFilterHandler(self),
            PlaintextHandler(self),
            FramesetTagHandler(self),
            ForeignTagHandler(self) if handle_foreign_elements else None,  # Move before other handlers
            SelectTagHandler(self),  # Move before TableTagHandler so select can control table elements
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
            FormTagHandler(self),
            HeadingTagHandler(self),
            RubyElementHandler(self),  # Handle ruby annotation elements
            UnknownElementHandler(self),  # Handle unknown/namespace elements
        ]
        self.tag_handlers = [h for h in self.tag_handlers if h is not None]

        # Expose specific handlers for cross-handler coordination (minimal public surface)
        for handler in self.tag_handlers:
            if isinstance(handler, TextHandler):
                self.text_handler = handler
                break

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
    def transition_to_state(self, context: ParseContext, new_state: DocumentState, new_parent: "Node" = None) -> None:
        """Transition context to any document state, optionally with a new parent node"""
        context.transition_to_state(new_state, new_parent)

    def ensure_body_context(self, context: ParseContext) -> None:
        """Ensure context is in body context, transitioning if needed"""
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            body = self._ensure_body_node(context)
            context.transition_to_state(DocumentState.IN_BODY, body)

    # DOM traversal helper methods
    def find_current_table(self, context: ParseContext) -> Optional["Node"]:
        """Find the current table element from the open elements stack when in table context."""
        # When in explicit table context, look for the table in the open elements stack
        if context.document_state in (DocumentState.IN_TABLE, DocumentState.IN_TABLE_BODY, 
                                    DocumentState.IN_ROW, DocumentState.IN_CELL, DocumentState.IN_CAPTION):
            # Search through the open elements stack from top to bottom for a table
            for element in reversed(context.open_elements._stack):
                if element.tag_name == "table":
                    return element
        
        # Special case: if we're AFTER_BODY but have tables in open_elements,
        # we should still consider them for table-related elements (not foster parenting)
        elif context.document_state == DocumentState.AFTER_BODY:
            # Search through the open elements stack from top to bottom for a table
            for element in reversed(context.open_elements._stack):
                if element.tag_name == "table":
                    return element
        
        # Fallback: traverse ancestors from current parent
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
        if self.fragment_context == "template":
            # Special fragment parsing for templates: create a template/content container
            context = ParseContext(
                len(self.html),
                self.root,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.transition_to_state(DocumentState.IN_BODY, self.root)
            # Build the template wrapper under the fragment root and parse children into its content
            template_node = Node("template")
            self.root.append_child(template_node)
            content_node = Node("content")
            template_node.append_child(content_node)
            # Set insertion point to content
            context.move_to_element(content_node)
            # Track template depth to prevent implicit body promotions elsewhere
            try:
                context.template_content_depth = getattr(context, "template_content_depth", 0) + 1
            except Exception:
                pass
            return context
        if self.fragment_context in ("td", "th"):
            # Fragment is parsed as if inside a table cell
            context = ParseContext(
                len(self.html),
                self.root,  # Fragment root as initial parent
                debug_callback=self.debug if self.env_debug else None,
            )
            context.transition_to_state(DocumentState.IN_CELL, self.root)
                
        elif self.fragment_context in ("tr",):
            context = ParseContext(
                len(self.html),
                self.root,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.transition_to_state(DocumentState.IN_ROW, self.root)
            
        elif self.fragment_context in ("thead", "tbody", "tfoot"):
            context = ParseContext(
                len(self.html),
                self.root,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.transition_to_state(DocumentState.IN_TABLE_BODY, self.root)
            
        elif self.fragment_context == "html":
            # HTML fragment context - allow document structure
            context = ParseContext(
                len(self.html),
                self.root,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.transition_to_state(DocumentState.INITIAL, self.root)
            
        elif self.fragment_context in self._get_rawtext_elements():
            # RAWTEXT fragment context - treat all content as raw text
            context = ParseContext(
                len(self.html),
                self.root,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.transition_to_state(DocumentState.IN_BODY, self.root)
            
        else:
            # Default fragment context (body-like)
            context = ParseContext(
                len(self.html),
                self.root,
                debug_callback=self.debug if self.env_debug else None,
            )
            context.transition_to_state(DocumentState.IN_BODY, self.root)
            
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

    def _should_ignore_fragment_start_tag(self, tag_name: str, context: "ParseContext") -> bool:
        """Check if a start tag should be ignored in fragment parsing context"""
        # HTML5 Fragment parsing rules
        
        # In html context, allow document structure
        if self.fragment_context == "html":
            return False  # Don't ignore anything in html context
            
        # In non-document contexts, ignore document structure elements
        if tag_name in ("html", "head", "body", "frameset"):
            return True
        
        # In foreign contexts (MathML/SVG), let the foreign handlers manage everything
        # Fragment parsing is less relevant in foreign contexts
        if context.current_context in ("math", "svg"):
            return False
        
        # Also ignore context element start tags in HTML context
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
                # In template fragment context, ignore the context's own end tag
                if self.fragment_context == "template" and token.tag_name == "template":
                    continue
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
                context.transition_to_state(DocumentState.IN_BODY)

        # Normalize tree: merge adjacent text nodes (can result from foster parenting / reconstruction)
        self._merge_adjacent_text_nodes(self.root)

    # Tag Handling Methods
    def _handle_start_tag(self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int) -> None:
        """Handle all opening HTML tags."""

        # Skip implicit body creation for fragments
        if not self.fragment_context:
            # Create body node if we're implicitly switching to body mode
            # But don't do this if we're inside template content
            if (
                context.document_state == DocumentState.INITIAL or context.document_state == DocumentState.IN_HEAD
            ) and tag_name not in HEAD_ELEMENTS and tag_name != "html" and not self._is_in_template_content(context):
                self.debug("Implicitly creating body node")
                if context.document_state != DocumentState.IN_FRAMESET:
                    body = self._ensure_body_node(context)
                    if body:
                        context.transition_to_state(DocumentState.IN_BODY, body)

        if context.content_state == ContentState.RAWTEXT:
            self.debug("In rawtext mode, ignoring start tag")
            return

        # Per HTML5 spec, before processing most start tags, reconstruct the active
        # formatting elements. However, in table insertion modes (IN_TABLE, IN_TABLE_BODY,
        # IN_ROW) and when not inside a cell/caption, reconstructing would wrongly insert
        # formatting elements as children of <table>/<tbody>/<tr>. Skip reconstruction in
        # those cases; formatting will be handled via foster parenting and adoption agency.
        try:
            if not self._is_in_template_content(context):
                in_table_modes = context.document_state in (
                    DocumentState.IN_TABLE, DocumentState.IN_TABLE_BODY, DocumentState.IN_ROW
                )
                in_cell_or_caption = bool(
                    context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th", "caption"))
                )
                if not (in_table_modes and not in_cell_or_caption):
                    self.reconstruct_active_formatting_elements(context)
        except Exception:
            pass

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context):
                if handler.handle_start(token, context, not token.is_last_token):
                    return

        # Default handling for unhandled tags
        self.debug(f"No handler found, using default handling for {tag_name}")
        
        # Check if we need table foster parenting (but not inside template content or integration points)
        if (context.document_state == DocumentState.IN_TABLE and 
            tag_name not in self._get_table_elements() and 
            tag_name not in self._get_head_elements() and
            not self._is_in_template_content(context) and
            not self._is_in_integration_point(context)):
            self.debug(f"Foster parenting {tag_name} out of table")
            self._foster_parent_element(tag_name, token.attributes, context)
            return
            
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.move_to_element(new_node)
        
        # Add to open elements stack
        context.open_elements.push(new_node)

    def _handle_end_tag(self, token: HTMLToken, tag_name: str, context: ParseContext) -> None:
        """Handle all closing HTML tags."""

        # Create body node if needed and not in frameset mode
        if not context.current_parent and context.document_state != DocumentState.IN_FRAMESET:
            if self.fragment_context:
                # In fragment mode, restore current_parent to fragment root
                context.move_to_element(self.root)
            else:
                body = self._ensure_body_node(context)
                if body:
                    context.move_to_element(body)

        # Check if adoption agency algorithm should run iteratively
        adoption_run_count = 0
        max_runs = 8  # HTML5 spec limit for adoption agency algorithm iterations
        
        while adoption_run_count < max_runs:
            if self.adoption_agency.should_run_adoption(tag_name, context):
                adoption_run_count += 1
                self.debug(f"Running adoption agency algorithm #{adoption_run_count} for {tag_name}")
                
                if not self.adoption_agency.run_algorithm(tag_name, context, adoption_run_count):
                    # If adoption agency returns False, stop trying
                    self.debug(f"Adoption agency returned False on run #{adoption_run_count}, stopping")
                    break
            else:
                # No more adoption agency runs needed
                break
        
        if adoption_run_count > 0:
            self.debug(f"Adoption agency completed after {adoption_run_count} run(s) for </{tag_name}>")
            return

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
                if node.tag_name == "content" and node.parent and node.parent.tag_name == "template":
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
                context.move_up_one_level()
                self.debug(f"Default end tag: closed {tag_name}, current_parent now: {context.current_parent.tag_name}")
            else:
                # At root level, restore to appropriate context
                if self.fragment_context:
                    context.move_to_element(self.root)
                else:
                    context.move_to_element_with_fallback(self.body_node, self.html_node)
                self.debug(f"Default end tag: closed {tag_name}, restored to root context")
        else:
            # If no immediate match, ignore the end tag (don't search ancestry)
            self.debug(f"Default end tag: no immediate match for {tag_name}, ignoring")

    def _handle_special_element(
        self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int
    ) -> bool:
        """Handle html, head, body and frameset tags."""
        # Inside template content, do not perform special html/head/body/frameset handling.
        # Let the TemplateContentFilterHandler decide how to treat these tokens.
        if self._is_in_template_content(context):
            context.index = end_tag_idx
            return False
        # If we're inside a transparent template (frameset mode), don't do special handling
        if getattr(context, "template_transparent_depth", 0):
            context.index = end_tag_idx
            return False
        if tag_name == "html":
            # Just update attributes, don't create a new node
            self.html_node.attributes.update(token.attributes)
            context.move_to_element(self.html_node)
            
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
            # Create body if needed
            body = self._ensure_body_node(context)
            if body:
                # Update attributes and switch to body mode
                body.attributes.update(token.attributes)
                context.transition_to_state(DocumentState.IN_BODY, body)
            return True
        elif tag_name == "frameset" and context.document_state == DocumentState.INITIAL:
            # Let the frameset handler handle this
            return False
        elif tag_name not in HEAD_ELEMENTS and context.document_state != DocumentState.IN_FRAMESET:
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
            # In INITIAL state, check if html_node is already in tree
            if self.html_node in self.root.children:
                # HTML node exists, comment should go inside it
                self.debug(f"Adding comment to html in initial state")
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
            self.debug(f"Root children after comment: {[c.tag_name for c in self.root.children]}")
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

    def _merge_adjacent_text_nodes(self, node: Node) -> None:
        """Recursively merge adjacent text node children for cleaner DOM output.

        This is a post-processing normalization to align with html5lib expectations
        where successive character insertions that are contiguous end up in a single
        text node. It is intentionally conservative: only merges direct siblings
        that are both '#text'.
        """
        if not node.children:
            return
        merged = []
        pending_text = None
        for child in node.children:
            if child.tag_name == '#text':
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
            if child.tag_name != '#text':
                self._merge_adjacent_text_nodes(child)
    
    def _foster_parent_element(self, tag_name: str, attributes: dict, context: "ParseContext"):
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
        # a new sibling. This matches html5lib behavior where successive foster-parented
        # start tags become children (e.g., <table><div><div> becomes nested divs).
        if table_index > 0:
            prev_sibling = foster_parent.children[table_index - 1]
            # Only nest if previous sibling is a block-like container and current insertion
            # point is that previous sibling (we just foster parented into it)
            if (prev_sibling is context.current_parent and
                prev_sibling.tag_name in ("div","p","section","article","blockquote","li")):
                self.debug(f"Nesting {tag_name} inside existing foster-parented {prev_sibling.tag_name}")
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
    
    def _is_in_integration_point(self, context: "ParseContext") -> bool:
        """Check if we're inside an SVG or MathML integration point where HTML rules apply"""
        # Check current parent and ancestors for integration points
        current = context.current_parent
        while current:
            # SVG integration points: foreignObject, desc, title
            if current.tag_name in ("svg foreignObject", "svg desc", "svg title"):
                return True
            
            # MathML integration points: annotation-xml with specific encoding
            if (current.tag_name == "math annotation-xml" and 
                current.attributes and
                any(attr.name.lower() == "encoding" and 
                    attr.value.lower() in ("text/html", "application/xhtml+xml")
                    for attr in current.attributes)):
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

        # Find the earliest entry that needs reconstruction per spec:
        # Walk backwards until we find first entry whose element is not on the open elements stack.
        index_to_reconstruct_from = None
        for i, entry in enumerate(afe_list):
            # Skip markers (not implemented) – all entries treated as normal
            if not context.open_elements.contains(entry.element):
                index_to_reconstruct_from = i
                break
        if index_to_reconstruct_from is None:
            # Every formatting element already open
            return

        # Step 3: For each entry from index_to_reconstruct_from onwards, if element already open continue;
        # otherwise create element, append, push and update entry.element
        for entry in afe_list[index_to_reconstruct_from:]:
            if context.open_elements.contains(entry.element):
                continue
            clone = Node(entry.element.tag_name, entry.element.attributes.copy())
            context.current_parent.append_child(clone)
            context.open_elements.push(clone)
            # Update the entry's element reference
            entry.element = clone
            # Set current parent to the clone (nesting)
            context.move_to_element(clone)
            self.debug(f"Reconstructed formatting element {clone.tag_name}")
