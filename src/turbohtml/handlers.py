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
    RAWTEXT_ELEMENTS,
    SVG_CASE_SENSITIVE_ELEMENTS,
    TABLE_ELEMENTS,
    VOID_ELEMENTS,
)
from turbohtml.context import ParseContext, ParserState
from turbohtml.node import Node
from turbohtml.tokenizer import HTMLToken


class ParserInterface(Protocol):
    """Interface that handlers expect from parser"""

    def debug(self, message: str, indent: int = 4) -> None: ...

    body_node: "Node"
    head_node: "Node"
    root: "Node"


class TagHandler:
    """Base class for tag-specific handling logic"""

    def __init__(self, parser: ParserInterface):
        self.parser = parser

    def debug(self, message: str, indent: int = 4) -> None:
        """Delegate debug to parser"""
        self.parser.debug(message, indent)

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return False

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", has_more_content: bool
    ) -> bool:
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
    """Handles all regular text content"""

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        return True

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        self.debug(f"TextHandler: handling text '{text}' in state {context.state}")
        self.debug(f"TextHandler: current parent is {context.current_parent}")

        # Skip text nodes in head unless they're only whitespace, but not in RAWTEXT mode
        if (
            not text.strip()
            and self._is_in_head(context.current_parent)
            and context.state != ParserState.RAWTEXT
        ):
            self.debug("TextHandler: skipping whitespace in head")
            return True

        # Try to merge with previous text node if possible
        last_child = (
            context.current_parent.children[-1]
            if context.current_parent.children
            else None
        )
        self.debug(f"TextHandler: last child is {last_child}")

        if last_child and last_child.tag_name == "#text":
            self.debug(
                f"TextHandler: merging with previous text node '{last_child.text_content}'"
            )
            last_child.text_content += text
            self.debug(f"TextHandler: merged result '{last_child.text_content}'")
        else:
            # Create new text node
            self.debug("TextHandler: creating new text node")
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            self.debug(f"TextHandler: created node with content '{text}'")
        return True

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
        if (
            context.current_parent.children
            and context.current_parent.children[-1].tag_name == "#text"
        ):
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
        return tag_name in FORMATTING_ELEMENTS

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        # Create new formatting element
        new_element = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_element)
        context.current_parent = new_element
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in FORMATTING_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"FormattingElementHandler: handling {token}, context={context}")

        # Check if we're inside an active block from adoption agency
        if context.current_parent and context.current_parent.tag_name == "div":
            # If we're inside a block, stay there
            self.debug(f"Inside block {context.current_parent}, staying in block")
            return True

        # Normal formatting element handling
        current = context.current_parent.find_ancestor(token.tag_name)
        if current and current.parent:
            context.current_parent = current.parent
            return True
        return False


class SelectTagHandler(TagHandler):
    """Handles select, option, optgroup and hr elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle these tags directly
        if tag_name in ("select", "option", "optgroup"):
            return True

        # Also handle hr if we're inside a select
        if tag_name == "hr" and context.current_parent.find_ancestor("select"):
            return True

        return False

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        tag_name = token.tag_name

        if tag_name == "hr":
            # Move back to select level
            select = context.current_parent.find_ancestor("select")
            if select:
                new_node = Node(tag_name, token.attributes)
                select.append_child(new_node)
                return True
            return False

        # If we're in an option and get a new option/optgroup, close the current option first
        if (
            tag_name in ("option", "optgroup")
            and context.current_parent.tag_name == "option"
        ):
            context.current_parent = context.current_parent.parent

        # Create the new node
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)

        # Only update current_parent for non-void elements
        if tag_name not in ("hr",):
            context.current_parent = new_node
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("select", "option", "optgroup")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        current = context.current_parent.find_ancestor(tag_name)

        if current:
            context.current_parent = current.parent or self.parser.body_node
            return True
        return False


class ParagraphTagHandler(TagHandler):
    """Handles paragraph elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "p"

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", has_more_content: bool
    ) -> bool:
        self.debug(f"ParagraphTagHandler: handling {token}, context={context}")

        # Close any open paragraphs
        current_p = context.current_parent.find_ancestor("p")
        if current_p:
            self.debug(f"Found existing paragraph, moving to its parent")
            context.current_parent = current_p.parent or self.parser.body_node

        # Create new paragraph at the current level
        new_p = Node("p", token.attributes)
        self.debug(f"Created new paragraph node: {new_p}")

        # Handle formatting elements
        parent, formatting_elements = AdoptionAgencyHelper.handle_formatting_boundary(
            context, self.parser
        )

        # Append the new paragraph to the appropriate parent
        if formatting_elements:
            parent.append_child(new_p)
        else:
            context.current_parent.append_child(new_p)

        # Update current parent to the new paragraph
        context.current_parent = new_p
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "p"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        current = context.current_parent.find_ancestor("p")
        if current and current.parent:
            context.current_parent = current.parent
            return True
        return False


class TableTagHandler(TagHandler):
    """Handles table-related elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle tags if we're inside a select element
        if context.current_parent.find_ancestor("select"):
            return False

        # Handle any tag when in table context
        if context.state == ParserState.IN_TABLE:
            self.debug(f"Handling {tag_name} in table context")
            return True

        return tag_name in (
            "table",
            "td",
            "th",
            "tr",
            "tbody",
            "thead",
            "tfoot",
            "caption",
            "colgroup",
        )

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        if token.tag_name == "table":
            # Create new table
            new_table = Node("table", token.attributes)
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

            if token.tag_name == "template":
                # Create template node and append to current parent
                new_node = Node(token.tag_name, token.attributes)
                context.current_parent.append_child(new_node)
                context.current_parent = new_node
                return True

            if token.tag_name in ["td", "th"]:
                # First ensure we have a tbody and tr if not in template
                if context.current_parent.tag_name != "template":
                    tbody = self._ensure_tbody(table)
                    tr = self._ensure_tr(tbody)
                    parent = tr
                else:
                    parent = context.current_parent

                # Create the cell
                new_cell = Node(token.tag_name, token.attributes)
                parent.append_child(new_cell)
                context.current_parent = new_cell
                return True

            elif token.tag_name == "tr":
                # If in template, append directly to it
                if context.current_parent.tag_name == "template":
                    parent = context.current_parent
                else:
                    # Only create tbody when we have rows
                    parent = self._ensure_tbody(table)

                new_tr = Node("tr", token.attributes)
                parent.append_child(new_tr)
                context.current_parent = new_tr
                return True

            # Check if we're inside a table cell
            in_cell = context.current_parent.tag_name in [
                "td",
                "th",
            ] or context.current_parent.find_ancestor(
                lambda n: n.tag_name in ["td", "th"]
            )

            if in_cell:
                # Inside a cell, handle normally without foster parenting
                if token.tag_name in FORMATTING_ELEMENTS:
                    new_node = Node(token.tag_name, token.attributes)
                    context.current_parent.append_child(new_node)
                    context.current_parent = new_node
                    return True
            else:
                # Not in a cell, foster parent non-table elements
                if token.tag_name not in TABLE_ELEMENTS:
                    if table.parent:
                        new_node = Node(token.tag_name, token.attributes)
                        table_index = table.parent.children.index(table)
                        table.parent.children.insert(table_index, new_node)
                        context.current_parent = new_node
                    return True

        return False

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        return context.state == ParserState.IN_TABLE

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        if not self.should_handle_text(text, context):
            return False

        # If we're inside a table cell, append text directly
        current_cell = context.current_parent.find_ancestor(
            lambda n: n.tag_name in ["td", "th"]
        )
        if current_cell:
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # If we're inside a foster-parented element, append text to it
        table = context.current_table
        if not table or not table.parent:
            return False

        # Check if current_parent is already foster-parented
        if context.current_parent != table:
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # Otherwise foster parent the text
        text_node = Node("#text")
        text_node.text_content = text

        table_index = table.parent.children.index(table)

        # Try to append to previous text node if possible
        if (
            table_index > 0
            and table.parent.children[table_index - 1].tag_name == "#text"
        ):
            table.parent.children[table_index - 1].text_content += text
        else:
            table.parent.children.insert(table_index, text_node)

        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle any end tag in table context to maintain proper structure
        return context.state == ParserState.IN_TABLE

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name

        if tag_name == "table":
            if context.current_table:
                context.current_parent = context.current_table.parent
                context.current_table = None
                context.state = ParserState.IN_BODY
                return True

        elif tag_name == "template":
            # Find nearest template ancestor
            template = context.current_parent.find_ancestor("template")
            if template and template.parent:
                context.current_parent = template.parent
                return True

        elif tag_name in TABLE_ELEMENTS:
            if tag_name == "tr":
                tbody = context.current_parent.find_ancestor("tbody")
                if tbody:
                    context.current_parent = tbody
                    return True
            elif tag_name in ["td", "th"]:
                tr = context.current_parent.find_ancestor("tr")
                if tr:
                    context.current_parent = tr
                    return True

        else:
            # Check if element is in scope
            if not context.current_parent.find_ancestor(
                tag_name, stop_at_boundary=True
            ):
                return True  # Ignore out-of-scope closing tags

            # Find the element to close
            temp_parent = context.current_parent.find_ancestor(tag_name)

            if temp_parent:
                # Move to parent's context
                target_parent = temp_parent.parent or self.parser.body_node

                # Special handling for table elements
                if tag_name in TABLE_ELEMENTS:
                    # Find first non-formatting ancestor
                    target_parent = target_parent.find_ancestor(
                        lambda n: n.tag_name not in FORMATTING_ELEMENTS
                    )

                # If we're still in a table cell or template after closing the tag, stay there
                current_container = target_parent.find_ancestor(
                    lambda n: n.tag_name in ["td", "th", "template"]
                )
                if current_container:
                    context.current_parent = target_parent
                    context.current_context = context.current_context
                else:
                    # If we've moved outside, ensure we stay in the table
                    context.current_parent = context.current_table
                return True

        return False

    def _ensure_tbody(self, table: Node) -> Node:
        """Ensure table has a tbody, create if needed"""
        for child in table.children:
            if child.tag_name == "tbody":
                return child

        tbody = Node("tbody", {})
        table.append_child(tbody)
        return tbody

    def _ensure_tr(self, tbody: Node) -> Node:
        """Ensure tbody has a tr, create if needed"""
        for child in tbody.children:
            if child.tag_name == "tr":
                return child

        tr = Node("tr", {})
        tbody.append_child(tr)
        return tr


class FormTagHandler(TagHandler):
    """Handles form-related elements (form, input, button, etc.)"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("form", "input", "button", "textarea", "select", "label")

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        tag_name = token.tag_name

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
            context.current_parent = current.parent or self.parser.body_node
            if tag_name == "form":
                context.has_form = False

        return True


class ListTagHandler(TagHandler):
    """Handles list-related elements (ul, ol, li)"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("ul", "ol", "li")

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        self.debug(f"Current parent before: {context.current_parent}")
        tag_name = token.tag_name

        if tag_name == "li":
            self.debug(
                f"Handling li tag, current parent is {context.current_parent.tag_name}"
            )

            # If we're in another li, move up to its parent first
            if context.current_parent.tag_name == "li":
                context.current_parent = (
                    context.current_parent.parent or self.parser.body_node
                )

            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            self.debug(f"Created new li: {new_node}, parent: {context.current_parent}")
            return True

        # Handle ul/ol elements
        if tag_name in ("ul", "ol"):
            self.debug(f"Handling {tag_name} tag")
            # Find nearest li ancestor to properly nest the list
            li_ancestor = context.current_parent.find_ancestor("li")
            if li_ancestor:
                context.current_parent = li_ancestor

            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node
            # Store the list container in the context for later reference
            context.current_list = new_node
            self.debug(f"Created new {tag_name}: {new_node}")
            return True

        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        self.debug(f"Checking if should handle end tag: {tag_name}")
        return tag_name in ("ul", "ol", "li")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"Current parent before end: {context.current_parent}")

        if token.tag_name in ("ul", "ol"):
            self.debug(f"Handling end tag for {token.tag_name}")
            # First try to use the current_list from context
            list_container = getattr(context, "current_list", None)
            self.debug(f"Found list container from context: {list_container}")

            # If not found in context, search up the tree
            if not list_container:
                current = context.current_parent
                while current and current != self.parser.root:
                    self.debug(f"Checking ancestor: {current}")
                    if current.tag_name == token.tag_name:
                        list_container = current
                        self.debug(
                            f"Found list container in ancestors: {list_container}"
                        )
                        break
                    current = current.parent
                    self.debug(f"Moving up to parent: {current}")

            if list_container:
                # First close any open li elements inside the list
                if context.current_parent.tag_name == "li":
                    li = context.current_parent.find_ancestor("li")
                    if li:
                        self.debug(f"Closing li inside list: {li}")
                        context.current_parent = li.parent

                # Move to the list container's parent
                self.debug(
                    f"Moving to list container's parent: {list_container.parent}"
                )
                context.current_parent = list_container.parent
                # Clear the current list reference
                context.current_list = None
                return True
            self.debug("No matching list container found")

        elif token.tag_name == "li":
            self.debug(f"Handling end tag for li")
            # Find and close the nearest li
            li = context.current_parent.find_ancestor("li")
            if li:
                self.debug(f"Found li to close: {li}, moving to parent: {li.parent}")
                context.current_parent = li.parent
                return True
            self.debug("No matching li found")

        self.debug(f"No handler for end tag {token.tag_name}")
        return False


class HeadingTagHandler(TagHandler):
    """Handles heading elements (h1-h6)"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        # Check if we're in a heading (includes current node and ancestors)
        current = context.current_parent.find_ancestor(
            lambda node: node.tag_name in HEADING_ELEMENTS
        )
        if current:
            self.debug(f"Found existing heading, moving to its parent")
            context.current_parent = current.parent or self.parser.body_node

        # Create and append the new heading
        new_node = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        current = context.current_parent.find_ancestor(token.tag_name)
        if current:
            context.current_parent = current.parent or self.parser.body_node
            return True
        return False


class RawtextTagHandler(TagHandler):
    """Handles rawtext elements like script, style, title, etc."""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in RAWTEXT_ELEMENTS

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        tag_name = token.tag_name

        # HEAD_ELEMENTS should always be in head unless explicitly in body
        if tag_name in HEAD_ELEMENTS and context.state != ParserState.IN_BODY:
            new_node = Node(tag_name, token.attributes)
            self.parser.head_node.append_child(new_node)
            context.current_parent = new_node
        else:
            # Other elements stay in their current context
            new_node = Node(tag_name, token.attributes)
            context.current_parent.append_child(new_node)
            context.current_parent = new_node

        # Switch to RAWTEXT state and let tokenizer handle the content
        context.state = ParserState.RAWTEXT
        self.parser.tokenizer.start_rawtext(tag_name)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in RAWTEXT_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        if (
            context.state == ParserState.RAWTEXT
            and token.tag_name == context.current_parent.tag_name
        ):
            # Move script/title to head if not explicitly in body
            if token.tag_name in HEAD_ELEMENTS and context.state != ParserState.IN_BODY:
                # Move the element to head if it's not already there
                if context.current_parent.parent != self.parser.head_node:
                    self.parser.head_node.append_child(context.current_parent)

                # Add space in head only if we have trailing whitespace
                if "trailing_space" in token.attributes:
                    text_node = Node("#text")
                    text_node.text_content = " "
                    self.parser.head_node.append_child(text_node)

            # Switch to body state
            context.state = ParserState.IN_BODY
            context.current_parent = self.parser.body_node
            return True
        return False


class ButtonTagHandler(TagHandler):
    """Handles button elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "button"

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        self.debug(f"Current parent: {context.current_parent}", indent=0)
        new_node = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.current_parent = new_node
        self.debug(f"New current parent: {context.current_parent}")
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle all end tags when inside a button
        button = context.current_parent.find_ancestor("button")
        return bool(button)

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"Current parent: {context.current_parent}")
        button = context.current_parent.find_ancestor("button")
        self.debug(f"Found button ancestor: {button}")

        # Only allow closing the button itself
        if token.tag_name != "button":
            self.debug(f"Inside button, ignoring end tag for {token.tag_name}")
            return True

        if button:
            self.debug("Merging text nodes in button")
            text_content = ""
            new_children = []
            for child in button.children:
                if child.tag_name == "#text":
                    text_content += child.text_content
                else:
                    new_children.append(child)

            if text_content:
                self.debug(f"Creating merged text node with content: {text_content}")
                text_node = Node("#text")
                text_node.text_content = text_content
                new_children.insert(0, text_node)

            button.children = new_children
            context.current_parent = button.parent or self.parser.body_node
            self.debug(f"New current parent: {context.current_parent}")
            return True
        return False

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        return True

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        self.debug(f"Current parent: {context.current_parent}")
        button = context.current_parent.find_ancestor("button")
        self.debug(f"Found button ancestor: {button}")
        if button:
            if button.children and button.children[-1].tag_name == "#text":
                self.debug("Appending to existing text node")
                button.children[-1].text_content += text
            else:
                self.debug("Creating new text node")
                text_node = Node("#text")
                text_node.text_content = text
                button.append_child(text_node)
            self.debug(f"Button children after text handling: {button.children}")
            return True
        self.debug("No button ancestor found, not handling text")
        return False


class VoidElementHandler(TagHandler):
    """Handles void elements that can't have children"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle void elements inside select
        if context.current_parent.find_ancestor("select"):
            return False

        return tag_name in VOID_ELEMENTS

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        # If we're in a paragraph and this is a block element, close the paragraph first
        if context.current_parent.tag_name == "p" and token.tag_name in BLOCK_ELEMENTS:
            # Move up to paragraph's parent
            context.current_parent = (
                context.current_parent.parent or self.parser.body_node
            )

        # Create the void element at the current level
        new_node = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_node)

        # If this is an hr, create a new paragraph after it
        if token.tag_name == "hr":
            self.debug("Creating new paragraph after hr")
            new_p = Node("p", {})
            context.current_parent.append_child(new_p)
            context.current_parent = new_p

        return True


class AutoClosingTagHandler(TagHandler):
    """Handles auto-closing behavior for certain tags"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in AUTO_CLOSING_TAGS

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        self.debug(f"Checking auto-closing rules for {token.tag_name}")
        current = context.current_parent
        if not current:
            current = context.current_parent = self.parser.body_node
        self.debug(f"Current parent: {current}")

        # If we're starting a block element inside a formatting element
        if token.tag_name in BLOCK_ELEMENTS and self._find_formatting_ancestor(current):

            # Find all formatting elements up to the block
            formatting_elements = []
            temp = current
            while temp and temp.tag_name != "body":
                if temp.tag_name in FORMATTING_ELEMENTS:
                    formatting_elements.insert(0, temp)
                temp = temp.parent

            self.debug(f"Found formatting elements: {formatting_elements}")

            if not formatting_elements:
                self.debug("No formatting elements found")
                return False

            # Get the formatting element we're currently in
            current_fmt = formatting_elements[-1]
            self.debug(f"Current formatting element: {current_fmt}")

            # Create block inside current formatting element
            new_block = Node(token.tag_name, token.attributes)
            current_fmt.append_child(new_block)
            self.debug(
                f"Created block {new_block} inside formatting element {current_fmt}"
            )

            # Move to the block
            context.current_parent = new_block
            self.debug(f"New current parent: {context.current_parent}")

            return True

        return False

    def _find_formatting_ancestor(self, node: Node) -> Optional[Node]:
        """Find the nearest formatting element ancestor"""
        self.debug(f"Looking for formatting ancestor starting from {node}")
        current = node
        seen = set()  # Prevent infinite loops
        while current and current.tag_name != "body" and current not in seen:
            seen.add(current)
            if current.tag_name in FORMATTING_ELEMENTS:
                self.debug(f"Found formatting ancestor: {current}")
                return current
            current = current.parent
        self.debug("No formatting ancestor found")
        return None

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle end tags for elements that close when their parent closes
        return tag_name in CLOSE_ON_PARENT_CLOSE or tag_name in (
            "tr",
            "td",
            "th",
        )  # Add table elements

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"AutoClosingTagHandler.handle_end: {token.tag_name}")

        if token.tag_name == "tr":
            # First find the tr element
            tr = context.current_parent.find_ancestor("tr")
            if tr:
                # Close everything up to the tr
                context.current_parent = tr.parent or self.parser.body_node
                context.state = ParserState.IN_TABLE
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


class AnchorTagHandler(TagHandler):
    """Special handling for <a> tags"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "a"

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int
    ) -> bool:
        # Find any existing anchor elements in the stack
        existing_anchor = context.current_parent.find_ancestor("a")
        if existing_anchor:
            # Move content before the anchor to a new anchor
            if existing_anchor.children:
                # Create new anchor with same attributes
                new_anchor = Node("a", existing_anchor.attributes.copy())

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
        new_anchor = Node("a", token.attributes)
        context.current_parent.append_child(new_anchor)
        context.current_parent = new_anchor
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "a"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        current_anchor = context.current_parent.find_ancestor("a")
        if not current_anchor or not current_anchor.parent:
            return False

        # Move to parent of anchor
        context.current_parent = current_anchor.parent
        return True


class AdoptionAgencyHelper:
    """Helper class for implementing the adoption agency algorithm"""

    @staticmethod
    def handle_formatting_boundary(
        context: "ParseContext", parser: "ParserInterface"
    ) -> Tuple[Node, List[Node]]:
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
            temp = temp.parent

        parser.debug(
            f"Found formatting elements: {[f.tag_name for f in formatting_elements]}"
        )

        if not formatting_elements:
            return context.current_parent, []

        return formatting_elements[-1], formatting_elements


class ForeignTagHandler(TagHandler):
    """Handles SVG and other foreign element contexts"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Handle any tag when in SVG or MathML context
        if context.current_context in ("svg", "math"):
            return True
        # Also handle svg and math tags to enter those contexts
        return tag_name in ("svg", "math")

    def handle_start(
        self, token: "HTMLToken", context: "ParseContext", has_more_content: bool
    ) -> bool:
        tag_name = token.tag_name
        tag_name_lower = tag_name.lower()

        if context.current_context == "math":
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

        # For other end tags, just move up the tree if possible
        if context.current_parent.parent:
            context.current_parent = context.current_parent.parent
        return True

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        # Handle text in annotation-xml specially
        return (
            context.current_context in ("svg", "math")
            and context.current_parent.tag_name == "math annotation-xml"
        )

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        if context.current_parent.tag_name == "math annotation-xml":
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True
        return False
