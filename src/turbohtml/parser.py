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
            return f"<{self.type} token: {self.data[:20]}...>"
        return f"<{self.type} token: {self.tag_name or self.data}>"


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

class TextHandler:
    """
    Groups the methods that specifically handle text- and rawtext-related logic.
    This helps keep the parser code more modular.
    """
    def __init__(self, parser: "TurboHTML"):
        self.parser = parser

    def handle_rawtext_mode(
        self,
        token: Optional[HTMLToken],
        current_parent: Node,
        rawtext_start: int,
        start_idx: int,
        end_tag_idx: int
    ) -> Tuple[Node, bool, int]:
        """
        Handle parsing while in rawtext mode, which continues until we see
        a matching closing tag or reach EOF.
        """
        # If EOF or closing tag matches the current parent
        if token is None or (
            token.type == 'EndTag' and
            token.tag_name.lower() == current_parent.tag_name.lower()
        ):
            text = self.parser.html[rawtext_start : (start_idx if token else None)]
            if text:
                self.handle_rawtext_content(text, current_parent)
            return (current_parent.parent, False, end_tag_idx)
        return (current_parent, True, end_tag_idx)

    def handle_rawtext_content(self, text: str, current_parent: Node) -> None:
        """
        Handle rawtext content for <script>, <style>, <textarea>, <pre>, etc.
        """
        if text:
            # Remove first newline for textarea/pre if this is the first child
            if (current_parent.tag_name.lower() in ('textarea', 'pre')
                and not current_parent.children
                and text.startswith('\n')):
                text = text[1:]
            if text:
                self._append_text_node(current_parent, text)

    def handle_text_between_tags(self, text: str, current_parent: Node) -> None:
        """
        Handle text nodes between tags, with special handling for <pre> and rawtext elements.
        """
        # Check if text needs foster parenting
        if self.parser._has_element_in_scope('#text', current_parent):
            foster_parent = self.parser._find_ancestor(current_parent, 'p')
            if foster_parent:
                if text.strip():  # Only foster parent non-whitespace text
                    self.handle_text_between_tags(text, foster_parent)
                return

        # <pre> requires entity decoding and preserving line breaks
        if current_parent.tag_name.lower() == 'pre':
            decoded_text = self._decode_html_entities(text)
            # Append to existing text node if present
            if (current_parent.children and
                current_parent.children[-1].tag_name == '#text'):
                current_parent.children[-1].text_content += decoded_text
            else:
                # Remove a leading newline if this is the first text node
                if not current_parent.children and decoded_text.startswith('\n'):
                    decoded_text = decoded_text[1:]
                if decoded_text:
                    self._append_text_node(current_parent, decoded_text)
            return

        # If it's a rawtext element (script/style/etc.), only add if there's actual content
        if current_parent.tag_name.lower() in RAWTEXT_ELEMENTS:
            if text.strip():
                self._append_text_node(current_parent, text)
            return

        # Foreign content (MathML/SVG)
        if (self.parser.foreign_handler and
            current_parent.tag_name == 'math annotation-xml'):
            node = self.parser.foreign_handler.handle_text(text, current_parent)
            if node:
                current_parent.append_child(node)
            return

        # Default text handling
        if text:
            self._append_text_node(current_parent, text)

    def _append_text_node(self, parent: Node, text: str) -> None:
        """
        Central place to create and attach a text node to a parent.
        """
        # If the last child is a text node, concatenate with it
        if parent.children and parent.children[-1].tag_name == '#text':
            parent.children[-1].text_content += text
            return

        # Otherwise create a new text node
        text_node = Node('#text')
        text_node.text_content = text
        parent.append_child(text_node)

    def _decode_html_entities(self, text: str) -> str:
        """
        Decode numeric HTML entities: both hex (&#x0a;) and decimal (&#10;).
        """
        text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r'&#([0-9]+);', lambda m: chr(int(m.group(1))), text)
        return text

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

        # Text handler for rawtext and text-related logic
        self.text_handler = TextHandler(self)

        # Set up debug flag
        global DEBUG
        DEBUG = debug

        # Trigger parsing
        self._parse()

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"

    def query_all(self, selector: str) -> List[Node]:
        """Query all nodes matching the selector."""
        return self.root.query_all(selector)

    def query(self, selector: str) -> Optional[Node]:
        """Shortcut to query the root node."""
        return self.root.query(selector)

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
                if context.in_rawtext:
                    self.text_handler.handle_rawtext_content(
                        token.data, context.current_parent
                    )
                else:
                    self._handle_text_between_tags(token.data, context.current_parent)

        # Handle any final rawtext content
        if context.in_rawtext:
            self._cleanup_rawtext(context)

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

        # If we're in a table context or any of its descendants
        current = context.current_parent
        while current:
            if current.tag_name.lower() == 'table':
                tbody = self._ensure_tbody(current)
                tbody.append_child(comment_node)
                return
            current = current.parent

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
        elif token.type == 'Character':
            self._handle_text_between_tags(token.data, context.current_parent)

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
        debug(f"_handle_start_tag: {tag_name_lower}, current_parent={context.current_parent}")
        
        # Ensure we always have a valid current_parent
        if not context.current_parent:
            context.current_parent = self.body_node

        # If we're in rawtext mode, treat everything as text
        if context.in_rawtext:
            self._handle_tag_in_rawtext(token, tag_name_lower, context, end_tag_idx)
            return

        # Switch to body mode for non-head elements
        if (context.state == ParserState.INITIAL and 
            tag_name_lower not in HEAD_ELEMENTS):
            debug(f"\tSwitching to body mode due to {tag_name_lower}")
            context.state = ParserState.IN_BODY
            context.current_parent = self.body_node

        # Handle list items
        if tag_name_lower == 'li':
            debug(f"\tProcessing list item, current parent: {context.current_parent}")
            # Find closest list container or li
            current = context.current_parent
            list_parent = None
            while current:
                if current.tag_name.lower() in ('ul', 'ol'):
                    list_parent = current
                    break
                if current.tag_name.lower() == 'li':
                    # Close current li if we find another li
                    debug(f"\tFound existing li, closing it: {current}")
                    context.current_parent = current.parent
                    break
                current = current.parent

            # Create and append the new li
            target_parent = list_parent or context.current_parent
            debug(f"\tAppending li to {target_parent}")
            new_node = self._create_node(tag_name_lower, token.attributes, target_parent, context.current_context)
            target_parent.append_child(new_node)
            context.current_parent = new_node
            debug(f"\tUpdated current_parent to {new_node}")
            return

        # Handle <form> limitation
        if tag_name_lower == 'form':
            if context.has_form:
                context.index = end_tag_idx
                return
            context.has_form = True

        # Check if this tag should trigger rawtext mode
        if tag_name_lower in RAWTEXT_ELEMENTS:
            new_parent, new_context = self._handle_rawtext_elements(
                tag_name_lower, token.attributes, context.current_parent, context.current_context
            )
            context.current_parent = new_parent or context.current_parent
            if new_context == ParserState.RAWTEXT.value:
                context.in_rawtext = True
                context.rawtext_start = end_tag_idx
                context.index = end_tag_idx
                return

        # Handle auto-closing tags
        if tag_name_lower in AUTO_CLOSING_TAGS:
            self._handle_auto_closing(tag_name_lower, context)
            if not context.current_parent:
                context.current_parent = self.body_node

        # Handle foster parenting for elements inside table
        if (context.current_parent and 
            context.current_parent.tag_name.lower() == 'table'):
            
            if tag_name_lower in TABLE_ELEMENTS:
                # Handle table structure elements properly
                if tag_name_lower in ('th', 'td'):
                    table = context.current_parent
                    tbody = self._ensure_tbody(table)
                    tr = self._ensure_tr(tbody)
                    new_node = self._create_node(tag_name_lower, token.attributes, tr, context.current_context)
                    tr.append_child(new_node)
                    context.current_parent = new_node
                    context.state = ParserState.IN_CELL
                    return
            else:
                # Foster parent non-table elements
                foster_parent = context.current_parent.parent
                if foster_parent:
                    table_index = foster_parent.children.index(context.current_parent)
                    new_node = self._create_node(tag_name_lower, token.attributes, foster_parent, context.current_context)
                    foster_parent.children.insert(table_index, new_node)
                    
                    # Store the table for later use
                    table = context.current_parent
                    
                    # Set current parent to new node temporarily
                    context.current_parent = new_node
                    
                    # Process any children
                    # ... process children ...
                    
                    # Restore table context
                    context.current_parent = table
                    
                    return

        # Handle table structure
        if tag_name_lower in TABLE_ELEMENTS:
            if self._handle_table_element(token, tag_name_lower, context, end_tag_idx):
                return

        # Create and append the new node
        new_node = self._create_node(tag_name_lower, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        debug(f"Created and appended {tag_name_lower} to {context.current_parent}")
        
        # Update current_parent for non-void elements
        if tag_name_lower not in VOID_ELEMENTS:
            context.current_parent = new_node
            debug(f"Updated current_parent to {new_node}")

    def _handle_tag_in_rawtext(self, token: HTMLToken, tag_name_lower: str, context: ParseContext, end_tag_idx: int) -> None:
        """Handle tags when in rawtext mode."""
        text = f"<{tag_name_lower}"
        if token.attributes:
            for name, value in token.attributes.items():
                text += f' {name}="{value}"'
        if token.is_self_closing:
            text += "/"
        text += ">"
        self.text_handler.handle_rawtext_content(text, context.current_parent)
        context.index = end_tag_idx

    def _handle_auto_closing(self, tag_name_lower: str, context: ParseContext) -> None:
        """Handle auto-closing tag logic."""
        current = context.current_parent
        while current and current != self.body_node:
            current_tag = current.tag_name.lower()
            if current_tag in AUTO_CLOSING_TAGS.get(tag_name_lower, set()):
                context.current_parent = current.parent
                break
            current = current.parent

    def _handle_table_element(self, token: HTMLToken, tag_name_lower: str, context: ParseContext, end_tag_idx: int) -> bool:
        """Handle table-related elements. Returns True if handled."""
        if tag_name_lower == 'table':
            new_node = self._create_node(tag_name_lower, token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            context.state = ParserState.IN_TABLE
            context.index = end_tag_idx
            return True
        elif tag_name_lower in ('td', 'th'):
            table = self._find_ancestor(context.current_parent, 'table')
            if table:
                tbody = self._ensure_tbody(table)
                tr = self._ensure_tr(tbody)
                new_node = self._create_node(tag_name_lower, token.attributes, tr, context.current_context)
                tr.append_child(new_node)
                context.current_parent = new_node
                context.state = ParserState.IN_CELL
                context.index = end_tag_idx
                return True
        elif tag_name_lower == 'tr':
            table = self._find_ancestor(context.current_parent, 'table')
            if table:
                tbody = self._ensure_tbody(table)
                new_node = self._create_node(tag_name_lower, token.attributes, tbody, context.current_context)
                tbody.append_child(new_node)
                context.current_parent = new_node
                context.state = ParserState.IN_ROW
                context.index = end_tag_idx
                return True
        return False

    def _handle_end_tag(self, token: HTMLToken, tag_name_lower: str, context: ParseContext) -> None:
        """Handle closing tags."""
        debug(f"_handle_end_tag: {tag_name_lower}, current_parent={context.current_parent}")
        
        if not context.current_parent:
            context.current_parent = self.body_node

        if context.in_rawtext:
            if tag_name_lower == context.current_parent.tag_name.lower():
                context.in_rawtext = False
                context.current_parent = context.current_parent.parent or self.body_node
                debug(f"Exiting rawtext mode, new parent={context.current_parent}")
            return

        # Special handling for </p>
        if tag_name_lower == 'p':
            debug(f"\tHandling </p> tag")
            debug(f"\tCurrent state: {context.state}")
            if context.state == ParserState.IN_BODY:
                debug(f"\tCreating new p tag in body")
                new_p = self._create_node('p', {}, context.current_parent, context.current_context)
                context.current_parent.append_child(new_p)
                context.current_parent = new_p
                return
            else:
                debug(f"\tNot creating new p, state={context.state}")

        # Handle table-specific closing tags
        if tag_name_lower == 'table':
            debug(f"\tHandling </table> tag")
            self._handle_table_end(context)
        else:
            if tag_name_lower in ('thead', 'tbody', 'tfoot'):
                self.state = ParserState.IN_TABLE_BODY
            elif tag_name_lower == 'tr':
                self.state = ParserState.IN_ROW

        new_parent, new_context = self._handle_closing_tag(
            tag_name_lower,
            context.current_parent,
            context.current_context
        )
        debug(f"\tAfter closing {tag_name_lower}: new_parent={new_parent}, new_context={new_context}")
        
        context.current_parent = new_parent or self.body_node
        context.current_context = new_context

    def _handle_table_end(self, context: ParseContext) -> None:
        """Handle table end tag special cases."""
        table = context.current_parent
        while table and table.tag_name.lower() != 'table':
            table = table.parent
        
        if table and table.parent:
            formatting_parent = table.parent
            while formatting_parent and formatting_parent != self.body_node:
                if formatting_parent.tag_name.lower() in FORMATTING_ELEMENTS:
                    context.current_parent = formatting_parent
                    break
                formatting_parent = formatting_parent.parent
            if formatting_parent == self.body_node:
                context.current_parent = table.parent

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

        # Special case: </p> inside button
        if result := self._handle_p_in_button(tag_name_lower, current_parent, current_context):
            return result

        # Special handling for </p>
        if tag_name_lower == 'p':
            # If we're in a block element, create an implicit <p>
            block_ancestor = None
            temp = current_parent
            while temp:
                if temp.tag_name.lower() in BLOCK_ELEMENTS:
                    block_ancestor = temp
                    break
                temp = temp.parent
                
            if block_ancestor:
                # Create implicit <p>
                new_p = Node('p')
                block_ancestor.append_child(new_p)
                return new_p, current_context

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

    def _handle_p_in_button(self, tag_name: str, current_parent: Node,
                           current_context: Optional[str]) -> Optional[Tuple[Node, Optional[str]]]:
        """Handle the special case of </p> inside a button."""
        if tag_name != 'p':
            return None

        if p_ancestor := self._find_ancestor(current_parent, 'p'):
            if current_parent.tag_name.lower() == 'button':
                new_p = Node('p')
                current_parent.append_child(new_p)
                return new_p, current_context
            return p_ancestor.parent, current_context
        return None

    def _handle_rawtext_elements(self, tag_name: str, attributes: dict, current_parent: Node,
                                 current_context: Optional[str]) -> Tuple[Optional[Node], Optional[str]]:
        """
        Handle <script>, <style>, <title> and other rawtext elements.
        """
        tag_name = tag_name.lower()
        is_dual_context = current_context in ('svg', 'mathml')
        is_dual_element = tag_name in DUAL_NAMESPACE_ELEMENTS

        if tag_name in RAWTEXT_ELEMENTS:
            # Always try to place RAWTEXT elements in head if we're not explicitly in body
            if (tag_name in HEAD_ELEMENTS and 
                self.state != ParserState.IN_BODY and 
                not (is_dual_context and is_dual_element)):
                new_node = self._create_node(tag_name, attributes, self.head_node, current_context)
                self.head_node.append_child(new_node)
                return new_node, ParserState.RAWTEXT.value

            # Otherwise create in current location
            new_node = self._create_node(tag_name, attributes, current_parent, current_context)
            current_parent.append_child(new_node)
            return new_node, ParserState.RAWTEXT.value
        return None, None

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

    def _ensure_tbody(self, table: Node) -> Node:
        """Ensure table has a tbody, create if needed"""
        for child in table.children:
            if child.tag_name.lower() == 'tbody':
                return child
        tbody = Node('tbody')
        table.append_child(tbody)
        return tbody

    def _ensure_tr(self, tbody: Node) -> Node:
        """Ensure tbody has a tr, create if needed"""
        if not tbody.children or tbody.children[-1].tag_name.lower() != 'tr':
            tr = Node('tr')
            tbody.append_child(tr)
            return tr
        return tbody.children[-1]

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

    def _cleanup_rawtext(self, context: ParseContext) -> None:
        """
        Handle any remaining rawtext content at the end of parsing.
        Treats unclosed RAWTEXT elements as if they were closed at EOF.
        """
        if context.in_rawtext and context.current_parent:
            # Reset rawtext state
            context.in_rawtext = False
            # Move back to parent node
            context.current_parent = context.current_parent.parent

    def _handle_text_between_tags(self, text: str, current_parent: Node) -> None:
        """Handle text nodes between tags, with special handling for tables."""
        if not current_parent:
            return

        # Check if we need foster parenting (text directly under table)
        if current_parent.tag_name.lower() == 'table':
            # Look for the most recent non-table element
            foster_parent = None
            table = current_parent
            
            if table.parent:
                # First try to find the last non-table element before the table
                table_index = table.parent.children.index(table)
                for sibling in reversed(table.parent.children[:table_index]):
                    if sibling.tag_name.lower() not in TABLE_ELEMENTS:
                        if sibling.tag_name == '#text':
                            # If it's a text node, append to its content
                            sibling.text_content += text
                            return
                        foster_parent = sibling
                        break
                
                # If no suitable sibling found, use the parent
                if not foster_parent:
                    foster_parent = table.parent

            if foster_parent:
                # Create new text node
                text_node = Node('#text')
                text_node.text_content = text
                foster_parent.append_child(text_node)
            return

        # Normal text handling for non-table elements
        self.text_handler.handle_text_between_tags(text, current_parent)
