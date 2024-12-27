import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Dict, Tuple, TYPE_CHECKING, Iterator

from .foreign import ForeignContentHandler
from .node import Node
from .constants import (
    VOID_ELEMENTS, HTML_ELEMENTS, SPECIAL_ELEMENTS, BLOCK_ELEMENTS,
    TABLE_CONTAINING_ELEMENTS, RAWTEXT_ELEMENTS, HEAD_ELEMENTS,
    TAG_OPEN_RE, ATTR_RE, COMMENT_RE, DUAL_NAMESPACE_ELEMENTS,
    SIBLING_ELEMENTS, TABLE_ELEMENTS, HEADER_ELEMENTS, BOUNDARY_ELEMENTS,
    FORMATTING_ELEMENTS, AUTO_CLOSING_TAGS, HEADING_ELEMENTS
)

if TYPE_CHECKING:
    from .node import Node

DEBUG = False

def debug(*args, indent=4, **kwargs) -> None:
    if DEBUG:
        if indent:
            print(f"{' ' * indent}{args[0]}", *args[1:], **kwargs)
        else:
            print(*args, **kwargs)

class HTMLToken:
    """Represents a token in the HTML stream"""
    def __init__(self, type_: str, data: str = None, tag_name: str = None, 
                 attributes: Dict[str, str] = None, is_self_closing: bool = False):
        self.type = type_  # 'DOCTYPE', 'StartTag', 'EndTag', 'Comment', 'Character'
        self.data = data
        self.tag_name = tag_name.lower() if tag_name is not None else None
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
    INITIAL = auto()
    AFTER_HEAD = auto()
    IN_BODY = auto()
    IN_TABLE = auto()
    IN_TABLE_BODY = auto()
    IN_ROW = auto()
    IN_CELL = auto()
    RAWTEXT = auto()
    IN_CAPTION = auto()

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

    def should_handle_start(self, tag_name: str) -> bool:
        """Return True if this handler should handle the given start tag"""
        return False

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        pass

    def should_handle_end(self, tag_name: str) -> bool:
        """Return True if this handler should handle the given end tag"""
        return False

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        pass

    def should_handle_text(self, text: str) -> bool:
        """Return True if this handler should handle the given text"""
        return False

    def handle_text(self, text: str, context: ParseContext) -> bool:
        pass

class TextHandler(TagHandler):
    """Handles all regular text content"""
    def should_handle_text(self, text: str) -> bool:
        """Return True if this handler should handle the given text"""
        return True

    def handle_text(self, text: str, context: ParseContext) -> bool:
        """Handle regular text content"""
        if not text:
            return

        # Skip if we're in rawtext mode (let RawtextTagHandler handle it)
        if context.in_rawtext:
            # Store the text in the current rawtext element
            text_node = Node('#text')
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return

        # If we're in a table context, let the table handler deal with it
        if context.state == ParserState.IN_TABLE:
            return

        # Check if text needs foster parenting
        if self.parser._find_ancestor(context.current_parent, '#text', stop_at_boundary=True):
            foster_parent = self.parser._find_ancestor(context.current_parent, 'p')
            if foster_parent:
                if text.strip():  # Only foster parent non-whitespace text
                    self._handle_normal_text(text, ParseContext(
                        context.length, foster_parent, context.html_node)
                    )
                return

        # Handle <pre> elements specially
        if context.current_parent.tag_name == 'pre':
            self._handle_pre_text(text, context.current_parent)
            return

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

    def _decode_html_entities(self, text: str) -> str:
        """Decode numeric HTML entities."""
        text = re.sub(r'&#x([0-9a-fA-F]+);', 
                     lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r'&#([0-9]+);', 
                     lambda m: chr(int(m.group(1))), text)
        return text

class SelectTagHandler(TagHandler):
    """Handles select, option, and optgroup elements"""
    def should_handle_start(self, tag_name: str) -> bool:
        return tag_name in ('select', 'option', 'optgroup')

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"SelectTagHandler.handle_start: {token.tag_name}")
        if token.tag_name in ('optgroup', 'select'):
            current = self.parser._find_ancestor(context.current_parent, 'option')
            new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
            
            # If we found an option parent, append to it, otherwise append to current parent
            if current:
                current.append_child(new_node)
            else:
                context.current_parent.append_child(new_node)
            
            context.current_parent = new_node
        else:  # option
            new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node

    def should_handle_end(self, tag_name: str) -> bool:
        return tag_name == 'option'

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"SelectTagHandler.handle_end: {token.tag_name}")
        current = self.parser._find_ancestor(context.current_parent, 'option')

        if current and current.tag_name == 'option':
            for child in current.children[:]:
                if child.tag_name == 'optgroup':
                    current.parent.append_child(child)
                    current.children.remove(child)
            context.current_parent = current.parent or self.parser.body_node

class ParagraphTagHandler(TagHandler):
    """Handles paragraph elements"""
    def should_handle_start(self, tag_name: str) -> bool:
        return tag_name == 'p'

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"ParagraphTagHandler.handle_start: {token.tag_name}")
        if not context.current_parent:
            context.current_parent = self.parser.body_node
        new_node = self.parser._create_node('p', token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node

    def should_handle_end(self, tag_name: str) -> bool:
        return tag_name == 'p'

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"ParagraphTagHandler.handle_end: {token.tag_name}")
        current = self.parser._find_ancestor(context.current_parent, 'p')
        if current:
            context.current_parent = current.parent or self.parser.body_node
        else:
            new_p = self.parser._create_node('p', {}, context.current_parent, context.current_context)
            context.current_parent.append_child(new_p)

class TableTagHandler(TagHandler):
    """Handles table-related elements"""

    def should_handle_start(self, tag_name: str) -> bool:
        return tag_name in ('table', 'td', 'th', 'tr', 'tbody', 'thead', 'tfoot')

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"TableTagHandler.handle_start: {token.tag_name}")
        tag_name = token.tag_name
        
        if tag_name == 'table':
            new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            context.state = ParserState.IN_TABLE
            return
            
        if tag_name in ('td', 'th'):
            if context.state == ParserState.IN_TABLE:
                table = self.parser._find_ancestor(context.current_parent, 'table')
                if table:
                    debug(f"Found table for cell: {table}")
                    tbody = self._ensure_tbody(table)
                    tr = self._ensure_tr(tbody)
                    new_node = self.parser._create_node(tag_name, token.attributes, tr, context.current_context)
                    tr.append_child(new_node)
                    context.current_parent = new_node
                    return

        if context.state == ParserState.IN_TABLE:
            # Check if we're inside a table cell
            current = self.parser._find_ancestor(context.current_parent, 'td') or self.parser._find_ancestor(context.current_parent, 'th')
            if current:
                new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                return 

            table = self.parser._find_ancestor(context.current_parent, 'table')
            
            if not table:
                new_node = self.parser._create_node(tag_name, token.attributes, self.parser.body_node, context.current_context)
                self.parser.body_node.append_child(new_node)
                context.current_parent = new_node
                context.state = ParserState.IN_BODY
                return

            if not table.parent:
                new_node = self.parser._create_node(tag_name, token.attributes, self.parser.body_node, context.current_context)
                self.parser.body_node.append_child(new_node)
                context.current_parent = new_node
                return

            foster_parent = table.parent if table.parent.tag_name != 'template' else table.parent

            if not foster_parent:
                new_node = self.parser._create_node(tag_name, token.attributes, self.parser.body_node, context.current_context)
                self.parser.body_node.append_child(new_node)
                context.current_parent = new_node
                return

            new_node = self.parser._create_node(tag_name, token.attributes, foster_parent, context.current_context)
            self._foster_parent(new_node, foster_parent, table)
            context.current_parent = new_node
            return

    def handle_text(self, text: str, context: ParseContext) -> bool:
        debug(f"TableTagHandler.handle_text: '{text}'")
        if context.state == ParserState.IN_TABLE:
            # Check if we're inside a table cell
            cell = self.parser._find_ancestor(context.current_parent, 'td') or self.parser._find_ancestor(context.current_parent, 'th')
            if cell:
                debug("Inside table cell, creating text normally")
                text_node = Node('#text')
                text_node.text_content = text
                context.current_parent.append_child(text_node)
                return True

            # If parent is already foster parented (not in table structure),
            # append text directly to it
            if not self._is_table_element(context.current_parent.tag_name):
                debug(f"Adding text to foster parented element: {text}")
                text_node = Node('#text')
                text_node.text_content = text
                context.current_parent.append_child(text_node)
                return

            # Otherwise foster parent the text
            table = self.parser._find_ancestor(context.current_parent, 'table')
            if table and table.parent:
                debug(f"Foster parenting text: {text}")
                text_node = Node('#text')
                text_node.text_content = text
                self._foster_parent(text_node, table.parent, table)
                return
    
    def should_handle_end(self, tag_name: str) -> bool:
        return tag_name == 'tr'

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"TableTagHandler.handle_end: {token.tag_name}")
        current = self.parser._find_ancestor(context.current_parent, 'tr')
        if current:
            context.current_parent = current.parent or (
                self.parser._find_ancestor(current, 'table') or 
                self.parser.body_node
            )
        return

    def _foster_parent(self, node: Node, foster_parent: Node, table: Node) -> None:
        """
        Foster parent a node according to the HTML5 spec:
        - If last element before table is text, merge text nodes
        - Otherwise insert immediately before the table
        """
        debug(f"Foster parenting: {node}, foster_parent={foster_parent}")

        # Find the table's index in its parent
        table_index = foster_parent.children.index(table)
        
        # If we're foster parenting text and there's a text node before the table
        if (node.tag_name == '#text' and table_index > 0 and 
            foster_parent.children[table_index - 1].tag_name == '#text'):
            # Merge with existing text node
            debug("Merging with existing text node")
            foster_parent.children[table_index - 1].text_content += node.text_content
        else:
            # Insert before the table
            debug(f"Inserting before table at index {table_index}")
            foster_parent.children.insert(table_index, node)

    def _ensure_tbody(self, table):
        """Ensure table has a tbody element"""
        for child in table.children:
            if child.tag_name == 'tbody':
                return child
        tbody = self.parser._create_node('tbody', {}, table, None)
        table.append_child(tbody)
        return tbody

    def _ensure_tr(self, tbody):
        """Ensure tbody has a tr element"""
        for child in tbody.children:
            if child.tag_name == 'tr':
                return child
        tr = self.parser._create_node('tr', {}, tbody, None)
        tbody.append_child(tr)
        return tr

    def _is_table_element(self, tag_name: str) -> bool:
        """Check if an element is part of table structure"""
        return tag_name in ('table', 'tbody', 'thead', 'tfoot', 'tr', 'td', 'th', 'caption', 'colgroup', 'col')

class FormTagHandler(TagHandler):
    """Handles form-related elements (form, input, button, etc.)"""

    def should_handle_start(self, tag_name: str) -> bool:
        return tag_name in ('form', 'input', 'button', 'textarea', 'select', 'label')

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name

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

    def should_handle_end(self, tag_name: str) -> bool:
        return tag_name in ('form', 'button', 'textarea', 'select', 'label')

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name

        # Find the nearest matching element
        current = self.parser._find_ancestor(context.current_parent, tag_name)

        if current:
            context.current_parent = current.parent or self.parser.body_node
            if tag_name == 'form':
                context.has_form = False

class ListTagHandler(TagHandler):
    """Handles list-related elements (ul, ol, li)"""
    def should_handle_start(self, tag_name: str) -> bool:
        return tag_name in ('ul', 'ol', 'li')

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"ListTagHandler.handle_start: {token.tag_name}")
        tag_name = token.tag_name
        if tag_name == 'li':
            if context.current_parent.tag_name in ('ul', 'ol'):
                new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                return

            # Close any open li elements first
            li = self.parser._find_ancestor(context.current_parent, 'li')
            if li:
                context.current_parent = li.parent

            # Find nearest list container
            list_container = (
                self.parser._find_ancestor(context.current_parent, 'ul') or 
                self.parser._find_ancestor(context.current_parent, 'ol') or 
                self.parser.body_node
            )

            # Create and append the new node
            new_node = self.parser._create_node(tag_name, token.attributes, list_container, context.current_context)
            list_container.append_child(new_node)
            context.current_parent = new_node
            return

        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node

    def should_handle_end(self, tag_name: str) -> bool:
        return tag_name in ('ul', 'ol', 'li')

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"ListTagHandler.handle_end: {token.tag_name}")
        current = self.parser._find_ancestor(context.current_parent, token.tag_name)
        if current:
            context.current_parent = current.parent or self.parser.body_node
            return

class HeadingTagHandler(TagHandler):
    """Handles heading elements (h1-h6)"""
    def should_handle_start(self, tag_name: str) -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"HeadingTagHandler.handle_start: {token.tag_name}")
        # Close any open headings first
        current = self.parser._find_ancestor(context.current_parent, 
            lambda node: node.tag_name in HEADING_ELEMENTS)
        if current:
            context.current_parent = current.parent
        
        new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node

    def should_handle_end(self, tag_name: str) -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"HeadingTagHandler.handle_end: {token.tag_name}")
        current = self.parser._find_ancestor(context.current_parent, token.tag_name)
        if current:
            context.current_parent = current.parent or self.parser.body_node

class RawtextTagHandler(TagHandler):
    """Handles rawtext elements like script, style, title, etc."""
    def should_handle_start(self, tag_name: str) -> bool:
        return tag_name in RAWTEXT_ELEMENTS

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"RawtextTagHandler.handle_start: {token.tag_name}")
        tag_name = token.tag_name
        
        # Always try to place RAWTEXT elements in head if we're not explicitly in body
        if (tag_name in HEAD_ELEMENTS and 
            context.state != ParserState.IN_BODY):
            new_node = self.parser._create_node(tag_name, token.attributes, self.parser.head_node, context.current_context)
            self.parser.head_node.append_child(new_node)
            context.current_parent = new_node
            context.state = ParserState.RAWTEXT
            context.in_rawtext = True
            context.rawtext_start = end_tag_idx
            return

        # Otherwise create in current location
        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        context.state = ParserState.RAWTEXT
        context.in_rawtext = True
        context.rawtext_start = end_tag_idx

    def should_handle_end(self, tag_name: str) -> bool:
        return tag_name in RAWTEXT_ELEMENTS

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"RawtextTagHandler.handle_end: {token.tag_name}")
        if context.in_rawtext and token.tag_name == context.current_parent.tag_name:
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
            if (token.tag_name in HEAD_ELEMENTS and 
                context.current_parent.parent == self.parser.head_node):
                context.current_parent = self.parser.head_node
            else:
                # Otherwise move to body
                context.current_parent = self.parser.body_node
            return

class ButtonTagHandler(TagHandler):
    """Handles button elements"""
    def should_handle_start(self, tag_name: str) -> bool:
        debug(f"ButtonTagHandler.should_handle_start: {tag_name}", indent=0)
        return tag_name == 'button'

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"ButtonTagHandler.handle_start: {token.tag_name}", indent=0)
        debug(f"Current parent: {context.current_parent}", indent=0)
        new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        debug(f"New current parent: {context.current_parent}", indent=0)

    def should_handle_end(self, tag_name: str) -> bool:
        debug(f"ButtonTagHandler.should_handle_end: {tag_name}", indent=0)
        return tag_name == 'button'

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"ButtonTagHandler.handle_end: {token.tag_name}", indent=0)
        debug(f"Current parent: {context.current_parent}", indent=0)
        current = self.parser._find_ancestor(context.current_parent, 'button')
        debug(f"Found button ancestor: {current}", indent=0)
        if current:
            debug("Merging text nodes in button", indent=0)
            text_content = ""
            new_children = []
            for child in current.children:
                debug(f"Processing child: {child}", indent=0)
                if child.tag_name == '#text':
                    text_content += child.text_content
                else:
                    new_children.append(child)
            
            if text_content:
                debug(f"Creating merged text node with content: {text_content}", indent=0)
                text_node = Node('#text')
                text_node.text_content = text_content
                new_children.insert(0, text_node)
            
            current.children = new_children
            context.current_parent = current.parent or self.parser.body_node
            debug(f"New current parent: {context.current_parent}", indent=0)

    def handle_text(self, text: str, context: ParseContext) -> bool:
        debug(f"ButtonTagHandler.handle_text: '{text}'", indent=0)
        debug(f"Current parent: {context.current_parent}", indent=0)
        button = self.parser._find_ancestor(context.current_parent, 'button')
        debug(f"Found button ancestor: {button}", indent=0)
        if button:
            if (button.children and 
                button.children[-1].tag_name == '#text'):
                debug("Appending to existing text node", indent=0)
                button.children[-1].text_content += text
            else:
                debug("Creating new text node", indent=0)
                text_node = Node('#text')
                text_node.text_content = text
                button.append_child(text_node)
            debug(f"Button children after text handling: {button.children}", indent=0)
            return True
        debug("No button ancestor found, not handling text", indent=0)
        return False

class VoidElementHandler(TagHandler):
    """Handles void elements that can't have children"""
    def should_handle_start(self, tag_name: str) -> bool:
        return tag_name in VOID_ELEMENTS

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"VoidElementHandler.handle_start: {token.tag_name}")
        
        # If we're in a paragraph and this is a block element, close the paragraph first
        if (token.tag_name in BLOCK_ELEMENTS and 
            self.parser._find_ancestor(context.current_parent, 'p')):
            debug("Block element in paragraph, closing paragraph")
            p_node = self.parser._find_ancestor(context.current_parent, 'p')
            context.current_parent = p_node.parent or self.parser.body_node
        
        new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)

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
            VoidElementHandler(self),
            SelectTagHandler(self),
            ParagraphTagHandler(self),
            ListTagHandler(self),
            TableTagHandler(self),
            FormTagHandler(self),
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
            debug(f"_parse: {token}, context: {context}", indent=0)
            if token.type == 'Comment':
                self._handle_comment(token.data, context)
            
            # Handle DOCTYPE first since it doesn't have a tag_name
            if token.type == 'DOCTYPE':
                self._handle_doctype(token)
                context.index = tokenizer.pos
                continue

            if token.type == 'StartTag':
                if token.tag_name in ('html', 'head', 'body'):
                    self._handle_special_element(token, token.tag_name, context, tokenizer.pos)
                    continue

                self._handle_start_tag(token, token.tag_name, context, tokenizer.pos)
                context.index = tokenizer.pos

            if token.type == 'EndTag':
                self._handle_end_tag(token, token.tag_name, context)
                context.index = tokenizer.pos
            
            elif token.type == 'Character':
                for handler in self.tag_handlers:
                    if handler.should_handle_text(token.data):
                        debug(f"{handler.__class__.__name__}: handling {token}")
                        handler.handle_text(token.data, context)
                        break

    def _handle_comment(self, text: str, context: ParseContext) -> None:
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

    def _handle_special_element(self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int) -> None:
        """Handle html, head and body tags."""
        if tag_name == 'html':
            self.html_node.attributes.update(token.attributes)
        elif tag_name == 'head':
            context.current_parent = self.head_node
        elif tag_name == 'body':
            self.body_node.attributes.update(token.attributes)
            context.current_parent = self.body_node
        context.index = end_tag_idx

    def _handle_start_tag(self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int) -> None:
        """Handle all opening HTML tags."""
        debug(f"_handle_start_tag: {tag_name}, current_parent={context.current_parent}")
        
        # Ensure we always have a valid current_parent
        if not context.current_parent:
            debug("No parent, setting to body")
            context.current_parent = self.body_node

        # If we're in rawtext mode, ignore all tokens except for the matching end tag
        if context.state == ParserState.RAWTEXT:
            debug("In rawtext mode, ignoring start tag")
            return

        # Handle state transitions for non-head elements
        if tag_name not in HEAD_ELEMENTS:
            if context.state == ParserState.INITIAL:
                debug("\tImplicitly closing head and switching to body")
                context.state = ParserState.IN_BODY
                if context.current_parent == self.head_node:
                    context.current_parent = self.body_node
            elif context.current_parent == self.head_node:
                debug("\tClosing head and switching to body")
                context.state = ParserState.IN_BODY
                context.current_parent = self.body_node

        # Handle auto-closing tags
        debug(f"Checking auto-closing for {tag_name}")
        self._handle_auto_closing(tag_name, context)

        # Try tag handlers first
        debug(f"Trying tag handlers for {tag_name}")
        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name):
                debug(f"{handler.__class__.__name__}: handling {token}")
                handler.handle_start(token, context, end_tag_idx)
                return

        # Default handling for unhandled tags
        debug(f"No handler found, using default handling for {tag_name}")
        new_node = self._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        
        # Update current_parent for non-void elements
        if tag_name not in VOID_ELEMENTS:
            debug(f"Updating current_parent to {tag_name}")
            context.current_parent = new_node

    def _handle_end_tag(self, token: HTMLToken, tag_name: str, context: ParseContext) -> None:
        """Handle all closing HTML tags."""
        debug(f"_handle_end_tag: {tag_name}, current_parent={context.current_parent}")
        
        if not context.current_parent:
            context.current_parent = self.body_node

        # Check if we're inside a button - if so, don't allow closing ancestor tags
        button = self._find_ancestor(context.current_parent, 'button')
        if button and tag_name != 'button':
            debug(f"Inside button, ignoring end tag for {tag_name}")
            return

        # Try tag handlers first
        debug(f"Trying tag handlers for end tag {tag_name}")
        for handler in self.tag_handlers:
            if handler.should_handle_end(tag_name):
                debug(f"{handler.__class__.__name__}: handling {token}")
                handler.handle_end(token, context)
                return

        # Default handling for unhandled tags
        debug(f"No end tag handler found, looking for matching tag {tag_name}")
        current = context.current_parent
        current = self._find_ancestor(current, tag_name)
        if current:
            debug(f"Found matching tag {tag_name}, updating current_parent")
            context.current_parent = current.parent or self.body_node
            return

        debug(f"No matching tag found for {tag_name}")

    def _handle_auto_closing(self, tag_name: str, context: ParseContext) -> None:
        """Handle tags that should auto-close other tags"""
        if tag_name not in AUTO_CLOSING_TAGS:
            return

        debug(f"Checking auto-closing rules for {tag_name}")
        current = context.current_parent
        current = self._find_ancestor(current, tag_name)
        if current:
            debug(f"Auto-closing {current.tag_name}")
            context.current_parent = current.parent
            return

    def _handle_closing_tag(self, tag_name: str, current_parent: Node,
                            current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """
        Close the specified tag, with special handling for formatting elements
        inside special elements.
        """
        # Close any foreign context
        if self.foreign_handler:
            current_parent, current_context = self.foreign_handler.handle_foreign_end_tag(
                tag_name, current_parent, current_context
            )

        # Check if the element is in scope
        if not self._find_ancestor(current_parent, tag_name, stop_at_boundary=True):
            # If not in scope, ignore the closing tag completely
            return current_parent, current_context

        # Find the element to close
        temp_parent = self._find_ancestor(current_parent, tag_name)

        if temp_parent:
            # When closing any element, return to its parent's context
            target_parent = temp_parent.parent
            
            # If we're closing a table element, look for any active formatting elements
            if tag_name in TABLE_ELEMENTS:
                # Find the first non-formatting ancestor
                target_parent = self._find_ancestor(target_parent, 
                    lambda n: n.tag_name not in FORMATTING_ELEMENTS)
            
            return target_parent, current_context

        return current_parent, current_context

    def _handle_doctype(self, token: HTMLToken) -> None:
        """
        Handle DOCTYPE declarations by prepending them to the root's children.
        """
        doctype_node = Node('!doctype')
        self.root.children.insert(0, doctype_node)

    def _create_node(self, tag_name: str, attributes: dict,
                     current_parent: Node, current_context: Optional[str]) -> Node:
        """
        Create a new node, potentially using the foreign handler if present.
        """
        if self.foreign_handler:
            return self.foreign_handler.create_node(tag_name, attributes, current_parent, current_context)
        return Node(tag_name, attributes)

    def _find_ancestor(self, node: Node, tag_name_or_predicate, stop_at_boundary: bool = False) -> Optional[Node]:
        """Find the nearest ancestor matching the given tag name or predicate.
        
        Args:
            node: Starting node
            tag_name_or_predicate: Tag name or callable that takes a Node and returns bool
            stop_at_boundary: If True, stop searching at boundary elements (HTML5 scoping rules)
        """
        current = node
        while current and current != self.root:
            if callable(tag_name_or_predicate):
                if tag_name_or_predicate(current):
                    return current
            elif current.tag_name == tag_name_or_predicate:
                return current
            if stop_at_boundary and current.tag_name in BOUNDARY_ELEMENTS:
                return None
            current = current.parent
        return None
