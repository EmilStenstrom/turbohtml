import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Tuple, TYPE_CHECKING, Iterator

from .foreign import ForeignContentHandler
from .node import Node
from .constants import (
    VOID_ELEMENTS, HTML_ELEMENTS, SPECIAL_ELEMENTS, BLOCK_ELEMENTS,
    TABLE_CONTAINING_ELEMENTS, RAWTEXT_ELEMENTS, HEAD_ELEMENTS,
    TAG_OPEN_RE, ATTR_RE, COMMENT_RE, DUAL_NAMESPACE_ELEMENTS,
    SIBLING_ELEMENTS, TABLE_ELEMENTS, HEADER_ELEMENTS, BOUNDARY_ELEMENTS,
    FORMATTING_ELEMENTS, AUTO_CLOSING_TAGS
)

if TYPE_CHECKING:
    from .node import Node

DEBUG = False

def debug(*args, **kwargs) -> None:
    if DEBUG:
        print(*args, **kwargs)

class HTMLToken:
    """Represents a token in the HTML stream"""
    def __init__(self, type_: str, data: str = None, tag_name: str = None, 
                 attributes: Dict[str, str] = None, is_self_closing: bool = False):
        self.type = type_  # 'DOCTYPE', 'StartTag', 'EndTag', 'Comment', 'Character'
        self.data = data
        self.tag_name = tag_name
        self.attributes = attributes or {}
        self.is_self_closing = is_self_closing

    def __repr__(self):
        if self.type == 'Character':
            preview = self.data[:20]
            suffix = '...' if len(self.data) > 20 else ''
            return f"<{self.type}: '{preview}{suffix}'>"
        if self.type == 'Comment':
            preview = self.data[:20]
            suffix = '...' if len(self.data) > 20 else ''
            return f"<{self.type}: '{preview}{suffix}'>"
        return f"<{self.type}: {self.tag_name or self.data}>"


class ParserState(Enum):
    """
    Enumerates parser states for clarity and safety.
    """
    INITIAL = "initial"
    AFTER_HEAD = "after_head"
    IN_BODY = "in_body"
    IN_TABLE = "in_table"
    IN_TABLE_BODY = "in_table_body"
    IN_ROW = "in_row"
    IN_CELL = "in_cell"
    RAWTEXT = "rawtext"

class ParseContext:
    """
    Holds parser state during the parsing process.
    """
    def __init__(self, length: int, body_node: "Node", html_node: "Node"):
        self.index = 0
        self.length = length
        self.current_parent = body_node
        self.current_context = None
        self.has_form = False
        self.in_rawtext = False
        self.rawtext_start = 0
        self.html_node = html_node
        self._state = ParserState.INITIAL

    @property
    def state(self) -> ParserState:
        return self._state

    @state.setter
    def state(self, new_state: ParserState) -> None:
        if new_state != self._state:
            debug(f"State change: {self._state} -> {new_state}")
            self._state = new_state

    def __repr__(self):
        return f"<ParseContext: state={self.state.value}, parent={self.current_parent.tag_name}>"

class HTMLTokenizer:
    """
    HTML5 tokenizer that generates tokens from an HTML string.
    Maintains compatibility with existing parser logic while providing
    a cleaner separation of concerns.
    """
    def __init__(self, html: str):
        self.html = html
        self.pos = 0
        self.length = len(html)

    def tokenize(self) -> Iterator[HTMLToken]:
        """Generate tokens from the HTML string"""
        while self.pos < self.length:
            # 1. Try to match a comment
            if token := self._try_comment():
                yield token
                continue

            # 2. Try to match a tag
            if token := self._try_tag():
                yield token
                continue

            # 3. Handle character data
            if token := self._consume_character_data():
                yield token
                continue

            # Shouldn't reach here, but advance if we do
            self.pos += 1

    def _try_comment(self) -> Optional[HTMLToken]:
        """Try to match a comment at current position"""
        match = COMMENT_RE.match(self.html, self.pos)
        if not match or match.start() != self.pos:
            return None

        full_match = match.group(0)
        comment_text = match.group(1) or " "

        # Handle special malformed comment cases
        if full_match in ('<!-->', '<!--->'):
            comment_text = ""

        self.pos = match.end()
        return HTMLToken('Comment', data=comment_text)

    def _try_tag(self) -> Optional[HTMLToken]:
        """Try to match a tag at current position"""
        match = TAG_OPEN_RE.match(self.html, self.pos)
        if not match or match.start() != self.pos:
            return None

        is_exclamation = (match.group(1) == '!')
        is_closing = (match.group(2) == '/')
        tag_name = match.group(3)
        attr_string = match.group(4).strip()

        # Handle DOCTYPE
        if is_exclamation and tag_name.lower() == 'doctype':
            self.pos = match.end()
            return HTMLToken('DOCTYPE')

        # Parse attributes
        attributes = self._parse_attributes(attr_string)
        
        # Check for self-closing
        is_self_closing = attr_string.rstrip().endswith('/')

        self.pos = match.end()
        
        if is_closing:
            return HTMLToken('EndTag', tag_name=tag_name)
        return HTMLToken('StartTag', tag_name=tag_name, 
                        attributes=attributes, is_self_closing=is_self_closing)

    def _consume_character_data(self) -> HTMLToken:
        """Consume character data until the next tag or comment"""
        start = self.pos
        while self.pos < self.length:
            if self.html[self.pos] == '<':
                if (COMMENT_RE.match(self.html, self.pos) or 
                    TAG_OPEN_RE.match(self.html, self.pos)):
                    break
            self.pos += 1

        text = self.html[start:self.pos]
        return HTMLToken('Character', data=text)

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """Parse attributes from a string using the ATTR_RE pattern"""
        attr_string = attr_string.strip().rstrip('/')
        matches = ATTR_RE.findall(attr_string)
        attributes = {}
        for attr_name, val1, val2, val3 in matches:
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name] = attr_value
        return attributes

class TagHandler:
    """Base class for tag-specific handling logic"""
    def __init__(self, parser: 'TurboHTML'):
        self.parser = parser

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        """Handle start tag. Return True if handled."""
        return False

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        """Handle end tag. Return True if handled."""
        return False

class TextHandler(TagHandler):
    """Handles all regular text content"""
    
    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        return False  # Text handler doesn't handle start tags
        
    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        return False  # Text handler doesn't handle end tags
    
    def handle_text(self, text: str, context: ParseContext) -> bool:
        """Handle regular text content"""
        if not text:
            return True

        # Skip if we're in rawtext mode (let RawtextTagHandler handle it)
        if context.in_rawtext:
            # Store the text in the current rawtext element
            text_node = Node('#text')
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # If we're in a table context, let the table handler deal with it
        if context.state == ParserState.IN_TABLE:
            return False

        # Check if text needs foster parenting
        if self.parser._has_element_in_scope('#text', context.current_parent):
            foster_parent = self.parser._find_ancestor(context.current_parent, 'p')
            if foster_parent:
                if text.strip():  # Only foster parent non-whitespace text
                    return self._handle_normal_text(text, ParseContext(
                        context.length, foster_parent, context.html_node))
                return True

        # Handle <pre> elements specially
        if context.current_parent.tag_name.lower() == 'pre':
            return self._handle_pre_text(text, context.current_parent)

        # Default text handling
        return self._handle_normal_text(text, context)

    def _handle_normal_text(self, text: str, context: ParseContext) -> bool:
        """Handle normal text content"""
        # If last child is a text node, append to it
        if (context.current_parent.children and 
            context.current_parent.children[-1].tag_name == '#text'):
            context.current_parent.children[-1].text_content += text
        else:
            # Create new text node
            text_node = Node('#text')
            text_node.text_content = text
            context.current_parent.append_child(text_node)
        return True

    def _handle_pre_text(self, text: str, parent: Node) -> bool:
        """Handle text specifically for <pre> elements"""
        decoded_text = self._decode_html_entities(text)
        
        # Append to existing text node if present
        if (parent.children and
            parent.children[-1].tag_name == '#text'):
            parent.children[-1].text_content += decoded_text
        else:
            # Remove a leading newline if this is the first text node
            if not parent.children and decoded_text.startswith('\n'):
                decoded_text = decoded_text[1:]
            if decoded_text:
                text_node = Node('#text')
                text_node.text_content = decoded_text
                parent.append_child(text_node)
        return True

    def _decode_html_entities(self, text: str) -> str:
        """Decode numeric HTML entities."""
        text = re.sub(r'&#x([0-9a-fA-F]+);', 
                     lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r'&#([0-9]+);', 
                     lambda m: chr(int(m.group(1))), text)
        return text

class SelectTagHandler(TagHandler):
    """Handles select, option, and optgroup elements"""
    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in ('select', 'option', 'optgroup'):
            return False

        if tag_name in ('optgroup', 'select'):
            current = context.current_parent
            # If we're inside an option, move up to its parent
            while current and current.tag_name.lower() == 'option':
                current = current.parent
            
            # Create and append the new node to the appropriate parent
            new_node = self.parser._create_node(tag_name, token.attributes, current, context.current_context)
            current.append_child(new_node)
            context.current_parent = new_node
        else:  # option
            new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node

        return True

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        if token.tag_name.lower() != 'option':
            return False

        # Find the nearest option element
        current = context.current_parent
        while current and current.tag_name.lower() != 'option':
            current = current.parent
        
        if current and current.tag_name.lower() == 'option':
            # Move any optgroup children to be siblings
            for child in current.children[:]:
                if child.tag_name.lower() == 'optgroup':
                    current.parent.append_child(child)
                    current.children.remove(child)
            
            # Move back to the option's parent
            context.current_parent = current.parent or self.parser.body_node

        return True

class ParagraphTagHandler(TagHandler):
    """Handles paragraph elements"""
    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name != 'p':
            return False

        # Make sure we have a valid parent
        if not context.current_parent:
            context.current_parent = self.parser.body_node

        # Create and append the new node
        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        return True

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        if token.tag_name.lower() != 'p':
            return False

        # Find the nearest p element using the helper
        current = self.parser._find_ancestor(context.current_parent, 'p')
        
        if current:
            # Found a matching p element, close it
            context.current_parent = current.parent or self.parser.body_node
        else:
            # No matching p element found, create an implicit one
            new_p = self.parser._create_node('p', {}, context.current_parent, context.current_context)
            context.current_parent.append_child(new_p)

        return True

class TableTagHandler(TagHandler):
    """Handles table-related elements"""
    def _foster_parent(self, node: Node, parent_before_table: Node, table: Node) -> None:
        """Move a node to before the nearest table"""
        if not parent_before_table or not table:
            return

        # If we found a text node and the last element is also text, merge them
        if (isinstance(node, Node) and node.tag_name == '#text' and
            parent_before_table.children and 
            parent_before_table.children[-1].tag_name == '#text'):
            parent_before_table.children[-1].text_content += node.text_content
        else:
            # Otherwise insert before the table
            table_index = parent_before_table.children.index(table)
            parent_before_table.children.insert(table_index, node)

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in ('table', 'tbody', 'thead', 'tfoot', 'tr', 'td', 'th'):
            # If we're in a table context, move non-table elements before the table
            if context.state == ParserState.IN_TABLE:
                table = self.parser._find_ancestor(context.current_parent, 'table')
                if table and table.parent:
                    # Create node in the current parent first
                    new_node = self.parser._create_node(tag_name, token.attributes, table.parent, context.current_context)
                    # Then move it to before the table
                    self._foster_parent(new_node, table.parent, table)
                    context.current_parent = new_node
                    context.state = ParserState.IN_BODY  # Move back to body context
                    return True
                else:
                    # If we can't find a proper parent, add to body
                    new_node = self.parser._create_node(tag_name, token.attributes, self.parser.body_node, context.current_context)
                    self.parser.body_node.append_child(new_node)
                    context.current_parent = new_node
                    context.state = ParserState.IN_BODY  # Move back to body context
                    return True
            return False

        if tag_name == 'table':
            # Move any non-table content before the table
            if context.current_parent.tag_name.lower() != 'table':
                for child in context.current_parent.children[:]:
                    if child.tag_name.lower() not in TABLE_ELEMENTS:
                        # Find the last non-table element before where the table will be
                        table_index = len(context.current_parent.children)
                        for i, sibling in enumerate(context.current_parent.children):
                            if sibling.tag_name.lower() == 'table':
                                table_index = i
                                break
                        context.current_parent.children.insert(table_index - 1, child)
                        context.current_parent.children.remove(child)

            new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            context.state = ParserState.IN_TABLE
            return True

        elif tag_name in ('td', 'th'):
            table = self.parser._find_ancestor(context.current_parent, 'table')
            if table:
                tbody = self._ensure_tbody(table)
                tr = self._ensure_tr(tbody)
                new_node = self.parser._create_node(tag_name, token.attributes, tr, context.current_context)
                tr.append_child(new_node)
                context.current_parent = new_node
                context.state = ParserState.IN_CELL
                return True

        return False

    def handle_text(self, text: str, context: ParseContext) -> bool:
        """Handle text nodes in table context"""
        if context.state == ParserState.IN_TABLE:
            table = self.parser._find_ancestor(context.current_parent, 'table')
            if table and table.parent:
                # Create text node
                text_node = Node('#text')
                text_node.text_content = text
                # Move it before the table
                self._foster_parent(text_node, table.parent, table)
                return True
        return False

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in ('table', 'tbody', 'thead', 'tfoot', 'tr', 'td', 'th'):
            return False

        if tag_name == 'table':
            # Find the table element
            current = context.current_parent
            while current and current.tag_name.lower() != 'table':
                current = current.parent
            
            if current:
                context.current_parent = current.parent or self.parser.body_node
                context.state = ParserState.IN_BODY
        elif tag_name in ('thead', 'tbody', 'tfoot'):
            context.state = ParserState.IN_TABLE
        elif tag_name == 'tr':
            context.state = ParserState.IN_TABLE_BODY
        elif tag_name in ('td', 'th'):
            context.state = ParserState.IN_ROW

        return True

    def _ensure_tbody(self, table):
        """Ensure table has a tbody, create if needed"""
        for child in table.children:
            if child.tag_name.lower() == 'tbody':
                return child
        tbody = self.parser._create_node('tbody', {}, table, None)
        table.append_child(tbody)
        return tbody

    def _ensure_tr(self, tbody):
        """Ensure tbody has a tr, create if needed"""
        if not tbody.children or tbody.children[-1].tag_name.lower() != 'tr':
            tr = self.parser._create_node('tr', {}, tbody, None)
            tbody.append_child(tr)
            return tr
        return tbody.children[-1]

class FormTagHandler(TagHandler):
    """Handles form-related elements (form, input, button, etc.)"""
    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in ('form', 'input', 'button', 'textarea', 'select', 'label'):
            return False

        if tag_name == 'form':
            # Only one form element allowed
            if context.has_form:
                return True
            context.has_form = True

        # Create and append the new node
        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        
        # Update current parent for non-void elements
        if tag_name not in ('input',):
            context.current_parent = new_node

        return True

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in ('form', 'button', 'textarea', 'select', 'label'):
            return False

        # Find the nearest matching element
        current = context.current_parent
        while current and current.tag_name.lower() != tag_name:
            current = current.parent

        if current:
            context.current_parent = current.parent or self.parser.body_node
            if tag_name == 'form':
                context.has_form = False

        return True

class ListTagHandler(TagHandler):
    """Handles list-related elements (ul, ol, li)"""
    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in ('ul', 'ol', 'li'):
            return False

        # If we're in a table context, let the table handler deal with it
        if context.state == ParserState.IN_TABLE:
            return False

        # Make sure we have a valid parent
        if not context.current_parent:
            context.current_parent = self.parser.body_node

        if tag_name == 'li':
            # Close any open li elements first
            current = context.current_parent
            while current:
                if current.tag_name.lower() == 'li':
                    context.current_parent = current.parent or self.parser.body_node
                    break
                if current.tag_name.lower() in ('ul', 'ol'):
                    break
                current = current.parent

        # Create and append the new node
        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        return True

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in ('ul', 'ol', 'li'):
            return False

        # If we're in a table context, let the table handler deal with it
        if context.state == ParserState.IN_TABLE:
            return False

        # Find the nearest matching element
        current = context.current_parent
        while current and current.tag_name.lower() != tag_name:
            current = current.parent

        if current:
            context.current_parent = current.parent or self.parser.body_node
        else:
            context.current_parent = self.parser.body_node

        return True

class HeadingTagHandler(TagHandler):
    """Handles heading elements (h1-h6)"""
    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name.lower()
        if not tag_name.startswith('h') or not tag_name[1:].isdigit() or not (1 <= int(tag_name[1:]) <= 6):
            return False

        # Close any open headings first
        current = context.current_parent
        while current:
            current_tag = current.tag_name.lower()
            if current_tag.startswith('h') and current_tag[1:].isdigit():
                context.current_parent = current.parent
                break
            current = current.parent

        # Create and append the new heading
        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        return True

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name.lower()
        if not tag_name.startswith('h') or not tag_name[1:].isdigit() or not (1 <= int(tag_name[1:]) <= 6):
            return False

        # Find the nearest heading element
        current = context.current_parent
        while current:
            current_tag = current.tag_name.lower()
            if current_tag == tag_name:
                context.current_parent = current.parent or self.parser.body_node
                break
            current = current.parent

        return True

class RawtextTagHandler(TagHandler):
    """Handles rawtext elements like script, style, title, etc."""
    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in RAWTEXT_ELEMENTS:
            return False

        # Always try to place RAWTEXT elements in head if we're not explicitly in body
        if (tag_name in HEAD_ELEMENTS and 
            context.state != ParserState.IN_BODY):
            new_node = self.parser._create_node(tag_name, token.attributes, self.parser.head_node, context.current_context)
            self.parser.head_node.append_child(new_node)
            context.current_parent = new_node
            context.state = ParserState.RAWTEXT
            context.in_rawtext = True
            context.rawtext_start = end_tag_idx
            return True

        # Otherwise create in current location
        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        context.state = ParserState.RAWTEXT
        context.in_rawtext = True
        context.rawtext_start = end_tag_idx
        return True

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name not in RAWTEXT_ELEMENTS:
            return False

        if context.in_rawtext and tag_name == context.current_parent.tag_name.lower():
            # Get the raw text content before changing state
            text = self.parser.html[context.rawtext_start:context.index]
            if text:
                # Create a text node with the raw content
                text_node = Node('#text')
                text_node.text_content = text
                context.current_parent.append_child(text_node)
            
            context.in_rawtext = False
            context.state = ParserState.IN_BODY
            
            # If it's a head element and we're not in body mode, stay in head
            if (tag_name in HEAD_ELEMENTS and 
                context.current_parent.parent == self.parser.head_node):
                context.current_parent = self.parser.head_node
            else:
                # Otherwise move to body
                context.current_parent = self.parser.body_node
            return True

        return False

class ButtonTagHandler(TagHandler):
    """Handles button elements"""
    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name != 'button':
            return False

        # Create and append the new node
        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        return True

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name.lower()
        if tag_name != 'button':
            return False

        # Find the nearest button element
        current = context.current_parent
        while current and current.tag_name.lower() != 'button':
            current = current.parent

        if current:
            # Merge text nodes in button
            text_content = ""
            new_children = []
            for child in current.children:
                if child.tag_name == '#text':
                    text_content += child.text_content
                else:
                    new_children.append(child)
            
            if text_content:
                text_node = Node('#text')
                text_node.text_content = text_content
                new_children.insert(0, text_node)
            
            current.children = new_children
            context.current_parent = current
            return True

        return False

    def handle_text(self, text: str, context: ParseContext) -> bool:
        """Handle text nodes in button context"""
        if context.current_parent.tag_name.lower() == 'button':
            # If there's already a text node, append to it
            if (context.current_parent.children and 
                context.current_parent.children[-1].tag_name == '#text'):
                context.current_parent.children[-1].text_content += text
            else:
                # Otherwise create a new text node
                text_node = Node('#text')
                text_node.text_content = text
                context.current_parent.append_child(text_node)
            return True
        return False

class TurboHTML:
    """
    Main parser interface.
    - Instantiation with an HTML string automatically triggers parsing.
    - Provides a root Node that represents the DOM tree.
    """
    def __init__(self, html: str, handle_foreign_elements: bool = True, debug: bool = False):
        """
        Args:
            html: The HTML string to parse
            handle_foreign_elements: Whether to handle SVG/MathML elements
            debug: Whether to enable debug prints
        """
        self.html = html
        self.foreign_handler = ForeignContentHandler() if handle_foreign_elements else None
        self.state = ParserState.INITIAL

        # Create basic HTML structure
        self.root = Node('document')
        self.html_node = Node('html')
        self.head_node = Node('head')
        self.body_node = Node('body')

        self.root.append_child(self.html_node)
        self.html_node.append_child(self.head_node)
        self.html_node.append_child(self.body_node)

        # Set up debug flag
        global DEBUG
        DEBUG = debug

        # Initialize tag handlers
        self.tag_handlers = [
            TextHandler(self),
            RawtextTagHandler(self),
            SelectTagHandler(self),
            ParagraphTagHandler(self),
            TableTagHandler(self),
            FormTagHandler(self),
            ListTagHandler(self),
            HeadingTagHandler(self),
            ButtonTagHandler(self),
        ]

        # Trigger parsing
        self._parse()

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"

    def _parse(self) -> None:
        """
        Main parsing loop using ParseContext and HTMLTokenizer.
        Delegates text logic to TextHandler.
        """
        context = ParseContext(len(self.html), self.body_node, self.html_node)
        tokenizer = HTMLTokenizer(self.html)

        for token in tokenizer.tokenize():
            debug(f"_parse: {token}, context: {context}")
            if token.type == 'Comment':
                self._append_comment_node(token.data, context)
            
            elif token.type in ('DOCTYPE', 'StartTag', 'EndTag'):
                self._handle_tag(token, context, tokenizer.pos)
            
            elif token.type == 'Character':
                for handler in self.tag_handlers:
                    if hasattr(handler, 'handle_text') and handler.handle_text(token.data, context):
                        break

    def _append_comment_node(self, text: str, context: ParseContext) -> None:
        """
        Create and append a comment node with proper placement based on parser state.
        """
        comment_node = Node('#comment')
        comment_node.text_content = text

        # First comment should go in root if we're still in initial state
        if context.state == ParserState.INITIAL:
            self.root.children.insert(0, comment_node)
            context.state = ParserState.IN_BODY
            return

        context.current_parent.append_child(comment_node)

    def _handle_tag(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> None:
        """Handle all HTML tags: opening, closing, and special cases."""
        # Handle DOCTYPE first since it doesn't have a tag_name
        if token.type == 'DOCTYPE':
            self._handle_doctype(token)
            context.index = end_tag_idx
            return

        # Now we know we have a tag_name for all other cases
        tag_name_lower = token.tag_name.lower()

        if token.type == 'StartTag':
            if tag_name_lower in ('html', 'head', 'body'):
                self._handle_special_element(token, tag_name_lower, context, end_tag_idx)
                return
            self._handle_start_tag(token, tag_name_lower, context, end_tag_idx)
        elif token.type == 'EndTag':
            self._handle_end_tag(token, tag_name_lower, context)

        context.index = end_tag_idx

    def _handle_special_element(self, token: HTMLToken, tag_name_lower: str, context: ParseContext, end_tag_idx: int) -> None:
        """Handle html, head and body tags."""
        if tag_name_lower == 'html':
            self.html_node.attributes.update(token.attributes)
        elif tag_name_lower == 'head':
            context.current_parent = self.head_node
        elif tag_name_lower == 'body':
            self.body_node.attributes.update(token.attributes)
            context.current_parent = self.body_node
        context.index = end_tag_idx

    def _handle_start_tag(self, token: HTMLToken, tag_name_lower: str, context: ParseContext, end_tag_idx: int) -> None:
        """Handle all opening HTML tags."""
        debug(f"_handle_start_tag: {tag_name_lower}, current_parent={context.current_parent}")
        
        # Ensure we always have a valid current_parent
        if not context.current_parent:
            context.current_parent = self.body_node

        # If we're in rawtext mode, ignore all tokens except for the matching end tag
        if context.state == ParserState.RAWTEXT:
            return

        # Switch to body mode for non-head elements
        if ((context.state == ParserState.INITIAL or context.current_parent == self.head_node) and 
            tag_name_lower not in HEAD_ELEMENTS):
            debug(f"\tSwitching to body mode due to {tag_name_lower}")
            context.state = ParserState.IN_BODY
            context.current_parent = self.body_node

        # Handle special elements (html, head, body)
        if tag_name_lower in ('html', 'head', 'body'):
            self._handle_special_element(token, tag_name_lower, context, end_tag_idx)
            return

        # Handle auto-closing tags
        self._handle_auto_closing(tag_name_lower, context)

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.handle_start(token, context, end_tag_idx):
                return

        # Default handling for unhandled tags
        new_node = self._create_node(tag_name_lower, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        
        # Update current_parent for non-void elements
        if tag_name_lower not in VOID_ELEMENTS:
            context.current_parent = new_node

    def _handle_end_tag(self, token: HTMLToken, tag_name_lower: str, context: ParseContext) -> None:
        """Handle closing tags."""
        debug(f"_handle_end_tag: {tag_name_lower}, current_parent={context.current_parent}")
        
        if not context.current_parent:
            context.current_parent = self.body_node

        # Try tag handlers first
        for handler in self.tag_handlers:
            if handler.handle_end(token, context):
                return

        # Default handling for unhandled tags
        if self._has_element_in_scope(tag_name_lower, context.current_parent):
            current = context.current_parent
            while current and current.tag_name.lower() != tag_name_lower:
                current = current.parent
            
            if current:
                context.current_parent = current.parent or self.body_node

    def _handle_auto_closing(self, tag_name_lower: str, context: ParseContext) -> None:
        """Handle auto-closing tag logic."""
        current = context.current_parent
        while current and current != self.body_node:
            current_tag = current.tag_name.lower()
            if current_tag in AUTO_CLOSING_TAGS.get(tag_name_lower, set()):
                context.current_parent = current.parent
                break
            current = current.parent

    def _handle_closing_tag(self, tag_name: str, current_parent: Node,
                            current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """
        Close the specified tag, with special handling for formatting elements
        inside special elements.
        """
        tag_name_lower = tag_name.lower()

        # Close any foreign context
        if self.foreign_handler:
            current_parent, current_context = self.foreign_handler.handle_foreign_end_tag(
                tag_name, current_parent, current_context
            )

        # Check if the element is in scope
        if not self._has_element_in_scope(tag_name_lower, current_parent):
            # If not in scope, ignore the closing tag completely
            return current_parent, current_context

        # Find the element to close
        temp_parent = current_parent
        while temp_parent and temp_parent.tag_name.lower() != tag_name_lower:
            temp_parent = temp_parent.parent

        if temp_parent:
            # When closing any element, return to its parent's context
            target_parent = temp_parent.parent
            
            # If we're closing a table element, look for any active formatting elements
            if tag_name_lower in TABLE_ELEMENTS:
                while target_parent and target_parent.tag_name.lower() in FORMATTING_ELEMENTS:
                    return target_parent, current_context
            
            return target_parent, current_context

        return current_parent, current_context

    def _create_node(self, tag_name: str, attributes: dict,
                     current_parent: Node, current_context: Optional[str]) -> Node:
        """
        Create a new node, potentially using the foreign handler if present.
        """
        if self.foreign_handler:
            return self.foreign_handler.create_node(tag_name, attributes, current_parent, current_context)
        return Node(tag_name.lower(), attributes)

    def _handle_doctype(self, token: HTMLToken) -> None:
        """
        Handle DOCTYPE declarations by prepending them to the root's children.
        """
        doctype_node = Node('!doctype')
        self.root.children.insert(0, doctype_node)

    def _find_ancestor(self, current_parent: Node, tag_name: str) -> Optional[Node]:
        """
        Find the nearest ancestor with the given tag name.
        """
        ancestors = self._get_ancestors(current_parent)
        for ancestor in ancestors:
            if ancestor.tag_name.lower() == tag_name.lower():
                return ancestor
        return None

    def _get_ancestors(self, node: Node) -> List[Node]:
        """
        Return all ancestors of a node, including the node itself.
        """
        ancestors = []
        current = node
        while current:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def _has_element_in_scope(self, tag_name: str, current_parent: Node) -> bool:
        """
        Check if an element is in scope according to HTML5 rules.
        Returns False if we hit a scope boundary before finding the element.
        """
        node = current_parent
        while node:
            if node.tag_name.lower() == tag_name:
                return True
            # Check for scope boundaries
            if node.tag_name.lower() in BOUNDARY_ELEMENTS:
                return False
            node = node.parent
        return False
