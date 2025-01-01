import re
from enum import Enum, auto
from typing import Optional, Tuple, List

from .foreign import ForeignContentHandler
from .node import Node
from .tokenizer import HTMLToken, HTMLTokenizer
from .constants import (
    VOID_ELEMENTS, BLOCK_ELEMENTS, RAWTEXT_ELEMENTS, 
    HEAD_ELEMENTS, TABLE_ELEMENTS, BOUNDARY_ELEMENTS,
    FORMATTING_ELEMENTS, AUTO_CLOSING_TAGS, HEADING_ELEMENTS,
    CLOSE_ON_PARENT_CLOSE, ADOPTION_FORMATTING_ELEMENTS
)

DEBUG = False

def debug(*args, indent=4, **kwargs) -> None:
    if DEBUG:
        if indent:
            print(f"{' ' * indent}{args[0]}", *args[1:], **kwargs)
        else:
            print(*args, **kwargs)

class ParserState(Enum):
    """
    Enumerates parser states for clarity and safety.
    """
    INITIAL = auto()
    IN_HEAD = auto()
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
        self.current_table = None
        self.active_block = None  # Initialize active_block

    @property
    def state(self) -> ParserState:
        return self._state

    @state.setter
    def state(self, new_state: ParserState) -> None:
        if new_state != self._state:
            debug(f"State change: {self._state} -> {new_state}")
            self._state = new_state

    def __repr__(self):
        parent_name = self.current_parent.tag_name if self.current_parent else "None"
        return f"<ParseContext: state={self.state.name}, parent={parent_name}>"

class TagHandler:
    """Base class for tag-specific handling logic"""
    def __init__(self, parser: 'TurboHTML'):
        self.parser = parser

    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        """Return True if this handler should handle the given start tag"""
        return False

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        return False

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        """Return True if this handler should handle the given end tag"""
        return False

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        return False

    def should_handle_text(self, text: str, context: ParseContext) -> bool:
        """Return True if this handler should handle the given text"""
        return False

    def handle_text(self, text: str, context: ParseContext) -> bool:
        return False

class TextHandler(TagHandler):
    """Handles all regular text content"""
    def should_handle_text(self, text: str, context: ParseContext) -> bool:
        """Return True if this handler should handle the given text"""
        return True

    def handle_text(self, text: str, context: ParseContext) -> bool:
        debug(f"TextHandler: handling text '{text}' in state {context.state}")
        debug(f"TextHandler: current parent is {context.current_parent}")
        
        # Skip text nodes in head unless they're only whitespace, but not in RAWTEXT mode
        if (not text.strip() and 
            self._is_in_head(context.current_parent) and
            context.state != ParserState.RAWTEXT):
            debug("TextHandler: skipping whitespace in head")
            return True

        # Try to merge with previous text node if possible
        last_child = context.current_parent.children[-1] if context.current_parent.children else None
        debug(f"TextHandler: last child is {last_child}")
        
        if last_child and last_child.tag_name == '#text':
            debug(f"TextHandler: merging with previous text node '{last_child.text_content}'")
            last_child.text_content += text
            debug(f"TextHandler: merged result '{last_child.text_content}'")
        else:
            # Create new text node
            debug("TextHandler: creating new text node")
            text_node = Node('#text')
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            debug(f"TextHandler: created node with content '{text}'")
        return True
    
    def _is_in_head(self, node: Node) -> bool:
        """Check if node is inside the head element"""
        seen = set()  # Track nodes we've seen to detect cycles
        current = node
        while current and current not in seen:
            seen.add(current)
            if current.tag_name == 'head':
                return True
            current = current.parent
        return False

    def _handle_normal_text(self, text: str, context: ParseContext) -> bool:
        """Handle normal text content"""
        # If last child is a text node, append to it
        if (context.current_parent.children and 
            context.current_parent.children[-1].tag_name == '#text'):
            context.current_parent.children[-1].text_content += text
            return True

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
            return True

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

class FormattingElementHandler(TagHandler):
    """Handles formatting elements like <b>, <i>, etc."""
    
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in ADOPTION_FORMATTING_ELEMENTS

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        # Create new formatting element
        new_element = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_element)
        context.current_parent = new_element
        return True

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in ADOPTION_FORMATTING_ELEMENTS

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"FormattingElementHandler: handling {token}, context={context}")
        
        # Check if we're inside an active block from adoption agency
        if context.current_parent and context.current_parent.tag_name == 'div':
            # If we're inside a block, stay there
            debug(f"Inside block {context.current_parent}, staying in block")
            return True
            
        # Normal formatting element handling
        current = self.parser._find_ancestor(context.current_parent, token.tag_name)
        if current and current.parent:
            context.current_parent = current.parent
            return True
        return False

class SelectTagHandler(TagHandler):
    """Handles select, option, optgroup and hr elements"""
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        # Handle these tags directly
        if tag_name in ('select', 'option', 'optgroup'):
            return True
            
        # Also handle hr if we're inside a select
        if tag_name == 'hr' and self.parser._find_ancestor(context.current_parent, 'select'):
            return True
            
        return False

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name
        
        if tag_name == 'hr':
            # Move back to select level
            select = self.parser._find_ancestor(context.current_parent, 'select')
            if select:
                new_node = self.parser._create_node(tag_name, token.attributes, select, context.current_context)
                select.append_child(new_node)
                return True
            return False
            
        # If we're in an option and get a new option/optgroup, close the current option first
        if tag_name in ('option', 'optgroup') and context.current_parent.tag_name == 'option':
            context.current_parent = context.current_parent.parent
        
        # Create the new node
        new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        
        # Only update current_parent for non-void elements
        if tag_name not in ('hr',):
            context.current_parent = new_node
        return True

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in ('select', 'option', 'optgroup')

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name
        current = self.parser._find_ancestor(context.current_parent, tag_name)
        
        if current:
            context.current_parent = current.parent or self.parser.body_node
            return True
        return False

class ParagraphTagHandler(TagHandler):
    """Handles paragraph elements"""
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name == 'p'

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"ParagraphTagHandler: handling {token}, context={context}")
        
        # First, close any open paragraphs
        current_p = self.parser._find_ancestor(context.current_parent, 'p')
        if current_p:
            debug(f"Closing existing paragraph: {current_p}")
            context.current_parent = current_p.parent or self.parser.body_node
        
        # Create new paragraph
        new_p = self.parser._create_node('p', token.attributes, 
                                       context.current_parent, context.current_context)
        debug(f"Created new paragraph node: {new_p}")
        
        # Handle formatting elements
        parent, formatting_elements = AdoptionAgencyHelper.handle_formatting_boundary(context, self.parser)
        
        if formatting_elements:
            # Reparent formatting elements inside paragraph
            current = AdoptionAgencyHelper.reparent_formatting_elements(
                new_p, formatting_elements, context, self.parser)
            
            # Add paragraph after the formatting elements
            parent.append_child(new_p)
            context.current_parent = current
        else:
            # No formatting elements, simpler case
            parent = context.current_parent or self.parser.body_node
            parent.append_child(new_p)
            context.current_parent = new_p
            
        return True

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name == 'p'

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        current = self.parser._find_ancestor(context.current_parent, 'p')
        if current:
            context.current_parent = current.parent or self.parser.body_node
            return True
        return False

class TableTagHandler(TagHandler):
    """Handles table-related elements"""

    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        # Don't handle tags if we're inside a select element
        if self.parser._find_ancestor(context.current_parent, 'select'):
            return False
            
        # Handle any tag when in table context
        if context.state == ParserState.IN_TABLE:
            debug(f"Handling {tag_name} in table context")
            return True
        
        return tag_name in ('table', 'td', 'th', 'tr', 'tbody', 'thead', 'tfoot', 'caption', 'colgroup')

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        if token.tag_name == 'table':
            # Create new table
            new_table = self.parser._create_node('table', token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_table)
            context.current_parent = new_table
            context.state = ParserState.IN_TABLE
            # Store reference to current table
            context.current_table = new_table
            return True

        # Handle elements in table context
        if context.state == ParserState.IN_TABLE:
            table = context.current_table
            if not table:
                return False

            if token.tag_name == 'template':
                # Create template node and append to current parent
                new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                return True

            if token.tag_name in ['td', 'th']:
                # First ensure we have a tbody and tr if not in template
                if context.current_parent.tag_name != 'template':
                    tbody = self._ensure_tbody(table)
                    tr = self._ensure_tr(tbody)
                    parent = tr
                else:
                    parent = context.current_parent

                # Create the cell
                new_cell = self.parser._create_node(token.tag_name, token.attributes, parent, context.current_context)
                parent.append_child(new_cell)
                context.current_parent = new_cell
                return True
            
            elif token.tag_name == 'tr':
                # If in template, append directly to it
                if context.current_parent.tag_name == 'template':
                    parent = context.current_parent
                else:
                    # Only create tbody when we have rows
                    parent = self._ensure_tbody(table)

                new_tr = self.parser._create_node('tr', token.attributes, parent, context.current_context)
                parent.append_child(new_tr)
                context.current_parent = new_tr
                return True

            # If we're inside a table cell or template, allow non-table elements
            if (self.parser._find_ancestor(context.current_parent, lambda n: n.tag_name in ['td', 'th', 'template'])):
                new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
                context.current_parent.append_child(new_node)
                if token.tag_name not in VOID_ELEMENTS:
                    context.current_parent = new_node
                return True
            
            # Foster parent non-table elements only if not in a cell or template
            elif token.tag_name not in TABLE_ELEMENTS:
                if table.parent:
                    new_node = self.parser._create_node(token.tag_name, token.attributes, table.parent, context.current_context)
                    table_index = table.parent.children.index(table)
                    table.parent.children.insert(table_index, new_node)
                    context.current_parent = new_node
                return True

        return False

    def should_handle_text(self, text: str, context: ParseContext) -> bool:
        return context.state == ParserState.IN_TABLE

    def handle_text(self, text: str, context: ParseContext) -> bool:
        if not self.should_handle_text(text, context):
            return False

        # If we're inside a table cell, append text directly
        current_cell = self.parser._find_ancestor(context.current_parent, lambda n: n.tag_name in ['td', 'th'])
        if current_cell:
            text_node = Node('#text')
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # If we're inside a foster-parented element, append text to it
        table = context.current_table
        if not table or not table.parent:
            return False

        # Check if current_parent is already foster-parented
        if context.current_parent != table:
            text_node = Node('#text')
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # Otherwise foster parent the text
        text_node = Node('#text')
        text_node.text_content = text
        
        table_index = table.parent.children.index(table)
        
        # Try to append to previous text node if possible
        if table_index > 0 and table.parent.children[table_index - 1].tag_name == '#text':
            table.parent.children[table_index - 1].text_content += text
        else:
            table.parent.children.insert(table_index, text_node)
        
        return True

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        # Handle any end tag in table context to maintain proper structure
        return context.state == ParserState.IN_TABLE

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name

        if tag_name == 'table':
            if context.current_table:
                context.current_parent = context.current_table.parent
                context.current_table = None
                context.state = ParserState.IN_BODY
                return True

        elif tag_name == 'template':
            # Find nearest template ancestor
            template = self.parser._find_ancestor(context.current_parent, 'template')
            if template and template.parent:
                context.current_parent = template.parent
                return True

        elif tag_name in TABLE_ELEMENTS:
            if tag_name == 'tr':
                tbody = self.parser._find_ancestor(context.current_parent, 'tbody')
                if tbody:
                    context.current_parent = tbody
                    return True
            elif tag_name in ['td', 'th']:
                tr = self.parser._find_ancestor(context.current_parent, 'tr')
                if tr:
                    context.current_parent = tr
                    return True

        else:
            # For non-table elements, use the parser's closing tag logic
            target_parent, current_context = self.parser._handle_closing_tag(
                tag_name, 
                context.current_parent,
                context.current_context
            )
            
            if target_parent:
                # If we're still in a table cell or template after closing the tag, stay there
                current_container = self.parser._find_ancestor(target_parent, lambda n: n.tag_name in ['td', 'th', 'template'])
                if current_container:
                    context.current_parent = target_parent
                    context.current_context = current_context
                else:
                    # If we've moved outside, ensure we stay in the table
                    context.current_parent = context.current_table
                return True

        return False

    def _ensure_tbody(self, table: Node) -> Node:
        """Ensure table has a tbody, create if needed"""
        for child in table.children:
            if child.tag_name == 'tbody':
                return child
        
        tbody = self.parser._create_node('tbody', {}, table, None)
        table.append_child(tbody)
        return tbody

    def _ensure_tr(self, tbody: Node) -> Node:
        """Ensure tbody has a tr, create if needed"""
        for child in tbody.children:
            if child.tag_name == 'tr':
                return child
        
        tr = self.parser._create_node('tr', {}, tbody, None)
        tbody.append_child(tr)
        return tr


class FormTagHandler(TagHandler):
    """Handles form-related elements (form, input, button, etc.)"""

    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
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
        return True
    
    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in ('form', 'button', 'textarea', 'select', 'label')

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        tag_name = token.tag_name

        # Find the nearest matching element
        current = self.parser._find_ancestor(context.current_parent, tag_name)

        if current:
            context.current_parent = current.parent or self.parser.body_node
            if tag_name == 'form':
                context.has_form = False

        return True

class ListTagHandler(TagHandler):
    """Handles list-related elements (ul, ol, li)"""
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in ('ul', 'ol', 'li')

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"Current parent before: {context.current_parent}")
        tag_name = token.tag_name
        
        if tag_name == 'li':
            debug(f"Handling li tag, current parent is {context.current_parent.tag_name}")

            # If we're in another li, move up to its parent first
            if context.current_parent.tag_name == 'li':
                context.current_parent = context.current_parent.parent or self.parser.body_node
            
            new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            debug(f"Created new li: {new_node}, parent: {context.current_parent}")
            return True

        # Handle ul/ol elements
        if tag_name in ('ul', 'ol'):
            debug(f"Handling {tag_name} tag")
            # Find nearest li ancestor to properly nest the list
            li_ancestor = self.parser._find_ancestor(context.current_parent, 'li')
            if li_ancestor:
                context.current_parent = li_ancestor
            
            new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            # Store the list container in the context for later reference
            context.current_list = new_node
            debug(f"Created new {tag_name}: {new_node}")
            return True

        return False

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        debug(f"Checking if should handle end tag: {tag_name}")
        return tag_name in ('ul', 'ol', 'li')
    
    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"Current parent before end: {context.current_parent}")
        
        if token.tag_name in ('ul', 'ol'):
            debug(f"Handling end tag for {token.tag_name}")
            # First try to use the current_list from context
            list_container = getattr(context, 'current_list', None)
            debug(f"Found list container from context: {list_container}")
            
            # If not found in context, search up the tree
            if not list_container:
                current = context.current_parent
                while current and current != self.parser.root:
                    debug(f"Checking ancestor: {current}")
                    if current.tag_name == token.tag_name:
                        list_container = current
                        debug(f"Found list container in ancestors: {list_container}")
                        break
                    current = current.parent
                    debug(f"Moving up to parent: {current}")
            
            if list_container:
                # First close any open li elements inside the list
                if context.current_parent.tag_name == 'li':
                    li = self.parser._find_ancestor(context.current_parent, 'li')
                    if li:
                        debug(f"Closing li inside list: {li}")
                        context.current_parent = li.parent
                
                # Move to the list container's parent
                debug(f"Moving to list container's parent: {list_container.parent}")
                context.current_parent = list_container.parent
                # Clear the current list reference
                context.current_list = None
                return True
            debug("No matching list container found")
        
        elif token.tag_name == 'li':
            debug(f"Handling end tag for li")
            # Find and close the nearest li
            li = self.parser._find_ancestor(context.current_parent, 'li')
            if li:
                debug(f"Found li to close: {li}, moving to parent: {li.parent}")
                context.current_parent = li.parent
                return True
            debug("No matching li found")
        
        debug(f"No handler for end tag {token.tag_name}")
        return False

class HeadingTagHandler(TagHandler):
    """Handles heading elements (h1-h6)"""
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        # Close any open headings first
        current = self.parser._find_ancestor(context.current_parent, 
            lambda node: node.tag_name in HEADING_ELEMENTS)
        if current:
            context.current_parent = current.parent
        
        new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        return True

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        current = self.parser._find_ancestor(context.current_parent, token.tag_name)
        if current:
            context.current_parent = current.parent or self.parser.body_node
            return True
        return False

class RawtextTagHandler(TagHandler):
    """Handles rawtext elements like script, style, title, etc."""
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in RAWTEXT_ELEMENTS

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        tag_name = token.tag_name
        
        # HEAD_ELEMENTS should always be in head unless explicitly in body
        if (tag_name in HEAD_ELEMENTS and 
            context.state != ParserState.IN_BODY):
            new_node = self.parser._create_node(tag_name, token.attributes, self.parser.head_node, context.current_context)
            self.parser.head_node.append_child(new_node)
            context.current_parent = new_node
        else:
            # Other elements stay in their current context
            new_node = self.parser._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node

        # Switch to RAWTEXT state and let tokenizer handle the content
        context.state = ParserState.RAWTEXT
        self.parser.tokenizer.start_rawtext(tag_name)
        return True

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in RAWTEXT_ELEMENTS

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        if context.state == ParserState.RAWTEXT and token.tag_name == context.current_parent.tag_name:
            # Move script/title to head if not explicitly in body
            if token.tag_name in HEAD_ELEMENTS and context.state != ParserState.IN_BODY:
                # Move the element to head if it's not already there
                if context.current_parent.parent != self.parser.head_node:
                    self.parser.head_node.append_child(context.current_parent)
                
                # Add space in head only if we have trailing whitespace
                if 'trailing_space' in token.attributes:
                    text_node = Node('#text')
                    text_node.text_content = ' '
                    self.parser.head_node.append_child(text_node)
            
            # Switch to body state
            context.state = ParserState.IN_BODY
            context.current_parent = self.parser.body_node
            return True
        return False

class ButtonTagHandler(TagHandler):
    """Handles button elements"""
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name == 'button'

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"Current parent: {context.current_parent}", indent=0)
        new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        debug(f"New current parent: {context.current_parent}")
        return True

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        # Handle all end tags when inside a button
        button = self.parser._find_ancestor(context.current_parent, 'button')
        return bool(button)

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"Current parent: {context.current_parent}")
        button = self.parser._find_ancestor(context.current_parent, 'button')
        debug(f"Found button ancestor: {button}")
        
        # Only allow closing the button itself
        if token.tag_name != 'button':
            debug(f"Inside button, ignoring end tag for {token.tag_name}")
            return True
            
        if button:
            debug("Merging text nodes in button")
            text_content = ""
            new_children = []
            for child in button.children:
                debug(f"Processing child: {child}")
                if child.tag_name == '#text':
                    text_content += child.text_content
                else:
                    new_children.append(child)
            
            if text_content:
                debug(f"Creating merged text node with content: {text_content}")
                text_node = Node('#text')
                text_node.text_content = text_content
                new_children.insert(0, text_node)
            
            button.children = new_children
            context.current_parent = button.parent or self.parser.body_node
            debug(f"New current parent: {context.current_parent}")
            return True
        return False

    def should_handle_text(self, text: str, context: ParseContext) -> bool:
        return True

    def handle_text(self, text: str, context: ParseContext) -> bool:
        debug(f"Current parent: {context.current_parent}")
        button = self.parser._find_ancestor(context.current_parent, 'button')
        debug(f"Found button ancestor: {button}")
        if button:
            if (button.children and 
                button.children[-1].tag_name == '#text'):
                debug("Appending to existing text node")
                button.children[-1].text_content += text
            else:
                debug("Creating new text node")
                text_node = Node('#text')
                text_node.text_content = text
                button.append_child(text_node)
            debug(f"Button children after text handling: {button.children}")
            return True
        debug("No button ancestor found, not handling text")
        return False

class VoidElementHandler(TagHandler):
    """Handles void elements that can't have children"""
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        # Don't handle void elements inside select
        if self.parser._find_ancestor(context.current_parent, 'select'):
            return False
            
        return tag_name in VOID_ELEMENTS

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        # If we're in a paragraph and this is a block element, close the paragraph first
        if (context.current_parent.tag_name == 'p' and 
            token.tag_name in BLOCK_ELEMENTS):
            # Move up to paragraph's parent
            context.current_parent = context.current_parent.parent or self.parser.body_node
        
        # Create the void element at the current level
        new_node = self.parser._create_node(token.tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        
        # If this is an hr, create a new paragraph after it
        if token.tag_name == 'hr':
            debug("Creating new paragraph after hr")
            new_p = self.parser._create_node('p', {}, context.current_parent, context.current_context)
            context.current_parent.append_child(new_p)
            context.current_parent = new_p
        
        return True

class AutoClosingTagHandler(TagHandler):
    """Handles auto-closing behavior for certain tags"""
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name in AUTO_CLOSING_TAGS

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        debug(f"Checking auto-closing rules for {token.tag_name}")
        current = context.current_parent
        if not current:
            current = context.current_parent = self.parser.body_node
        debug(f"Current parent: {current}")
        
        # If we're starting a block element inside a formatting element
        if (token.tag_name in BLOCK_ELEMENTS and 
            self._find_formatting_ancestor(current)):
            
            # Find all formatting elements up to the block
            formatting_elements = []
            temp = current
            while temp and temp.tag_name != 'body':
                if temp.tag_name in ADOPTION_FORMATTING_ELEMENTS:
                    formatting_elements.insert(0, temp)
                temp = temp.parent
            
            debug(f"Found formatting elements: {formatting_elements}")
            
            if not formatting_elements:
                debug("No formatting elements found")
                return False

            # Get the formatting element we're currently in
            current_fmt = formatting_elements[-1]
            debug(f"Current formatting element: {current_fmt}")
            
            # Create block inside current formatting element
            new_block = self.parser._create_node(token.tag_name, token.attributes, 
                                               current_fmt, context.current_context)
            current_fmt.append_child(new_block)
            debug(f"Created block {new_block} inside formatting element {current_fmt}")
            
            # Move to the block
            context.current_parent = new_block
            debug(f"New current parent: {context.current_parent}")
            
            return True
            
        return False

    def _find_formatting_ancestor(self, node: Node) -> Optional[Node]:
        """Find the nearest formatting element ancestor"""
        debug(f"Looking for formatting ancestor starting from {node}")
        current = node
        seen = set()  # Prevent infinite loops
        while current and current.tag_name != 'body' and current not in seen:
            seen.add(current)
            if current.tag_name in ADOPTION_FORMATTING_ELEMENTS:
                debug(f"Found formatting ancestor: {current}")
                return current
            current = current.parent
        debug("No formatting ancestor found")
        return None

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        # Handle end tags for elements that close when their parent closes
        return tag_name in CLOSE_ON_PARENT_CLOSE or tag_name in ('tr', 'td', 'th')  # Add table elements

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        debug(f"AutoClosingTagHandler.handle_end: {token.tag_name}")
        
        if token.tag_name == 'tr':
            # First find the tr element
            tr = self.parser._find_ancestor(context.current_parent, 'tr')
            if tr:
                # Close everything up to the tr
                context.current_parent = tr.parent or self.parser.body_node
                context.state = ParserState.IN_TABLE
                return True
                
        # Handle other closing tags...
        if token.tag_name in CLOSE_ON_PARENT_CLOSE:
            parent_tags = CLOSE_ON_PARENT_CLOSE[token.tag_name]
            for parent_tag in parent_tags:
                parent = self.parser._find_ancestor(context.current_parent, parent_tag)
                if parent:
                    context.current_parent = parent
                    return True
        return False

class AnchorTagHandler(TagHandler):
    """Special handling for <a> tags"""
    
    def should_handle_start(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name == 'a'

    def handle_start(self, token: HTMLToken, context: ParseContext, end_tag_idx: int) -> bool:
        # Find any existing anchor elements in the stack
        existing_anchor = self.parser._find_ancestor(context.current_parent, 'a')
        if existing_anchor:
            # Move content before the anchor to a new anchor
            if existing_anchor.children:
                # Create new anchor with same attributes
                new_anchor = Node('a', existing_anchor.attributes.copy())
                
                # Move children to new anchor
                for child in existing_anchor.children[:]:
                    new_anchor.append_child(child)
                
                # Insert new anchor before existing one
                if existing_anchor.parent:
                    existing_anchor.parent.insert_before(new_anchor, existing_anchor)
                    # Remove the empty existing anchor
                    existing_anchor.parent.children.remove(existing_anchor)
            
            # Move to parent
            if existing_anchor.parent:
                context.current_parent = existing_anchor.parent

        # Create new anchor
        new_anchor = self.parser._create_node('a', token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_anchor)
        context.current_parent = new_anchor
        return True

    def should_handle_end(self, tag_name: str, context: ParseContext) -> bool:
        return tag_name == 'a'

    def handle_end(self, token: HTMLToken, context: ParseContext) -> bool:
        current_anchor = self.parser._find_ancestor(context.current_parent, 'a')
        if not current_anchor or not current_anchor.parent:
            return False

        # Move to parent of anchor
        context.current_parent = current_anchor.parent
        return True

class AdoptionAgencyHelper:
    """Helper class for implementing the adoption agency algorithm"""
    
    @staticmethod
    def handle_formatting_boundary(context: ParseContext, parser) -> Tuple[Node, List[Node]]:
        """
        Handles a formatting boundary (when block element meets formatting elements)
        Returns (new_parent, formatting_elements)
        """
        debug("AdoptionAgencyHelper: handling formatting boundary")
        
        # Find any formatting elements we're inside of
        formatting_elements = []
        temp = context.current_parent
        while temp and temp.tag_name != 'body':
            if temp.tag_name in ADOPTION_FORMATTING_ELEMENTS:
                formatting_elements.insert(0, temp)
                debug(f"Found formatting element: {temp.tag_name} with children: {[c.tag_name for c in temp.children]}")
            temp = temp.parent
            
        debug(f"Found formatting elements: {[f.tag_name for f in formatting_elements]}")
        
        if not formatting_elements:
            return context.current_parent, []
            
        # Get the parent of the outermost formatting element
        parent = formatting_elements[0].parent or parser.body_node
        debug(f"Using parent: {parent.tag_name}")
        
        return parent, formatting_elements

    @staticmethod
    def reparent_formatting_elements(new_container: Node, formatting_elements: List[Node], 
                                   context: ParseContext, parser) -> Node:
        """
        Creates new copies of formatting elements inside a new container
        Returns the innermost new formatting element
        """
        current = new_container
        for fmt in formatting_elements:
            debug(f"Processing formatting element {fmt.tag_name}")
            # Create new formatting element
            new_fmt = parser._create_node(fmt.tag_name, fmt.attributes, 
                                        current, context.current_context)
            debug(f"Created new formatting element: {new_fmt.tag_name}")
            
            # Move children from original to new formatting element
            if fmt.children:
                debug(f"Moving children from {fmt.tag_name}: {[c.tag_name for c in fmt.children]}")
                children_to_move = fmt.children[:]  # Create a copy of the list
                
                for child in children_to_move:
                    # First detach from old parent
                    child.parent = None
                    fmt.children.remove(child)
                    
                    # Then attach to new parent
                    child.parent = new_fmt
                    new_fmt.children.append(child)
                    
                debug(f"After move - Original {fmt.tag_name} children: {[c.tag_name for c in fmt.children]}")
                debug(f"After move - New {new_fmt.tag_name} children: {[c.tag_name for c in new_fmt.children]}")
            
            current.append_child(new_fmt)
            current = new_fmt
            
        return current

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
        global DEBUG
        DEBUG = debug

        self.html = html
        self.foreign_handler = ForeignContentHandler() if handle_foreign_elements else None
        
        # Reset all state for each new parser instance
        self.state = ParserState.INITIAL
        self.root = Node('document')
        self.html_node = Node('html')
        self.head_node = Node('head')
        self.body_node = Node('body')
        
        # Ensure deterministic order of children
        self.root.children = []
        self.html_node.children = []
        self.head_node.children = []
        self.body_node.children = []
        
        self.root.append_child(self.html_node)
        self.html_node.append_child(self.head_node)
        self.html_node.append_child(self.body_node)
        
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
        ]
        
        # Trigger parsing
        self._parse()

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"

    def _parse(self) -> None:
        """
        Main parsing loop using ParseContext and HTMLTokenizer.
        """
        context = ParseContext(len(self.html), self.body_node, self.html_node)
        self.tokenizer = HTMLTokenizer(self.html)  # Store tokenizer instance

        if DEBUG:
            debug(f"TOKENS: {list(HTMLTokenizer(self.html).tokenize())}", indent=0)

        for token in self.tokenizer.tokenize():
            debug(f"_parse: {token}, context: {context}", indent=0)
            if token.type == 'Comment':
                self._handle_comment(token.data, context)
            
            # Handle DOCTYPE first since it doesn't have a tag_name
            if token.type == 'DOCTYPE':
                self._handle_doctype(token)
                context.index = self.tokenizer.pos
                continue

            if token.type == 'StartTag':
                # Handle special elements and state transitions first
                if self._handle_special_element(token, token.tag_name, context, self.tokenizer.pos):
                    context.index = self.tokenizer.pos
                    continue
                
                # Then handle the actual tag
                self._handle_start_tag(token, token.tag_name, context, self.tokenizer.pos)
                context.index = self.tokenizer.pos

            if token.type == 'EndTag':
                self._handle_end_tag(token, token.tag_name, context)
                context.index = self.tokenizer.pos
            
            elif token.type == 'Character':
                for handler in self.tag_handlers:
                    if handler.should_handle_text(token.data, context):
                        debug(f"{handler.__class__.__name__}: handling {token}, context={context}")
                        if handler.handle_text(token.data, context):
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

    def _handle_special_element(self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int) -> bool:
        """Handle html, head and body tags.
        Returns True if the tag was handled and should not be processed further."""
        if tag_name == 'html':
            # Just update attributes, don't create a new node
            self.html_node.attributes.update(token.attributes)
            context.current_parent = self.html_node
            return True
        elif tag_name == 'head':
            # Don't create duplicate head elements
            context.current_parent = self.head_node
            context.state = ParserState.IN_HEAD
            return True
        elif tag_name == 'body':
            # Don't create duplicate body elements
            self.body_node.attributes.update(token.attributes)
            context.current_parent = self.body_node
            context.state = ParserState.IN_BODY
            return True
        elif tag_name not in HEAD_ELEMENTS:
            # Handle implicit head/body transitions
            if context.state == ParserState.INITIAL:
                debug("Implicitly closing head and switching to body")
                context.state = ParserState.IN_BODY
                if context.current_parent == self.head_node:
                    context.current_parent = self.body_node
            elif context.current_parent == self.head_node:
                debug("Closing head and switching to body")
                context.state = ParserState.IN_BODY
                context.current_parent = self.body_node
        context.index = end_tag_idx
        return False

    def _handle_start_tag(self, token: HTMLToken, tag_name: str, context: ParseContext, end_tag_idx: int) -> None:
        """Handle all opening HTML tags."""
        debug(f"_handle_start_tag: {tag_name}, current_parent={context.current_parent}")
        
        if context.state == ParserState.RAWTEXT:
            debug("In rawtext mode, ignoring start tag")
            return

        # Try tag handlers first
        debug(f"Trying tag handlers for {tag_name}")
        for handler in self.tag_handlers:
            if handler.should_handle_start(tag_name, context):
                debug(f"{handler.__class__.__name__}: handling {token}, context={context}")
                if handler.handle_start(token, context, end_tag_idx):
                    return

        # Default handling for unhandled tags
        debug(f"No handler found, using default handling for {tag_name}")
        new_node = self._create_node(tag_name, token.attributes, context.current_parent, context.current_context)
        context.current_parent.append_child(new_node)
        
        if tag_name not in VOID_ELEMENTS:
            debug(f"Updating current_parent to {tag_name}")
            context.current_parent = new_node

    def _handle_end_tag(self, token: HTMLToken, tag_name: str, context: ParseContext) -> None:
        """Handle all closing HTML tags."""
        debug(f"_handle_end_tag: {tag_name}, current_parent={context.current_parent}")
        
        if not context.current_parent:
            context.current_parent = self.body_node

        # Try tag handlers first
        debug(f"Trying tag handlers for end tag {tag_name}")
        for handler in self.tag_handlers:
            if handler.should_handle_end(tag_name, context):
                debug(f"{handler.__class__.__name__}: handling {token}, context={context}")
                if handler.handle_end(token, context):
                    return

        # Default handling for unhandled tags
        debug(f"No end tag handler found, looking for matching tag {tag_name}")
        current = self._find_ancestor(context.current_parent, tag_name)
        if current:
            debug(f"Found matching tag {tag_name}, updating current_parent")
            context.current_parent = current.parent or self.body_node

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
