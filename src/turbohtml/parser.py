# fast_html.py
#
# Minimal HTML parser built from scratch:
# - Partially HTML5-compliant tokenizer
# - Lightweight DOM (Node)
# - Basic CSS-like query methods: tag, #id, .class

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
    FORMATTING_ELEMENTS
)

if TYPE_CHECKING:
    from .node import Node

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
        self.state = ParserState.INITIAL

    def at_end(self) -> bool:
        """Check if we've reached or passed the end of the HTML text."""
        return self.index >= self.length

    def enter_table_mode(self, state: ParserState) -> None:
        """Update parser state for table-related elements."""
        self.state = state

    def enter_rawtext_mode(self) -> None:
        """Enter rawtext mode for script, style, etc."""
        self.in_rawtext = True
        self.rawtext_start = self.index

    def exit_rawtext_mode(self) -> None:
        """Exit rawtext mode."""
        self.in_rawtext = False
        self.rawtext_start = 0


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
            comment_text = " "

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
        if self.parser._needs_foster_parenting('#text', current_parent):
            foster_parent = self.parser._get_foster_parent(current_parent)
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
    def __init__(self, html: str, handle_foreign_elements: bool = True):
        """
        Args:
            html: The HTML string to parse
            handle_foreign_elements: Whether to handle SVG/MathML elements
        """
        self.html = html
        self.foreign_handler = ForeignContentHandler() if handle_foreign_elements else None
        self.has_doctype = False
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
            if token.type == 'Comment':
                self._append_comment_node(token.data, context)
            
            elif token.type == 'DOCTYPE':
                self._handle_doctype(token)
            
            elif token.type in ('StartTag', 'EndTag'):
                self._handle_regular_tag(token, context, tokenizer.pos)
            
            elif token.type == 'Character':
                if context.in_rawtext:
                    self.text_handler.handle_rawtext_content(
                        token.data, context.current_parent
                    )
                else:
                    self.text_handler.handle_text_between_tags(
                        token.data, context.current_parent
                    )

        # Handle any final rawtext content
        if context.in_rawtext:
            self._cleanup_rawtext(context)

    def _process_comment(self, context: ParseContext) -> bool:
        """Check if the next token is a comment. If so, handle it."""
        match = COMMENT_RE.search(self.html, context.index)
        if not match or match.start() != context.index:
            return False

        # Extract comment text and handle special cases
        full_match = match.group(0)
        comment_text = match.group(1) or " "  # Default to space for malformed comments
        
        # Handle special malformed comment cases
        if full_match in ('<!-->', '<!--->'):
            comment_text = " "
            context.index += len(full_match)
        else:
            context.index = match.end()

        # Create and insert comment node
        self._append_comment_node(comment_text, context)
        return True

    def _append_comment_node(self, text: str, context: ParseContext) -> None:
        """
        Create and append a comment node with proper placement based on parser state.
        """
        comment_node = Node('#comment')
        comment_node.text_content = text

        # Determine proper parent and insertion location based on parser state
        if self.state == ParserState.INITIAL:
            # Comments before <html> go directly under root
            self.root.children.insert(0, comment_node)
        elif self.state == ParserState.AFTER_HEAD:
            # Comments between </head> and <body> go after head
            head_index = self.html_node.children.index(self.head_node)
            self.html_node.children.insert(head_index + 1, comment_node)
            comment_node.parent = self.html_node
        elif (self.state != ParserState.IN_BODY and 
              context.current_parent.tag_name != 'math annotation-xml'):
            # Special handling for certain states
            self.html_node.append_child(comment_node)
        else:
            # All other comments go under their current parent
            context.current_parent.append_child(comment_node)

    def _process_tag(self, context: ParseContext) -> bool:
        """Check if the next token is a tag. If so, handle it and update context."""
        index = context.index
        match = TAG_OPEN_RE.search(self.html, index)
        if not match:
            return False

        start_idx = match.start()

        # 1) Handle text before this tag if we're not in rawtext
        if start_idx > index and not context.in_rawtext:
            context.current_parent, new_state = self._handle_text_before_tag(
                index, start_idx, context.current_parent
            )
            if new_state:
                self.state = ParserState.IN_BODY
            context.index = start_idx

        # 2) Extract tag info
        start_tag_idx, end_tag_idx, tag_info = self._extract_tag_info(match)

        # 3) If we're in rawtext, pass control to TextHandler
        if context.in_rawtext:
            (
                context.current_parent,
                context.in_rawtext,
                new_index
            ) = self.text_handler.handle_rawtext_mode(
                tag_info,
                context.current_parent,
                context.rawtext_start,
                start_idx,
                end_tag_idx
            )
            context.index = new_index
            return True

        # 4) Check if this tag triggers rawtext mode
        if self._tag_requires_rawtext_mode(tag_info, context.current_context):
            context.current_parent, context.current_context = self._handle_opening_tag(
                tag_info,
                context.current_parent,
                context.current_context,
                context
            )
            context.in_rawtext = True
            context.rawtext_start = end_tag_idx
            context.index = end_tag_idx
            return True

        # 5) Otherwise handle doctype, closing, or a regular opening tag
        self._handle_regular_tag(tag_info, context, end_tag_idx)
        return True

    def _handle_regular_tag(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> None:
        """
        Handle doctype, closing, or opening tags (excluding rawtext entry).
        """
        tag_name_lower = token.tag_name.lower()

        # If this is </head>, move to after_head state
        if token.type == 'EndTag' and tag_name_lower == 'head':
            self.state = ParserState.AFTER_HEAD
            context.current_parent = context.html_node
            context.index = end_tag_idx
            return

        # Closing tag
        if token.type == 'EndTag':
            if context.in_rawtext:
                # For RAWTEXT elements, only look for exact matching end tag
                if tag_name_lower == context.current_parent.tag_name.lower():
                    context.in_rawtext = False
                    context.current_parent = context.current_parent.parent
                # Ignore all other end tags in rawtext mode
                context.index = end_tag_idx
                return

            # Special handling for table closing - find the nearest formatting parent
            if tag_name_lower == 'table':
                table = context.current_parent
                while table and table.tag_name.lower() != 'table':
                    table = table.parent
                
                if table and table.parent:
                    # Look for formatting elements that contain this table
                    formatting_parent = table.parent
                    while formatting_parent and formatting_parent != self.body_node:
                        if formatting_parent.tag_name.lower() in FORMATTING_ELEMENTS:
                            context.current_parent = formatting_parent
                            break
                        formatting_parent = formatting_parent.parent
                    if formatting_parent == self.body_node:
                        context.current_parent = table.parent
            else:
                # Update table state for other closing tags
                if tag_name_lower in ('thead', 'tbody', 'tfoot'):
                    self.state = ParserState.IN_TABLE_BODY
                elif tag_name_lower == 'tr':
                    self.state = ParserState.IN_ROW

                context.current_parent, context.current_context = self._handle_closing_tag(
                    tag_name_lower,
                    context.current_parent,
                    context.current_context
                )
        # DOCTYPE
        elif token.type == 'DOCTYPE':
            self._handle_doctype(token)
        else:
            # If we're in rawtext mode, treat everything as text until we see the matching end tag
            if context.in_rawtext:
                text = f"<{tag_name_lower}"
                if token.attributes:
                    for name, value in token.attributes.items():
                        text += f' {name}="{value}"'
                if token.is_self_closing:
                    text += "/"
                text += ">"
                self.text_handler.handle_rawtext_content(text, context.current_parent)
                context.index = end_tag_idx
                return

            # Handle <form> limitation (only one form)
            if tag_name_lower == 'form':
                if context.has_form:
                    context.index = end_tag_idx
                    return
                context.has_form = True

            # Check if this tag should trigger rawtext mode
            if tag_name_lower in RAWTEXT_ELEMENTS:
                context.current_parent, new_context = self._handle_rawtext_elements(
                    tag_name_lower, token.attributes, context.current_parent, context.current_context
                )
                if new_context == ParserState.RAWTEXT.value:
                    context.in_rawtext = True
                    context.rawtext_start = end_tag_idx
                    context.index = end_tag_idx
                    return

            context.current_parent, context.current_context = self._handle_opening_tag(
                token,
                context.current_parent,
                context.current_context,
                context
            )
        context.index = end_tag_idx

    def _handle_text_before_tag(self, start: int, end: int, current_parent: Node) -> Tuple[Node, Optional[str]]:
        """
        Handle any text found before a tag. If non-whitespace text appears after
        head, we switch to body mode.
        """
        text = self.html[start:end]
        new_state = None

        if text.strip() and self.state == ParserState.AFTER_HEAD:
            new_state = 'in_body'  # We'll translate this to ParserState.IN_BODY later
            if current_parent.tag_name.lower() != 'pre':
                current_parent = self.body_node

        if text:
            if self.foreign_handler and current_parent.tag_name == 'math annotation-xml':
                node = self.foreign_handler.handle_text(text, current_parent)
                if node:
                    current_parent.append_child(node)
            else:
                # Delegate to TextHandler
                self.text_handler.handle_text_between_tags(text, current_parent)

        return current_parent, new_state

    def _handle_rawtext_eof(self, context: ParseContext) -> None:
        """
        If in rawtext mode and no more tags found, handle leftover rawtext.
        """
        index = context.index
        length = context.length
        (
            context.current_parent,
            context.in_rawtext,
            new_index
        ) = self.text_handler.handle_rawtext_mode(
            None,
            context.current_parent,
            context.rawtext_start,
            index,
            length
        )
        context.index = new_index

    def _handle_remaining_text(self, context: ParseContext) -> None:
        """
        If not in rawtext, any remaining text from index to end is handled.
        """
        index = context.index
        length = context.length
        if index < length:
            text = self.html[index:]
            if text:
                self.text_handler.handle_text_between_tags(text, context.current_parent)
        context.index = length

    def _cleanup_rawtext(self, context: ParseContext) -> None:
        """
        If parsing ended while in rawtext mode, finalize leftover rawtext.
        """
        text = self.html[context.rawtext_start:]
        if text:
            self.text_handler.handle_rawtext_content(text, context.current_parent)

    def _tag_requires_rawtext_mode(self, token: HTMLToken, current_context: Optional[str]) -> bool:
        """
        Check if this tag should trigger rawtext mode.
        Renamed from '_should_enter_rawtext_mode' for clarity.
        """
        return (
            not token.type == 'EndTag'
            and token.tag_name.lower() in RAWTEXT_ELEMENTS
            and (not current_context or current_context not in ('svg', 'mathml'))
        )

    def _handle_opening_tag(self, token: HTMLToken, current_parent: Node,
                            current_context: Optional[str], context: ParseContext) -> Tuple[Node, Optional[str]]:
        """
        Handle an opening or self-closing tag, including special (html/head/body),
        rawtext, and foreign elements.
        """
        tag_name = token.tag_name.lower()
        attributes = token.attributes

        # If we're in head or initial state and encounter a non-head element
        if (self.state in (ParserState.INITIAL, ParserState.AFTER_HEAD) and 
            tag_name not in HEAD_ELEMENTS and 
            tag_name not in ('html', 'head', 'body')):
            self.state = ParserState.IN_BODY
            current_parent = self.body_node

        # Rest of the existing _handle_opening_tag logic...
        if self._needs_foster_parenting(tag_name, current_parent):
            foster_parent = self._get_foster_parent(current_parent)
            new_node = self._create_node(tag_name, attributes, foster_parent, current_context)
            foster_parent.append_child(new_node)
            if tag_name not in VOID_ELEMENTS:
                return new_node, current_context
            return foster_parent, current_context

        # Handle table structure before other special elements
        if result := self._handle_table_structure(tag_name, attributes, current_parent, current_context, context):
            return result

        # If we don't have a valid parent, use body node
        if not current_parent:
            current_parent = self.body_node

        # Handle head elements that appear before <head>
        if (tag_name in HEAD_ELEMENTS 
            and self.state == ParserState.INITIAL 
            and current_parent == self.html_node):
            self.head_node.append_child(self._create_node(tag_name, attributes, self.head_node, current_context))
            return current_parent, current_context

        # Possibly handle <html>, <head>, <body>
        if result := self._handle_special_elements(tag_name, attributes):
            if result[0]:
                return result

        # Rawtext elements
        if result := self._handle_rawtext_elements(tag_name, attributes, current_parent, current_context):
            if result[0]:
                return result

        # <option> nesting logic
        if result := self._handle_option_tag(tag_name, attributes, current_parent, current_context):
            if result[0]:
                return result

        # Possibly handle foreign context (SVG/MathML)
        if self.foreign_handler:
            current_parent, current_context = self.foreign_handler.handle_context(
                tag_name, current_parent, current_context
            )

        # Auto-closing for certain tags
        current_parent = self._handle_auto_closing(tag_name, current_parent)

        # Create and attach the new node
        new_node = self._create_node(tag_name, attributes, current_parent, current_context)
        current_parent.append_child(new_node)

        # For non-void elements, the new node becomes the current parent
        if tag_name not in VOID_ELEMENTS:
            current_parent = new_node

        return current_parent, current_context

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

    def _insert_into_head_if_appropriate(
        self,
        tag_name: str,
        attributes: dict,
        current_context: Optional[str],
        is_dual_context: bool,
        is_dual_element: bool
    ) -> Optional[Node]:
        """
        If it's a head element and we're not in body mode,
        insert it into the head node instead of the current parent.
        """
        if (tag_name in HEAD_ELEMENTS
            and self.head_node
            and self.state != ParserState.IN_BODY
            and not (is_dual_context and is_dual_element)):
            new_node = self._create_node(tag_name, attributes, self.head_node, ParserState.RAWTEXT.value)
            self.head_node.append_child(new_node)
            return new_node
        return None

    def _handle_option_tag(self, tag_name: str, attributes: dict, current_parent: Node,
                           current_context: Optional[str]) -> Tuple[Optional[Node], Optional[str]]:
        """
        Handle special nesting rules for <option> tags.
        """
        if tag_name != 'option':
            return None, None

        temp_parent = current_parent
        while temp_parent:
            if temp_parent.tag_name.lower() == 'option':
                # If there's something else inside the option
                if any(child.tag_name.lower() != 'option' for child in temp_parent.children):
                    new_node = self._create_node(tag_name, attributes, current_parent, current_context)
                    current_parent.append_child(new_node)
                    return new_node, current_context
                # Otherwise place it as a sibling
                new_node = self._create_node(tag_name, attributes, temp_parent.parent, current_context)
                temp_parent.parent.append_child(new_node)
                return new_node, current_context
            temp_parent = temp_parent.parent
        return None, None

    def _handle_special_elements(self, tag_name: str, attributes: dict) -> Tuple[Optional[Node], Optional[str]]:
        """
        Handle <html>, <head>, <body> if encountered again in the markup.
        """
        if tag_name == 'html':
            self.html_node.attributes.update(attributes)
            return self.html_node, None
        if tag_name == 'body':
            self.body_node.attributes.update(attributes)
            return self.body_node, None
        if tag_name == 'head':
            return self.head_node, None
        return None, None

    def _create_node(self, tag_name: str, attributes: dict,
                     current_parent: Node, current_context: Optional[str]) -> Node:
        """
        Create a new node, potentially using the foreign handler if present.
        """
        if self.foreign_handler:
            return self.foreign_handler.create_node(tag_name, attributes, current_parent, current_context)
        return Node(tag_name.lower(), attributes)

    def _handle_auto_closing(self, tag_name: str, current_parent: Node) -> Node:
        """
        Handle auto-closing rules for elements that can't be nested.
        """
        tag_name_lower = tag_name.lower()

        # Close previous sibling if it's the same or another header
        if tag_name_lower in SIBLING_ELEMENTS:
            temp_parent = current_parent
            while temp_parent:
                parent_tag = temp_parent.tag_name.lower()
                if parent_tag in SIBLING_ELEMENTS:
                    # For headers, any header should close any other header
                    if ((tag_name_lower in HEADER_ELEMENTS and 
                         parent_tag in HEADER_ELEMENTS) or
                        tag_name_lower == parent_tag):
                        return temp_parent.parent
                temp_parent = temp_parent.parent

        # Block elements close paragraphs
        if tag_name_lower in BLOCK_ELEMENTS:
            button_ancestor = self._find_ancestor(current_parent, 'button')
            if not button_ancestor:
                if p_ancestor := self._find_ancestor(current_parent, 'p'):
                    return p_ancestor.parent

        return current_parent

    def _extract_tag_info(self, match) -> Tuple[int, int, HTMLToken]:
        """
        Extract tag information from a regex match, returning start idx, end idx, and a TagInfo object.
        """
        is_exclamation = (match.group(1) == '!')
        is_closing = (match.group(2) == '/')
        tag_name = match.group(3)
        attr_string = match.group(4).strip()

        tag_info = HTMLToken(
            type_='StartTag',
            tag_name=tag_name,
            attributes=self._parse_attributes(attr_string)
        )
        # Check for DOCTYPE
        tag_info.is_self_closing = attr_string.rstrip().endswith('/')

        return match.start(), match.end(), tag_info

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """
        Parse attributes from a string using the ATTR_RE pattern.
        """
        attr_string = attr_string.strip().rstrip('/')
        matches = ATTR_RE.findall(attr_string)
        attributes = {}
        for attr_name, val1, val2, val3 in matches:
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name] = attr_value
        return attributes

    def _handle_doctype(self, token: HTMLToken) -> None:
        """
        Handle DOCTYPE declarations by prepending them to the root's children.
        """
        self.has_doctype = True
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

    def _handle_table_structure(self, tag_name: str, attributes: dict, 
                              current_parent: Node, current_context: Optional[str],
                              context: ParseContext) -> Optional[Tuple[Node, Optional[str]]]:
        """Handle table structure elements according to HTML5 spec"""
        tag_name = tag_name.lower()
        
        if not current_parent:
            current_parent = self.body_node

        # Handle td/th first as they're most common
        if tag_name in ('td', 'th'):
            table_parent = self._find_ancestor(current_parent, 'table')
            if table_parent:
                tbody = self._ensure_tbody(table_parent)
                tr = self._ensure_tr(tbody)
                new_node = self._create_node(tag_name, attributes, tr, current_context)
                tr.append_child(new_node)
                context.enter_table_mode(ParserState.IN_CELL)
                return new_node, current_context
            table = Node('table')
            current_parent.append_child(table)
            tbody = self._ensure_tbody(table)
            tr = self._ensure_tr(tbody)
            new_node = self._create_node(tag_name, attributes, tr, current_context)
            tr.append_child(new_node)
            context.enter_table_mode(ParserState.IN_CELL)
            return new_node, current_context

        # Handle tr
        if tag_name == 'tr':
            section_parent = self._find_nearest_table_section(current_parent)
            if section_parent:
                new_node = self._create_node(tag_name, attributes, section_parent, current_context)
                section_parent.append_child(new_node)
                context.enter_table_mode(ParserState.IN_ROW)
                return new_node, current_context
            return None

        # Handle thead/tbody/tfoot
        if tag_name in ('thead', 'tbody', 'tfoot'):
            table = self._find_ancestor(current_parent, 'table')
            if table:
                new_node = self._create_node(tag_name, attributes, table, current_context)
                table.append_child(new_node)
                context.enter_table_mode(ParserState.IN_TABLE_BODY)
                return new_node, current_context
            return None

        # Handle table
        if tag_name == 'table':
            new_node = self._create_node(tag_name, attributes, current_parent, current_context)
            current_parent.append_child(new_node)
            context.enter_table_mode(ParserState.IN_TABLE)
            return new_node, current_context

        # Handle caption
        if tag_name == 'caption':
            table = self._find_ancestor(current_parent, 'table')
            if table:
                new_node = self._create_node(tag_name, attributes, table, current_context)
                if not table.children or table.children[0].tag_name != 'caption':
                    table.children.insert(0, new_node)
                else:
                    table.append_child(new_node)
                return new_node, current_context
            return None

        # Handle colgroup and col
        if tag_name in ('colgroup', 'col'):
            table = self._find_ancestor(current_parent, 'table')
            if table:
                if tag_name == 'col':
                    # Always ensure colgroup exists
                    colgroup = self._ensure_colgroup(table)
                    new_node = self._create_node(tag_name, attributes, colgroup, current_context)
                    colgroup.append_child(new_node)
                    return current_parent, current_context
                else:
                    # Direct colgroup handling
                    new_node = self._create_node(tag_name, attributes, table, current_context)
                    # Insert after caption if it exists, otherwise at start
                    if table.children and table.children[0].tag_name == 'caption':
                        table.children.insert(1, new_node)
                    else:
                        table.children.insert(0, new_node)
                    return new_node, current_context
            return None

        return None

    def _ensure_colgroup(self, table: Node) -> Node:
        """Ensure table has a colgroup, create if needed"""
        for child in table.children:
            if child.tag_name == 'colgroup':
                return child
        colgroup = Node('colgroup')
        # Insert after caption if it exists
        if table.children and table.children[0].tag_name == 'caption':
            table.children.insert(1, colgroup)
        else:
            table.children.insert(0, colgroup)
        return colgroup

    def _find_nearest_table_section(self, node: Node) -> Optional[Node]:
        """Find nearest thead/tbody/tfoot ancestor, or create tbody if in table"""
        while node:
            if node.tag_name in ('thead', 'tbody', 'tfoot'):
                return node
            if node.tag_name == 'table':
                return self._ensure_tbody(node)
            node = node.parent
        return None

    def _is_in_table_row(self, node: Node) -> bool:
        """Check if we're inside a table row context"""
        while node:
            if node.tag_name.lower() == 'tr':
                return True
            if node.tag_name.lower() in ('table', 'thead', 'tbody', 'tfoot'):
                return False
            node = node.parent
        return False

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

    def _needs_foster_parenting(self, tag_name: str, current_parent: Node) -> bool:
        """
        Determine if an element needs foster parenting based on HTML5 rules.
        """
        # Don't foster parent table elements themselves
        if tag_name in TABLE_ELEMENTS:
            return False

        # Check if we're in a table context where foster parenting applies
        parent = current_parent
        while parent:
            if parent.tag_name.lower() == 'table':
                # We're in a table context where non-table elements need foster parenting
                return True
            if parent.tag_name in ('td', 'th'):
                # We're in a table cell - no foster parenting needed
                return False
            parent = parent.parent
        return False

    def _get_foster_parent(self, current_parent: Node) -> Node:
        """
        Find the appropriate foster parent for an element that can't be in a table.
        Returns the parent node where the fostered element should be placed.
        """
        # Find the table ancestor
        table = None
        node = current_parent
        while node:
            if node.tag_name == 'table':
                table = node
                break
            node = node.parent

        if not table or not table.parent:
            return self.body_node

        # Place fostered elements before the table
        return table.parent

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
