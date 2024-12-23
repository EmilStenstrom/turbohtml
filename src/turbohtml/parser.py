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
    TAG_OPEN_RE, ATTR_RE, COMMENT_RE, DUAL_NAMESPACE_ELEMENTS,
    SIBLING_ELEMENTS
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
        
        # Trigger the parsing
        self._parse()

    def query_all(self, selector: str) -> List[Node]:
        """Query all nodes matching the selector."""
        return self.root.query_all(selector)

    def query(self, selector: str) -> Optional[Node]:
        """Shortcut to query the root node."""
        return self.root.query(selector)

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"

    # ─────────────────────────────────────────────────────────────────────
    #           Refactored parsing below with smaller helper methods
    # ─────────────────────────────────────────────────────────────────────

    def _parse(self) -> None:
        """
        Main parsing loop, refactored for clarity.
        """
        context = self._initialize_parse_context()

        while context['index'] < context['length']:
            # 1) Process comment first
            if self._process_comment(context):
                continue

            # 2) Process tag if found
            if self._process_tag(context):
                continue

            # 3) Handle leftover text or break out
            if context['in_rawtext']:
                self._handle_rawtext_eof(context)
            else:
                self._handle_remaining_text(context)
            break

        # If we ended while still in rawtext mode, finalize any leftover rawtext
        if context['in_rawtext']:
            self._cleanup_rawtext(context)

    def _initialize_parse_context(self) -> dict:
        """
        Initialize a dictionary holding essential parser context variables.
        """
        return {
            'index': 0,
            'length': len(self.html),
            'current_parent': self.body_node,
            'current_context': None,
            'has_form': False,
            'in_rawtext': False,
            'rawtext_start': 0
        }

    def _process_comment(self, context: dict) -> bool:
        """
        Check if the next token is a comment. If so, handle it and update
        the parse context. Return True if processed, False otherwise.
        """
        index = context['index']
        match = COMMENT_RE.search(self.html, index)
        if match and match.start() == index:
            # Decide comment parent
            if (self.state == 'after_head' and 
                self.state != 'in_body' and 
                context['current_parent'].tag_name != 'math annotation-xml'):
                comment_parent = self.html_node
            else:
                comment_parent = context['current_parent']

            # Handle comment
            new_index = self._handle_comment(match, comment_parent, context['in_rawtext'])
            context['index'] = new_index
            return True
        return False

    def _process_tag(self, context: dict) -> bool:
        """
        Check if the next token is a tag. If so, handle it and update
        the parse context. Return True if processed, False otherwise.
        """
        index = context['index']
        match = TAG_OPEN_RE.search(self.html, index)
        if not match:
            return False

        start_idx = match.start()

        # 1) If there's text before this tag, handle that first
        if start_idx > index and not context['in_rawtext']:
            context['current_parent'], new_state = self._handle_text_before_tag(
                index, start_idx, context['current_parent']
            )
            if new_state:
                self.state = new_state
            context['index'] = start_idx

        # 2) Extract tag info
        start_tag_idx, end_tag_idx, tag_info = self._extract_tag_info(match)

        # 3) If currently in rawtext, handle rawtext mode
        if context['in_rawtext']:
            (context['current_parent'],
             context['in_rawtext'],
             new_index) = self._handle_rawtext_mode(
                 tag_info,
                 context['current_parent'],
                 context['rawtext_start'],
                 start_idx,
                 end_tag_idx
             )
            context['index'] = new_index
            return True

        # 4) Check if we should enter rawtext
        if self._should_enter_rawtext_mode(tag_info, context['current_context']):
            (context['current_parent'],
             context['current_context']) = self._handle_opening_tag(
                 tag_info,
                 context['current_parent'],
                 context['current_context']
             )
            context['in_rawtext'] = True
            context['rawtext_start'] = end_tag_idx
            context['index'] = end_tag_idx
            return True

        # 5) Otherwise handle doctype, closing, or opening tags
        self._process_tag_basic(tag_info, context, end_tag_idx)
        return True

    def _process_tag_basic(self, tag_info: "TagInfo", context: dict, end_tag_idx: int) -> None:
        """
        Handle doctype, closing, or opening tags (excluding rawtext entry).
        """
        tag_name_lower = tag_info.tag_name.lower()

        if tag_info.is_closing and tag_name_lower == 'head':
            self.state = 'after_head'
            context['current_parent'] = self.html_node
            context['index'] = end_tag_idx
            return

        if tag_info.is_closing:
            (context['current_parent'],
             context['current_context']) = self._handle_closing_tag(
                 tag_name_lower,
                 context['current_parent'],
                 context['current_context']
             )
        elif tag_info.is_doctype:
            self._handle_doctype(tag_info)
        else:
            # Handle <form> limitations
            if tag_name_lower == 'form':
                if context['has_form']:
                    context['index'] = end_tag_idx
                    return
                context['has_form'] = True
            (context['current_parent'],
             context['current_context']) = self._handle_opening_tag(
                 tag_info,
                 context['current_parent'],
                 context['current_context']
             )
        context['index'] = end_tag_idx

    def _handle_rawtext_eof(self, context: dict) -> None:
        """
        If in rawtext mode and we can't find more tags, handle the rawtext
        from rawtext_start to the end of the string.
        """
        index = context['index']
        length = context['length']
        (context['current_parent'],
         context['in_rawtext'],
         new_index) = self._handle_rawtext_mode(
             None,
             context['current_parent'],
             context['rawtext_start'],
             index,
             length
         )
        context['index'] = new_index

    def _handle_remaining_text(self, context: dict) -> None:
        """
        If not in rawtext, any remaining text from index to end is appended.
        """
        index = context['index']
        length = context['length']
        if index < length:
            text = self.html[index:]
            if text:
                self._handle_text_between_tags(text, context['current_parent'])
        context['index'] = length

    def _cleanup_rawtext(self, context: dict) -> None:
        """
        If parsing ended while in rawtext mode, finalize leftover rawtext.
        """
        text = self.html[context['rawtext_start']:]
        if text:
            self._handle_rawtext_content(text, context['current_parent'])

    # ─────────────────────────────────────────────────────────────────────
    #                     Original helper methods
    # ─────────────────────────────────────────────────────────────────────

    def _should_enter_rawtext_mode(self, tag_info: "TagInfo", current_context: Optional[str]) -> bool:
        """Check if we should enter rawtext mode."""
        return (not tag_info.is_closing and 
                tag_info.tag_name.lower() in RAWTEXT_ELEMENTS and 
                (not current_context or current_context not in ('svg', 'mathml')))

    def _handle_rawtext_mode(self, tag_info: Optional["TagInfo"], current_parent: Node, 
                             rawtext_start: int, start_idx: int, end_tag_idx: int
                            ) -> Tuple[Node, bool, int]:
        """
        Handle parsing while in rawtext mode.
        """
        # Handle EOF or closing tag
        if tag_info is None or (
            tag_info.is_closing and 
            tag_info.tag_name.lower() == current_parent.tag_name.lower()
        ):
            text = self.html[rawtext_start : (start_idx if tag_info else None)]
            if text:
                self._handle_rawtext_content(text, current_parent)
            return (current_parent.parent, False, end_tag_idx)
        return (current_parent, True, end_tag_idx)

    def _handle_rawtext_content(self, text: str, current_parent: Node) -> None:
        """
        Handle content in rawtext elements (e.g. <script>, <style>, <textarea>).
        """
        if text:
            if (current_parent.tag_name.lower() in ('textarea', 'pre') and 
                not current_parent.children and 
                text.startswith('\n')):
                text = text[1:]
            if text:
                text_node = Node('#text')
                text_node.text_content = text
                current_parent.append_child(text_node)

    def _handle_text_before_tag(self, start: int, end: int, current_parent: Node) -> Tuple[Node, Optional[str]]:
        """
        Handle any text found before a tag.
        """
        text = self.html[start:end]
        new_state = None
        
        # If we have non-whitespace text after head, switch to in_body
        if text.strip() and self.state == 'after_head':
            new_state = 'in_body'
            if current_parent.tag_name.lower() != 'pre':
                current_parent = self.body_node
        
        if text:
            if self.foreign_handler and current_parent.tag_name == 'math annotation-xml':
                node = self.foreign_handler.handle_text(text, current_parent)
                if node:
                    current_parent.append_child(node)
            else:
                self._handle_text_between_tags(text, current_parent)
            
        return current_parent, new_state

    def _handle_opening_tag(self, tag_info: "TagInfo", current_parent: Node, 
                            current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """
        Handle an opening or self-closing tag, including special, rawtext,
        or foreign elements.
        """
        tag_name = tag_info.tag_name.lower()
        attributes = self._parse_attributes(tag_info.attr_string)

        # Special elements (html, head, body)
        if result := self._handle_special_elements(tag_name, attributes):
            if result[0]:
                return result

        # Rawtext elements
        if result := self._handle_rawtext_elements(tag_name, attributes, current_parent, current_context):
            if result[0]:
                return result

        # Option tag
        if result := self._handle_option_tag(tag_name, attributes, current_parent, current_context):
            if result[0]:
                return result

        # Foreign handling if present
        if self.foreign_handler:
            (current_parent, current_context) = self.foreign_handler.handle_context(
                tag_name, current_parent, current_context
            )

        # Auto-closing for certain tags
        current_parent = self._handle_auto_closing(tag_name, current_parent)

        # Create the node
        new_node = self._create_node(tag_name, attributes, current_parent, current_context)
        current_parent.append_child(new_node)

        # For non-void elements, the new node becomes the current parent
        if tag_name not in VOID_ELEMENTS:
            current_parent = new_node

        return (current_parent, current_context)

    def _create_node(self, tag_name: str, attributes: dict, 
                     current_parent: Node, current_context: Optional[str]) -> Node:
        """
        Create a new node, potentially using the foreign handler if present.
        """
        if self.foreign_handler:
            return self.foreign_handler.create_node(tag_name, attributes, current_parent, current_context)
        return Node(tag_name.lower(), attributes)

    def _handle_closing_tag(self, tag_name: str, current_parent: Node, 
                            current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """
        Handle a closing tag, including special logic for <p> and foreign elements.
        """
        tag_name_lower = tag_name.lower()

        # Foreign
        if self.foreign_handler:
            current_parent, current_context = self.foreign_handler.handle_foreign_end_tag(
                tag_name, current_parent, current_context
            )

        # Special case for </p>
        if tag_name_lower == 'p':
            original_p = None
            temp_parent = current_parent
            while temp_parent:
                if temp_parent.tag_name.lower() == 'p':
                    original_p = temp_parent
                    break
                temp_parent = temp_parent.parent
            if original_p:
                # e.g. <p><button></p> or <p><table></p>
                if current_parent.tag_name.lower() == 'button':
                    new_p = Node('p')
                    current_parent.append_child(new_p)
                    return new_p, current_context
                elif current_parent.tag_name.lower() == 'table':
                    return original_p.parent, current_context
            return (original_p.parent if original_p else current_parent, current_context)

        # Normal closing tags
        temp_parent = current_parent
        while temp_parent and temp_parent.tag_name.lower() != tag_name_lower:
            temp_parent = temp_parent.parent
        
        if temp_parent:
            return temp_parent.parent, current_context
        return current_parent, current_context

    def _decode_html_entities(self, text: str) -> str:
        """
        Decode numeric HTML entities: both hex (&#x0a;) and decimal (&#10;).
        """
        text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r'&#([0-9]+);', lambda m: chr(int(m.group(1))), text)
        return text

    def _handle_text_between_tags(self, text: str, current_parent: Node) -> None:
        """
        Handle text nodes between tags, with special treatment for <pre> and rawtext elements.
        """
        if current_parent.tag_name.lower() == 'pre':
            decoded_text = self._decode_html_entities(text)
            if (current_parent.children and 
                current_parent.children[-1].tag_name == '#text'):
                current_parent.children[-1].text_content += decoded_text
            else:
                if not current_parent.children and decoded_text.startswith('\n'):
                    decoded_text = decoded_text[1:]
                if decoded_text:
                    text_node = Node('#text')
                    text_node.text_content = decoded_text
                    text_node.parent = current_parent
                    current_parent.children.append(text_node)
            return

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

        if text:
            text_node = Node('#text')
            text_node.text_content = text
            current_parent.append_child(text_node)

    def _handle_doctype(self, tag_info: "TagInfo") -> None:
        """Handle DOCTYPE declarations."""
        self.has_doctype = True
        doctype_node = Node('!doctype')
        self.root.children.insert(0, doctype_node)

    def _get_ancestors(self, node: Node) -> List[Node]:
        """Return all ancestors of a node, including the node itself."""
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
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name] = attr_value
        return attributes

    def _extract_tag_info(self, match) -> Tuple[int, int, "TagInfo"]:
        """
        Extract tag information from a regex match.
        """
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

    def _find_ancestor(self, current_parent: Node, tag_name: str) -> Optional[Node]:
        """Find the nearest ancestor with the given tag name."""
        return next(
            (p for p in self._get_ancestors(current_parent)
             if p.tag_name.lower() == tag_name.lower()),
            None
        )

    def _find_block_ancestor(self, current_parent: Node) -> Optional[Node]:
        """Find the nearest block element ancestor."""
        return next(
            (p for p in self._get_ancestors(current_parent)
             if p.tag_name.lower() in BLOCK_ELEMENTS),
            None
        )

    def _handle_auto_closing(self, tag_name: str, current_parent: Node) -> Node:
        """
        Handle auto-closing rules, e.g. some tags can't nest themselves
        or must close upon encountering certain sibling elements.
        """
        tag_name_lower = tag_name.lower()

        # Close previous sibling if same
        if tag_name_lower in SIBLING_ELEMENTS:
            if ancestor := self._find_ancestor(current_parent, tag_name_lower):
                return ancestor.parent

        # Certain elements can't nest themselves
        if tag_name_lower in ('nobr', 'button', 'option'):
            if ancestor := self._find_ancestor(current_parent, tag_name_lower):
                return ancestor.parent

        # p tags close on block elements if not inside a button
        if tag_name_lower in BLOCK_ELEMENTS:
            button_ancestor = self._find_ancestor(current_parent, 'button')
            if not button_ancestor:
                if p_ancestor := self._find_ancestor(current_parent, 'p'):
                    if tag_name_lower == 'table':
                        new_p = Node('p')
                        p_ancestor.append_child(new_p)
                        return p_ancestor
                    return p_ancestor.parent

        return current_parent

    def _handle_comment(self, match: re.Match, current_parent: Node, in_rawtext: bool) -> int:
        """
        Insert an HTML comment node into the tree.
        """
        comment_text = match.group(1)
        comment_node = Node('#comment')
        comment_node.text_content = comment_text
        
        if current_parent == self.html_node:
            # Insert comment after head but before body
            head_index = self.html_node.children.index(self.head_node)
            self.html_node.children.insert(head_index + 1, comment_node)
            comment_node.parent = self.html_node
        else:
            current_parent.append_child(comment_node)
        return match.end()

    def _handle_special_elements(self, tag_name: str, attributes: dict) -> Tuple[Optional[Node], Optional[str]]:
        """
        Handle <html>, <head>, <body> if encountered again.
        """
        if tag_name == 'html':
            self.html_node.attributes.update(attributes)
            return (self.html_node, None)
        if tag_name == 'body':
            self.body_node.attributes.update(attributes)
            return (self.body_node, None)
        if tag_name == 'head':
            return (self.head_node, None)
        return (None, None)

    def _handle_rawtext_elements(self, tag_name: str, attributes: dict, current_parent: Node,
                                 current_context: Optional[str]) -> Tuple[Optional[Node], Optional[str]]:
        """
        Handle <script>, <style>, and other rawtext elements.
        """
        is_dual_context = current_context in ('svg', 'mathml')
        is_dual_element = tag_name in DUAL_NAMESPACE_ELEMENTS

        if tag_name in RAWTEXT_ELEMENTS:
            # Possibly place in head if HEAD element, not in body mode, and not dual
            if (tag_name in HEAD_ELEMENTS and 
                self.head_node and 
                self.state != 'in_body' and 
                not (is_dual_context and is_dual_element)):
                new_node = self._create_node(tag_name, attributes, self.head_node, 'rawtext')
                self.head_node.append_child(new_node)
                return (new_node, 'rawtext')
            # Otherwise treat as normal rawtext
            new_node = self._create_node(tag_name, attributes, current_parent, current_context)
            current_parent.append_child(new_node)
            return (new_node, current_context if is_dual_context else 'rawtext')
        return (None, None)

    def _handle_option_tag(self, tag_name: str, attributes: dict, current_parent: Node,
                           current_context: Optional[str]) -> Tuple[Optional[Node], Optional[str]]:
        """
        Handle special nesting rules for <option> tags.
        """
        if tag_name != 'option':
            return (None, None)

        temp_parent = current_parent
        while temp_parent:
            if temp_parent.tag_name.lower() == 'option':
                # If there's something else inside the option
                if any(child.tag_name.lower() != 'option' for child in temp_parent.children):
                    new_node = self._create_node(tag_name, attributes, current_parent, current_context)
                    current_parent.append_child(new_node)
                    return (new_node, current_context)
                # Otherwise place it as a sibling
                new_node = self._create_node(tag_name, attributes, temp_parent.parent, current_context)
                temp_parent.parent.append_child(new_node)
                return (new_node, current_context)
            temp_parent = temp_parent.parent
        return (None, None)
