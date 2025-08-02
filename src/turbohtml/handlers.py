import re
from typing import Callable, List, Optional, Protocol, Tuple

from turbohtml.constants import (
    AUTO_CLOSING_TAGS,
    BLOCK_ELEMENTS,
    CLOSE_ON_PARENT_CLOSE,
    FORMATTING_ELEMENTS,
    HEAD_ELEMENTS,
    HEADING_ELEMENTS,
    HTML_ELEMENTS,
    MATHML_ELEMENTS,
    RAWTEXT_ELEMENTS,
    SVG_CASE_SENSITIVE_ELEMENTS,
    TABLE_ELEMENTS,
    VOID_ELEMENTS,
    BOUNDARY_ELEMENTS,
)
from turbohtml.context import ParseContext, DocumentState, ContentState  # Add import at top
from turbohtml.node import Node
from turbohtml.tokenizer import HTMLToken


class ParserInterface(Protocol):
    """Interface that handlers expect from parser"""

    def debug(self, message: str, indent: int = 4) -> None: ...

    root: "Node"


class TagHandler:
    """Base class for tag-specific handling logic"""

    def __init__(self, parser: ParserInterface):
        self.parser = parser

    def debug(self, message: str, indent: int = 4) -> None:
        """Delegate debug to parser with class name prefix"""
        class_name = self.__class__.__name__
        prefixed_message = f"{class_name}: {message}"
        self.parser.debug(prefixed_message, indent=indent)

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return False

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return False

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        return False

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        return False

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        return False


class TextHandler(TagHandler):
    """Default handler for text nodes"""

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        return True

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        self.debug(f"handling text '{text}' in state {context.document_state}")
        self.debug(f"current parent is {context.current_parent}")

        # If we have no current parent, create body and add text there
        if context.current_parent is None:
            self.debug("No current parent, switching to body")
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY
                # Strip leading whitespace when transitioning from INITIAL state (no parent)
                text = text.lstrip()
                if text:  # Only append if there's content after stripping
                    self._append_text(text, context)
            return True

        # In frameset mode, keep only whitespace
        if context.document_state == DocumentState.IN_FRAMESET:
            whitespace = "".join(c for c in text if c.isspace())
            if whitespace:
                self._append_text(whitespace, context)
            self.debug("Keeping only whitespace in frameset mode")
            return True

        # Handle text after </body>
        if context.document_state == DocumentState.AFTER_BODY:
            if text.isspace():
                self.debug("Processing whitespace after </body> in body")
                body = self.parser._get_body_node()
                if body:
                    context.current_parent = body
                    self._append_text(text, context)
            else:
                self.debug("Parse error: non-whitespace after </body>, switching back to in body")
                context.document_state = DocumentState.IN_BODY
                body = self.parser._get_body_node()
                if body:
                    context.current_parent = body
                    self._append_text(text, context)
            return True

        if context.content_state == ContentState.RAWTEXT:
            self._append_text(text, context)
            return True

        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            # Store the original state before modification
            was_initial = context.document_state == DocumentState.INITIAL

            # Find the first non-whitespace character
            for i, char in enumerate(text):
                if not char.isspace():
                    # If we're in head state, keep leading whitespace in head
                    if i > 0 and not was_initial:
                        self.debug(f"Keeping leading whitespace '{text[:i]}' in head")
                        head = self.parser._ensure_head_node()
                        context.current_parent = head
                        self._append_text(text[:i], context)

                    # Switch to body for non-whitespace and remaining text
                    self.debug(f"Found non-whitespace at pos {i}, switching to body")
                    body = self.parser._ensure_body_node(context)
                    if body:
                        context.current_parent = body
                        context.document_state = DocumentState.IN_BODY
                        # For INITIAL state, ignore leading whitespace; for IN_HEAD, start from i
                        start_pos = i if was_initial else 0
                        if start_pos < len(text):
                            self._append_text(text[start_pos:], context)
                    return True

            # If we get here, it's all whitespace
            if context.document_state == DocumentState.IN_HEAD:
                self.debug("All whitespace, keeping in head")
                self._append_text(text, context)
                return True

            # If we're in INITIAL state with all whitespace, still move to body
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY
            return True

        # Handle other text normally
        self._append_text(text, context)
        return True

    def _append_text(self, text: str, context: "ParseContext") -> None:
        """Helper to append text, either as new node or merged with previous"""
        self.debug(f"last child is {context.current_parent.children[-1] if context.current_parent.children else None}")

        # Try to merge with previous text node
        if context.current_parent.children and context.current_parent.children[-1].tag_name == "#text":
            prev_node = context.current_parent.children[-1]
            self.debug(f"merging with previous text node '{prev_node.text_content}'")
            prev_node.text_content += text
            self.debug(f"merged result '{prev_node.text_content}'")
        else:
            # Create new text node
            self.debug("creating new text node")
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            self.debug(f"created node with content '{text}'")

    def _is_in_head(self, node: Node) -> bool:
        """Check if node is inside the head element"""
        seen = set()  # Track nodes we've seen to detect cycles
        current = node
        while current and current not in seen:
            seen.add(current)
            if current.tag_name == "head":
                return True
            current = current.parent
        return False

    def _handle_normal_text(self, text: str, context: "ParseContext") -> bool:
        """Handle normal text content"""
        # If last child is a text node, append to it
        if context.current_parent.children and context.current_parent.children[-1].tag_name == "#text":
            context.current_parent.children[-1].text_content += text
            return True

        # Create new text node
        text_node = Node("#text")
        text_node.text_content = text
        context.current_parent.append_child(text_node)
        return True

    def _handle_pre_text(self, text: str, parent: Node) -> bool:
        """Handle text specifically for <pre> elements"""
        decoded_text = self._decode_html_entities(text)

        # Append to existing text node if present
        if parent.children and parent.children[-1].tag_name == "#text":
            parent.children[-1].text_content += decoded_text
            return True

        # Remove a leading newline if this is the first text node
        if not parent.children and decoded_text.startswith("\n"):
            decoded_text = decoded_text[1:]
        if decoded_text:
            text_node = Node("#text")
            text_node.text_content = decoded_text
            parent.append_child(text_node)

        return True

    def _decode_html_entities(self, text: str) -> str:
        """Decode numeric HTML entities."""
        text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r"&#([0-9]+);", lambda m: chr(int(m.group(1))), text)
        return text


class FormattingElementHandler(TagHandler):
    """Handles formatting elements like <b>, <i>, etc."""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle formatting elements inside select
        if context.current_parent.find_ancestor("select"):
            return False
        return tag_name in FORMATTING_ELEMENTS

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling <{tag_name}>, context={context}")

        # Special handling for nobr tags to prevent infinite loops
        if tag_name == "nobr":
            current = context.current_parent.find_ancestor("nobr")
            if current:
                self.debug("Found existing nobr, closing it and creating new one at same level")
                if current.parent:
                    context.current_parent = current.parent
                    new_element = Node("nobr", token.attributes)
                    current.parent.append_child(new_element)
                    context.current_parent = new_element
                return True

        # If we're in a table cell, handle normally
        if context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th")):
            self.debug("Inside table cell, creating formatting element normally")
            new_element = Node(token.tag_name, token.attributes)
            context.current_parent.append_child(new_element)
            context.current_parent = new_element
            return True

        # First check for existing instance of same formatting element (except nobr)
        current = context.current_parent.find_ancestor(token.tag_name)
        if current:
            self.debug(f"Found existing formatting element: {current}, adopting content")
            # Move up to the parent of the existing formatting element
            if current.parent:
                context.current_parent = current.parent
                # Create new formatting element at same level
                new_element = Node(token.tag_name, token.attributes)
                current.parent.append_child(new_element)
                context.current_parent = new_element
                return True

        # If we're in a table but not in a cell, foster parent
        if context.document_state in (DocumentState.IN_TABLE, DocumentState.IN_TABLE_BODY, DocumentState.IN_ROW):
            # First try to find a cell to put the element in
            cell = context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th"))
            if cell:
                self.debug(f"Found table cell {cell.tag_name}, placing formatting element inside")
                new_element = Node(token.tag_name, token.attributes)
                cell.append_child(new_element)
                context.current_parent = new_element
                return True

            # If no cell, foster parent before table
            table = context.current_table
            if table and table.parent:
                self.debug("Foster parenting formatting element before table")
                new_element = Node(token.tag_name, token.attributes)
                table_index = table.parent.children.index(table)
                table.parent.children.insert(table_index, new_element)
                new_element.parent = table.parent
                context.current_parent = new_element
                return True

        # Create new formatting element normally
        self.debug(f"Creating new formatting element: {tag_name} under {context.current_parent}")
        new_element = Node(token.tag_name, token.attributes)

        # Ensure we have a valid parent
        if not context.current_parent:
            body = self.parser._ensure_body_node(context)
            context.current_parent = body

        context.current_parent.append_child(new_element)
        context.current_parent = new_element
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in FORMATTING_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        self.debug(f"handling end tag <{tag_name}>, context={context}")

        # If we're in a table cell, ignore the end tag
        cell = context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th"))
        if cell:
            self.debug(f"Inside table cell {cell.tag_name}, ignoring end tag")
            return True

        # Check if we're inside a boundary element (except table cells)
        boundary = context.current_parent.find_ancestor(
            lambda n: n.tag_name in BOUNDARY_ELEMENTS and n.tag_name not in ("td", "th")
        )
        if boundary:
            self.debug(f"Inside boundary element {boundary.tag_name}")
            # First try to find formatting element within the boundary
            current = context.current_parent.find_ancestor(tag_name, stop_at_boundary=True)
            if current:
                self.debug(f"Found formatting element within boundary: {current}")
                if current.parent:
                    context.current_parent = current.parent
                return True

            # Look for a matching formatting element in the boundary's parent
            if boundary.parent:
                outer_formatting = boundary.parent.find_ancestor(token.tag_name)
                if outer_formatting:
                    self.debug(f"Found outer formatting element: {outer_formatting}")
                    # Stay inside the boundary element
                    context.current_parent = boundary
                    return True

            # If no formatting element found, ignore the end tag
            return True

        # Find matching formatting element
        current = context.current_parent.find_ancestor(token.tag_name)
        if not current:
            self.debug(f"No matching formatting element found for end tag: {tag_name}")
            return False

        self.debug(f"Found matching formatting element: {current}")

        # If we're in a table but not in a cell, move to formatting element's parent
        if context.document_state in (DocumentState.IN_TABLE, DocumentState.IN_TABLE_BODY, DocumentState.IN_ROW):
            if current.parent:
                self.debug(f"Moving to formatting element's parent: {current.parent}")
                context.current_parent = current.parent
                return True

        # Otherwise close normally
        self.debug(f"Moving to parent of formatting element: {current.parent}")
        context.current_parent = current.parent or self.parser._get_body_node()
        return True


class SelectTagHandler(TagHandler):
    """Handles select elements and their children (option, optgroup) and datalist"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # If we're in a select, handle all tags to prevent formatting elements
        if context.current_parent.find_ancestor("select"):
            return True
        return tag_name in ("select", "option", "optgroup", "datalist")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"Handling {tag_name} in select context, current_parent={context.current_parent}")

        if tag_name in ("select", "datalist"):
            # If we're already in a select, close it and ignore the nested select
            if context.current_parent.find_ancestor("select"):
                self.debug("Found nested select, closing outer select")
                outer_select = context.current_parent.find_ancestor("select")
                if outer_select and outer_select.parent:
                    self.debug(f"Moving up to outer select's parent: {outer_select.parent}")
                    context.current_parent = outer_select.parent
                    # Don't create anything for the nested select itself
                    self.debug("Ignoring nested select tag")
                    return True

            # Create new select/datalist
            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            self.debug(f"Created new {tag_name}: {new_node}, parent now: {context.current_parent}")
            return True

        # If we're in a select, ignore any formatting elements
        if context.current_parent.find_ancestor("select") and tag_name in FORMATTING_ELEMENTS:
            self.debug(f"Ignoring formatting element {tag_name} inside select")
            return True

        # If we're in a select, ignore any foreign elements (svg, math)
        if context.current_parent.find_ancestor("select") and tag_name in ("svg", "math"):
            self.debug(f"Ignoring foreign element {tag_name} inside select")
            return True

        elif tag_name in ("optgroup", "option"):
            # Check if we're in a select or datalist
            parent = context.current_parent.find_ancestor(lambda n: n.tag_name in ("select", "datalist"))
            self.debug(f"Checking for select/datalist ancestor: found={bool(parent)}")

            # If we're not in a select/datalist, create elements at body level
            if not parent:
                self.debug(f"Creating {tag_name} outside select/datalist")
                # Move up to body level if we're inside another option/optgroup
                while context.current_parent.tag_name in ("option", "optgroup"):
                    self.debug(f"Moving up from {context.current_parent.tag_name}")
                    context.current_parent = context.current_parent.parent

                new_node = Node(token.tag_name, token.attributes)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                self.debug(f"Created {tag_name}: {new_node}, parent now: {context.current_parent}")
                return True

            # Inside select/datalist, handle normally
            if tag_name == "optgroup":
                self.debug("Creating optgroup inside select/datalist")
                # If we're inside an option, move up to select/datalist level
                if context.current_parent.tag_name == "option":
                    self.debug("Moving up from option to select/datalist level")
                    parent = context.current_parent.find_ancestor(lambda n: n.tag_name in ("select", "datalist"))
                    if parent:
                        context.current_parent = parent

                new_optgroup = Node(tag_name, token.attributes)
                context.current_parent.append_child(new_optgroup)
                context.current_parent = new_optgroup
                self.debug(f"Created optgroup: {new_optgroup}, parent now: {context.current_parent}")
                return True
            else:  # option
                self.debug("Creating option inside select/datalist")
                # If we're inside a formatting element, move up to select
                formatting = context.current_parent.find_ancestor(lambda n: n.tag_name in FORMATTING_ELEMENTS)
                if formatting:
                    self.debug("Found formatting element, moving up to select")
                    parent = formatting.find_ancestor(lambda n: n.tag_name in ("select", "datalist"))
                    if parent:
                        context.current_parent = parent
                # If we're inside an optgroup, stay there, otherwise move to select/datalist level
                elif context.current_parent.tag_name not in ("select", "datalist", "optgroup"):
                    self.debug("Moving up to select/datalist/optgroup level")
                    parent = context.current_parent.find_ancestor(
                        lambda n: n.tag_name in ("select", "datalist", "optgroup")
                    )
                    if parent:
                        context.current_parent = parent

                new_option = Node(token.tag_name, token.attributes)
                context.current_parent.append_child(new_option)
                context.current_parent = new_option
                self.debug(f"Created option: {new_option}, parent now: {context.current_parent}")
                return True

        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("select", "option", "optgroup", "datalist")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        self.debug(f"Handling end tag {tag_name}, current_parent={context.current_parent}")

        if tag_name in ("select", "datalist"):
            # Find nearest select/datalist ancestor and move up to its parent
            ancestor = context.current_parent.find_ancestor(tag_name)
            if ancestor and ancestor.parent:
                self.debug(f"Found {tag_name} ancestor: {ancestor}, moving to parent: {ancestor.parent}")
                context.current_parent = ancestor.parent
            else:
                self.debug(f"No {tag_name} ancestor found")
            return True

        elif tag_name in ("optgroup", "option"):
            # Find nearest matching ancestor and move up to its parent
            ancestor = context.current_parent.find_ancestor(tag_name)
            if ancestor and ancestor.parent:
                self.debug(f"Found {tag_name} ancestor: {ancestor}, moving to parent: {ancestor.parent}")
                context.current_parent = ancestor.parent
            else:
                self.debug(f"No {tag_name} ancestor found")
            return True

        return False


class ParagraphTagHandler(TagHandler):
    """Handles paragraph elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle p tags directly
        if tag_name == "p":
            return True

        # Also handle any tag that would close a p
        if context.current_parent and context.current_parent.tag_name == "p":
            return tag_name in AUTO_CLOSING_TAGS["p"]

        return False

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        self.debug(f"handling {token}, context={context}")
        self.debug(f"Current parent: {context.current_parent}")

        # If we're in a formatting element, close it first
        if context.current_parent.tag_name in FORMATTING_ELEMENTS:
            formatting_element = context.current_parent
            context.current_parent = formatting_element.parent

            # Create p at body level
            new_p = Node(token.tag_name, token.attributes)
            context.current_parent.append_child(new_p)
            context.current_parent = new_p

            # Re-open formatting element inside p
            new_formatting = Node(formatting_element.tag_name, formatting_element.attributes.copy())
            new_p.append_child(new_formatting)
            context.current_parent = new_formatting
            return True

        # If we're handling a tag that should close p
        if token.tag_name != "p" and context.current_parent.tag_name == "p":
            self.debug(f"Auto-closing p due to {token.tag_name}")
            context.current_parent = context.current_parent.parent
            return False  # Let the original handler handle the new tag

        # Rest of the original p tag handling...
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY

        # Check if we're inside another p tag
        p_ancestor = context.current_parent.find_ancestor("p")
        if p_ancestor:
            self.debug(f"Found <p> ancestor: {p_ancestor}, closing it")
            context.current_parent = p_ancestor.parent

        # Check if we're inside a container element
        container_ancestor = context.current_parent.find_ancestor(
            lambda n: n.tag_name in ("div", "article", "section", "aside", "nav")
        )
        if container_ancestor and container_ancestor == context.current_parent:
            self.debug(f"Inside container element {container_ancestor.tag_name}, keeping p nested")
            new_node = Node("p", token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            return True

        # Create new p node under current parent (keeping formatting context)
        new_node = Node("p", token.attributes)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node

        self.debug(f"Created new paragraph node: {new_node} under {new_node.parent}")
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "p"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling <EndTag: p>, context={context}")

        # Find nearest p ancestor and move up to its parent
        current = context.current_parent
        while current and current != self.parser.html_node:
            if current.tag_name == "p":
                # If we're inside formatting elements inside the p,
                # we need to close up to the p's parent
                context.current_parent = current.parent
                return True
            current = current.parent

        # HTML5 spec: If no p element is in scope, create an implicit p element
        # and immediately close it (this creates an empty p element)
        self.debug("No open p element found, creating implicit p element")
        p_node = Node("p")
        context.current_parent.append_child(p_node)
        # Don't change current_parent - the implicit p is immediately closed

        return True


class TableTagHandler(TagHandler):
    """Handles table-related elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Always handle col/colgroup to prevent them being handled by VoidElementHandler
        if tag_name in ("col", "colgroup"):
            # But only process them if in table context
            return True

        # Don't handle table elements in foreign contexts
        if context.current_context in ("math", "svg"):
            return False

        return tag_name in ("table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"Handling {tag_name} in table context")

        # Ignore col/colgroup outside of table context
        if tag_name in ("col", "colgroup") and context.document_state != DocumentState.IN_TABLE:
            self.debug("Ignoring col/colgroup outside table context")
            return True

        # Handle table element separately since it creates the context
        if tag_name == "table":
            return self._handle_table(token, context)

        # For other table elements, we need a current table
        if not context.current_table:
            new_table = Node("table")
            # Ensure we have a valid parent
            if not context.current_parent:
                # This shouldn't happen, but if it does, skip table creation
                return False
            context.current_parent.append_child(new_table)
            context.current_table = new_table
            context.current_parent = new_table
            context.document_state = DocumentState.IN_TABLE

        # Handle each element type
        handlers = {
            "caption": self._handle_caption,
            "colgroup": self._handle_colgroup,
            "col": self._handle_col,
            "tbody": self._handle_tbody,
            "thead": self._handle_thead,
            "tfoot": self._handle_tfoot,
            "tr": self._handle_tr,
            "td": self._handle_cell,
            "th": self._handle_cell,
        }

        return handlers[tag_name](token, context)

    def _handle_caption(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle caption element"""
        # Always create caption at table level
        context.current_parent = context.current_table
        new_caption = Node(token.tag_name, token.attributes)
        context.current_table.append_child(new_caption)
        context.current_parent = new_caption
        context.document_state = DocumentState.IN_CAPTION
        return True

    def _handle_table(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle table element"""
        # If we're in head, implicitly close it and switch to body
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            self.debug("Implicitly closing head and switching to body")
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY

        new_table = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_table)
        context.current_table = new_table
        context.current_parent = new_table
        context.document_state = DocumentState.IN_TABLE
        return True

    def _handle_colgroup(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle colgroup element according to spec"""
        self.debug(f"_handle_colgroup: token={token}, current_parent={context.current_parent}")

        # Rule 1: If we're not in a table context, ignore
        if context.document_state != DocumentState.IN_TABLE:
            self.debug("Ignoring colgroup outside table context")
            return True

        # Rule 2: Always create new colgroup at table level
        self.debug("Creating new colgroup")
        new_colgroup = Node(token.tag_name, token.attributes)
        context.current_table.append_child(new_colgroup)

        # Rule 3: Check context and create new tbody if needed
        current = context.current_parent
        while current and current != context.current_table:
            self.debug(f"Checking ancestor: {current}")
            if current.tag_name == "td":
                self.debug("Found td ancestor, staying in current context")
                return True
            if current.tag_name in ("tbody", "tr", "colgroup"):
                self.debug("Found tbody/tr/colgroup ancestor, creating new tbody")
                # Create new empty tbody after the colgroup
                new_tbody = Node("tbody")
                context.current_table.append_child(new_tbody)
                context.current_parent = new_tbody
                return True
            current = current.parent

        # Rule 4: Otherwise stay at table level
        self.debug("No tbody/tr/td ancestors, staying at table level")
        context.current_parent = context.current_table
        return True

    def _handle_col(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle col element according to spec"""
        self.debug(f"_handle_col: token={token}, current_parent={context.current_parent}")

        # Rule 1: If we're not in a table context, ignore
        if context.document_state != DocumentState.IN_TABLE:
            self.debug("Ignoring col outside table context")
            return True

        # Rule 2: Check if we need a new colgroup
        need_new_colgroup = True
        last_colgroup = None

        # Look for last colgroup that's still valid
        for child in reversed(context.current_table.children):
            if child.tag_name == "colgroup":
                # Found a colgroup, but check if there's tbody/tr/td after it
                idx = context.current_table.children.index(child)
                has_content_after = any(
                    c.tag_name in ("tbody", "tr", "td") for c in context.current_table.children[idx + 1 :]
                )
                self.debug(f"Found colgroup at index {idx}, has_content_after={has_content_after}")
                if not has_content_after:
                    last_colgroup = child
                    need_new_colgroup = False
                break

        # Rule 3: Create or reuse colgroup
        if need_new_colgroup:
            self.debug("Creating new colgroup")
            last_colgroup = Node("colgroup")
            context.current_table.append_child(last_colgroup)
        else:
            self.debug(f"Reusing existing colgroup: {last_colgroup}")

        # Rule 4: Add col to colgroup
        new_col = Node(token.tag_name, token.attributes)
        last_colgroup.append_child(new_col)
        self.debug(f"Added col to colgroup: {new_col}")

        # Rule 5: Check context and create new tbody if needed
        current = context.current_parent
        while current and current != context.current_table:
            self.debug(f"Checking ancestor: {current}")
            if current.tag_name == "td":
                self.debug("Found td ancestor, staying in current context")
                return True
            if current.tag_name in ("tbody", "tr"):
                self.debug("Found tbody/tr ancestor, creating new tbody")
                # Create new empty tbody after the colgroup
                new_tbody = Node("tbody")
                context.current_table.append_child(new_tbody)
                context.current_parent = new_tbody
                return True
            current = current.parent

        # Rule 6: Otherwise stay at table level
        self.debug("No tbody/tr/td ancestors, staying at table level")
        context.current_parent = context.current_table
        return True

    def _handle_tbody(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle tbody element"""
        # Always create new tbody at table level
        context.current_parent = context.current_table
        new_tbody = Node(token.tag_name, token.attributes)
        context.current_table.append_child(new_tbody)
        context.current_parent = new_tbody
        return True

    def _handle_thead(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle thead element"""
        return self._handle_tbody(token, context)  # Same logic as tbody

    def _handle_tfoot(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle tfoot element"""
        return self._handle_tbody(token, context)  # Same logic as tbody

    def _handle_tr(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle tr element"""
        if context.current_parent.tag_name in ("tbody", "thead", "tfoot"):
            new_tr = Node(token.tag_name, token.attributes)
            context.current_parent.append_child(new_tr)
            context.current_parent = new_tr
            return True

        tbody = self._find_or_create_tbody(context)
        new_tr = Node(token.tag_name, token.attributes)
        tbody.append_child(new_tr)
        context.current_parent = new_tr
        return True

    def _handle_cell(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle td/th elements"""
        tr = self._find_or_create_tr(context)
        new_cell = Node(token.tag_name, token.attributes)
        tr.append_child(new_cell)
        context.current_parent = new_cell
        return True

    def _find_or_create_tbody(self, context: "ParseContext") -> "Node":
        """Find existing tbody or create new one"""
        # First check current context
        current = context.current_parent
        while current and current != context.current_table:
            if current.tag_name == "tbody":
                return current
            current = current.parent

        # Look for existing tbody in table
        for child in context.current_table.children:
            if child.tag_name == "tbody":
                return child

        # Create new tbody
        tbody = Node("tbody")
        context.current_table.append_child(tbody)
        return tbody

    def _find_or_create_tr(self, context: "ParseContext") -> "Node":
        """Find existing tr or create new one in tbody"""
        # First check if we're in a tr
        current = context.current_parent
        while current and current != context.current_table:
            if current.tag_name == "tr":
                return current
            current = current.parent

        # Get tbody and look for last tr
        tbody = self._find_or_create_tbody(context)
        if tbody.children and tbody.children[-1].tag_name == "tr":
            return tbody.children[-1]

        # Create new tr
        tr = Node("tr")
        tbody.append_child(tr)
        return tr

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        return context.document_state == DocumentState.IN_TABLE

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        if not self.should_handle_text(text, context):
            return False

        self.debug(f"handling text '{text}' in {context}")

        # If we're inside a caption, handle text directly
        if context.document_state == DocumentState.IN_CAPTION:
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # If we're inside a table cell, append text directly
        current_cell = context.current_parent.find_ancestor(lambda n: n.tag_name in ["td", "th"])
        if current_cell:
            self.debug(f"Inside table cell {current_cell}, appending text directly")
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # Foster parent text nodes
        table = context.current_table
        if not table or not table.parent:
            self.debug("No table or table parent found")
            return False

        # Find the appropriate parent for foster parenting
        foster_parent = table.parent
        table_index = foster_parent.children.index(table)
        self.debug(f"Foster parent: {foster_parent}, table index: {table_index}")

        # Find the most recent <a> tag before the table with content
        prev_a = None
        for child in reversed(foster_parent.children[:table_index]):
            if child.tag_name == "a" and child.children:
                prev_a = child
                self.debug(f"Found previous <a> tag with content: {prev_a} with attributes {prev_a.attributes}")
                break

        if prev_a:
            self.debug("Creating new <a> tag with attributes from previous one")
            # Create new <a> with same attributes
            new_a = Node("a", prev_a.attributes.copy())
            text_node = Node("#text")
            text_node.text_content = text
            new_a.append_child(text_node)
            foster_parent.children.insert(table_index, new_a)
            self.debug(f"Inserted new <a> tag before table: {new_a}")
            return True

        # Check for other formatting context
        formatting_elements = []
        current = context.current_parent
        while current and current != foster_parent:
            if current.tag_name in FORMATTING_ELEMENTS:
                formatting_elements.insert(0, current)
            current = current.parent
        self.debug(f"Found formatting elements: {formatting_elements}")

        # If we have formatting elements, maintain their nesting
        if formatting_elements:
            # Find or create the outermost formatting element before the table
            outer_format = None
            for child in foster_parent.children[:table_index]:
                if child.tag_name == formatting_elements[0].tag_name:
                    outer_format = child
                    self.debug(f"Found existing formatting element: {outer_format}")
                    break

            if not outer_format:
                self.debug("Creating new formatting elements")
                # Create new formatting elements with same nesting
                current_parent = foster_parent
                for fmt_elem in formatting_elements:
                    new_fmt = Node(fmt_elem.tag_name, fmt_elem.attributes.copy())
                    if current_parent == foster_parent:
                        foster_parent.children.insert(table_index, new_fmt)
                    else:
                        current_parent.append_child(new_fmt)
                    current_parent = new_fmt
                    self.debug(f"Created new formatting element: {new_fmt}")

                # Try to merge with previous text node
                prev_text = None
                if table_index > 0 and foster_parent.children[table_index - 1].tag_name == "#text":
                    prev_text = foster_parent.children[table_index - 1]
                    prev_text.text_content += text
                    self.debug(f"Merged with previous text node: {prev_text}")
                else:
                    # Add new text node to the innermost formatting element
                    text_node = Node("#text")
                    text_node.text_content = text
                    current_parent.append_child(text_node)
                    self.debug(f"Created new text node in formatting: {text_node}")
            else:
                # Try to merge with previous text node in the formatting element
                if outer_format.children and outer_format.children[-1].tag_name == "#text":
                    outer_format.children[-1].text_content += text
                    self.debug(f"Merged with existing text in formatting: {outer_format.children[-1]}")
                else:
                    # Add new text node to existing formatting element
                    text_node = Node("#text")
                    text_node.text_content = text
                    outer_format.append_child(text_node)
                    self.debug(f"Added new text node to existing formatting: {text_node}")
        else:
            self.debug("No formatting context found")
            # Try to merge with previous text node
            if table_index > 0 and foster_parent.children[table_index - 1].tag_name == "#text":
                foster_parent.children[table_index - 1].text_content += text
                self.debug(f"Merged with previous text node: {foster_parent.children[table_index-1]}")
            else:
                # No formatting context, foster parent directly
                text_node = Node("#text")
                text_node.text_content = text
                foster_parent.children.insert(table_index, text_node)
                self.debug(f"Created new text node directly: {text_node}")

        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle any end tag in table context to maintain proper structure
        return context.document_state in (DocumentState.IN_TABLE, DocumentState.IN_CAPTION)

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        self.debug(f"handling end tag {tag_name}")

        # If we're in a table cell
        cell = context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th"))
        if cell:
            if tag_name == "p":
                # Create an implicit p element in the cell
                self.debug("Creating implicit p element in table cell")
                new_p = Node("p")
                cell.append_child(new_p)
                context.current_parent = new_p
                return True

        # Rest of existing table end tag handling...
        if tag_name == "caption" and context.document_state == DocumentState.IN_CAPTION:
            caption = context.current_parent.find_ancestor("caption")
            if caption:
                context.current_parent = caption.parent
                context.document_state = DocumentState.IN_TABLE
            return True

        if tag_name == "table":
            if context.current_table:
                # Find any active formatting element that contained the table
                formatting_parent = context.current_table.parent
                if formatting_parent and formatting_parent.tag_name in FORMATTING_ELEMENTS:
                    self.debug(f"Returning to formatting context: {formatting_parent}")
                    context.current_parent = formatting_parent
                else:
                    context.current_parent = self.parser._get_body_node()

                # # Find the original <a> tag that contained the table
                # original_a = context.current_table.parent
                # if original_a and original_a.tag_name == "a":
                #     # Check if there was an <a> tag with different attributes inside the table
                #     different_a = None
                #     for child in original_a.children:
                #         if child.tag_name == "a" and child.attributes != original_a.attributes:
                #             different_a = child
                #             break

                #     if different_a:
                #         # Case like test #76 - create new <a> with the inner attributes
                #         self.debug(f"Creating new <a> with inner attributes: {different_a.attributes}")
                #         new_a = Node("a", different_a.attributes.copy())
                #         body = self.parser._get_body_node()
                #         if body:
                #             body.append_child(new_a)
                #             context.current_parent = new_a
                #     else:
                #         # Case like test #77 - keep using original <a>
                #         self.debug(f"Keeping original <a> tag: {original_a}")
                #         context.current_parent = original_a
                # else:
                #     # Find the first <a> tag in the document
                #     body = self.parser._get_body_node()
                #     first_a = None
                #     if body:
                #         for child in body.children:
                #             if child.tag_name == "a":
                #                 first_a = child
                #                 break

                #     if first_a:
                #         # Create new <a> with same attributes as first one
                #         self.debug(f"Creating new <a> with first <a> attributes: {first_a.attributes}")
                #         new_a = Node("a", first_a.attributes.copy())
                #         body = self.parser._get_body_node()
                #         if body:
                #             body.append_child(new_a)
                #             context.current_parent = new_a
                #     else:
                #         body = self.parser._get_body_node()
                #         context.current_parent = body or self.parser.html_node

                context.current_table = None
                context.document_state = DocumentState.IN_BODY
                return True

        elif tag_name == "a":
            # Find the matching <a> tag
            a_element = context.current_parent.find_ancestor("a")
            if a_element:
                body = self.parser._get_body_node()
                context.current_parent = a_element.parent or context.current_table or body or self.parser.html_node
                return True

        elif tag_name in TABLE_ELEMENTS:
            if tag_name in ["tbody", "thead", "tfoot"]:
                tbody = context.current_parent.find_ancestor("tbody")
                if tbody:
                    context.current_parent = tbody
                    return True
            elif tag_name in ["td", "th"]:
                tr = context.current_parent.find_ancestor("tr")
                if tr:
                    context.current_parent = tr
                    return True
            elif tag_name == "tr":
                tbody = context.current_parent.find_ancestor("tbody")
                if tbody:
                    context.current_parent = tbody
                    return True

        return False


class FormTagHandler(TagHandler):
    """Handles form-related elements (form, input, button, etc.)"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("form", "input", "button", "textarea", "select", "label")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int) -> bool:
        tag_name = token.tag_name

        # If we're in head, implicitly close it and switch to body
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY

        if tag_name == "form":
            # Only one form element allowed
            if context.has_form:
                return True
            context.has_form = True

        # Create and append the new node
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)

        # Update current parent for non-void elements
        if tag_name not in ("input",):
            context.current_parent = new_node
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("form", "button", "textarea", "select", "label")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name

        # Find the nearest matching element
        current = context.current_parent.find_ancestor(tag_name)

        if current:
            body = self.parser._get_body_node()
            context.current_parent = current.parent or body or self.parser.html_node
            if tag_name == "form":
                context.has_form = False

        return True


class ListTagHandler(TagHandler):
    """Handles list-related elements (ul, ol, li, dl, dt, dd)"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # First check if we have a current parent
        if not context.current_parent:
            return False

        # If we're inside a p tag, defer to AutoClosingTagHandler first
        if context.current_parent.tag_name == "p" and tag_name in ("dt", "dd", "li"):
            self.debug(f"Deferring {tag_name} inside p to AutoClosingTagHandler")
            return False

        return tag_name in ("li", "dt", "dd")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        self.debug(f"handling {token.tag_name}")
        self.debug(f"Current parent before: {context.current_parent}")
        tag_name = token.tag_name

        # If we're in head, implicitly close it and switch to body
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY

        # Handle dd/dt elements
        if tag_name in ("dd", "dt"):
            self.debug(f"Handling {tag_name} tag")
            # Find any existing dt/dd ancestor
            ancestor = context.current_parent.find_ancestor("dt") or context.current_parent.find_ancestor("dd")
            if ancestor:
                self.debug(f"Found existing {ancestor.tag_name} ancestor")
                # Close everything up to the dl parent
                dl_parent = ancestor.parent
                self.debug(f"Closing up to dl parent: {dl_parent}")
                context.current_parent = dl_parent

                # Create new element at same level
                new_node = Node(tag_name, token.attributes)
                dl_parent.append_child(new_node)
                context.current_parent = new_node
                self.debug(f"Created new {tag_name} at dl level: {new_node}")
                return True

            # No existing dt/dd, create normally
            self.debug("No existing dt/dd found, creating normally")
            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            self.debug(f"Created new {tag_name}: {new_node}")
            return True

        if tag_name == "li":
            self.debug(f"Handling li tag, current parent is {context.current_parent.tag_name}")

            # If we're in another li, close it first
            if context.current_parent.tag_name == "li":
                self.debug("Inside another li, closing it first")
                parent = context.current_parent.parent
                if parent and parent.tag_name in ("ul", "ol"):
                    self.debug(f"Moving up to list parent: {parent.tag_name}")
                    context.current_parent = parent
                else:
                    self.debug("No list parent found, moving to body")
                    body = self.parser._get_body_node()
                    context.current_parent = body or self.parser.html_node

            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            self.debug(f"Created new li: {new_node}")
            return True

        # Handle ul/ol/dl elements
        if tag_name in ("ul", "ol", "dl"):
            self.debug(f"Handling {tag_name} tag")
            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            self.debug(f"Created new {tag_name}: {new_node}")
            return True

        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("ul", "ol", "li", "dl", "dt", "dd")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling end tag {token.tag_name}")
        self.debug(f"Current parent before end: {context.current_parent}")
        tag_name = token.tag_name

        if tag_name in ("dt", "dd"):
            self.debug(f"Handling end tag for {tag_name}")
            # Find the nearest dt/dd ancestor
            current = context.current_parent
            while current and current != self.parser.html_node:
                if current.tag_name in ("dt", "dd"):
                    self.debug(f"Found matching {current.tag_name}")
                    # Move to the dl parent
                    if current.parent and current.parent.tag_name == "dl":
                        self.debug("Moving to dl parent")
                        context.current_parent = current.parent
                    else:
                        self.debug("No dl parent found, moving to body")
                        body = self.parser._get_body_node()
                        context.current_parent = body or self.parser.html_node
                    return True
                current = current.parent
            self.debug(f"No matching {tag_name} found")
            return False

        if tag_name == "li":
            self.debug("Handling end tag for li")
            # Find the nearest li ancestor
            current = context.current_parent
            while current and current != self.parser.html_node:
                if current.tag_name == "li":
                    self.debug("Found matching li")
                    # Move to the list parent
                    if current.parent and current.parent.tag_name in ("ul", "ol"):
                        self.debug("Moving to list parent")
                        context.current_parent = current.parent
                    else:
                        self.debug("No list parent found, moving to body")
                        body = self.parser._get_body_node()
                        context.current_parent = body or self.parser.html_node
                    return True
                # If we hit a ul/ol before finding an li, ignore the end tag
                if current.tag_name in ("ul", "ol"):
                    self.debug(f"Found {current.tag_name} before li, ignoring end tag")
                    return True
                current = current.parent
            self.debug("No matching li found")
            return False

        elif tag_name in ("ul", "ol", "dl"):
            self.debug(f"Handling end tag for {tag_name}")
            # Find the matching list container
            current = context.current_parent
            while current and current != self.parser.html_node:
                if current.tag_name == tag_name:
                    self.debug(f"Found matching {tag_name}")
                    # If we're inside an li/dt/dd, stay there
                    if current.parent and current.parent.tag_name in ("li", "dt", "dd"):
                        self.debug(f"Staying in {current.parent.tag_name}")
                        context.current_parent = current.parent
                    else:
                        self.debug("Moving to parent")
                        body = self.parser._get_body_node()
                        context.current_parent = current.parent or body or self.parser.html_node
                    return True
                current = current.parent
            self.debug(f"No matching {tag_name} found")
            return False

        return False


class HeadingTagHandler(TagHandler):
    """Handles h1-h6 heading elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name

        # Check if we're inside a table cell
        in_cell = context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th"))

        # If we're in a table cell, handle normally
        if in_cell:
            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            return True

        # Outside table cells, close any existing heading
        current = context.current_parent
        while current and current != self.parser.html_node:
            if current.tag_name in HEADING_ELEMENTS:
                context.current_parent = current.parent
                break
            current = current.parent

        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name

        # Find matching heading and move to its parent
        current = context.current_parent
        while current and current != self.parser.html_node:
            if current.tag_name == tag_name:
                context.current_parent = current.parent
                return True
            current = current.parent

        return False


class RawtextTagHandler(TagHandler):
    """Handles rawtext elements like script, style, title, etc."""

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling {tag_name}")

        # Create and append the new node
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)

        # Switch to RAWTEXT state and let tokenizer handle the content
        self.debug(f"Switching to RAWTEXT content state for {tag_name}")
        context.content_state = ContentState.RAWTEXT
        context.current_parent = new_node
        self.parser.tokenizer.start_rawtext(tag_name)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        self.debug(
            f"RawtextTagHandler.should_handle_end: checking {tag_name} in content_state {context.content_state}"
        )
        return tag_name in RAWTEXT_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling end tag {token.tag_name}")
        self.debug(
            f"Current state: doc={context.document_state}, content={context.content_state}, parent: {context.current_parent}"
        )

        if context.content_state == ContentState.RAWTEXT and token.tag_name == context.current_parent.tag_name:

            # Find the original parent before the RAWTEXT element
            original_parent = context.current_parent.parent
            self.debug(f"Original parent: {original_parent.tag_name if original_parent else None}")

            # Return to the original parent
            if original_parent:
                context.current_parent = original_parent
                # Clear RAWTEXT content mode
                context.content_state = ContentState.NONE
                self.debug("Returned to NONE content state")
            else:
                # Fallback to body if no parent
                body = self.parser._ensure_body_node(context)
                context.current_parent = body
                context.content_state = ContentState.NONE
                self.debug("Fallback to body, NONE content state")

            return True

        return False

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        self.debug(f"RawtextTagHandler.should_handle_text: checking in content_state {context.content_state}")
        return context.content_state == ContentState.RAWTEXT

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        self.debug(f"handling text in content_state {context.content_state}")
        if not self.should_handle_text(text, context):
            return False

        # Try to merge with previous text node if it exists
        if context.current_parent.children and context.current_parent.children[-1].tag_name == "#text":
            prev_node = context.current_parent.children[-1]
            self.debug(f"merging with previous text node '{prev_node.text_content}'")
            prev_node.text_content += text
            self.debug(f"merged result '{prev_node.text_content}'")
        else:
            # Create new text node
            self.debug("creating new text node")
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            self.debug(f"created node with content '{text}'")
        return True


class VoidElementHandler(TagHandler):
    """Handles void elements that can't have children"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle void elements inside select
        if context.current_parent and context.current_parent.find_ancestor("select"):
            return False

        return tag_name in VOID_ELEMENTS

    def handle_start(self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling {tag_name}, context={context}")
        self.debug(f"Current parent: {context.current_parent}")

        # HEAD_ELEMENTS should always be in head unless explicitly in body
        if tag_name in HEAD_ELEMENTS and not tag_name in RAWTEXT_ELEMENTS:
            self.debug(f"Found HEAD_ELEMENT: {tag_name}")
            self.debug(f"Current state: {context.document_state}")
            if context.document_state != DocumentState.IN_BODY:
                self.debug(f"Moving {tag_name} to head")
                new_node = Node(tag_name, token.attributes)
                head = self.parser._ensure_head_node()
                head.append_child(new_node)
                context.current_parent = head
                return True
            else:
                self.debug(f"Keeping {tag_name} in body due to IN_BODY state")

        # If we're in a paragraph and this is a block element, close the paragraph first
        if context.current_parent.tag_name == "p" and tag_name in BLOCK_ELEMENTS:
            self.debug(f"Closing paragraph for block element {tag_name}")
            body = self.parser._get_body_node()
            context.current_parent = context.current_parent.parent or body or self.parser.html_node

        # Create the void element at the current level
        self.debug(f"Creating void element {tag_name} at current level")
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)

        return True


class AutoClosingTagHandler(TagHandler):
    """Handles auto-closing behavior for certain tags"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle both formatting cases and auto-closing cases
        if not context.current_parent:
            body = self.parser._ensure_body_node(context)
            current = context.current_parent = body if body else self.parser.html_node
            if not current:
                return False

        return tag_name in AUTO_CLOSING_TAGS or (
            tag_name in BLOCK_ELEMENTS
            and context.current_parent.find_ancestor(lambda n: n.tag_name in FORMATTING_ELEMENTS)
        )

    def handle_start(self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int) -> bool:
        self.debug(f"Checking auto-closing rules for {token.tag_name}")
        current = context.current_parent
        if not current:
            body = self.parser._ensure_body_node(context)
            current = context.current_parent = body if body else self.parser.html_node

        self.debug(f"Current parent: {current}")
        self.debug(f"Current parent's parent: {current.parent}")
        self.debug(f"Current parent's children: {[c.tag_name for c in current.children]}")

        # First check if we're in a container element
        if current.tag_name in ("div", "article", "section", "aside", "nav"):
            self.debug(f"Inside container element {current.tag_name}, allowing nesting")
            return False

        # Check if we're inside a formatting element
        formatting_element = current.find_ancestor(lambda n: n.tag_name in FORMATTING_ELEMENTS)
        if formatting_element:
            self.debug(f"Found formatting element ancestor: {formatting_element}")

            # If we're in a <p> tag, close it first
            p_ancestor = current.find_ancestor("p")
            if p_ancestor and p_ancestor.parent:
                self.debug(f"Found p ancestor, closing it first: {p_ancestor}")
                context.current_parent = p_ancestor.parent
            else:
                # Move up to formatting element's parent
                context.current_parent = formatting_element.parent

            # Create block element
            new_block = Node(token.tag_name, token.attributes)
            context.current_parent.append_child(new_block)

            # Re-open formatting element inside block
            new_formatting = Node(formatting_element.tag_name, formatting_element.attributes.copy())
            new_block.append_child(new_formatting)
            context.current_parent = new_formatting
            self.debug(f"Created new block {new_block.tag_name} with formatting element {new_formatting.tag_name}")

            return True

        # Then check if current tag should be closed by new tag
        current_tag = current.tag_name
        if current_tag in AUTO_CLOSING_TAGS:
            closing_list = AUTO_CLOSING_TAGS[current_tag]
            if token.tag_name in closing_list:
                self.debug(f"Auto-closing {current_tag} due to new tag {token.tag_name}")
                if current.parent:
                    context.current_parent = current.parent
                return False

        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle end tags for block elements and elements that close when their parent closes
        return (
            tag_name in CLOSE_ON_PARENT_CLOSE
            or tag_name in BLOCK_ELEMENTS
            or tag_name
            in (
                "tr",
                "td",
                "th",
            )
        )  # Add table elements

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"AutoClosingTagHandler.handle_end: {token.tag_name}")
        self.debug(f"Current parent: {context.current_parent}")

        if token.tag_name == "tr":
            # First find the tr element
            tr = context.current_parent.find_ancestor("tr")
            if tr:
                # Close everything up to the tr
                body = self.parser._get_body_node()
                context.current_parent = tr.parent or body or self.parser.html_node
                context.document_state = DocumentState.IN_TABLE
                return True

        # Handle block elements
        if token.tag_name in BLOCK_ELEMENTS:
            # Find matching block element
            current = context.current_parent.find_ancestor(token.tag_name)
            if not current:
                self.debug(f"No matching block element found for end tag: {token.tag_name}")
                return False

            self.debug(f"Found matching block element: {current}")

            # If we're inside a boundary element, stay there
            boundary = context.current_parent.find_ancestor(lambda n: n.tag_name in BOUNDARY_ELEMENTS)
            if boundary:
                self.debug(f"Inside boundary element {boundary.tag_name}, staying inside")
                context.current_parent = boundary
                return True

            # Move up to block element's parent
            context.current_parent = current.parent or self.parser._get_body_node()
            return True

        # Handle other closing tags...
        if token.tag_name in CLOSE_ON_PARENT_CLOSE:
            parent_tags = CLOSE_ON_PARENT_CLOSE[token.tag_name]
            for parent_tag in parent_tags:
                parent = context.current_parent.find_ancestor(parent_tag)
                if parent:
                    context.current_parent = parent
                    return True
        return False


class AdoptionAgencyHelper:
    """Helper class for implementing the adoption agency algorithm"""

    @staticmethod
    def handle_formatting_boundary(context: "ParseContext", parser: "ParserInterface") -> Tuple[Node, List[Node]]:
        """
        Handles a formatting boundary (when block element meets formatting elements)
        Returns (parent_node, formatting_elements)
        """
        parser.debug("AdoptionAgencyHelper: handling formatting boundary")

        # Find any formatting elements we're inside of
        formatting_elements = []
        temp = context.current_parent
        while temp and temp.tag_name != "body":
            if temp.tag_name in FORMATTING_ELEMENTS:
                formatting_elements.insert(0, temp)
                parser.debug(
                    f"Found formatting element: {temp.tag_name} with children: {[c.tag_name for c in temp.children]}"
                )
            # Stop at table boundaries
            if temp.tag_name in TABLE_ELEMENTS:
                parser.debug(f"Found table boundary: {temp.tag_name}")
                break
            temp = temp.parent

        parser.debug(f"Found formatting elements: {[f.tag_name for f in formatting_elements]}")

        if not formatting_elements:
            # If we're in a table context, move formatting elements before table
            if context.document_state == DocumentState.IN_TABLE:
                table = context.current_table
                if table and table.parent:
                    parser.debug("Moving formatting elements before table")
                    return table.parent, []
            return context.current_parent, []

        # If we're crossing a table boundary, reparent formatting elements
        if any(e.find_ancestor(lambda n: n.tag_name in TABLE_ELEMENTS) for e in formatting_elements):
            table = context.current_table
            if table and table.parent:
                parser.debug("Reparenting formatting elements before table")
                for elem in formatting_elements:
                    # Move element before table
                    if elem.parent:
                        elem.parent.remove_child(elem)
                    table_index = table.parent.children.index(table)
                    table.parent.children.insert(table_index, elem)
                    elem.parent = table.parent

        return formatting_elements[-1], formatting_elements


class ForeignTagHandler(TagHandler):
    """Handles SVG and other foreign element contexts"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle foreign elements in restricted contexts
        if tag_name in ("svg", "math"):
            # Check if we're inside a select element (foreign elements not allowed)
            temp_parent = context.current_parent
            while temp_parent:
                if temp_parent.tag_name == "select":
                    return False
                temp_parent = temp_parent.parent
        
        # Handle any tag when in SVG or MathML context
        if context.current_context in ("svg", "math"):
            return True
        # Also handle svg and math tags to enter those contexts
        if tag_name in ("svg", "math"):
            return True
        # Handle MathML elements that should automatically enter MathML context
        if tag_name in MATHML_ELEMENTS:
            return True
        return False

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        tag_name_lower = tag_name.lower()

        # Check if this is an HTML element that should break out of foreign content
        if context.current_context in ("svg", "math") and tag_name_lower in HTML_ELEMENTS:
            # Special case: font element only breaks out if it has attributes
            if tag_name_lower == "font" and not token.attributes:
                # font with no attributes stays in foreign context
                pass
            else:
                # HTML elements break out of foreign content and are processed as regular HTML
                self.debug(f"HTML element {tag_name_lower} breaks out of foreign content")
                context.current_context = None  # Exit foreign context
                # Move current_parent up to the appropriate level, but never make it None
                if context.current_parent:
                    # In fragment parsing, go to document-fragment
                    # In document parsing, go to html_node (or stay if we're already there)
                    if self.parser.fragment_context:
                        while (context.current_parent and 
                               context.current_parent.tag_name != "document-fragment" and
                               context.current_parent.parent):
                            context.current_parent = context.current_parent.parent
                    else:
                        # In document parsing, go back to the HTML node or body
                        while (context.current_parent and 
                               context.current_parent.tag_name not in ("html", "body") and
                               context.current_parent.parent):
                            context.current_parent = context.current_parent.parent
                return False  # Let other handlers process this element

        if context.current_context == "math":
            # Auto-close certain MathML elements when encountering table elements
            if tag_name_lower in ("tr", "td", "th") and context.current_parent.tag_name.startswith("math "):
                # Find if we're inside a MathML operator/leaf element that should auto-close
                auto_close_elements = ["math mo", "math mi", "math mn", "math mtext", "math ms"]
                if context.current_parent.tag_name in auto_close_elements:
                    self.debug(f"Auto-closing {context.current_parent.tag_name} for {tag_name_lower}")
                    if context.current_parent.parent:
                        context.current_parent = context.current_parent.parent
            
            # In foreign contexts, RAWTEXT elements behave as normal elements
            if tag_name_lower in RAWTEXT_ELEMENTS:
                self.debug(f"Treating {tag_name_lower} as normal element in foreign context")
                new_node = Node(f"math {tag_name}", token.attributes)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                # Reset tokenizer if it entered RAWTEXT mode
                if hasattr(self.parser, 'tokenizer') and self.parser.tokenizer.state == "RAWTEXT":
                    self.parser.tokenizer.state = "DATA"
                    self.parser.tokenizer.rawtext_tag = None
                return True
            
            # Handle MathML elements
            if tag_name_lower == "annotation-xml":
                new_node = Node("math annotation-xml", token.attributes)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                return True

            # Handle HTML elements inside annotation-xml
            if context.current_parent.tag_name == "math annotation-xml":
                encoding = context.current_parent.attributes.get("encoding", "").lower()
                if encoding in ("application/xhtml+xml", "text/html"):
                    # Keep HTML elements nested for these encodings
                    new_node = Node(tag_name_lower, token.attributes)
                    context.current_parent.append_child(new_node)
                    context.current_parent = new_node
                    return True
                if tag_name_lower in HTML_ELEMENTS:
                    new_node = Node(tag_name_lower, token.attributes)
                    context.current_parent.append_child(new_node)
                    context.current_parent = new_node
                    return True

            new_node = Node(f"math {tag_name}", token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            return True

        elif context.current_context == "svg":
            # Auto-close certain SVG elements when encountering table elements
            if tag_name_lower in ("tr", "td", "th") and context.current_parent.tag_name.startswith("svg "):
                # Find if we're inside an SVG element that should auto-close
                auto_close_elements = ["svg title", "svg desc"]
                if context.current_parent.tag_name in auto_close_elements:
                    self.debug(f"Auto-closing {context.current_parent.tag_name} for {tag_name_lower}")
                    if context.current_parent.parent:
                        context.current_parent = context.current_parent.parent
                        
            # In foreign contexts, RAWTEXT elements behave as normal elements
            if tag_name_lower in RAWTEXT_ELEMENTS:
                self.debug(f"Treating {tag_name_lower} as normal element in foreign context")
                new_node = Node(f"svg {tag_name}", token.attributes)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                # Reset tokenizer if it entered RAWTEXT mode
                if hasattr(self.parser, 'tokenizer') and self.parser.tokenizer.state == "RAWTEXT":
                    self.parser.tokenizer.state = "DATA"
                    self.parser.tokenizer.rawtext_tag = None
                return True
                
            # Handle case-sensitive SVG elements
            if tag_name_lower in SVG_CASE_SENSITIVE_ELEMENTS:
                correct_case = SVG_CASE_SENSITIVE_ELEMENTS[tag_name_lower]
                new_node = Node(f"svg {correct_case}", token.attributes)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                return True

            # Handle HTML elements inside foreignObject
            elif tag_name_lower in HTML_ELEMENTS:
                temp_parent = context.current_parent
                while temp_parent:
                    if temp_parent.tag_name == "svg foreignObject":
                        new_node = Node(tag_name_lower, token.attributes)
                        context.current_parent.append_child(new_node)
                        context.current_parent = new_node
                        return True
                    temp_parent = temp_parent.parent

            new_node = Node(f"svg {tag_name_lower}", token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            return True

        # Enter new context for svg/math tags
        if tag_name_lower == "math":
            new_node = Node(f"math {tag_name}", token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            context.current_context = "math"
            return True

        if tag_name_lower == "svg":
            new_node = Node(f"svg {tag_name}", token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            context.current_context = "svg"
            return True

        # Handle MathML elements outside of MathML context (re-enter MathML)
        if tag_name_lower in MATHML_ELEMENTS:
            new_node = Node(f"math {tag_name}", token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            context.current_context = "math"
            return True

        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle any end tag in foreign contexts
        return context.current_context in ("svg", "math")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name.lower()

        if context.current_context == "math":
            if tag_name == "math":
                if context.current_parent.parent:
                    context.current_parent = context.current_parent.parent
                    context.current_context = None
                return True
        elif context.current_context == "svg":
            if tag_name == "svg":
                if context.current_parent.parent:
                    context.current_parent = context.current_parent.parent
                    context.current_context = None
                return True

        # For foreign content, look for the first matching element and close to there
        search_parent = context.current_parent
        while search_parent:
            # Check if this element matches (remove namespace prefix for comparison)
            element_name = search_parent.tag_name
            if " " in element_name:
                element_name = element_name.split(" ", 1)[1]
            
            if element_name == tag_name:
                # Found matching element, close up to its parent
                if search_parent.parent:
                    context.current_parent = search_parent.parent
                else:
                    # No parent, stay at current level
                    pass
                return True
            search_parent = search_parent.parent

        # No matching element found, ignore the end tag
        return True

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        # Handle text in annotation-xml specially
        return context.current_context in ("svg", "math") and context.current_parent.tag_name == "math annotation-xml"

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        if context.current_parent.tag_name == "math annotation-xml":
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True
        return False


class HeadElementHandler(TagHandler):
    """Handles head element and its contents"""

    def _has_body_content(self, html_node):
        """Check if body has actual content or if we just have a body element"""
        for child in html_node.children:
            if child.tag_name == "body":
                # Body exists, check if it has non-whitespace content or child elements
                return len(child.children) > 0 or (
                    hasattr(child, 'text_content') and
                    child.text_content and
                    child.text_content.strip()
                )
        return False

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in HEAD_ELEMENTS

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling {tag_name}, has_more_content={has_more_content}")
        self.debug(f"Current state: {context.document_state}, current_parent: {context.current_parent}")

        # Debug current parent details
        if context.current_parent:
            self.debug(f"Current parent tag: {context.current_parent.tag_name}")
            self.debug(f"Current parent children: {len(context.current_parent.children)}")
            if context.current_parent.children:
                self.debug(f"Current parent's children: {[c.tag_name for c in context.current_parent.children]}")

        # If we're in body after seeing real content
        if context.document_state == DocumentState.IN_BODY:
            self.debug("In body state with real content")
            # Check if we're still at html level with no body content yet
            if (context.current_parent.tag_name == "html" and
                not self._has_body_content(context.current_parent)):
                # Head elements appearing before body content should go to head
                head = self.parser._ensure_head_node()
                if head:
                    new_node = Node(tag_name, token.attributes)
                    head.append_child(new_node)
                    self.debug(f"Added {tag_name} to head (no body content yet)")

                    # For elements that can have content, update current parent
                    if tag_name not in VOID_ELEMENTS:
                        context.current_parent = new_node
                        if tag_name in RAWTEXT_ELEMENTS:
                            context.content_state = ContentState.RAWTEXT
                            self.debug(f"Switched to RAWTEXT state for {tag_name}")
                    return True

            # Head elements appearing after body content should stay in body
            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            self.debug(f"Added {tag_name} to body")

            # For elements that can have content, update current parent
            if tag_name not in VOID_ELEMENTS:
                context.current_parent = new_node
                if tag_name in RAWTEXT_ELEMENTS:
                    context.content_state = ContentState.RAWTEXT
                    self.debug(f"Switched to RAWTEXT state for {tag_name}")
            return True

        # Handle head elements in head normally
        else:
            self.debug("Handling element in head context")
            # If we're not in head, switch to head
            if context.document_state != DocumentState.IN_HEAD:
                head = self.parser._ensure_head_node()
                context.current_parent = head
                context.document_state = DocumentState.IN_HEAD
                self.debug("Switched to head state")

            # Create and append the new element
            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            self.debug(f"Added {tag_name} to head")

            # For elements that can have content, update current parent
            if tag_name not in VOID_ELEMENTS:
                context.current_parent = new_node
                if tag_name in RAWTEXT_ELEMENTS:
                    context.content_state = ContentState.RAWTEXT
                    self.debug(f"Switched to RAWTEXT state for {tag_name}")

        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "head"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling end tag {token.tag_name}")
        self.debug(f"current state: {context.document_state}, current parent: {context.current_parent}")

        # For template, only close up to the nearest template boundary
        if token.tag_name == "template":
            self.debug("handling template end tag")
            self.debug(f"starting search at: {context.current_parent}")

            # Find nearest template ancestor, stopping at boundaries
            template_ancestor = context.current_parent.find_ancestor("template", stop_at_boundary=True)

            if template_ancestor:
                self.debug(f"found matching template, moving to parent: {template_ancestor.parent}")
                context.current_parent = template_ancestor.parent
                return True

            self.debug("no matching template found within boundaries")
            return False

        # For other head elements...
        if context.content_state == ContentState.RAWTEXT:
            self.debug(f"handling RAWTEXT end tag {token.tag_name}")
            context.document_state = DocumentState.IN_HEAD
            context.current_parent = context.current_parent.parent
            self.debug(f"returned to head state, new parent: {context.current_parent}")
            return True

        return False

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        # Handle text in RAWTEXT mode or spaces in head
        return (
            context.content_state == ContentState.RAWTEXT
            and context.current_parent
            and context.current_parent.tag_name in RAWTEXT_ELEMENTS
        ) or (context.document_state == DocumentState.IN_HEAD and text.isspace())

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        if not self.should_handle_text(text, context):
            return False

        self.debug(f"handling text '{text}' in {context.current_parent.tag_name}")

        # If we're in head state and see non-space text, don't handle it
        if context.document_state == DocumentState.IN_HEAD and not text.isspace():
            self.debug("Non-space text in head, not handling")
            return False

        # Try to combine with previous text node if it exists
        if context.current_parent.children and context.current_parent.children[-1].tag_name == "#text":
            self.debug("Found previous text node, combining")
            context.current_parent.children[-1].text_content += text
            self.debug(f"Combined text: '{context.current_parent.children[-1].text_content}'")
        else:
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)

        self.debug(f"Text node content: {text}")
        return True

    def should_handle_comment(self, comment: str, context: "ParseContext") -> bool:
        return (
            context.content_state == ContentState.RAWTEXT
            and context.current_parent
            and context.current_parent.tag_name in RAWTEXT_ELEMENTS
        )

    def handle_comment(self, comment: str, context: "ParseContext") -> bool:
        self.debug(f"handling comment '{comment}' in RAWTEXT mode")
        # In RAWTEXT mode, treat comments as text
        return self.handle_text(comment, context)


class HtmlTagHandler(TagHandler):
    """Handles html element"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "html"

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        self.debug("handling start tag")
        # Update html node attributes if it exists
        if self.parser.html_node:
            self.parser.html_node.attributes.update(token.attributes)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "html"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling end tag, current state: {context.document_state}")

        # If we're in head, implicitly close it
        if context.document_state == DocumentState.IN_HEAD:
            self.debug("Closing head and switching to body")
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY

        # Any content after </html> should be treated as body content
        elif context.document_state == DocumentState.AFTER_HTML:
            self.debug("Content after </html>, switching to body mode")
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY

        return True


class FramesetTagHandler(TagHandler):
    """Handles frameset, frame, and noframes elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("frameset", "frame", "noframes")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling {tag_name}")

        # Ensure we have a valid parent node
        if not context.current_parent:
            body = self.parser._ensure_body_node(context)
            context.current_parent = body if body else self.parser.html_node
            if not context.current_parent:
                self.debug("No valid parent node available")
                return False

        if tag_name == "frameset":
            # Skip frameset handling in fragment mode
            if not self.parser.html_node:
                return False
                
            # If we're not already in a frameset tree, replace body with it
            if not context.current_parent.find_ancestor("frameset"):
                self.debug("Creating root frameset")
                new_node = Node(tag_name, token.attributes)
                body = self.parser._get_body_node()
                if body:
                    body.parent.remove_child(body)
                self.parser.html_node.append_child(new_node)
                context.current_parent = new_node
                context.document_state = DocumentState.IN_FRAMESET
            else:
                # Nested frameset
                self.debug("Creating nested frameset")
                new_node = Node(tag_name, token.attributes)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
            return True

        elif tag_name == "frame":
            # Frame must be inside frameset
            if context.current_parent.tag_name == "frameset":
                self.debug("Creating frame in frameset")
                new_node = Node(tag_name, token.attributes)
                context.current_parent.append_child(new_node)
                # frame is a void element, don't change current_parent
            return True

        elif tag_name == "noframes":
            self.debug("Creating noframes element")
            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            context.content_state = ContentState.RAWTEXT
            return True

        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("frameset", "noframes")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        self.debug(f"handling end tag {tag_name}")

        if tag_name == "frameset":
            # Find nearest frameset ancestor
            target = context.current_parent.find_ancestor("frameset")
            if target:
                # Move to parent frameset if it exists
                if target.parent and target.parent.tag_name == "frameset":
                    context.current_parent = target.parent
                else:
                    # Otherwise stay at root level
                    context.current_parent = self.parser.html_node
                return True
            return False

        elif tag_name == "noframes":
            if context.current_parent.tag_name == "noframes":
                # Return to frameset
                parent = context.current_parent.parent
                if parent and parent.tag_name == "frameset":
                    context.current_parent = parent
                    context.document_state = DocumentState.IN_FRAMESET
                else:
                    context.current_parent = self.parser.html_node
                    context.document_state = DocumentState.IN_FRAMESET
            return True

        return False


class ImageTagHandler(TagHandler):
    """Special handling for img tags"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("img", "image")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int) -> bool:
        # If we're in head, implicitly close it and switch to body
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = body
                context.document_state = DocumentState.IN_BODY

        # Always create as "img" regardless of input tag
        new_node = Node("img", token.attributes)
        context.current_parent.append_child(new_node)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("img", "image")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        # Images are void elements, no need to handle end tag
        return True


class BodyElementHandler(TagHandler):
    """Handles body element"""

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "body"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        # If we're not in frameset mode, ensure we have a body
        if context.document_state != DocumentState.IN_FRAMESET:
            body = self.parser._ensure_body_node(context)
            if body:
                context.current_parent = self.parser.html_node
                context.document_state = DocumentState.AFTER_BODY
            return True
        return False


class BoundaryElementHandler(TagHandler):
    """Handles elements that can affect formatting elements like marquee"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle foreign elements (svg, math) as boundary elements
        # since they should be handled by ForeignTagHandler
        if tag_name in ("svg", "math"):
            return False
        return tag_name in BOUNDARY_ELEMENTS

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        # If we're in a <p> tag, close it first
        p_ancestor = context.current_parent.find_ancestor("p")
        if p_ancestor and p_ancestor.parent:
            self.debug(f"Found p ancestor, closing it first: {p_ancestor}")
            context.current_parent = p_ancestor.parent

        # Check if we're inside a formatting element
        formatting_element = context.current_parent.find_ancestor(lambda n: n.tag_name in FORMATTING_ELEMENTS)
        if formatting_element:
            self.debug(f"Found formatting element ancestor: {formatting_element}")
            self.debug(f"Current parent before: {context.current_parent}")

            # Create the boundary element
            new_node = Node(token.tag_name, token.attributes)
            formatting_element.append_child(new_node)
            context.current_parent = new_node
            self.debug(f"Created boundary element {new_node.tag_name} under {formatting_element.tag_name}")

            # Create an implicit paragraph inside the boundary element
            new_p = Node("p")
            new_node.append_child(new_p)
            context.current_parent = new_p
            self.debug(f"Created implicit paragraph under {new_node.tag_name}")
            return True

        # Create the boundary element normally
        new_node = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node

        # Create an implicit paragraph inside the boundary element
        new_p = Node("p")
        new_node.append_child(new_p)
        context.current_parent = new_p
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle foreign elements (svg, math) as boundary elements
        if tag_name in ("svg", "math"):
            return False
        return tag_name in BOUNDARY_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        self.debug(f"handling end tag {tag_name}")

        # Find the boundary element we're trying to close
        target = context.current_parent.find_ancestor(tag_name, stop_at_boundary=True)
        if not target:
            self.debug("no matching boundary element found")
            return False

        self.debug(f"found matching boundary element: {target}")

        # Find any formatting elements between current position and target
        formatting_elements = []
        current = context.current_parent
        while current and current != target:
            if current.tag_name in FORMATTING_ELEMENTS:
                formatting_elements.append(current)
                self.debug(f"found formatting element to close: {current.tag_name}")
            current = current.parent

        # Close any formatting elements inside the boundary element
        if formatting_elements:
            self.debug(f"closing formatting elements: {[f.tag_name for f in formatting_elements]}")
            # Move back to the boundary element's parent
            context.current_parent = target.parent or self.parser.html_node
            self.debug(f"moved to boundary parent: {context.current_parent}")

            # Look for outer formatting element of same type
            outer_fmt = target.parent.find_ancestor(
                lambda n: (n.tag_name in FORMATTING_ELEMENTS and n.tag_name == formatting_elements[0].tag_name)
            )

            if outer_fmt:
                self.debug(f"found outer formatting element: {outer_fmt}")
                context.current_parent = outer_fmt
                self.debug(f"moved to outer formatting element: {context.current_parent}")
        else:
            self.debug("no formatting elements to close")
            context.current_parent = target.parent or self.parser.html_node
            self.debug(f"moved to boundary parent: {context.current_parent}")

        return True


class DoctypeHandler(TagHandler):
    """Handles DOCTYPE declarations"""

    def should_handle_doctype(self, doctype: str, context: "ParseContext") -> bool:
        return True

    def handle_doctype(self, doctype: str, context: "ParseContext") -> bool:
        # If we've already seen a doctype, ignore additional ones
        if context.doctype_seen:
            self.debug("Ignoring duplicate DOCTYPE")
            return True

        self.debug(f"handling {doctype}")
        doctype_node = Node("!doctype")

        # Parse and normalize the DOCTYPE according to HTML5 spec
        if not doctype.strip():
            # Empty DOCTYPE should result in space after DOCTYPE
            doctype_node.text_content = ""
        else:
            # Parse the full DOCTYPE declaration according to HTML5 spec
            parsed_doctype = self._parse_doctype_declaration(doctype)
            doctype_node.text_content = parsed_doctype

        self.parser.root.append_child(doctype_node)
        context.doctype_seen = True
        return True

    def _parse_doctype_declaration(self, doctype: str) -> str:
        """Parse DOCTYPE declaration and normalize it according to HTML5 spec"""
        import re

        # Basic parsing to extract name, public, and system identifiers
        # This is a simplified version of the full HTML5 DOCTYPE parsing

        # First, normalize the basic name but preserve content
        doctype_stripped = doctype.strip()
        if not doctype_stripped:
            return ""

        # Extract just the name (first word)
        match = re.match(r'(\S+)', doctype_stripped)
        if not match:
            return ""

        name = match.group(1).lower()
        rest = doctype_stripped[len(match.group(1)):].lstrip()

        # If nothing after name, return just the name
        if not rest:
            return name

        # Look for PUBLIC keyword with careful quote handling, preserving whitespace
        public_pattern = (r'PUBLIC\s*(["\'])([^"\']*(?:["\'][^"\']*)*?)'
                         r'(?:\1|$)(?:\s*(["\'])([^"\']*(?:["\'][^"\']*)*?)(?:\3|$))?')
        public_match = re.search(public_pattern, rest, re.IGNORECASE | re.DOTALL)
        if public_match:
            public_id = public_match.group(2)
            system_id = public_match.group(4) if public_match.group(4) is not None else ""
            return f'{name} "{public_id}" "{system_id}"'

        # Look for SYSTEM keyword with more careful quote handling, preserving whitespace
        system_pattern = r'SYSTEM\s*(["\'])([^"\']*(?:["\'][^"\']*)*?)(?:\1|$)'
        system_match = re.search(system_pattern, rest, re.IGNORECASE | re.DOTALL)
        if system_match:
            content = system_match.group(2)
            return f'{name} "" "{content}"'

        # If no PUBLIC/SYSTEM found, just return the name
        return name


class PlaintextHandler(TagHandler):
    """Handles plaintext element which switches to plaintext mode"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle plaintext start tag, or any tag when already in PLAINTEXT mode
        return tag_name == "plaintext" or context.content_state == ContentState.PLAINTEXT

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        # If we're already in PLAINTEXT mode, treat the tag as text
        if context.content_state == ContentState.PLAINTEXT:
            self.debug(f"treating tag as text: <{token.tag_name}>")
            text_node = Node("#text")
            text_node.text_content = f"<{token.tag_name}>"
            context.current_parent.append_child(text_node)
            return True

        self.debug("handling plaintext")

        # Create plaintext node
        new_node = Node("plaintext", token.attributes)

        # If we're in a table, foster parent the plaintext node
        if context.document_state == DocumentState.IN_TABLE:
            self.debug("Foster parenting plaintext out of table")
            table = context.current_table
            if table and table.parent:
                table_index = table.parent.children.index(table)
                table.parent.children.insert(table_index, new_node)
                context.current_parent = new_node
        else:
            context.current_parent.append_child(new_node)
            context.current_parent = new_node

        # Switch to PLAINTEXT mode
        context.content_state = ContentState.PLAINTEXT
        return True

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        return context.content_state == ContentState.PLAINTEXT

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        if not self.should_handle_text(text, context):
            return False

        # In PLAINTEXT mode, all text is handled literally
        text_node = Node("#text")
        text_node.text_content = text
        context.current_parent.append_child(text_node)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle all end tags in PLAINTEXT mode
        return context.content_state == ContentState.PLAINTEXT

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"treating end tag as text: </{token.tag_name}>")
        text_node = Node("#text")
        text_node.text_content = f"</{token.tag_name}>"
        context.current_parent.append_child(text_node)
        return True


class ButtonTagHandler(TagHandler):
    """Handles button elements with special formatting element rules"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "button"

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        self.debug(f"handling {token}, context={context}")

        # Check if we're inside a formatting element
        formatting_element = context.current_parent.find_ancestor(lambda n: n.tag_name in FORMATTING_ELEMENTS)
        if formatting_element:
            self.debug(f"Found formatting element ancestor: {formatting_element}")
            # Move up to formatting element's parent
            context.current_parent = formatting_element.parent

            # Create button at same level
            new_button = Node("button", token.attributes)
            context.current_parent.append_child(new_button)

            # Re-open formatting element inside button
            new_formatting = Node(formatting_element.tag_name, formatting_element.attributes.copy())
            new_button.append_child(new_formatting)
            context.current_parent = new_formatting
            return True

        # Handle normally if not in formatting element
        new_button = Node("button", token.attributes)
        context.current_parent.append_child(new_button)
        context.current_parent = new_button
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "button"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        button = context.current_parent.find_ancestor("button")
        if button:
            context.current_parent = button.parent
        return True


class MenuitemElementHandler(TagHandler):
    """Handles menuitem elements with special behaviors"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle li tags when inside menuitem to auto-close menuitem
        if tag_name == "li":
            # Check if we're anywhere inside a menuitem
            menuitem_ancestor = context.current_parent.find_ancestor("menuitem")
            if menuitem_ancestor:
                return True
        return tag_name == "menuitem"

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling {tag_name}")

        # Special case: li tag when inside menuitem should auto-close menuitem
        if tag_name == "li":
            menuitem_ancestor = context.current_parent.find_ancestor("menuitem")
            if menuitem_ancestor:
                # Check if the menuitem is inside an li - if so, auto-close
                li_ancestor = menuitem_ancestor.find_ancestor("li")
                if li_ancestor:
                    self.debug(f"Auto-closing menuitem {menuitem_ancestor} for new li (menuitem inside li)")
                    # Move up to menuitem's parent
                    context.current_parent = menuitem_ancestor.parent or context.current_parent
                    # Don't handle the li here, let ListTagHandler handle it
                    return False
                else:
                    self.debug("Menuitem not inside li, allowing li inside menuitem")
                    # Don't handle this, let ListTagHandler create the li inside menuitem
                    return False

        # If we're inside a select, ignore menuitem (stray tag)
        if context.current_parent.find_ancestor("select"):
            self.debug("Ignoring menuitem inside select")
            return True

        # Create the menuitem element
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node  # Set as current parent to contain children
        self.debug(f"Created menuitem: {new_node}")

        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "menuitem"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling end tag {token.tag_name}")

        # Find the nearest menuitem ancestor
        menuitem = context.current_parent.find_ancestor("menuitem")
        if menuitem:
            self.debug(f"Found menuitem ancestor: {menuitem}")

            # Check if we're directly inside the menuitem or nested deeper
            if context.current_parent == menuitem:
                # We're directly inside menuitem, close it
                context.current_parent = menuitem.parent or context.current_parent
                return True
            else:
                # We're nested inside menuitem, check the current element
                current_tag = context.current_parent.tag_name
                if current_tag == "p":
                    # Special case for <p> - treat </menuitem> as stray to keep content flowing
                    self.debug("Inside <p>, treating </menuitem> as stray end tag - ignoring")
                    return True
                else:
                    # For other elements, close the menuitem normally
                    self.debug(f"Inside <{current_tag}>, closing menuitem")
                    context.current_parent = menuitem.parent or context.current_parent
                    return True

        # No menuitem found, treat as stray end tag
        self.debug("No menuitem ancestor found, treating as stray end tag")
        return True
