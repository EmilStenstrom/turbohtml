# fast_html.py
#
# Minimal HTML parser built from scratch:
# - Partially HTML5 compliant tokenizer
# - Lightweight DOM (Node)
# - Basic CSS-like query methods: tag, #id, .class

import re
from typing import List, Optional, Dict, Tuple, Set, TYPE_CHECKING

from .foreign import ForeignContentHandler
from .node import Node
from .constants import (
    VOID_ELEMENTS, HTML_ELEMENTS, SPECIAL_ELEMENTS, BLOCK_ELEMENTS,
    TABLE_CONTAINING_ELEMENTS, RAWTEXT_ELEMENTS, HEAD_ELEMENTS,
    TAG_OPEN_RE, ATTR_RE, COMMENT_RE, DUAL_NAMESPACE_ELEMENTS
)

if TYPE_CHECKING:
    from .node import Node

class TurboHTML:
    """
    Main parser interface.
    - Instantiation with HTML string automatically triggers parsing.
    - Provides a root Node that represents the DOM tree.
    """
    def __init__(self, html: str, handle_foreign_elements: bool = True):
        """Initialize the HTML parser.
        
        Args:
            html: The HTML string to parse
            handle_foreign_elements: Whether to handle SVG/MathML elements
        """
        self.html = html
        self.foreign_handler = ForeignContentHandler() if handle_foreign_elements else None
        self.has_doctype = False
        self.state = 'initial'  # Add parser state

        # Create basic HTML structure
        self.root = Node('document')
        self.html_node = Node('html')
        self.head_node = Node('head')
        self.body_node = Node('body')
        
        self.root.append_child(self.html_node)
        self.html_node.append_child(self.head_node)
        self.html_node.append_child(self.body_node)
        
        self.current_parent = self.body_node
        self._parse()

    # Public methods
    def query_all(self, selector: str) -> List[Node]:
        """Query all nodes matching the selector."""
        return self.root.query_all(selector)

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"

    # Core parsing methods
    def _parse(self) -> None:
        """Main parsing loop."""
        index = 0
        length = len(self.html)
        current_parent = self.current_parent
        current_context = None
        has_form = False
        self.state = 'initial'
        in_rawtext = False
        rawtext_start = 0

        while index < length:
            # Look for comments first
            comment_match = COMMENT_RE.search(self.html, index)
            if comment_match and comment_match.start() == index:
                # Skip comment handling if we're in rawtext
                if in_rawtext:
                    index = comment_match.end()
                    continue
                
                comment_text = comment_match.group(1)
                comment_node = Node('#comment')
                comment_node.text_content = comment_text
                
                # Handle comments based on state
                if self.state == 'after_head':
                    # Comments in after_head state go directly under html node
                    body_index = self.html_node.children.index(self.body_node)
                    self.html_node.children.insert(body_index, comment_node)
                    comment_node.parent = self.html_node
                else:
                    current_parent.append_child(comment_node)
                
                index = comment_match.end()
                continue

            # Look for next tag
            tag_open_match = TAG_OPEN_RE.search(self.html, index)
            if not tag_open_match:
                # Handle remaining text
                if index < length:
                    text = self.html[index:]
                    if not in_rawtext:
                        self._handle_text_between_tags(text, current_parent)
                        if text.strip():
                            if self.state == 'after_head':
                                self.state = 'in_body'
                                current_parent = self.body_node
                break

            start_idx = tag_open_match.start()
            
            # Handle text before tag
            if start_idx > index and not in_rawtext:
                text = self.html[index:start_idx]
                
                # Update parent to body if we have non-whitespace text after head
                if text.strip() and self.state == 'after_head':
                    self.state = 'in_body'
                    # Only update current_parent if we're not inside a pre tag
                    if current_parent.tag_name.lower() != 'pre':
                        current_parent = self.body_node
                
                if self.foreign_handler and current_parent.tag_name == 'math annotation-xml':
                    node = self.foreign_handler.handle_text(text, current_parent)
                    if node:
                        current_parent.append_child(node)
                else:
                    self._handle_text_between_tags(text, current_parent)  # Handle text only once
                
                index = start_idx

            # Process the tag
            start_tag_idx, end_tag_idx, tag_info = self._extract_tag_info(tag_open_match)

            # If we're in rawtext mode, only look for matching end tag
            if in_rawtext:
                if not tag_open_match:
                    # No more tags - capture rest of content
                    text = self.html[rawtext_start:]
                    if text:
                        # Strip first newline for textarea/pre
                        if (current_parent.tag_name.lower() in ('textarea', 'pre') and 
                            not current_parent.children and text.startswith('\n')):
                            text = text[1:]
                        if text:  # Check again after stripping
                            text_node = Node('#text')
                            text_node.text_content = text
                            current_parent.append_child(text_node)
                    break

                if (tag_info.is_closing and 
                    tag_info.tag_name.lower() == current_parent.tag_name.lower()):
                    # Create text node with all content
                    text = self.html[rawtext_start:start_idx]
                    if text:
                        # Strip first newline for textarea/pre
                        if (current_parent.tag_name.lower() in ('textarea', 'pre') and 
                            not current_parent.children and text.startswith('\n')):
                            text = text[1:]
                        if text:  # Check again after stripping
                            text_node = Node('#text')
                            text_node.text_content = text
                            current_parent.append_child(text_node)
                    in_rawtext = False
                    current_parent = current_parent.parent
                index = end_tag_idx
                continue

            # Start rawtext mode if entering a rawtext element (but not in SVG/MathML context)
            if (not tag_info.is_closing and 
                tag_info.tag_name.lower() in RAWTEXT_ELEMENTS and 
                (not current_context or current_context not in ('svg', 'mathml'))):
                current_parent, current_context = self._handle_opening_tag(
                    tag_info, current_parent, current_context
                )
                in_rawtext = True
                rawtext_start = end_tag_idx
                index = end_tag_idx
                continue

            # Update state based on tags - move this AFTER we get tag_info
            if tag_info.is_closing and tag_info.tag_name.lower() == 'head':
                self.state = 'after_head'
                current_parent = self.html_node  # Set parent to html for comments
                index = end_tag_idx
                continue

            if tag_info.is_closing:
                current_parent, current_context = self._handle_closing_tag(
                    tag_info.tag_name, current_parent, current_context
                )
            elif tag_info.is_doctype:
                self._handle_doctype(tag_info)
            else:
                # Skip nested form tags
                if tag_info.tag_name.lower() == 'form':
                    if has_form:
                        index = end_tag_idx
                        continue
                    has_form = True
                    
                current_parent, current_context = self._handle_opening_tag(
                    tag_info, current_parent, current_context
                )
            
            index = end_tag_idx

        # Cleanup: handle any remaining rawtext content at EOF
        if in_rawtext:
            text = self.html[rawtext_start:]
            if text:
                # Strip first newline for textarea/pre
                if (current_parent.tag_name.lower() in ('textarea', 'pre') and 
                    not current_parent.children and text.startswith('\n')):
                    text = text[1:]
                if text:  # Check again after stripping
                    text_node = Node('#text')
                    text_node.text_content = text
                    current_parent.append_child(text_node)

        # Update the current_parent for future reference
        self.current_parent = current_parent

    def _handle_opening_tag(self, tag_info: "TagInfo", current_parent: Node, 
                            current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """Handle opening/self-closing tags with special cases."""
        tag_name = tag_info.tag_name.lower()
        attributes = self._parse_attributes(tag_info.attr_string)

        # Special handling for html tag - reuse existing html node
        if tag_name == 'html':
            self.html_node.attributes.update(attributes)
            return self.html_node, current_context

        # Special handling for body tag - reuse existing body node
        if tag_name == 'body':
            self.body_node.attributes.update(attributes)
            return self.body_node, current_context

        # Special handling for head tag - reuse existing head node
        if tag_name == 'head':
            return self.head_node, current_context

        # Don't hoist if we're inside an SVG/MathML context and it's a dual element
        is_dual_context = current_context in ('svg', 'mathml')
        is_dual_element = tag_name in DUAL_NAMESPACE_ELEMENTS

        # Handle raw text elements first
        if tag_name in RAWTEXT_ELEMENTS:
            # Only move to head if it's a head element, not in body mode, and not a dual element in svg/mathml
            if (tag_name in HEAD_ELEMENTS and 
                self.head_node and 
                self.state != 'in_body' and 
                not (is_dual_context and is_dual_element)):
                new_node = self._create_node(tag_name, attributes, self.head_node, 'rawtext')
                self.head_node.append_child(new_node)
                return new_node, 'rawtext'
            # Otherwise handle as normal rawtext, preserving the current context
            new_node = self._create_node(tag_name, attributes, current_parent, current_context)
            current_parent.append_child(new_node)
            return new_node, current_context if is_dual_context else 'rawtext'

        # Move other head elements to head ONLY if not in body mode and not a dual element in svg/mathml
        if (tag_name in HEAD_ELEMENTS and 
            self.head_node and 
            not (is_dual_context and is_dual_element)):
            if (current_parent != self.head_node and 
                current_context is None and 
                self.state != 'in_body'):
                new_node = self._create_node(tag_name, attributes, self.head_node, None)
                self.head_node.append_child(new_node)
                return current_parent, current_context

        # Special handling for option tags
        if tag_name == 'option':
            # Find the nearest option parent
            temp_parent = current_parent
            while temp_parent:
                if temp_parent.tag_name.lower() == 'option':
                    # If there are elements between options, nest it
                    if any(child.tag_name.lower() != 'option' 
                          for child in temp_parent.children):
                        new_node = self._create_node(tag_name, attributes, current_parent, current_context)
                        current_parent.append_child(new_node)
                        return new_node, current_context
                    # Otherwise make it a sibling
                    new_node = self._create_node(tag_name, attributes, temp_parent.parent, current_context)
                    temp_parent.parent.append_child(new_node)
                    return new_node, current_context
                temp_parent = temp_parent.parent

        # Special handling for <table> inside <p>
        if tag_name == 'table' and current_parent.tag_name.lower() == 'p':
            # Create a new <p> as a child of the original <p>
            new_p = Node('p')
            current_parent.append_child(new_p)
            # Create and append table to original <p>
            new_node = self._create_node(tag_name, attributes, current_parent, current_context)
            current_parent.append_child(new_node)
            return new_node, current_context

        # Handle auto-closing first
        current_parent = self._handle_auto_closing(tag_name, current_parent)

        # Then handle foreign elements if enabled
        if self.foreign_handler:
            current_parent, current_context = self.foreign_handler.handle_context(
                tag_name, current_parent, current_context
            )

        # Create node with proper namespace
        new_node = self._create_node(tag_name, attributes, current_parent, current_context)

        # Append the new node to current parent
        current_parent.append_child(new_node)

        # For non-void elements, make the new node the current parent
        if tag_name not in VOID_ELEMENTS:
            current_parent = new_node

        return current_parent, current_context

    def _create_node(self, tag_name: str, attributes: dict, 
                    current_parent: Node, current_context: Optional[str]) -> Node:
        """Create a new node with proper namespace handling."""
        if self.foreign_handler:
            return self.foreign_handler.create_node(tag_name, attributes, current_parent, current_context)
        return Node(tag_name.lower(), attributes)

    def _handle_closing_tag(self, tag_name: str, current_parent: Node, 
                           current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """Handle closing tags with special cases for table voodoo."""
        tag_name_lower = tag_name.lower()

        # Handle foreign elements if enabled
        if self.foreign_handler:
            current_parent, current_context = self.foreign_handler.handle_foreign_end_tag(
                tag_name, current_parent, current_context
            )

        # Special case for </p>
        if tag_name_lower == 'p':
            # Find the original p tag
            original_p = None
            temp_parent = current_parent
            while temp_parent:
                if temp_parent.tag_name.lower() == 'p':
                    original_p = temp_parent
                    break
                temp_parent = temp_parent.parent

            if original_p:
                if current_parent.tag_name.lower() == 'button':
                    # For <p><button></p> case - create new <p> inside button
                    new_p = Node('p')
                    current_parent.append_child(new_p)
                    return new_p, current_context
                elif current_parent.tag_name.lower() == 'table':
                    # For <p><table></p> case - don't create a new p
                    return original_p.parent, current_context
                
            # Normal </p> handling
            return original_p.parent if original_p else current_parent, current_context

        # Normal closing tag handling
        temp_parent = current_parent
        while temp_parent and temp_parent.tag_name.lower() != tag_name_lower:
            temp_parent = temp_parent.parent
        
        if temp_parent:
            return temp_parent.parent, current_context

        return current_parent, current_context

    def _decode_html_entities(self, text: str) -> str:
        """Decode HTML entities in text."""
        # Handle hex entities (&#x0a;)
        text = re.sub(r'&#x([0-9a-fA-F]+);', 
                    lambda m: chr(int(m.group(1), 16)), 
                    text)
        # Handle decimal entities (&#10;)
        text = re.sub(r'&#([0-9]+);',
                    lambda m: chr(int(m.group(1))),
                    text)
        return text

    # Helper methods
    def _handle_text_between_tags(self, text: str, current_parent: Node) -> None:
        """Handle text found between tags."""
        # Special handling for pre tags
        if current_parent.tag_name.lower() == 'pre':
            # Decode entities first
            decoded_text = self._decode_html_entities(text)
            
            # For pre tags, combine all text into a single node
            if current_parent.children and current_parent.children[-1].tag_name == '#text':
                # Append to existing text node
                current_parent.children[-1].text_content += decoded_text
            else:
                # Only strip first newline if this is the first text node
                if not current_parent.children and decoded_text.startswith('\n'):
                    decoded_text = decoded_text[1:]
                if decoded_text:  # Only create node if there's content
                    text_node = Node('#text')
                    text_node.text_content = decoded_text
                    text_node.parent = current_parent
                    current_parent.children.append(text_node)
            return

        # Special handling for raw text elements
        if current_parent.tag_name.lower() in RAWTEXT_ELEMENTS:
            if text.strip():
                text_node = Node('#text')
                text_node.text_content = text
                current_parent.append_child(text_node)

        if self.foreign_handler:
            node = self.foreign_handler.handle_text(text, current_parent)
            if node:
                current_parent.append_child(node)
                return

        # Default text handling - preserve all whitespace for regular elements
        if text:
            text_node = Node('#text')
            text_node.text_content = text
            current_parent.append_child(text_node)

    def _handle_doctype(self, tag_info: "TagInfo") -> None:
        """Handle DOCTYPE declaration."""
        self.has_doctype = True
        doctype_node = Node('!doctype')
        self.root.children.insert(0, doctype_node)  # Insert DOCTYPE as first child

    def _get_ancestors(self, node: Node) -> list[Node]:
        """Helper method to get all ancestors of a node."""
        ancestors = []
        current = node
        while current:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """
        Parse attributes from a string using the ATTR_RE pattern.
        """
        attr_string = attr_string.strip().rstrip('/')
        matches = ATTR_RE.findall(attr_string)
        attributes = {}
        for attr_name, val1, val2, val3 in matches:
            # Depending on which group matched, pick the correct value
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name] = attr_value
        return attributes

    def query(self, selector: str) -> Optional[Node]:
        """Shortcut to query the root node."""
        return self.root.query(selector)

    def _extract_tag_info(self, match) -> tuple[int, int, "TagInfo"]:
        """Extract tag information from a regex match."""
        class TagInfo:
            def __init__(self, is_exclamation, is_closing, tag_name, attr_string):
                self.is_exclamation = is_exclamation
                self.is_closing = is_closing
                self.tag_name = tag_name
                self.attr_string = attr_string
                self.is_doctype = (is_exclamation and tag_name.lower() == 'doctype')

        return (
            match.start(),
            match.end(),
            TagInfo(
                match.group(1) == '!',
                match.group(2) == '/',
                match.group(3),
                match.group(4).strip()
            )
        )

    def _handle_auto_closing(self, tag_name: str, current_parent: Node) -> Node:
        """Handle tags that cause auto-closing of parent tags."""
        tag_name_lower = tag_name.lower()

        # Handle nested nobr tags
        if tag_name_lower == 'nobr':
            nobr_ancestor = next(
                (p for p in self._get_ancestors(current_parent)
                 if p.tag_name.lower() == 'nobr'),
                None
            )
            if nobr_ancestor:
                return nobr_ancestor.parent

        # Special handling for button inside button
        if tag_name_lower == 'button':
            button_ancestor = next(
                (p for p in self._get_ancestors(current_parent)
                 if p.tag_name.lower() == 'button'),
                None
            )
            if button_ancestor:
                return button_ancestor.parent

        # Special handling for option inside option
        if tag_name_lower == 'option':
            option_ancestor = next(
                (p for p in self._get_ancestors(current_parent)
                 if p.tag_name.lower() == 'option'),
                None
            )
            if option_ancestor:
                return option_ancestor.parent

        # Handle other auto-closing cases
        if current_parent.tag_name.lower() == 'p' and tag_name_lower in BLOCK_ELEMENTS:
            return current_parent.parent

        return current_parent
