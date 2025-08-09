import re
from typing import List, Optional, Protocol, Tuple

from turbohtml.constants import (
    AUTO_CLOSING_TAGS,
    BLOCK_ELEMENTS,
    CLOSE_ON_PARENT_CLOSE,
    FORMATTING_ELEMENTS,
    HEAD_ELEMENTS,
    HEADING_ELEMENTS,
    HTML_ELEMENTS,
    HTML_BREAK_OUT_ELEMENTS,
    MATHML_ELEMENTS,
    SVG_CASE_SENSITIVE_ATTRIBUTES,
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

    def _is_in_template_content(self, context: "ParseContext") -> bool:
        """Check if we're inside actual template content (not just a user <content> tag)"""
        # Check if current parent is content node
        if (context.current_parent and 
            context.current_parent.tag_name == "content" and 
            context.current_parent.parent and 
            context.current_parent.parent.tag_name == "template"):
            return True
        
        # Check if any ancestor is template content
        return (context.current_parent and 
                context.current_parent.has_ancestor_matching(
                    lambda n: (n.tag_name == "content" and 
                              n.parent and 
                              n.parent.tag_name == "template")
                ))

    # Common helper methods to reduce duplication
    def _create_element(self, token: "HTMLToken") -> "Node":
        """Create a new element node from a token"""
        return Node(token.tag_name, token.attributes)

    def _create_and_append_element(self, token: "HTMLToken", context: "ParseContext") -> "Node":
        """Create a new element and append it to current parent"""
        new_node = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        return new_node

    def _is_in_select(self, context: "ParseContext") -> bool:
        """Check if we're inside a select element"""
        return context.current_parent.is_inside_tag("select")

    def _is_in_table_cell(self, context: "ParseContext") -> bool:
        """Check if we're inside a table cell (td or th)"""
        return context.current_parent.find_first_ancestor_in_tags(["td", "th"]) is not None

    def _move_to_parent_of_ancestor(self, context: "ParseContext", ancestor: "Node") -> None:
        """Move current_parent to the parent of the given ancestor"""
        context.move_to_ancestor_parent(ancestor)

    def _should_foster_parent_in_table(self, context: "ParseContext") -> bool:
        """Check if element should be foster parented due to table context"""
        return (context.document_state == DocumentState.IN_TABLE
                and not self._is_in_cell_or_caption(context))

    def _foster_parent_before_table(self, token: "HTMLToken", context: "ParseContext") -> "Node":
        """Foster parent an element before the current table"""
        table = self.parser.find_current_table(context)
        if table and table.parent:
            new_node = self._create_element(token)
            table_index = table.parent.children.index(table)
            table.parent.children.insert(table_index, new_node)
            new_node.parent = table.parent
            return new_node
        return None

    def _is_in_table_context(self, context: "ParseContext") -> bool:
        """Check if we're in any table-related context"""
        return context.document_state in (
            DocumentState.IN_TABLE,
            DocumentState.IN_TABLE_BODY,
            DocumentState.IN_ROW,
            DocumentState.IN_CAPTION
        )

    def _is_in_cell_or_caption(self, context: "ParseContext") -> bool:
        """Check if we're inside a table cell (td/th) or caption"""
        return bool(context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th", "caption")))

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


class TemplateAwareHandler(TagHandler):
    """Mixin for handlers that need to skip template content"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        if self._is_in_template_content(context):
            return False
        return self._should_handle_start_impl(tag_name, context)

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
        """Override this instead of should_handle_start"""
        return False


class SelectAwareHandler(TagHandler):
    """Mixin for handlers that need to avoid handling inside select elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        if self._is_in_select(context):
            return False
        return self._should_handle_start_impl(tag_name, context)

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
        """Override this instead of should_handle_start"""
        return False


class SimpleElementHandler(TagHandler):
    """Base handler for simple elements that create nodes and may nest"""

    def __init__(self, parser: ParserInterface, handled_tags: tuple):
        super().__init__(parser)
        self.handled_tags = handled_tags

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        new_node = self._create_and_append_element(token, context)
        
        if not self._is_void_element(token.tag_name):
            context.enter_element(new_node)
            # Ensure formatting elements are tracked in the open elements stack
            context.open_elements.push(new_node)
        return True

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        ancestor = context.current_parent.find_ancestor(token.tag_name)
        if ancestor:
            self._move_to_parent_of_ancestor(context, ancestor)
        return True

    def _is_void_element(self, tag_name: str) -> bool:
        """Override in subclasses to specify void elements"""
        return False


class AncestorCloseHandler(TagHandler):
    """Mixin for handlers that close by finding ancestor and moving to its parent"""

    def handle_end_by_ancestor(self, token: "HTMLToken", context: "ParseContext", 
                              tag_name: str = None, stop_at_boundary: bool = False) -> bool:
        """Standard pattern: find ancestor by tag name and move to its parent"""
        search_tag = tag_name or token.tag_name
        ancestor = context.current_parent.find_ancestor(search_tag, stop_at_boundary=stop_at_boundary)
        if ancestor:
            context.move_to_element_with_fallback(ancestor.parent, context.current_parent)
            self.debug(f"Found {search_tag} ancestor, moved to parent")
            return True
        self.debug(f"No {search_tag} ancestor found")
        return False


class TemplateTagHandler(TagHandler):
    """Handle <template> elements by creating a 'template' node with a dedicated 'content' subtree.

    Fundamental behavior per spec: contents are parsed in a separate tree (DocumentFragment). We approximate
    this by creating a 'template' element node and a child 'content' node; all children between <template>
    and its matching end tag are placed under the 'content' node. This isolated subtree should NOT influence
    outer foster parenting or formatting reconstruction.
    """

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Do not treat <template> specially when in foreign (SVG/MathML) contexts; let foreign handlers manage it
        if context.current_context in ("math", "svg"):
            return False
        return tag_name == "template"

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        # If we're in frameset parsing context, treat <template> as transparent (contents go to parent)
        from turbohtml.context import DocumentState
        if context.document_state in (DocumentState.IN_FRAMESET, DocumentState.AFTER_FRAMESET):
            # Do not create a template/content; just parse its children in-place
            if hasattr(context, "template_transparent_depth"):
                context.template_transparent_depth += 1
            return True
        # Determine insertion parent following simplified WHATWG rules:
        # 1. If in the initial/head/after-head phase and template appears at top-level (parent is <html> or <head>), insert into <head>
        # 2. If after body (AFTER_BODY states) insert into existing <body>
        # 3. Otherwise (including inside flow/content), insert at current_parent (do NOT hoist to body)
        insertion_parent = context.current_parent
        html_node = self.parser.html_node
        head_node = None
        body_node = None
        if html_node:
            for child in html_node.children:
                if child.tag_name == "head":
                    head_node = child
                elif child.tag_name == "body":
                    body_node = child
        try:
            from turbohtml.context import DocumentState
            state = context.document_state
            at_top_level = context.current_parent in (html_node, head_node)
            if body_node and state.name.startswith("AFTER_BODY"):
                insertion_parent = body_node
            elif head_node and at_top_level and state in (DocumentState.INITIAL, DocumentState.IN_HEAD, DocumentState.AFTER_HEAD):
                insertion_parent = head_node
            # Else leave insertion_parent as current_parent
        except Exception:
            pass
        # Create template element
        template_node = Node("template", token.attributes)
        insertion_parent.append_child(template_node)
        # Create content container
        content_node = Node("content")
        template_node.append_child(content_node)
        # Enter content node for subsequent children
        context.enter_element(template_node)
        context.open_elements.push(template_node)
        # Keep content node off the open elements stack to avoid interfering with scope algorithms
        context.enter_element(content_node)
        # Record outer document state (for possible future nuanced handling)
        # Persist outer document state for potential restoration; store in attributes dict to avoid dynamic attribute issues
        try:
            saved_state = getattr(context, "document_state", None)
            if saved_state is not None:
                template_node.attributes.append(NodeAttribute(name="data-saved-state", value=saved_state.name))
        except Exception:
            pass
        if hasattr(context, "template_content_depth"):
            context.template_content_depth += 1
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        if context.current_context in ("math", "svg"):
            return False
        return tag_name == "template"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        # If we were treating template as transparent (frameset context), just consume the end tag
        from turbohtml.context import DocumentState
        if context.document_state in (DocumentState.IN_FRAMESET, DocumentState.AFTER_FRAMESET):
            if hasattr(context, "template_transparent_depth") and context.template_transparent_depth > 0:
                context.template_transparent_depth -= 1
            return True
        # Close a template: unwind any elements inside its content, then remove template from open stack
        # If currently inside the content node, move to its parent (the template)
        if (
            context.current_parent.tag_name == "content"
            and context.current_parent.parent
            and context.current_parent.parent.tag_name == "template"
        ):
            context.move_to_element_with_fallback(context.current_parent.parent, context.current_parent)

        # Pop elements until we reach the template (simplified implied end tag handling inside template)
        while context.current_parent and context.current_parent.tag_name not in ("template",):
            if context.current_parent.parent:
                context.move_to_element_with_fallback(context.current_parent.parent, context.current_parent)
            else:
                break

        if context.current_parent and context.current_parent.tag_name == "template":
            # Remove from open elements if present
            template_node = context.current_parent
            if context.open_elements.contains(template_node):
                context.open_elements.remove_element(template_node)
            # Move insertion point to the template's parent (outside the template subtree)
            template_parent = template_node.parent or template_node
            context.move_to_element_with_fallback(template_parent, template_node)
            # Restore previous document state if saved (currently advisory)
            saved_state = getattr(template_node, "_saved_document_state", None)
            if saved_state is not None:
                # Only restore if parser hasn't already transitioned due to other logic
                try:
                    if hasattr(context, "document_state") and saved_state != context.document_state:
                        self.parser.transition_to_state(context, saved_state, template_parent)
                except Exception:
                    pass
            if hasattr(context, "template_content_depth") and context.template_content_depth > 0:
                context.template_content_depth -= 1
        return True


class TemplateContentFilterHandler(TagHandler):
    """Filter/adjust tokens while inside <template> content.

    Inside template content, many table-structure tokens are not supposed to trigger
    HTML table construction; they are either ignored (caption, colgroup, tbody, thead, tfoot, table)
    or treated as generic elements (td, th, tr, col). Also ignore stray html/head/body tags.
    This handler must run before table handling.
    """

    IGNORED_START = {"html", "head", "body", "frameset", "frame"}
    # Treat table & select related and nested template triggers as plain generics (no special algorithms)
    GENERIC_AS_PLAIN = {"table", "thead", "tbody", "tfoot", "caption", "colgroup", "tr", "td", "th", "col", "option", "optgroup"}

    def _in_template_content(self, context: "ParseContext") -> bool:
        # Mirror parser._is_in_template_content: allow being inside descendants of content
        p = context.current_parent
        if not p:
            return False
        if (p.tag_name == "content" and p.parent and p.parent.tag_name == "template"):
            return True
        return p.has_ancestor_matching(lambda n: n.tag_name == "content" and n.parent and n.parent.tag_name == "template")

    def _current_content_boundary(self, context: "ParseContext") -> Optional["Node"]:
        node = context.current_parent
        while node:
            if node.tag_name == "content" and node.parent and node.parent.tag_name == "template":
                return node
            node = node.parent
        return None

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        if not self._in_template_content(context):
            return False
        # In foreign (SVG/MathML) contexts inside template content, let foreign handlers manage tags
        if context.current_context in ("math", "svg"):
            return False
        # Intercept all start tags while inside template content to avoid outer promotions
        return True

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        if token.tag_name in self.IGNORED_START:
            # frameset and friends are ignored inside template content; however,
            # if we're currently inside a table-ish container, move back to the content boundary first
            tableish = {"table", "thead", "tfoot", "tbody", "tr", "td", "th", "col", "colgroup"}
            if context.current_parent and context.current_parent.tag_name in tableish:
                boundary = self._current_content_boundary(context)
                if boundary:
                    context.move_to_element(boundary)
            return True  # Ignore entirely
        if token.tag_name == "template":
            # If inside a foreign subtree (SVG/MathML), do not treat as HTML template
            # Detect by current_context or ancestor tag names starting with 'svg ' or 'math '
            if (context.current_context in ("math", "svg") or
                context.current_parent.has_ancestor_matching(lambda n: n.tag_name.startswith("svg ") or n.tag_name == "svg" or n.tag_name.startswith("math ") or n.tag_name == "math")):
                return False
            # Create an actual nested template element with its own content fragment
            template_node = Node("template", token.attributes)
            context.current_parent.append_child(template_node)
            content_node = Node("content")
            template_node.append_child(content_node)
            # Enter template then its content
            context.enter_element(template_node)
            context.open_elements.push(template_node)
            context.enter_element(content_node)
            return True
        boundary = self._current_content_boundary(context) or context.current_parent

        # If a table-related tag appears while nested inside a non-table element,
        # normalize insertion to the content boundary first
        table_related = {"table", "thead", "tbody", "tfoot", "caption", "colgroup", "col", "tr", "td", "th"}
        if (token.tag_name in table_related and
            context.current_parent is not boundary and
            context.current_parent.tag_name not in {"tr", "td", "th"}):
            context.move_to_element(boundary)

        # If the last structural entry was a col/colgroup, drop unexpected content that follows
        last_child = boundary.children[-1] if boundary and boundary.children else None
        if last_child and last_child.tag_name in {"col", "colgroup"}:
            # After a <col> or <colgroup>, ignore subsequent content inside template content,
            # except allow another <col>
            allowed_after_col = {"col"}
            if token.tag_name not in allowed_after_col:
                return True

        # Minimal handling for rows and cells inside template content
        if token.tag_name in ("td", "th"):
            if context.current_parent.tag_name == "tr":
                cell = Node(token.tag_name, token.attributes)
                context.current_parent.append_child(cell)
                context.enter_element(cell)
                return True
            if context.current_parent is boundary:
                # If previous child was a tr, start a new tr for the next cell; else, place directly
                prev = boundary.children[-1] if boundary.children else None
                if prev and prev.tag_name == "tr":
                    new_tr = Node("tr")
                    boundary.append_child(new_tr)
                    context.enter_element(new_tr)
                    cell = Node(token.tag_name, token.attributes)
                    new_tr.append_child(cell)
                    context.enter_element(cell)
                else:
                    cell = Node(token.tag_name, token.attributes)
                    boundary.append_child(cell)
                    context.enter_element(cell)
                return True

        if token.tag_name == "tr":
            if context.current_parent is not boundary:
                context.move_to_element(boundary)
            new_tr = Node("tr", token.attributes)
            boundary.append_child(new_tr)
            context.enter_element(new_tr)
            return True
        # If currently inside a generic table-ish context, and a non-table element arrives,
        # either ignore (for col/colgroup) or break out to content before inserting.
        tableish = {"table", "thead", "tfoot", "tbody", "tr", "td", "th", "col", "colgroup"}
        if context.current_parent.tag_name in tableish and token.tag_name not in (self.IGNORED_START | self.GENERIC_AS_PLAIN | {"template"}):
            # If inside a cell, allow generic content inside the cell; otherwise, move out to content
            if context.current_parent.tag_name in {"td", "th"}:
                pass  # keep inside cell
            elif context.current_parent.tag_name in {"col", "colgroup"}:
                return True  # Drop unexpected content after col/colgroup inside template content
            # Move up to the content boundary before inserting
            else:
                boundary2 = self._current_content_boundary(context)
                if boundary2:
                    context.move_to_element(boundary2)
        # Treat other specific tags as generic elements (no special algorithms)
        new_node = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        # Do not descend into table-structure tags; keep insertion at current parent
        do_not_enter = {"table", "thead", "tbody", "tfoot", "caption", "colgroup", "col"}
        if new_node.tag_name not in do_not_enter:
            context.enter_element(new_node)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        if not self._in_template_content(context):
            return False
        # In foreign (SVG/MathML) contexts inside template content, let foreign handlers manage tags
        if context.current_context in ("math", "svg"):
            return False
        # Intercept all end tags while inside template content so we can safely bound popping
        return True

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        if token.tag_name in self.IGNORED_START or token.tag_name == "select":
            return True
        # Handle closing of a nested template we opened here: move from content to template, then out
        if token.tag_name == "template":
            # If currently inside content of a template, move to the template node
            if (context.current_parent.tag_name == "content" and context.current_parent.parent and context.current_parent.parent.tag_name == "template"):
                context.move_to_element_with_fallback(context.current_parent.parent, context.current_parent)
            # Now move out of the template
            if context.current_parent.tag_name == "template":
                if context.open_elements.contains(context.current_parent):
                    context.open_elements.remove_element(context.current_parent)
                parent = context.current_parent.parent or context.current_parent
                context.move_to_element_with_fallback(parent, context.current_parent)
            return True
        # Close generic element: pop up until we exit the matching element,
        # but never move above the current template content boundary.
        boundary = self._current_content_boundary(context)
        # First, check if there is a matching ancestor below the boundary
        cursor = context.current_parent
        found = None
        while cursor and cursor is not boundary:
            if cursor.tag_name == token.tag_name:
                found = cursor
                break
            cursor = cursor.parent
        if not found:
            return True  # Ignore unmatched end tag inside template content
        # Move up to the found element and then step out of it
        while context.current_parent is not found and context.current_parent and context.current_parent.parent:
            context.move_to_element_with_fallback(context.current_parent.parent, context.current_parent)
        if context.current_parent is found and context.current_parent.parent:
            context.move_to_element_with_fallback(context.current_parent.parent, context.current_parent)
        return True


class TextHandler(TagHandler):
    """Default handler for text nodes"""

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        return True

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        self.debug(f"handling text '{text}' in state {context.document_state}")

    # (Removed flag-based forced reconstruction; paragraph splitting now handled
    #  by popping formatting descendants from open stack at </p> so standard
    #  reconstruction logic applies when needed.)

        # Special case: Handle malformed DOCTYPE endings that become text content
        if context.document_state == DocumentState.INITIAL and text.strip() == "]>":
            # This looks like a DOCTYPE ending that was parsed as text
            # Normalize by removing leading whitespace
            normalized_text = text.lstrip()
            self.debug(f"Normalizing DOCTYPE-like text from '{text}' to '{normalized_text}'")
            text = normalized_text

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
                    context.move_to_element(body)
                    self._append_text(text, context)
            else:
                self.debug("Parse error: non-whitespace after </body>, switching back to in body")
                body = self.parser._ensure_body_node(context)
                self.parser.transition_to_state(context, DocumentState.IN_BODY, body)
                self._append_text(text, context)
            return True

        if context.content_state == ContentState.RAWTEXT:
            self._append_text(text, context)
            return True

        # Check if we're inside template content
        if self._is_in_template_content(context):
            # Suppress text immediately following <col> or <colgroup> inside template content
            boundary = None
            current = context.current_parent
            while current:
                if current.tag_name == "content" and current.parent and current.parent.tag_name == "template":
                    boundary = current
                    break
                current = current.parent
            if boundary:
                last_child = boundary.children[-1] if boundary.children else None
                if last_child and last_child.tag_name in {"col", "colgroup"}:
                    return True
            self.debug("Text inside template content, keeping in content")
            self._append_text(text, context)
            return True

        # Handle text in AFTER_HEAD state - should transition to body
        if context.document_state == DocumentState.AFTER_HEAD:
            self.debug("In AFTER_HEAD state, handling text placement")
            
            # If it's only whitespace, place it at html level before body
            if text.isspace():
                self.debug("Whitespace-only text in AFTER_HEAD, placing at html level")
                # Check if body already exists
                body = self.parser._get_body_node()
                if body:
                    # Insert text before existing body
                    text_node = Node("#text")
                    text_node.text_content = text
                    self.parser.html_node.insert_before(text_node, body)
                    self.debug(f"Inserted whitespace before existing body: '{text}'")
                else:
                    # Add whitespace to html level, body will be created after
                    context.move_to_element(self.parser.html_node)
                    self._append_text(text, context)
                    self.debug(f"Added whitespace to html level: '{text}'")
                self.parser.transition_to_state(context, DocumentState.IN_BODY)
            else:
                # Non-whitespace text should trigger body creation and go there
                self.debug("Non-whitespace text in AFTER_HEAD, transitioning to body")
                body = self.parser._ensure_body_node(context)
                self.parser.transition_to_state(context, DocumentState.IN_BODY, body)
                self._append_text(text, context)
                self.debug(f"Added text to body: '{text}'")
            
            return True

        if (context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD)
            and not getattr(context, "template_content_depth", 0)
            and not getattr(context, "template_transparent_depth", 0)):
            # Store the original state before modification
            was_initial = context.document_state == DocumentState.INITIAL

            # Find the first non-whitespace character
            for i, char in enumerate(text):
                if not char.isspace():
                    # If we're in head state, keep leading whitespace in head
                    if i > 0 and not was_initial:
                        self.debug(f"Keeping leading whitespace '{text[:i]}' in head")
                        head = self.parser._ensure_head_node()
                        context.move_to_element(head)
                        self._append_text(text[:i], context)

                    # Switch to body for non-whitespace and remaining text
                    self.debug(f"Found non-whitespace at pos {i}, switching to body")
                    body = self.parser._ensure_body_node(context)
                    self.parser.transition_to_state(context, DocumentState.IN_BODY, body)
                    # In INITIAL state: preserve ALL text including leading whitespace when non-whitespace follows
                    # In IN_HEAD state: start from current non-whitespace position
                    self._append_text(text if was_initial else text[i:], context)
                    return True

            # If we get here, it's all whitespace
            if context.document_state == DocumentState.IN_HEAD:
                self.debug("All whitespace, keeping in head")
                self._append_text(text, context)
                return True

            # If we're in INITIAL state with whitespace, be selective about preservation
            # Only preserve whitespace that's not just basic ASCII spaces/newlines
            if context.document_state == DocumentState.INITIAL:
                # Check if this is "interesting" whitespace (entities, Unicode, etc.)
                is_basic_whitespace = all(c in ' \t\n\r\f' for c in text)
                
                if is_basic_whitespace:
                    self.debug("Basic ASCII whitespace in INITIAL state, ignoring")
                    return True
                else:
                    self.debug("Non-basic whitespace in INITIAL state, preserving")
                    body = self.parser._ensure_body_node(context)
                    self.parser.transition_to_state(context, DocumentState.IN_BODY, body)
                    self._append_text(text, context)
                    return True

            return True

        # Handle other text normally
        
        # Check for table foster parenting before other text handling
        if (context.document_state == DocumentState.IN_TABLE and 
            not self._is_in_integration_point(context) and
            not text.isspace()):  # Only foster parent non-whitespace text
            self.debug(f"Foster parenting text '{text}' out of table context")
            self._foster_parent_text(text, context)
            return True
        
        # Check if we need to reconstruct active formatting elements
        # This happens when text is encountered but the current insertion point
        # is not inside the appropriate formatting elements
        if (len(context.active_formatting_elements._stack) and 
            context.document_state == DocumentState.IN_BODY):
            # Iterate only over real formatting entries (skip markers via iterator)
            needs_reconstruction = True
            for entry in context.active_formatting_elements:
                if entry.element and context.current_parent.find_ancestor(entry.element.tag_name):
                    needs_reconstruction = False
                    break

            # If we still think we need reconstruction, check for already reconstructed children
            if needs_reconstruction and context.current_parent.tag_name in BLOCK_ELEMENTS:
                has_reconstructed_formatting = False
                # Gather active formatting tag names (skip markers)
                active_tags = {e.element.tag_name for e in context.active_formatting_elements if e.element}
                for child in context.current_parent.children:
                    if child.tag_name in active_tags:
                        has_reconstructed_formatting = True
                        break
                if has_reconstructed_formatting:
                    self.debug(f"Block element {context.current_parent.tag_name} already has reconstructed formatting - not reconstructing again")
                    needs_reconstruction = False

            if needs_reconstruction:
                self.debug("Text encountered outside active formatting elements, reconstructing")
                self.parser.reconstruct_active_formatting_elements(context)
        
        self._append_text(text, context)
        return True

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

    def _is_plain_svg_foreign(self, context: "ParseContext") -> bool:
        """Return True if current parent is inside an <svg> subtree that is NOT an HTML integration point.

        In such cases, HTML table-related tags (table, tbody, thead, tfoot, tr, td, th, caption, col, colgroup)
        should NOT trigger HTML table construction; instead they are treated as raw foreign elements (the
        svg*.dat tests expect nested <svg tagname> nodes rather than HTML table scaffolding).
        """
        cur = context.current_parent
        seen_svg = False
        while cur:
            if cur.tag_name.startswith("svg "):
                seen_svg = True
            # Any integration point breaks the foreign-only condition
            if cur.tag_name in ("svg foreignObject", "svg desc", "svg title"):
                return False
            cur = cur.parent
        return seen_svg

    def _foster_parent_text(self, text: str, context: "ParseContext") -> None:
        """Foster parent text content before the current table"""
        # Find the table element
        table = self.parser.find_current_table(context)
        if not table:
            # No table found, just append normally
            self._append_text(text, context)
            return
        
        # Find the table's parent
        table_parent = table.parent
        if not table_parent:
            # Table has no parent, just append normally
            self._append_text(text, context)
            return
        
        # Create text node and insert it before the table
        text_node = Node("#text")
        text_node.text_content = text
        table_parent.insert_before(text_node, table)
        self.debug(f"Foster parented text '{text}' before table")

    def _append_text(self, text: str, context: "ParseContext") -> None:
        """Helper to append text, either as new node or merged with previous"""
        
        # Special handling for pre elements
        if context.current_parent.tag_name == "pre":
            self.debug(f"handling text in pre element: '{text}'")
            self._handle_pre_text(text, context.current_parent)
            return

        # Try to merge with previous text node
        if context.current_parent.last_child_is_text():
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

    def _handle_normal_text(self, text: str, context: "ParseContext") -> bool:
        """Handle normal text content"""
        # If last child is a text node, append to it
        if context.current_parent.last_child_is_text():
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


class FormattingElementHandler(TemplateAwareHandler, SelectAwareHandler):
    """Handles formatting elements like <b>, <i>, etc."""

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in FORMATTING_ELEMENTS

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"Handling <{tag_name}>, context={context}")

        # Check for duplicate active formatting elements (e.g., <a> inside <a>)
        existing_entry = context.active_formatting_elements.find(tag_name)
        if existing_entry and tag_name in ('a',):  # Apply to specific elements that shouldn't nest
            self.debug(f"Found existing active {tag_name}, running adoption agency to close it first")
            # Run adoption agency algorithm to close the existing element
            if self.parser.adoption_agency.run_algorithm(tag_name, context, 1):
                self.debug(f"Adoption agency handled duplicate {tag_name}")

        # Special handling for duplicate <nobr> per HTML5 spec:
        # If a start tag whose tag name is "nobr" is seen, and there is a nobr
        # element in scope, then this is a parse error; run the adoption agency
        # algorithm for the tag name "nobr", then reconstruct the active formatting
        # elements (if any), then create the element for the token and push it onto
        # the list of active formatting elements.
        if tag_name == "nobr" and context.open_elements.has_element_in_scope("nobr"):
            self.debug("Duplicate <nobr> in scope; running adoption agency before creating new one")
            self.parser.adoption_agency.run_algorithm("nobr", context, 1)
            self.parser.reconstruct_active_formatting_elements(context)
            # After adoption, if insertion point is still inside a nobr, move outward so new nobr becomes sibling
            if context.current_parent.tag_name == "nobr" and context.current_parent.parent:
                context.move_to_element(context.current_parent.parent)

        # Create element after any adoption agency handling. For nobr we delay push until after DOM insert
        new_element = self._create_element(token)
        if tag_name != "nobr":
            context.open_elements.push(new_element)

        # Determine if the formatting element is being created as a descendant of <object>.
        # If so, per spec, do not add it to the active formatting elements list.
        # We check both current parent and the new element's ancestry as it is appended.
        inside_object = (
            context.current_parent.find_ancestor("object") is not None or
            context.current_parent.tag_name == "object"
        )

        # If we're in a table cell, handle normally
        if self._is_in_table_cell(context):
            self.debug("Inside table cell, creating formatting element normally")
            context.current_parent.append_child(new_element)
            context.enter_element(new_element)
            
            # Add to active formatting elements
            if not inside_object:
                context.active_formatting_elements.push(new_element, token)
            return True

        # If we're in a table but not in a cell, foster parent
        if self._is_in_table_context(context) and context.document_state != DocumentState.IN_CAPTION:
            # First try to find a cell to put the element in
            cell = context.current_parent.find_first_ancestor_in_tags(["td", "th"])
            if cell:
                self.debug(f"Found table cell {cell.tag_name}, placing formatting element inside")
                cell.append_child(new_element)
                context.enter_element(new_element)
                
                # Add to active formatting elements
                context.active_formatting_elements.push(new_element, token)
                return True

            # If no cell, foster parent before table
            table = self.parser.find_current_table(context)
            if table and table.parent:
                self.debug("Foster parenting formatting element before table")
                table_index = table.parent.children.index(table)
                table.parent.children.insert(table_index, new_element)
                new_element.parent = table.parent
                context.enter_element(new_element)
                
                # Add to active formatting elements
                if not inside_object:
                    context.active_formatting_elements.push(new_element, token)
                return True

        # Create new formatting element normally
        self.debug(f"Creating new formatting element: {tag_name} under {context.current_parent}")

        # Add the new formatting element ensuring nobr siblings rather than nesting
        if tag_name == "nobr" and context.current_parent.tag_name == "nobr" and context.current_parent.parent:
            # Move out one level to prevent nesting (belt-and-suspenders after earlier move)
            context.move_to_element(context.current_parent.parent)
        context.current_parent.append_child(new_element)
        
        # Update current parent to the new formatting element for nesting
        context.enter_element(new_element)
        
        # Push nobr now (after DOM insertion) to better mirror spec ordering
        if tag_name == "nobr":
            context.open_elements.push(new_element)
        
        # Add to active formatting elements
        if not inside_object:
            context.active_formatting_elements.push(new_element, token)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in FORMATTING_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        self.debug(f"FormattingElementHandler: *** START PROCESSING END TAG </{tag_name}> ***")
        self.debug(f"FormattingElementHandler: handling end tag <{tag_name}>, context={context}")

        # Track adoption agency runs for this end tag
        adoption_run_count = 0
        max_runs = 8  # HTML5 spec limit for adoption agency algorithm iterations
        self.debug(f"FormattingElementHandler: MAX_RUNS SET TO {max_runs}")

        # Keep running adoption agency algorithm until no more reconstructions are needed
        while True:
            self.debug(f"FormattingElementHandler: Checking should_run_adoption for run #{adoption_run_count + 1}")
            should_run = self.parser.adoption_agency.should_run_adoption(tag_name, context)
            self.debug(f"FormattingElementHandler: should_run_adoption returned: {should_run}")

            if not should_run:
                self.debug(f"FormattingElementHandler: should_run_adoption returned False after {adoption_run_count} run(s)")
                break

            # Check if we've reached the limit before running
            if adoption_run_count >= max_runs:
                self.debug(f"FormattingElementHandler: Reached maximum runs ({max_runs}) for {tag_name}, stopping")
                break

            adoption_run_count += 1
            self.debug(f"FormattingElementHandler: Running adoption agency algorithm #{adoption_run_count} for end tag </{tag_name}>")

            # Run the adoption agency algorithm
            result = self.parser.adoption_agency.run_algorithm(tag_name, context, adoption_run_count)
            self.debug(f"FormattingElementHandler: Adoption agency run #{adoption_run_count} returned: {result}")

            if not result:
                # If adoption agency returns False, stop trying
                self.debug(f"FormattingElementHandler: Adoption agency returned False on run #{adoption_run_count}, stopping")
                break

        if adoption_run_count > 0:
            self.debug(f"FormattingElementHandler: Adoption agency completed after {adoption_run_count} run(s) for </{tag_name}>")
            return True

        if adoption_run_count >= max_runs:
            self.debug(f"FormattingElementHandler: WARNING: Adoption agency hit maximum runs ({max_runs}) for {tag_name}")
            return True

        self.debug(f"FormattingElementHandler: No adoption agency runs needed for </{tag_name}>, proceeding with normal end tag handling")

        # If we're in a table cell, ignore the end tag
        if self._is_in_table_cell(context):
            cell = context.current_parent.find_first_ancestor_in_tags(["td", "th"])
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
                self._move_to_parent_of_ancestor(context, current)
                return True

            # Look for a matching formatting element in the boundary's parent
            if boundary.parent:
                outer_formatting = boundary.parent.find_ancestor(token.tag_name)
                if outer_formatting:
                    self.debug(f"Found outer formatting element: {outer_formatting}")
                    # Stay inside the boundary element
                    context.move_to_element(boundary)
                    return True

            # If no formatting element found, ignore the end tag
            return True

        # Find matching formatting element for simple case (no adoption agency needed)
        current = context.current_parent.find_ancestor(token.tag_name)
        if not current:
            self.debug(f"No matching formatting element found for end tag: {tag_name}")
            return False

        self.debug(f"Found matching formatting element: {current}")

        # Remove from active formatting elements if present
        entry = context.active_formatting_elements.find_element(current)
        if entry:
            context.active_formatting_elements.remove(current)

        # Pop from open elements stack until we find the element
        while not context.open_elements.is_empty():
            popped = context.open_elements.pop()
            if popped == current:
                break

        # Special case: if the formatting element contains a paragraph as a child,
        # and we're currently in that paragraph, we should stay in the paragraph
        # rather than moving to the formatting element's parent
        if (current.find_child_by_tag("p") and 
            context.current_parent.find_ancestor("p") and 
            current.tag_name == token.tag_name):

            p_element = context.current_parent.find_ancestor("p")
            if p_element and p_element.parent == current:
                self.debug(f"Staying in paragraph that's inside formatting element")
                context.move_to_element(p_element)
                return True

        # If we're in a table but not in a cell, move to formatting element's parent
        if context.document_state in (DocumentState.IN_TABLE, DocumentState.IN_TABLE_BODY, DocumentState.IN_ROW):
            self._move_to_parent_of_ancestor(context, current)
            return True

        # Otherwise close normally
        self.debug(f"Moving to parent of formatting element: {current.parent}")
        context.move_to_element_with_fallback(current.parent, self.parser._get_body_node())
        return True


class SelectTagHandler(TemplateAwareHandler, AncestorCloseHandler):
    """Handles select elements and their children (option, optgroup) and datalist"""

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
        # If we're in a select, handle all tags to prevent formatting elements
        # BUT only if we're not in template content (template elements should be handled by template handlers)
        if self._is_in_select(context) and not self._is_in_template_content(context):
            return True
        return tag_name in ("select", "option", "optgroup", "datalist")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"Handling {tag_name} in select context, current_parent={context.current_parent}")

        # If we're inside template content, block select semantics entirely. The content filter
        # will represent option/optgroup/select as plain elements without promotion or relocation.
        if self._is_in_template_content(context):
            # Special case: if a caption appears after select inside a table cell, ensure it moves to table level
            if tag_name == "caption":
                table = self.parser.find_current_table(context)
                if table:
                    context.move_to_element(table)
                    new_caption = Node("caption")
                    table.append_child(new_caption)
                    context.enter_element(new_caption)
                    return True
            # Swallow select semantics; let content filter represent nested template and other tags
            return True

        if tag_name in ("select", "datalist"):
            # Foster parent if in table context (but not in a cell or caption)
            if self._should_foster_parent_in_table(context):
                self.debug("Foster parenting select out of table")
                new_node = self._foster_parent_before_table(token, context)
                if new_node:
                    context.enter_element(new_node)
                    self.debug(f"Foster parented select before table: {new_node}")
                    return True

            # If we're already in a select, close it and ignore the nested select
            if self._is_in_select(context):
                self.debug("Found nested select, closing outer select")
                outer_select = context.current_parent.find_ancestor("select")
                if outer_select and outer_select.parent:
                    self.debug(f"Moving up to outer select's parent: {outer_select.parent}")
                    context.move_to_element(outer_select.parent)
                    # Don't create anything for the nested select itself
                    self.debug("Ignoring nested select tag")
                    return True

            # Create new select/datalist
            new_node = self._create_and_append_element(token, context)
            context.enter_element(new_node)
            self.debug(f"Created new {tag_name}: {new_node}, parent now: {context.current_parent}")
            return True

        # If we're in a select, ignore any formatting elements
        if self._is_in_select(context) and tag_name in FORMATTING_ELEMENTS:
            self.debug(f"Ignoring formatting element {tag_name} inside select")
            return True

        # If we're in a select, ignore any foreign elements (svg, math)
        if self._is_in_select(context) and tag_name in ("svg", "math"):
            self.debug(f"Ignoring foreign element {tag_name} inside select")
            return True

        # If we're in a select, ignore any rawtext elements (plaintext, script, style, etc.)
        if self._is_in_select(context) and tag_name in RAWTEXT_ELEMENTS:
            self.debug(f"Ignoring rawtext element {tag_name} inside select")
            return True

        # If we're in a select and encounter table elements, check if we should foster parent
        if self._is_in_select(context) and tag_name in TABLE_ELEMENTS:
            # Find the select element
            select_element = context.current_parent.find_ancestor("select")
            if select_element:
                # Check if we're in table document state - if so, this select is in table context
                if context.document_state in (DocumentState.IN_TABLE, DocumentState.IN_CAPTION):
                    # Find the current table for foster parenting
                    current_table = self.parser.find_current_table(context)
                    if current_table:
                        # Foster parent the table element out of select and back to table context
                        self.debug(f"Foster parenting table element {tag_name} from select back to table context")
                        
                        # Find the appropriate foster parent location
                        foster_parent = self._find_foster_parent_for_table_element_in_current_table(current_table, tag_name)
                        if foster_parent:
                            # Create the new table element
                            new_node = Node(tag_name, token.attributes)
                            foster_parent.append_child(new_node)
                            context.enter_element(new_node)
                            
                            self.debug(f"Foster parented {tag_name} to {foster_parent.tag_name}: {new_node}")
                            return True
                        else:
                            # No appropriate foster parent found - delegate to TableTagHandler for complex table structure creation
                            self.debug(f"No simple foster parent found for {tag_name}, delegating to TableTagHandler")
                            return False  # Let TableTagHandler handle this
                else:
                    # Not in table document state, so ignore the table element completely
                    self.debug(f"Ignoring table element {tag_name} inside select (not in table document state)")
                    return True
            
            # Fallback: ignore the table element
            self.debug(f"Ignoring table element {tag_name} inside select")
            return True

        elif tag_name in ("optgroup", "option"):
            # Check if we're in a select or datalist
            parent = context.current_parent.find_ancestor(lambda n: n.tag_name in ("select", "datalist"))
            self.debug(f"Checking for select/datalist ancestor: found={bool(parent)}")

            # If we're not in a select/datalist, create elements at body level
            if not parent:
                self.debug(f"Creating {tag_name} outside select/datalist")
                # Move up to body level if we're inside another option/optgroup
                target_parent = context.current_parent.move_up_while_in_tags(("option", "optgroup"))
                if target_parent != context.current_parent:
                    self.debug(f"Moved up from {context.current_parent.tag_name} to {target_parent.tag_name}")
                    context.move_to_element(target_parent)

                new_node = self._create_element(token)
                context.current_parent.append_child(new_node)
                context.enter_element(new_node)
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
                        context.move_to_element(parent)

                new_optgroup = self._create_element(token)
                context.current_parent.append_child(new_optgroup)
                context.enter_element(new_optgroup)
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
                        context.move_to_element(parent)
                # If we're inside an optgroup, stay there, otherwise move to select/datalist level
                elif context.current_parent.tag_name not in ("select", "datalist", "optgroup"):
                    self.debug("Moving up to select/datalist/optgroup level")
                    parent = context.current_parent.find_ancestor(
                        lambda n: n.tag_name in ("select", "datalist", "optgroup")
                    )
                    if parent:
                        context.move_to_element(parent)

                new_option = self._create_element(token)
                context.current_parent.append_child(new_option)
                context.enter_element(new_option)
                self.debug(f"Created option: {new_option}, parent now: {context.current_parent}")
                return True

        # If we're in a select and this is any other tag, ignore it
        if self._is_in_select(context):
            self.debug(f"Ignoring {tag_name} inside select")
            return True

        return False

    def _find_foster_parent_for_table_element_in_current_table(self, table: "Node", table_tag: str) -> Optional["Node"]:
        """Find the appropriate foster parent for a table element within the current table"""
        if table_tag in ("tr",):
            # <tr> elements should go in tbody, thead, tfoot - look for the last one
            last_section = None
            for child in table.children:
                if child.tag_name in ("tbody", "thead", "tfoot"):
                    last_section = child
            
            # If we found a table section, use it
            if last_section:
                return last_section
            
            # No table section found - this means we need to create implicit tbody
            # Instead of doing it here, return None to signal that TableTagHandler should handle this
            return None
            
        elif table_tag in ("td", "th"):
            # Cell elements should go in the last <tr> of the last table section
            last_section = None
            for child in table.children:
                if child.tag_name in ("tbody", "thead", "tfoot"):
                    last_section = child
            
            if last_section:
                # Find the last tr in this section
                last_tr = None
                for child in last_section.children:
                    if child.tag_name == "tr":
                        last_tr = child
                if last_tr:
                    return last_tr
                # No tr found, return the section (TableTagHandler will create tr if needed)
                return last_section
            
            # No table section found, return None to delegate to TableTagHandler
            return None
            
        elif table_tag in ("tbody", "thead", "tfoot", "caption"):
            # These go directly in table
            return table
            
        elif table_tag in ("col", "colgroup"):
            # These go in table or colgroup
            return table
        
        return table

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("select", "option", "optgroup", "datalist")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        self.debug(f"Handling end tag {tag_name}, current_parent={context.current_parent}")

        if tag_name in ("select", "datalist", "optgroup", "option"):
            # Use standard ancestor close pattern
            return self.handle_end_by_ancestor(token, context)

        return False


class ParagraphTagHandler(TagHandler):
    """Handles paragraph elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle elements inside template content - let them be handled by default
        if self._is_in_template_content(context):
            return False
            
        # Handle p tags directly
        if tag_name == "p":
            return True

        # Also handle any tag that would close a p
        if context.current_parent.tag_name == "p":
            return tag_name in AUTO_CLOSING_TAGS["p"]

        return False

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        self.debug(f"handling {token}, context={context}")
        self.debug(f"Current parent: {context.current_parent}")

        # Special case: HTML integration points inside foreign content (e.g. svg foreignObject)
        # A <p> starting inside an integration point should NOT close an outer <p> ancestor
        # that lives outside the integration subtree. We just create a new <p> inside.
        if token.tag_name == "p":
            integration_ancestor = context.current_parent.find_ancestor(
                lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title")
            )
            if (context.current_parent.tag_name in ("svg foreignObject", "svg desc", "svg title") or integration_ancestor):
                self.debug("Inside SVG integration point: creating paragraph locally without closing outer <p>")
                # Clear any active formatting elements inherited from outside the integration point
                # so they don't get reconstructed inside the foreignObject subtree.
                if context.active_formatting_elements:
                    context.active_formatting_elements._stack.clear()
                new_node = self._create_element(token)
                context.current_parent.append_child(new_node)
                context.enter_element(new_node)
                context.open_elements.push(new_node)
                return True

        # If inside an SVG integration point, clear active formatting elements to avoid
        # leaking HTML formatting from outside into this subtree.
        if (
            context.current_parent.tag_name in ("svg foreignObject", "svg desc", "svg title") or
            context.current_parent.has_ancestor_matching(lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title"))
        ):
            context.active_formatting_elements._stack.clear()

        # If we're handling a tag that should close p
        if token.tag_name != "p" and context.current_parent.tag_name == "p":
            self.debug(f"Auto-closing p due to {token.tag_name}")
            if context.current_parent.parent:
                context.move_up_one_level()
            else:
                # Fallback to body if p has no parent
                body = self.parser._ensure_body_node(context)
                context.move_to_element(body)
            return False  # Let the original handler handle the new tag

        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            body = self.parser._ensure_body_node(context)
            self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

        # Check if we need to foster parent the paragraph due to table context FIRST
        # before closing formatting elements
        if (context.document_state == DocumentState.IN_TABLE and 
            token.tag_name == "p" and
            not self._is_in_template_content(context)):
            self.debug(f"Foster parenting paragraph out of table")
            self.parser._foster_parent_element(token.tag_name, token.attributes, context)
            return True
        
        # No foster parenting needed, continue with normal logic
        needs_foster_parenting = False
        
        if needs_foster_parenting:
            # This is now handled above with proper foster parenting
            pass

        # Close any active formatting elements before creating block element
        # This implements part of the HTML5 block element behavior
        if token.tag_name == "p" and context.active_formatting_elements:
            # Collect formatting ancestors that are DESCENDANTS of the paragraph being closed.
            # We traverse upward until we reach the paragraph ancestor; do NOT include
            # formatting elements that are outside (above) that paragraph (e.g. outer <a>),
            # since removing those would suppress required adoption-agency behavior.
            formatting_ancestors = []
            current = context.current_parent
            paragraph_ancestor = None
            # First locate the paragraph ancestor (the one being implicitly closed)
            temp = current
            while temp and not paragraph_ancestor:
                if temp.tag_name == "p":
                    paragraph_ancestor = temp
                temp = temp.parent
            # Now walk upwards collecting formatting elements until we hit that paragraph
            while current and current is not paragraph_ancestor:
                if (current.tag_name in FORMATTING_ELEMENTS and
                        context.active_formatting_elements.find(current.tag_name)):
                    formatting_ancestors.append(current)
                current = current.parent
            # Innermost first already due to upward traversal; ensure list order innermost->outermost
            if paragraph_ancestor and formatting_ancestors:
                self.debug(f"Closing (popping) formatting ancestors before new <p>: {[n.tag_name for n in formatting_ancestors]}")
                outermost = formatting_ancestors[-1]
                # Move insertion point to parent of outermost formatting element
                if outermost.parent:
                    context.move_to_element(outermost.parent)
                else:
                    body = self.parser._ensure_body_node(context)
                    if body:
                        context.move_to_element(body)
                # Remove formatting ancestors from open elements stack (not only contiguous top ones)
                to_remove = set()
                # Only remove those whose paragraph ancestor is the same paragraph_ancestor we identified
                for fmt in formatting_ancestors:
                    anc = fmt.find_ancestor("p")
                    if anc is paragraph_ancestor:
                        to_remove.add(fmt)
                new_stack = []
                for elem in context.open_elements._stack:
                    if elem in to_remove:
                        self.debug(f"Removing formatting element {elem.tag_name} from open elements stack")
                        continue
                    new_stack.append(elem)
                context.open_elements._stack = new_stack
                # After popping, formatting elements remain in active list; defer reconstruction
                # until actual inline/text content appears in the new paragraph. Immediate
                # reconstruction here caused over‑nesting and duplication in deep font chains.

        # Check if we're inside another p tag
        p_ancestor = context.current_parent.find_ancestor("p")
        if p_ancestor:
            # If integration point lies between current parent and the found p ancestor, do NOT close it
            boundary_between = context.current_parent.find_ancestor(
                lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title")
            )
            if boundary_between and boundary_between != p_ancestor:
                self.debug("Found outer <p> beyond integration point boundary; keeping it open")
                p_ancestor = None  # Suppress closing logic
        if p_ancestor:
            # Special case: if we're inside a button, create p inside the button
            # rather than closing the outer p (HTML5 button scope behavior)
            button_ancestor = context.current_parent.find_ancestor("button")
            if button_ancestor:
                self.debug(f"Inside button {button_ancestor}, creating p inside button instead of closing outer p")
                # Create new p node inside the button
                new_node = self._create_element(token)
                context.current_parent.append_child(new_node)
                context.enter_element(new_node)
                return True
            
            self.debug(f"Found <p> ancestor: {p_ancestor}, closing it")
            if p_ancestor.parent:
                context.move_to_element(p_ancestor.parent)
            # If p_ancestor.parent is None, keep current_parent as is

        # Check if we're inside a container element
        container_ancestor = context.current_parent.find_ancestor(
            lambda n: n.tag_name in ("div", "article", "section", "aside", "nav")
        )
        if container_ancestor and container_ancestor == context.current_parent:
            self.debug(f"Inside container element {container_ancestor.tag_name}, keeping p nested")
            new_node = Node("p", token.attributes)
            context.current_parent.append_child(new_node)
            context.enter_element(new_node)
            return True

        # Create new p node under current parent (keeping formatting context)
        new_node = self._create_element(token)
        context.current_parent.append_child(new_node)
        context.enter_element(new_node)

        # Add to stack of open elements
        context.open_elements.push(new_node)

        # Note: Active formatting elements will be reconstructed as needed
        # when content is encountered that requires them (per HTML5 spec)

        self.debug(f"Created new paragraph node: {new_node} under {new_node.parent}")
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "p"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling <EndTag: p>, context={context}")

        # Check if we're inside a button first - special button scope behavior
        button_ancestor = context.current_parent.find_ancestor("button")
        if button_ancestor:
            # Look for p element only within the button scope using new Node method
            p_in_button = context.current_parent.find_ancestor("p")
            if p_in_button:
                # Found p within button scope, close it
                context.move_to_element_with_fallback(p_in_button.parent, context.current_parent)
                self.debug(f"Closed p within button scope, current_parent now: {context.current_parent.tag_name}")
            
            # Always create implicit p inside button when </p> is encountered in button scope
            self.debug("Creating implicit p inside button due to </p> end tag")
            p_node = Node("p")
            button_ancestor.append_child(p_node)
            self.debug(f"Created implicit p inside button: {p_node}")
            # Don't change current_parent - the implicit p is immediately closed
            return True

        # Special handling: when in table context, an end tag </p> may appear while inside
        # a table subtree. The tests expect an implicit empty <p> around tables in this case.
        if context.document_state == DocumentState.IN_TABLE and self.parser.find_current_table(context):
            self.debug("In table context; creating implicit p relative to table per tests")
            table = self.parser.find_current_table(context)
            # If the table is inside a paragraph, insert an empty <p> BEFORE the table inside that paragraph
            paragraph_ancestor = table.find_ancestor("p")
            if paragraph_ancestor:
                p_node = Node("p")
                try:
                    idx = paragraph_ancestor.children.index(table)
                except ValueError:
                    idx = len(paragraph_ancestor.children)
                paragraph_ancestor.children.insert(idx, p_node)
                p_node.parent = paragraph_ancestor
                self.debug(f"Inserted implicit empty <p> before table inside paragraph {paragraph_ancestor}")
                return True
            # If the table was foster-parented after a paragraph, create empty <p> in original paragraph
            elif table.parent and table.previous_sibling and table.previous_sibling.tag_name == "p":
                original_paragraph = table.previous_sibling
                p_node = Node("p")
                original_paragraph.append_child(p_node)
                self.debug(f"Created implicit p as child of original paragraph {original_paragraph}")
                return True

        # Standard behavior: Find nearest p ancestor and move up to its parent
        if context.current_parent.tag_name == "p":
            closing_p = context.current_parent
            # Move insertion point out of the paragraph first
            if closing_p.parent:
                context.move_up_one_level()
            else:
                body = self.parser._ensure_body_node(context)
                context.move_to_element(body)
            # Pop any formatting elements that were descendants of the closed paragraph
            if context.active_formatting_elements._stack:
                # Build set of descendant formatting nodes under closing paragraph
                descendant_fmt = set()
                def collect_fmt(node: Node):
                    for ch in node.children:
                        if ch.tag_name in FORMATTING_ELEMENTS:
                            descendant_fmt.add(ch)
                        collect_fmt(ch)
                collect_fmt(closing_p)
                if descendant_fmt:
                    new_stack = []
                    for elem in context.open_elements._stack:
                        if elem in descendant_fmt:
                            self.debug(f"Popping formatting element <{elem.tag_name}> at paragraph boundary for reconstruction later")
                            continue
                        new_stack.append(elem)
                    context.open_elements._stack = new_stack
            return True
            
        p_ancestor = context.current_parent.find_ancestor("p")
        if p_ancestor:
            closing_p = p_ancestor
            if closing_p.parent:
                context.move_to_element(closing_p.parent)
            else:
                body = self.parser._ensure_body_node(context)
                context.move_to_element(body)
            # Pop descendant formatting elements of this paragraph
            if context.active_formatting_elements._stack:
                descendant_fmt = set()
                def collect_fmt(node: Node):
                    for ch in node.children:
                        if ch.tag_name in FORMATTING_ELEMENTS:
                            descendant_fmt.add(ch)
                        collect_fmt(ch)
                collect_fmt(closing_p)
                if descendant_fmt:
                    new_stack = []
                    for elem in context.open_elements._stack:
                        if elem in descendant_fmt:
                            self.debug(f"Popping formatting element <{elem.tag_name}> at paragraph boundary for reconstruction later")
                            continue
                        new_stack.append(elem)
                    context.open_elements._stack = new_stack
            return True

        # HTML5 spec: If no p element is in scope, check for special contexts
        # But we still need to handle implicit p creation in table context
        if (context.document_state != DocumentState.IN_BODY and 
            context.document_state != DocumentState.IN_TABLE):
            # Invalid context for p elements - ignore the end tag
            self.debug("No open p element found and not in body/table context, ignoring end tag")
            return True
        
        # Special case: if we're inside a button, create implicit p inside the button
        button_ancestor = context.current_parent.find_ancestor("button")
        if button_ancestor:
            self.debug("No open p element found but inside button, creating implicit p inside button")
            p_node = Node("p")
            context.current_parent.append_child(p_node)
            # Don't change current_parent - the implicit p is immediately closed
            return True
        
        # Even in body context, only create implicit p if we're in a container that can hold p elements
        current_parent = context.current_parent
        if current_parent and current_parent.tag_name in ("html", "head"):
            # Cannot create p elements directly in html or head - ignore the end tag
            self.debug("No open p element found and in invalid parent context, ignoring end tag")
            return True
        
        # Special case: if we're in table context, handle implicit p creation correctly
        if context.document_state == DocumentState.IN_TABLE and self.parser.find_current_table(context):
            self.debug("No open p element found in table context, creating implicit p")
            table = self.parser.find_current_table(context)
            
            # Check if table has a paragraph ancestor (indicating it's inside a p, not foster parented)
            paragraph_ancestor = table.find_ancestor("p")
            if paragraph_ancestor:
                # The table is inside a paragraph; create the implicit empty <p> BEFORE the table
                # as a sibling within the same paragraph to match html5lib expectations.
                p_node = Node("p")
                try:
                    idx = paragraph_ancestor.children.index(table)
                except ValueError:
                    idx = len(paragraph_ancestor.children)
                paragraph_ancestor.children.insert(idx, p_node)
                p_node.parent = paragraph_ancestor
                self.debug(f"Inserted implicit empty <p> before table inside paragraph {paragraph_ancestor}")
                # Don't change current_parent - the implicit p is immediately closed
                return True
            
            # Check if table has a paragraph sibling (indicating it was foster parented from a p)
            elif table.parent and table.previous_sibling and table.previous_sibling.tag_name == "p":
                # The table was inserted after closing a paragraph. Move the table back
                # inside the original paragraph and create an implicit empty <p> before it
                # to match html5lib expectations for this edge case.
                original_paragraph = table.previous_sibling
                parent = table.parent
                try:
                    idx = parent.children.index(table)
                    parent.children.pop(idx)
                except ValueError:
                    pass
                # Insert an empty <p> inside the original paragraph
                p_node = Node("p")
                original_paragraph.append_child(p_node)
                # Append the table into the original paragraph
                original_paragraph.append_child(table)
                table.parent = original_paragraph
                self.debug(f"Moved table into original paragraph and created implicit p under it: {original_paragraph}")
                return True

        # In valid body context with valid parent - create implicit p (rare case)
        self.debug("No open p element found, creating implicit p element in valid context")
        p_node = Node("p")
        context.current_parent.append_child(p_node)
        # Don't change current_parent - the implicit p is immediately closed

        return True


class TableElementHandler(TagHandler):
    """Base class for table-related element handlers"""
    
    def _create_table_element(self, token: "HTMLToken", context: "ParseContext") -> "Node":
        """Create a table element and ensure table context"""
        if not self.parser.find_current_table(context):
            new_table = Node("table")
            context.current_parent.append_child(new_table)
            context.enter_element(new_table)
            self.parser.transition_to_state(context, DocumentState.IN_TABLE)
        
        return self._create_element(token)

    def _append_to_table_level(self, element: "Node", context: "ParseContext") -> None:
        """Append element at table level"""
        current_table = self.parser.find_current_table(context)
        if current_table:
            context.move_to_element(current_table)
            current_table.append_child(element)
            context.move_to_element(element)


class TableTagHandler(TemplateAwareHandler, TableElementHandler):
    """Handles table-related elements"""

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
        # Always handle col/colgroup to prevent them being handled by VoidElementHandler
        if tag_name in ("col", "colgroup"):
            return True

        # Don't handle table elements in foreign contexts unless in integration point
        if context.current_context in ("math", "svg"):
            # Check if we're in an integration point
            in_integration_point = False
            if context.current_context == "svg":
                svg_integration_ancestor = context.current_parent.find_ancestor(
                    lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title"))
                if svg_integration_ancestor:
                    in_integration_point = True
            elif context.current_context == "math":
                # Check if we're inside annotation-xml with HTML encoding
                annotation_ancestor = context.current_parent.find_ancestor("math annotation-xml")
                if annotation_ancestor:
                    encoding = annotation_ancestor.attributes.get("encoding", "").lower()
                    if encoding in ("application/xhtml+xml", "text/html"):
                        in_integration_point = True
                    
            if not in_integration_point:
                return False

        # Suppress HTML table construction inside plain SVG (non integration point) foreign subtree
        if tag_name in ("table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption"):
            text_handler = getattr(self.parser, 'text_handler', None)
            try:
                if text_handler and text_handler._is_plain_svg_foreign(context):  # type: ignore[attr-defined]
                    return False
            except Exception:
                pass
            return True
        return False

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"Handling {tag_name} in table context")

        # Suppress HTML table construction entirely when inside an <svg title> element;
        # tests expect these table-related tags to be ignored (parse errors) rather than
        # creating table scaffolding. We simply consume the token.
        if context.current_parent.tag_name == "svg title":
            return True

        # If inside a plain (non-integration) SVG subtree, do not perform HTML table processing;
        # let generic foreign content handling represent this tag as a foreign element.
        # The text handler got the helper; access via parser.handlers ordering may vary, so use
        # getattr defensively.
        text_handler = getattr(self.parser, 'text_handler', None)
        try:
            if text_handler and text_handler._is_plain_svg_foreign(context):  # type: ignore[attr-defined]
                return False
        except Exception:
            pass

        # Ignore col/colgroup outside of table context
        if tag_name in ("col", "colgroup") and context.document_state != DocumentState.IN_TABLE:
            self.debug("Ignoring col/colgroup outside table context")
            return True

        # Handle table element separately since it creates the context
        if tag_name == "table":
            return self._handle_table(token, context)

        # For other table elements, we need a current table
        if not self.parser.find_current_table(context):
            new_table = Node("table")
            context.current_parent.append_child(new_table)
            context.enter_element(new_table)
            self.parser.transition_to_state(context, DocumentState.IN_TABLE)

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
        new_caption = self._create_element(token)
        self._append_to_table_level(new_caption, context)
        self.parser.transition_to_state(context, DocumentState.IN_CAPTION)
        return True

    def _handle_table(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle table element"""
        # If we're in head, implicitly close it and switch to body
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD) and not getattr(context, "template_content_depth", 0):
            self.debug("Implicitly closing head and switching to body")
            body = self.parser._ensure_body_node(context)
            self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

        # If we're already in table insertion mode, encountering a new <table> while
        # not inside a cell should create a sibling table (html5lib expectation for
        # inputs like x<table><table>x). Only nest when inside a cell.
        if (context.document_state == DocumentState.IN_TABLE and
            context.current_parent.tag_name not in ("td", "th")):
            current_table = self.parser.find_current_table(context)
            if current_table and current_table.parent:
                self.debug("Encountered <table> inside existing table context (not in cell); creating sibling table")
                new_table = self._create_element(token)
                parent = current_table.parent
                idx = parent.children.index(current_table)
                parent.children.insert(idx + 1, new_table)
                new_table.parent = parent
                context.move_to_element(new_table)
                context.open_elements.push(new_table)
                # Push formatting marker for new table boundary
                context.active_formatting_elements.push_marker()
                self.debug("Pushed active formatting marker at <table> sibling boundary")
                # Stay in IN_TABLE state
                return True

        # Per HTML parsing algorithm: handling differs between standards and quirks.
        # If a table start tag is seen while inside a p:
        # - Standards mode: close the p first and insert table at the parent level (foster parenting path)
        # - Quirks mode (no doctype): keep the table inside the paragraph
        if context.current_parent and context.current_parent.tag_name == "p":
            # If the paragraph is empty (no children), leave it in place and
            # insert the table as a sibling after the existing empty <p> so
            # the empty <p> remains in the tree (matches tests20.dat:41).
            paragraph_node = context.current_parent
            is_empty_paragraph = len(paragraph_node.children) == 0
            if is_empty_paragraph:
                # Decide based on standards vs quirks mode
                if self._should_foster_parent_table(context):
                    self.debug("Empty <p> before <table> in standards mode; close <p> and insert table as sibling")
                    parent = paragraph_node.parent
                    if parent is None:
                        body = self.parser._ensure_body_node(context)
                        context.move_to_element(body)
                    else:
                        context.move_to_element(parent)
                else:
                    # Quirks mode: keep the table inside the empty paragraph
                    self.debug("Empty <p> before <table> in quirks mode; keep table inside <p>")
            else:
                # Non-empty <p>: close it in standards mode
                if self._should_foster_parent_table(context):
                    self.debug("Non-empty <p> with <table>; closing paragraph before inserting table")
                    if context.current_parent.parent:
                        context.move_up_one_level()
                    else:
                        body = self.parser._ensure_body_node(context)
                        context.move_to_element(body)
                else:
                    self.debug("Quirks mode: keep table inside non-empty <p>")

        new_table = self._create_element(token)
        context.current_parent.append_child(new_table)
		
        context.enter_element(new_table)
        context.open_elements.push(new_table)  # Add table to open elements stack
        # Insert active formatting marker to bound formatting across table boundary
        context.active_formatting_elements.push_marker()
        self.debug("Pushed active formatting marker at <table> boundary")
        self.parser.transition_to_state(context, DocumentState.IN_TABLE)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "table"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        # Close current table: pop open elements up to table, clear formatting to marker
        current_table = self.parser.find_current_table(context)
        if not current_table:
            return True
        # Pop open elements until we remove this table
        while context.open_elements._stack:
            popped = context.open_elements.pop()
            if popped is current_table:
                break
        # Move insertion point to parent of table (if exists)
        if current_table.parent:
            context.move_to_element(current_table.parent)
        # Clear active formatting entries up to last marker for this table boundary
        context.active_formatting_elements.clear_up_to_last_marker()
        # Transition back to body (or appropriate containing state)
        self.parser.transition_to_state(context, DocumentState.IN_BODY)
        self.debug("Closed </table>, popped formatting marker")
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
        new_colgroup = self._create_element(token)
        self.parser.find_current_table(context).append_child(new_colgroup)

        # Rule 3: Enter the colgroup context so content goes inside it
        self.debug("Entering colgroup context")
        context.enter_element(new_colgroup)
        
        # Rule 4: Check context and create new tbody if needed after colgroup
        td_ancestor = context.current_parent.find_ancestor("td")
        if td_ancestor:
            self.debug("Found td ancestor, staying in colgroup context")
            return True
            
        tbody_ancestor = context.current_parent.find_first_ancestor_in_tags(
            ["tbody", "tr"], self.parser.find_current_table(context))
        if tbody_ancestor:
            self.debug("Found tbody/tr ancestor, staying in colgroup context")
            return True

        # Rule 5: Stay in colgroup context
        self.debug("Staying in colgroup context")
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
        for child in reversed(self.parser.find_current_table(context).children):
            if child.tag_name == "colgroup":
                # Found a colgroup, but check if there's tbody/tr/td after it
                idx = self.parser.find_current_table(context).children.index(child)
                has_content_after = any(
                    c.tag_name in ("tbody", "tr", "td") for c in self.parser.find_current_table(context).children[idx + 1 :]
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
            self.parser.find_current_table(context).append_child(last_colgroup)
        else:
            self.debug(f"Reusing existing colgroup: {last_colgroup}")

        # Rule 4: Add col to colgroup
        new_col = self._create_element(token)
        last_colgroup.append_child(new_col)
        self.debug(f"Added col to colgroup: {new_col}")

        # Rule 5: Check context and create new tbody if needed
        td_ancestor = context.current_parent.find_ancestor("td")
        if td_ancestor:
            self.debug("Found td ancestor, staying in current context")
            return True
            
        tbody_ancestor = context.current_parent.find_first_ancestor_in_tags(
            ["tbody", "tr"], self.parser.find_current_table(context))
        if tbody_ancestor:
            self.debug("Found tbody/tr ancestor, creating new tbody")
            # Create new empty tbody after the colgroup
            new_tbody = Node("tbody")
            self.parser.find_current_table(context).append_child(new_tbody)
            context.enter_element(new_tbody)
            return True

        # Rule 6: Otherwise stay at table level
        self.debug("No tbody/tr/td ancestors, staying at table level")
        context.move_to_element(self.parser.find_current_table(context))
        return True

    def _handle_tbody(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle tbody element"""
        # Always create new tbody at table level
        new_tbody = self._create_element(token)
        self._append_to_table_level(new_tbody, context)
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
            new_tr = self._create_element(token)
            context.current_parent.append_child(new_tr)
            context.enter_element(new_tr)
            return True

        tbody = self._find_or_create_tbody(context)
        new_tr = self._create_element(token)
        tbody.append_child(new_tr)
        context.enter_element(new_tr)
        return True

    def _handle_cell(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle td/th elements"""
        # Check if we're inside template content
        if self._is_in_template_content(context):
            # Inside template content, just create the cell directly without table structure
            new_cell = self._create_element(token)
            context.current_parent.append_child(new_cell)
            context.enter_element(new_cell)
            return True
            
        tr = self._find_or_create_tr(context)
        new_cell = self._create_element(token)
        tr.append_child(new_cell)
        context.enter_element(new_cell)
        return True

    def _find_or_create_tbody(self, context: "ParseContext") -> "Node":
        """Find existing tbody or create new one"""
        # First check current context using new Node method
        tbody_ancestor = context.current_parent.find_ancestor("tbody")
        if tbody_ancestor:
            return tbody_ancestor

        # Look for existing tbody in table using new Node method
        existing_tbody = self.parser.find_current_table(context).find_child_by_tag("tbody")
        if existing_tbody:
            return existing_tbody

        # Create new tbody
        tbody = Node("tbody")
        self.parser.find_current_table(context).append_child(tbody)
        return tbody

    def _find_or_create_tr(self, context: "ParseContext") -> "Node":
        """Find existing tr or create new one in tbody"""
        # First check if we're in a tr using new Node method
        tr_ancestor = context.current_parent.find_ancestor("tr")
        if tr_ancestor:
            return tr_ancestor

        # Get tbody and look for last tr
        tbody = self._find_or_create_tbody(context)
        last_tr = tbody.get_last_child_with_tag("tr")
        if last_tr:
            return last_tr

        # Create new tr
        tr = Node("tr")
        tbody.append_child(tr)
        return tr

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        # Don't handle text if we're in a special content state (rawtext, plaintext, etc.)
        # Those should be handled by their respective handlers
        if context.content_state != ContentState.NONE:
            return False
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

        # Special handling for colgroup context
        if context.current_parent.tag_name == "colgroup":
            self.debug(f"Inside colgroup, checking text content: '{text}'")
            # Split text into whitespace and non-whitespace parts
            import re
            parts = re.split(r'(\S+)', text)
            
            for part in parts:
                if not part:  # Skip empty strings
                    continue
                    
                if part.isspace():
                    # Whitespace stays in colgroup
                    self.debug(f"Adding whitespace '{part}' to colgroup")
                    text_node = Node("#text")
                    text_node.text_content = part
                    context.current_parent.append_child(text_node)
                else:
                    # Non-whitespace gets foster-parented - temporarily move to table context
                    self.debug(f"Foster-parenting non-whitespace '{part}' from colgroup")
                    saved_parent = context.current_parent
                    table = self.parser.find_current_table(context)
                    context.move_to_element(table)
                    
                    # Recursively call handle_text for this part with table context
                    self.handle_text(part, context)
                    
                    # Restore colgroup context for any remaining parts
                    context.move_to_element(saved_parent)
            return True

        # If it's whitespace-only text, allow it in table
        if text.isspace():
            self.debug("Whitespace text in table, keeping in table")
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # Check if we're already inside a foster parented element that can contain text
        if context.current_parent.tag_name in ("p", "div", "section", "article", "blockquote"):
            self.debug(f"Already inside foster parented block element {context.current_parent.tag_name}, adding text directly")
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return True

        # Foster parent non-whitespace text nodes
        table = self.parser.find_current_table(context)
        if not table or not table.parent:
            self.debug("No table or table parent found")
            return False

        # Find the appropriate parent for foster parenting
        foster_parent = table.parent
        table_index = foster_parent.children.index(table)
        self.debug(f"Foster parent: {foster_parent}, table index: {table_index}")

        # If the immediate previous sibling before the table is suitable, decide placement:
        # 1. If it's a text node, merge.
        # 2. If it's a foster-parented block container (div/p/section/article/blockquote/li), append inside it.
        if table_index > 0:
            prev_sibling = foster_parent.children[table_index - 1]
            if prev_sibling.tag_name == "#text":
                self.debug("Merging foster-parented text into previous sibling text node")
                prev_sibling.text_content += text
                return True
            elif prev_sibling.tag_name in ("div","p","section","article","blockquote","li"):
                self.debug(f"Appending foster-parented text into previous block container <{prev_sibling.tag_name}>")
                # Merge with its last text child if present
                if prev_sibling.children and prev_sibling.children[-1].tag_name == "#text":
                    prev_sibling.children[-1].text_content += text
                else:
                    text_node = Node("#text")
                    text_node.text_content = text
                    prev_sibling.append_child(text_node)
                return True

        # Find the most recent <a> tag before the table
        prev_a = None
        for child in reversed(foster_parent.children[:table_index]):
            if child.tag_name == "a":
                prev_a = child
                self.debug(f"Found previous <a> tag: {prev_a} with attributes {prev_a.attributes}")
                break

        # Check if we can continue the previous <a> tag or need to create a new one
        if prev_a:
            # We can only continue the previous <a> if we haven't entered and exited any table structure
            # since it was created. Check if the current context suggests we're still in the same "run"
            # by examining if we're directly in the <a> context or if there have been intervening table elements.
            
            # If we're currently inside the <a> element's context (meaning we're still processing
            # the same foster parenting run), we can add to it
            if context.current_parent.find_ancestor("a") == prev_a:
                self.debug("Still in same <a> context, adding text to existing <a> tag")
                text_node = Node("#text")
                text_node.text_content = text
                prev_a.append_child(text_node)
                self.debug(f"Added text to existing <a> tag: {prev_a}")
                return True
            else:
                # We're not in the same context anymore, so create a new <a> tag
                self.debug("No longer in same <a> context, creating new <a> tag")
                new_a = Node("a", prev_a.attributes.copy())
                text_node = Node("#text")
                text_node.text_content = text
                new_a.append_child(text_node)
                foster_parent.children.insert(table_index, new_a)
                self.debug(f"Inserted new <a> tag before table: {new_a}")
                return True

        # Check for other formatting context
        # Collect formatting elements from current position up to foster parent
        formatting_elements = context.current_parent.collect_ancestors_until(
            foster_parent, lambda n: n.tag_name in FORMATTING_ELEMENTS)
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
        # Don't handle end tags inside template content that would affect document state
        if self._is_in_template_content(context):
            return False
            
        # Handle table-related end tags in table context
        if context.document_state in (DocumentState.IN_TABLE, DocumentState.IN_CAPTION):
            # Handle table structure elements
            if tag_name in ("table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption"):
                return True
            
            # Handle p end tags only when inside table cells
            if tag_name == "p":
                cell = context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th"))
                return cell is not None
            
            # Handle formatting elements that might interact with tables
            if tag_name in FORMATTING_ELEMENTS:
                return True
                
        return False

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
                context.enter_element(new_p)
                return True

        if tag_name == "caption" and context.document_state == DocumentState.IN_CAPTION:
            caption = context.current_parent.find_ancestor("caption")
            if caption:
                context.move_to_element(caption.parent)
                self.parser.transition_to_state(context, DocumentState.IN_TABLE)
            return True

        if tag_name == "table":
            if self.parser.find_current_table(context):
                # Find any active formatting element that contained the table
                formatting_parent = self.parser.find_current_table(context).parent
                table_node = self.parser.find_current_table(context)
                if formatting_parent and formatting_parent.tag_name in FORMATTING_ELEMENTS:
                    self.debug(f"Returning to formatting context: {formatting_parent}")
                    context.move_to_element(formatting_parent)
                # If table lives inside foreignObject/SVG/MathML integration subtree, stay inside that subtree
                elif formatting_parent and (
                    formatting_parent.tag_name.startswith("svg ") or
                    formatting_parent.tag_name.startswith("math ") or
                    formatting_parent.tag_name in ("svg foreignObject", "math annotation-xml")
                ):
                    self.debug(f"Table closed inside foreign context; staying in {formatting_parent.tag_name}")
                    context.move_to_element(formatting_parent)
                elif table_node and table_node.parent and (
                    table_node.parent.tag_name.startswith("svg ") or
                    table_node.parent.tag_name.startswith("math ") or
                    table_node.parent.tag_name in ("svg foreignObject", "math annotation-xml")
                ):
                    self.debug(f"Table parent is foreign context {table_node.parent.tag_name}; moving there instead of body")
                    context.move_to_element(table_node.parent)
                else:
                    # Try to get body node, but fall back to root in fragment contexts
                    body_node = self.parser._ensure_body_node(context)
                    if body_node:
                        context.move_to_element(body_node)
                    else:
                        # In fragment contexts, fall back to the fragment root
                        context.move_to_element(self.parser.root)

                # # Find the original <a> tag that contained the table
                # original_a = self.parser.find_current_table(context).parent
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
                #             context.enter_element(new_a)
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
                #             context.enter_element(new_a)
                #     else:
                #         body = self.parser._get_body_node()
                #         context.move_to_element_with_fallback(body, self.parser.html_node)

                self.parser.transition_to_state(context, DocumentState.IN_BODY)
                return True

        elif tag_name == "a":
            # Find the matching <a> tag
            a_element = context.current_parent.find_ancestor("a")
            if a_element:
                body = self.parser._get_body_node()
                context.move_to_element_with_fallback(a_element.parent, self.parser.find_current_table(context) or body) or self.parser.html_node
                return True

        elif tag_name in TABLE_ELEMENTS:
            if tag_name in ["tbody", "thead", "tfoot"]:
                tbody = context.current_parent.find_ancestor("tbody")
                if tbody:
                    context.move_to_element(tbody)
                    return True
            elif tag_name in ["td", "th"]:
                tr = context.current_parent.find_ancestor("tr")
                if tr:
                    context.move_to_element(tr)
                    return True
            elif tag_name == "tr":
                tbody = context.current_parent.find_ancestor("tbody")
                if tbody:
                    context.move_to_element(tbody)
                    return True

        return False

    def _should_foster_parent_table(self, context: "ParseContext") -> bool:
        """
        Determine if table should be foster parented based on DOCTYPE.
        
        HTML5 spec: Foster parenting should happen in standards mode.
        Legacy/quirks mode allows tables inside paragraphs.
        """
        # Look for a DOCTYPE in the document root
        if hasattr(self, 'parser') and self.parser and hasattr(self.parser, 'root'):
            for child in self.parser.root.children:
                if child.tag_name == "!doctype":
                    doctype = child.text_content.lower() if child.text_content else ""
                    self.debug(f"Found DOCTYPE: '{doctype}'")
                    
                    # HTML5 standard DOCTYPE triggers foster parenting
                    if doctype == "html" or not doctype:
                        self.debug("DOCTYPE is HTML5 standard - using foster parenting")
                        return True
                    
                    # Legacy DOCTYPEs (HTML 3.2, HTML 4.0, etc.) use quirks mode
                    # Check for specific legacy patterns first (before XHTML check)
                    if any(legacy in doctype for legacy in ["html 3.2", "html 4.0", "transitional", "system", '"html"']):
                        self.debug("DOCTYPE is legacy - using quirks mode (no foster parenting)")
                        return False
                    
                    # XHTML DOCTYPEs that are not transitional trigger foster parenting
                    if "xhtml" in doctype and "strict" in doctype:
                        self.debug("DOCTYPE is strict XHTML - using foster parenting")
                        return True
                    
                    # Default for unknown DOCTYPEs: use standards mode
                    self.debug("DOCTYPE is unknown - defaulting to foster parenting")
                    return True
        
        # No DOCTYPE found: assume quirks mode (matches html5lib test expectations)
        self.debug("No DOCTYPE found - defaulting to quirks mode (no foster parenting)")
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
            self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

        if tag_name == "form":
            # Only one active form element at a time: detect dynamically by scanning open elements.
            # Also ignore if there's a form ancestor (nested form).
            has_open_form = context.open_elements.has_element_in_scope("form")
            if has_open_form:
                return True
            if self.parser.has_form_ancestor(context):
                return True

        # Create and append the new node
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)

        # Update current parent for non-void elements
        if tag_name not in ("input",):
            context.enter_element(new_node)
            # Track form in open elements so dynamic detection works
            if tag_name == "form":
                context.open_elements.push(new_node)
        
        # No persistent pointer; dynamic detection is used instead
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("form", "button", "textarea", "select", "label")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name

        # Find the nearest matching element
        current = context.current_parent.find_ancestor(tag_name)

        if current:
            # Remove the form from open elements stack if present
            if tag_name == "form":
                context.open_elements.remove_element(current)
            body = self.parser._get_body_node()
            context.move_to_element_with_fallback(current.parent, body) or self.parser.html_node

        return True


class ListTagHandler(TagHandler):
    """Handles list-related elements (ul, ol, li, dl, dt, dd)"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
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
            self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

        # Handle dd/dt elements
        if tag_name in ("dd", "dt"):
            return self._handle_definition_list_item(token, context)

        if tag_name == "li":
            return self._handle_list_item(token, context)

        # Handle ul/ol/dl elements
        if tag_name in ("ul", "ol", "dl"):
            return self._handle_list_container(token, context)

        return False

    def _handle_definition_list_item(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle dd/dt elements"""
        tag_name = token.tag_name
        self.debug(f"Handling {tag_name} tag")
        
        # Find any existing dt/dd ancestor
        ancestor = context.current_parent.find_first_ancestor_in_tags(["dt", "dd"])
        if ancestor:
            self.debug(f"Found existing {ancestor.tag_name} ancestor")
            # Close everything up to the dl parent
            dl_parent = ancestor.parent
            self.debug(f"Closing up to dl parent: {dl_parent}")
            context.move_to_element(dl_parent)

            # Create new element at same level
            new_node = self._create_element(token)
            dl_parent.append_child(new_node)
            context.enter_element(new_node)
            self.debug(f"Created new {tag_name} at dl level: {new_node}")
            return True

        # No existing dt/dd, create normally
        self.debug("No existing dt/dd found, creating normally")
        new_node = self._create_element(token)
        context.current_parent.append_child(new_node)
        context.enter_element(new_node)
        self.debug(f"Created new {tag_name}: {new_node}")
        return True

    def _handle_list_item(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle li elements"""
        self.debug(f"Handling li tag, current parent is {context.current_parent.tag_name}")

        # If we're in table context, foster parent the li element
        if context.document_state == DocumentState.IN_TABLE:
            self.debug("Foster parenting li out of table")
            table = self.parser.find_current_table(context)
            if table and table.parent:
                new_node = self._create_element(token)
                table_index = table.parent.children.index(table)
                table.parent.children.insert(table_index, new_node)
                context.enter_element(new_node)
                self.debug(f"Foster parented li before table: {new_node}")
                return True

        # If we're in another li, close it first
        if context.current_parent.tag_name == "li":
            self.debug("Inside another li, closing it first")
            parent = context.current_parent.parent
            if parent and parent.tag_name in ("ul", "ol"):
                self.debug(f"Moving up to list parent: {parent.tag_name}")
                context.move_to_element(parent)
            else:
                self.debug("No list parent found, moving to body")
                body = self.parser._get_body_node()
                context.move_to_element_with_fallback(body, self.parser.html_node)
        else:
            # Look for the nearest list container (ul, ol, menu) ancestor
            list_ancestor = context.current_parent.find_ancestor(lambda n: n.tag_name in ("ul", "ol", "menu"))
            if list_ancestor:
                self.debug(f"Found list ancestor: {list_ancestor.tag_name}, moving to it")
                context.move_to_element(list_ancestor)
            else:
                self.debug("No list ancestor found - creating li in current context")

        new_node = self._create_element(token)
        context.current_parent.append_child(new_node)
        context.enter_element(new_node)
        self.debug(f"Created new li: {new_node}")
        return True

    def _handle_list_container(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle ul/ol/dl elements"""
        tag_name = token.tag_name
        self.debug(f"Handling {tag_name} tag")
        new_node = self._create_element(token)
        context.current_parent.append_child(new_node)
        context.enter_element(new_node)
        self.debug(f"Created new {tag_name}: {new_node}")
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("ul", "ol", "li", "dl", "dt", "dd")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling end tag {token.tag_name}")
        self.debug(f"Current parent before end: {context.current_parent}")
        tag_name = token.tag_name

        if tag_name in ("dt", "dd"):
            return self._handle_definition_list_item_end(token, context)

        if tag_name == "li":
            return self._handle_list_item_end(token, context)

        elif tag_name in ("ul", "ol", "dl"):
            return self._handle_list_container_end(token, context)

        return False

    def _handle_definition_list_item_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle end tags for dt/dd"""
        tag_name = token.tag_name
        self.debug(f"Handling end tag for {tag_name}")
        
        # Find the nearest dt/dd ancestor
        dt_dd_ancestor = context.current_parent.find_ancestor_until(
            lambda n: n.tag_name in ("dt", "dd"), self.parser.html_node)
        if dt_dd_ancestor:
            self.debug(f"Found matching {dt_dd_ancestor.tag_name}")
            # Move to the dl parent
            if dt_dd_ancestor.parent and dt_dd_ancestor.parent.tag_name == "dl":
                self.debug("Moving to dl parent")
                context.move_to_element(dt_dd_ancestor.parent)
            else:
                self.debug("No dl parent found, moving to body")
                body = self.parser._get_body_node()
                context.move_to_element_with_fallback(body, self.parser.html_node)
            return True
        self.debug(f"No matching {tag_name} found")
        return False

    def _handle_list_item_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle end tags for li"""
        self.debug("Handling end tag for li")
        
        # Find the nearest li ancestor, but stop if we hit a ul/ol first
        li_ancestor, stop_element = context.current_parent.find_ancestor_with_early_stop(
            "li", ("ul", "ol"), self.parser.html_node
        )
        
        if li_ancestor:
            self.debug("Found matching li")
            # Move to the list parent
            if li_ancestor.parent and li_ancestor.parent.tag_name in ("ul", "ol"):
                self.debug("Moving to list parent")
                context.move_to_element(li_ancestor.parent)
            else:
                self.debug("No list parent found, moving to body")
                body = self.parser._get_body_node()
                context.move_to_element_with_fallback(body, self.parser.html_node)
            return True
        elif stop_element:
            self.debug(f"Found {stop_element.tag_name} before li, ignoring end tag")
            return True
        
        self.debug("No matching li found")
        return False

    def _handle_list_container_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle end tags for ul/ol/dl"""
        tag_name = token.tag_name
        self.debug(f"Handling end tag for {tag_name}")
        
        # Find the matching list container
        matching_container = context.current_parent.find_ancestor_until(
            lambda n: n.tag_name == tag_name, self.parser.html_node
        )
        
        if matching_container:
            self.debug(f"Found matching {tag_name}")
            # If we're inside an li/dt/dd, stay there
            if matching_container.parent and matching_container.parent.tag_name in ("li", "dt", "dd"):
                self.debug(f"Staying in {matching_container.parent.tag_name}")
                context.move_to_element(matching_container.parent)
            else:
                self.debug("Moving to parent")
                body = self.parser._get_body_node()
                context.move_to_element_with_fallback(matching_container.parent, body) or self.parser.html_node
            return True
        
        self.debug(f"No matching {tag_name} found")
        return False


class HeadingTagHandler(SimpleElementHandler):
    """Handles h1-h6 heading elements"""

    def __init__(self, parser: ParserInterface):
        super().__init__(parser, HEADING_ELEMENTS)

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name

        # Check if we're inside a table cell
        if self._is_in_table_cell(context):
            return super().handle_start(token, context, has_more_content)

        # Outside table cells, close any existing heading
        existing_heading = context.current_parent.find_ancestor(lambda n: n.tag_name in HEADING_ELEMENTS)
        if existing_heading:
            self._move_to_parent_of_ancestor(context, existing_heading)

        return super().handle_start(token, context, has_more_content)

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in HEADING_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        return super().handle_end(token, context)


class RawtextTagHandler(SelectAwareHandler):
    """Handles rawtext elements like script, style, title, etc."""

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in RAWTEXT_ELEMENTS

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling {tag_name}")

        # Create and append the new node
        new_node = self._create_element(token)
        context.current_parent.append_child(new_node)

        # Switch to RAWTEXT state and let tokenizer handle the content
        self.debug(f"Switching to RAWTEXT content state for {tag_name}")
        context.content_state = ContentState.RAWTEXT
        context.enter_element(new_node)
        self.parser.tokenizer.start_rawtext(tag_name)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        self.debug(f"RawtextTagHandler.should_handle_end: checking {tag_name} in content_state {context.content_state}")
        return tag_name in RAWTEXT_ELEMENTS

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling end tag {token.tag_name}")
        self.debug(f"Current state: doc={context.document_state}, content={context.content_state}, parent: {context.current_parent}")

        if context.content_state == ContentState.RAWTEXT and token.tag_name == context.current_parent.tag_name:
            # Find the original parent before the RAWTEXT element
            original_parent = context.current_parent.parent
            self.debug(f"Original parent: {original_parent.tag_name if original_parent else None}")

            # Return to the original parent
            if original_parent:
                context.move_to_element(original_parent)
                # If we're in AFTER_HEAD state and the original parent is head,
                # move current_parent to html level for subsequent content
                if (context.document_state == DocumentState.AFTER_HEAD and 
                    original_parent.tag_name == "head"):
                    context.move_to_element(self.parser.html_node)
                    self.debug(f"AFTER_HEAD state: moved current_parent from head to html")
                # Clear RAWTEXT content mode
                context.content_state = ContentState.NONE
                self.debug("Returned to NONE content state")
            else:
                # Fallback to body if no parent
                body = self.parser._ensure_body_node(context)
                context.move_to_element(body)
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


class VoidElementHandler(SelectAwareHandler):
    """Handles void elements that can't have children"""

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
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
                new_node = self._create_element(token)
                head = self.parser._ensure_head_node()
                head.append_child(new_node)
                context.move_to_element(head)
                return True
            else:
                self.debug(f"Keeping {tag_name} in body due to IN_BODY state")

        # If we're in a paragraph and this is a block element, close the paragraph first
        if context.current_parent.tag_name == "p" and tag_name in BLOCK_ELEMENTS:
            self.debug(f"Closing paragraph for block element {tag_name}")
            body = self.parser._get_body_node()
            context.move_up_one_level() or body or self.parser.html_node

        # Special handling for input elements in table context
        if tag_name == "input" and context.document_state == DocumentState.IN_TABLE:
            # In table context, inputs should generally be foster parented
            # Check if we're in a form within a table
            form_ancestor = context.current_parent.find_ancestor("form")
            table_ancestor = context.current_parent.find_ancestor("table")
            
            if form_ancestor and table_ancestor:
                # Input is inside a form which is inside a table
                input_type = token.attributes.get("type", "").lower()
                if input_type == "hidden":
                    # Hidden inputs should be siblings to the form, not children
                    self.debug(f"Making hidden input a sibling to form in table")
                    new_node = self._create_element(token)
                    form_parent = form_ancestor.parent
                    if form_parent:
                        form_index = form_parent.children.index(form_ancestor)
                        form_parent.children.insert(form_index + 1, new_node)
                        new_node.parent = form_parent
                        return True
                else:
                    # Non-hidden inputs should be foster parented outside the table
                    self.debug(f"Foster parenting non-hidden input outside table")
                    if table_ancestor.parent:
                        new_node = self._create_element(token)
                        table_index = table_ancestor.parent.children.index(table_ancestor)
                        table_ancestor.parent.children.insert(table_index, new_node)
                        new_node.parent = table_ancestor.parent
                        return True

        # Create the void element at the current level
        self.debug(f"Creating void element {tag_name} at current level")
        new_node = self._create_element(token)
        context.current_parent.append_child(new_node)

        return True


    def _create_element_from_node(self, node: "Node") -> "Node":
        """Create a new element with the same tag name and attributes as the given node"""
        from .tokenizer import HTMLToken
        
        # Create a token-like object for the new element
        token = HTMLToken("start_tag", node.tag_name, {}, False)
        
        # Copy attributes if any
        if hasattr(node, 'attributes') and node.attributes:
            token.attributes.update(node.attributes)
            
        return self._create_element(token)


class AutoClosingTagHandler(TemplateAwareHandler):
    """Handles auto-closing behavior for certain tags"""

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't intercept list item tags in table context; let ListTagHandler handle foster parenting
        if context.document_state == DocumentState.IN_TABLE and tag_name in ("li","dt","dd"):
            return False
        # Handle both formatting cases and auto-closing cases
        return tag_name in AUTO_CLOSING_TAGS or (
            tag_name in BLOCK_ELEMENTS
            and context.current_parent.find_ancestor(lambda n: n.tag_name in FORMATTING_ELEMENTS)
        )

    def handle_start(self, token: "HTMLToken", context: "ParseContext", end_tag_idx: int) -> bool:
        self.debug(f"Checking auto-closing rules for {token.tag_name}")
        current = context.current_parent

        self.debug(f"Current parent: {current}")
        self.debug(f"Current parent's parent: {current.parent}")
        self.debug(f"Current parent's children: {[c.tag_name for c in current.children]}")

        # Check if we're inside a formatting element AND this is a block element
        formatting_element = current.find_ancestor(lambda n: n.tag_name in FORMATTING_ELEMENTS)
        
        # Also check if there are active formatting elements that need reconstruction
        has_active_formatting = len(context.active_formatting_elements) > 0
        
        if (formatting_element or has_active_formatting) and token.tag_name in BLOCK_ELEMENTS:
            # Do not perform auto-closing/reconstruction inside HTML integration points
            if self._is_in_integration_point(context):
                self.debug("In integration point; skipping auto-closing/reconstruction for block element")
                return False
            if formatting_element:
                self.debug(f"Found formatting element ancestor: {formatting_element}")
            if has_active_formatting:
                self.debug(f"Found active formatting elements: {[e.element.tag_name for e in context.active_formatting_elements]}")

            # If we're in a container element but have active formatting elements,
            # we still need to handle reconstruction
            if current.tag_name in ("div", "article", "section", "aside", "nav") and not has_active_formatting:
                self.debug(f"Inside container element {current.tag_name} with no active formatting, allowing nesting")
                return False

            # Move current_parent up to the same level as the outermost formatting element
            target_parent = None
            if formatting_element:
                # Find the outermost formatting element in the chain
                outermost_formatting = formatting_element
                while outermost_formatting.parent and outermost_formatting.parent.tag_name in FORMATTING_ELEMENTS:
                    outermost_formatting = outermost_formatting.parent
                
                # The target parent should be the parent of the outermost formatting element
                target_parent = outermost_formatting.parent
            
            if target_parent:
                # If this is a simple case: single active formatting element (current) and a block (like <div>)
                # keep the block inside the formatting element instead of moving it outside. This matches
                # expected tree where <b><div>... rather than lifting div out before adoption.
                # (Reverted experimental simple-case logic to avoid regressions)
                pass

            if target_parent:
                # Save the current parent before moving
                original_parent = context.current_parent
                
                self.debug(f"Moving context to target parent: {target_parent.tag_name}")
                context.move_to_element(target_parent)
                
                # When we move out of formatting elements due to a block element,
                # we need to remove the "inner" formatting elements that were properly closed
                # but keep the "outer" formatting elements that should be reconstructed
                if formatting_element:
                    formatting_elements_to_remove = []
                    
                    # Find the path from the formatting_element to the block insertion point
                    path_elements = []
                    temp = original_parent
                    while temp and temp != formatting_element and temp.tag_name in FORMATTING_ELEMENTS:
                        path_elements.append(temp)
                        temp = temp.parent
                    
                    # Remove formatting elements that are in the path but not the outermost one
                    for entry in context.active_formatting_elements:
                        elem = entry.element
                        if elem in path_elements and elem != formatting_element:
                            formatting_elements_to_remove.append(entry)
                            self.debug(f"Removing inner formatting element: {elem.tag_name}")
                    
                    # Remove the inner formatting elements
                    for entry in formatting_elements_to_remove:
                        context.active_formatting_elements.remove_entry(entry)
            
            # Create the block element normally
            new_block = self._create_element(token)
            context.current_parent.append_child(new_block)
            context.enter_element(new_block)
            
            # Add block element to open elements stack
            context.open_elements.push(new_block)

            # Check the formatting elements in the stack for decision making
            formatting_elements_in_stack = [e for e in context.open_elements._stack 
                                          if e.tag_name in FORMATTING_ELEMENTS]

            # Check if we should reconstruct formatting elements
            # Only reconstruct if we're in a simple case (not deeply nested formatting)
            if len(formatting_elements_in_stack) <= 2:  # Simple case - reconstruct
                # Check if this is a very simple case (like <a><div>) vs nested case (like <b><em>...<aside>)
                # For nested formatting elements, let adoption agency handle everything
                if len(formatting_elements_in_stack) == 1:
                    # Very simple case like <a><div> - reconstruct the single formatting element
                    active_elements = []
                    for entry in context.active_formatting_elements:
                        active_elements.append(entry.element)
                    
                    if active_elements:
                        self.debug(f"Very simple case: reconstructing single formatting element: {[e.tag_name for e in active_elements]}")
                        self.parser.adoption_agency._reconstruct_formatting_elements(active_elements, context)
                    
                    self.debug(f"Created new block {new_block.tag_name}, with simple formatting element reconstruction")
                else:
                    # Multiple formatting elements case - no reconstruction here
                    # Let the adoption agency handle all reconstruction when end tags are processed
                    self.debug(f"Multiple formatting elements case: no reconstruction, letting adoption agency handle it")
            else:  # Complex case - let adoption agency handle it
                self.debug(f"Complex case: created new block {new_block.tag_name}, letting adoption agency handle reconstruction")

            return True

        # Then check if current tag should be closed by new tag
        current_tag = current.tag_name
        if current_tag in AUTO_CLOSING_TAGS:
            closing_list = AUTO_CLOSING_TAGS[current_tag]
            if token.tag_name in closing_list:
                self.debug(f"Auto-closing {current_tag} due to new tag {token.tag_name}")
                if current.parent:
                    context.move_to_element(current.parent)
                return False

        return False

    def _is_in_integration_point(self, context: "ParseContext") -> bool:
        """Check if we're inside an SVG or MathML integration point where HTML rules apply."""
        current = context.current_parent
        while current:
            # SVG integration points: foreignObject, desc, title
            if current.tag_name in ("svg foreignObject", "svg desc", "svg title"):
                return True
            # MathML integration points: annotation-xml with specific encoding
            if current.tag_name == "math annotation-xml":
                encoding = current.attributes.get("encoding", "").lower()
                if encoding in ("text/html", "application/xhtml+xml"):
                    return True
            current = current.parent
        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        # Don't handle end tags inside template content that would affect document state
        if self._is_in_template_content(context):
            return False
            
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
                context.move_to_element_with_fallback(tr.parent, body) or self.parser.html_node
                self.parser.transition_to_state(context, DocumentState.IN_TABLE)
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
                # Special case: if we're in template content, stay in content
                if self._is_in_template_content(context):
                    self.debug("Staying in template content")
                    # Don't change current_parent, stay in content
                else:
                    context.move_to_element(boundary)
                return True

            # Move up to block element's parent
            context.move_to_element_with_fallback(current.parent, self.parser._get_body_node())
            return True

        if token.tag_name in CLOSE_ON_PARENT_CLOSE:
            parent_tags = CLOSE_ON_PARENT_CLOSE[token.tag_name]
            for parent_tag in parent_tags:
                parent = context.current_parent.find_ancestor(parent_tag)
                if parent:
                    context.move_to_element(parent)
                    return True
        return False


class ForeignTagHandler(TagHandler):
    """Handles SVG and other foreign element contexts"""

    def _fix_foreign_attribute_case(self, attributes, element_context):
        """Fix case for SVG/MathML attributes according to HTML5 spec
        
        Args:
            attributes: Dict of attribute name->value pairs
            element_context: "svg" or "math" to determine casing rules
        """
        if not attributes:
            return attributes
        
        from .constants import SVG_CASE_SENSITIVE_ATTRIBUTES, MATHML_CASE_SENSITIVE_ATTRIBUTES
        
        fixed_attrs = {}
        for name, value in attributes.items():
            name_lower = name.lower()
            
            if element_context == "svg":
                # SVG: Use case mapping if available, otherwise preserve case
                if name_lower in SVG_CASE_SENSITIVE_ATTRIBUTES:
                    fixed_attrs[SVG_CASE_SENSITIVE_ATTRIBUTES[name_lower]] = value
                else:
                    # For SVG, attributes not in the mapping are lowercased per spec
                    fixed_attrs[name_lower] = value
            elif element_context == "math":
                # MathML: Lowercase all attributes unless in case mapping
                if name_lower in MATHML_CASE_SENSITIVE_ATTRIBUTES:
                    fixed_attrs[MATHML_CASE_SENSITIVE_ATTRIBUTES[name_lower]] = value
                else:
                    # For MathML, all other attributes are lowercased
                    fixed_attrs[name_lower] = value
            else:
                # Default: lowercase
                fixed_attrs[name_lower] = value
                
        return fixed_attrs

    def _create_foreign_element(self, tag_name: str, attributes: dict, context_type: str, context: "ParseContext", token=None):
        """Create a foreign element (SVG/MathML) and append to current parent
        
        Args:
            tag_name: The tag name to create
            attributes: The attributes dict 
            context_type: "svg" or "math" 
            context: Parse context
            token: Optional token for self-closing check
            
        Returns:
            The created node
        """
        fixed_attrs = self._fix_foreign_attribute_case(attributes, context_type)
        new_node = Node(f"{context_type} {tag_name}", fixed_attrs)

        # Set foreign context BEFORE appending so downstream handlers in same token sequence
        # (e.g., immediate table-related elements) can detect we're inside foreign content.
        if context_type == "svg" and tag_name.lower() == "svg":
            context.current_context = "svg"
        elif context_type == "math" and tag_name.lower() == "math":
            context.current_context = "math"

        context.current_parent.append_child(new_node)

        # Only set as current parent if not self-closing
        if not token or not token.is_self_closing:
            context.enter_element(new_node)
            # Track in open elements stack for correct ancestor logic
            if hasattr(context, "open_elements"):
                context.open_elements.push(new_node)
        return new_node

    def _handle_foreign_foster_parenting(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle foster parenting for foreign elements (SVG/MathML) in table context"""
        tag_name = token.tag_name
        tag_name_lower = tag_name.lower()
        
        # Foster parent if in table context (but not in a cell or caption)
        if (
            tag_name_lower in ("svg", "math")
            and context.current_context not in ("svg", "math")
            and context.document_state
            in (
                DocumentState.IN_TABLE,
                DocumentState.IN_TABLE_BODY,
                DocumentState.IN_ROW,
            )
        ):
            # If we are in a cell or caption, handle normally (don't foster)
            if not self._is_in_cell_or_caption(context):
                table = self.parser.find_current_table(context)
                if table and table.parent:
                    self.debug(f"Foster parenting foreign element <{tag_name}> before table")
                    table_index = table.parent.children.index(table)

                    # Create the new node
                    if tag_name_lower == "math":
                        fixed_attrs = self._fix_foreign_attribute_case(token.attributes, "math")
                        new_node = Node(f"math {tag_name}", fixed_attrs)
                        context.current_context = "math"
                    elif tag_name_lower == "svg":
                        fixed_attrs = self._fix_foreign_attribute_case(token.attributes, "svg")
                        new_node = Node(f"svg {tag_name}", fixed_attrs)
                        context.current_context = "svg"

                    table.parent.children.insert(table_index, new_node)
                    new_node.parent = table.parent
                    context.enter_element(new_node)

                    # We are no longer in the table, so switch state
                    self.parser.transition_to_state(context, DocumentState.IN_BODY)
                    return True
        return False

    def _handle_html_breakout(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle HTML elements breaking out of foreign content"""
        tag_name_lower = token.tag_name.lower()
        
        if not (context.current_context in ("svg", "math") and tag_name_lower in HTML_BREAK_OUT_ELEMENTS):
            return False
            
        # Check if we're in an integration point where HTML is allowed
        in_integration_point = False
        
        # Check for MathML integration points
        if context.current_context == "math":
            # Check if we're inside annotation-xml with HTML encoding
            annotation_xml = context.current_parent.find_ancestor_until(
                lambda n: (
                    n.tag_name == "math annotation-xml" and 
                    n.attributes.get("encoding", "").lower() in ("application/xhtml+xml", "text/html")
                ),
                None
            )
            if annotation_xml:
                in_integration_point = True
            
            # Check if we're inside mtext/mi/mo/mn/ms which are integration points for ALL HTML elements
            if not in_integration_point:
                mtext_ancestor = context.current_parent.find_ancestor(
                    lambda n: n.tag_name in ("math mtext", "math mi", "math mo", "math mn", "math ms"))
                if mtext_ancestor:
                    # These are integration points - ALL HTML elements should remain HTML
                    in_integration_point = True
        
        # Check for SVG integration points  
        elif context.current_context == "svg":
            # Check if we're inside foreignObject, desc, or title
            integration_ancestor = context.current_parent.find_ancestor(
                lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title"))
            if integration_ancestor:
                in_integration_point = True
        
        # Only break out if NOT in an integration point
        if not in_integration_point:
            # Special case: font element only breaks out if it has attributes
            # Special case: font elements with HTML-specific attributes should break out
            if tag_name_lower == "font":
                # Check if font has HTML-specific attributes that should cause breakout
                html_font_attrs = {"color", "face", "size"}
                has_html_attrs = any(attr.lower() in html_font_attrs for attr in token.attributes)
                if has_html_attrs:
                    # font with HTML attributes breaks out of foreign context
                    pass  # Continue with breakout logic
                else:
                    # font with non-HTML attributes stays in foreign context
                    return False
            
            # HTML elements break out of foreign content and are processed as regular HTML
            self.debug(f"HTML element {tag_name_lower} breaks out of foreign content")
            context.current_context = None  # Exit foreign context
            
            # Look for the nearest table in the document tree that's still open
            table = context.current_parent.find_ancestor("table")
            
            # Also check self.parser.find_current_table(context)
            if not table and self.parser.find_current_table(context):
                table = self.parser.find_current_table(context)
            
            # Check if we're inside a caption/cell before deciding to foster parent
            in_caption_or_cell = context.current_parent.find_ancestor(lambda n: n.tag_name in ("td", "th", "caption"))
            
            # Check if we need to foster parent before exiting foreign context
            if (table and table.parent and not in_caption_or_cell):
                
                # Foster parent the HTML element before the table
                table_index = table.parent.children.index(table)
                self.debug(f"Foster parenting HTML element <{tag_name_lower}> before table")
                
                # Create the HTML element
                new_node = Node(tag_name_lower, token.attributes)
                table.parent.children.insert(table_index, new_node)
                new_node.parent = table.parent
                context.enter_element(new_node)
                
                # Update document state - we're still in the table context logically
                self.parser.transition_to_state(context, DocumentState.IN_TABLE)
                return True
            
            # If we're in caption/cell, move to that container instead of foster parenting
            if in_caption_or_cell:
                self.debug(f"HTML element {tag_name_lower} breaking out inside {in_caption_or_cell.tag_name}")
                context.move_to_element(in_caption_or_cell)
                return False  # Let other handlers process this element
            
            # Move current_parent up to the appropriate level, but never make it None
            if context.current_parent:
                # In fragment parsing, go to document-fragment
                # In document parsing, go to html_node (or stay if we're already there)
                if self.parser.fragment_context:
                    target = context.current_parent.find_ancestor("document-fragment")
                    if target:
                        context.move_to_element(target)
                else:
                    # In document parsing, go back to the HTML node or body
                    target = context.current_parent.find_ancestor_until(
                        lambda n: n.tag_name in ("html", "body"),
                        stop_at=None
                    )
                    if target:
                        context.move_to_element(target)
            return False  # Let other handlers process this element
        
        return False

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        """Decide if this foreign handler should process a start tag.

        Returns True when we want the foreign handler to create a foreign element node
        (svg/math prefixed). Returns False to delegate to normal HTML handlers.
        """
        # 1. Restricted contexts: inside <select> we don't start foreign elements
        if tag_name in ("svg", "math") and context.current_parent.is_inside_tag("select"):
            return False

        # 2. Already inside SVG foreign content
        if context.current_context == "svg":
            # SVG integration points (foreignObject/desc/title) switch back to HTML parsing rules
            if (
                context.current_parent.tag_name in ("svg foreignObject", "svg desc", "svg title") or
                context.current_parent.has_ancestor_matching(lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title"))
            ):
                # Exception: table-related tags should STILL be treated as foreign (tests expect nested <svg tag>)
                table_related = {"table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "col", "colgroup"}
                if tag_name.lower() in table_related:
                    return True  # handle as foreign element
                return False  # delegate other HTML tags to HTML handlers
            return True  # keep handling inside generic SVG subtree

        # 3. Already inside MathML foreign content
        if context.current_context == "math":
            # MathML text integration points (mtext, mi, mo, mn, ms) treat contained HTML tags as HTML
            in_text_ip = context.current_parent.find_ancestor(
                lambda n: n.tag_name in ("math mtext", "math mi", "math mo", "math mn", "math ms")
            ) is not None
            if in_text_ip:
                from .constants import HTML_ELEMENTS, TABLE_ELEMENTS
                tnl = tag_name.lower()
                if tnl in HTML_ELEMENTS and tnl not in TABLE_ELEMENTS and tnl != "table":
                    return False
            # annotation-xml with HTML/XHTML encoding delegates HTML elements
            if context.current_parent.tag_name == "math annotation-xml":
                encoding = context.current_parent.attributes.get("encoding", "").lower()
                if encoding in ("application/xhtml+xml", "text/html"):
                    from .constants import HTML_ELEMENTS
                    if tag_name.lower() in HTML_ELEMENTS:
                        return False
            return True

        # 4. Starting a new foreign context root or MathML element outside context
        if tag_name in ("svg", "math"):
            return True
        if tag_name in MATHML_ELEMENTS:
            return True

        # Otherwise let HTML handlers process it
        return False

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        tag_name_lower = tag_name.lower()

        # Check for foster parenting in table context
        if self._handle_foreign_foster_parenting(token, context):
            return True

        # Check for HTML elements breaking out of foreign content
        breakout_result = self._handle_html_breakout(token, context)
        if breakout_result is not False:
            return breakout_result

        if context.current_context == "math":
            # Check for invalid table element nesting in MathML
            if tag_name_lower in ("tr", "td", "th", "tbody", "thead", "tfoot"):
                # Invalid table nesting in MathML: drop the element completely
                current_ancestors = []
                parent = context.current_parent
                while parent:
                    current_ancestors.append(parent.tag_name)
                    parent = parent.parent
                
                # Check for invalid nesting patterns
                invalid_patterns = [
                    (tag_name_lower == "tr" and any(ancestor in ["math td", "math th"] for ancestor in current_ancestors)),
                    (tag_name_lower == "td" and any(ancestor in ["math td", "math th"] for ancestor in current_ancestors)),
                    (tag_name_lower == "th" and any(ancestor in ["math td", "math th"] for ancestor in current_ancestors)),
                    (tag_name_lower in ("tbody", "thead", "tfoot") and any(ancestor in ["math tbody", "math thead", "math tfoot"] for ancestor in current_ancestors)),
                ]
                
                if any(invalid_patterns):
                    self.debug(f"MathML: Dropping invalid table element {tag_name_lower} in context {current_ancestors}")
                    return True  # Ignore this element completely
            
            # Auto-close certain MathML elements when encountering table elements
            if tag_name_lower in ("tr", "td", "th") and context.current_parent.tag_name.startswith("math "):
                # Find if we're inside a MathML operator/leaf element that should auto-close
                auto_close_elements = ["math mo", "math mi", "math mn", "math mtext", "math ms"]
                if context.current_parent.tag_name in auto_close_elements:
                    self.debug(f"Auto-closing {context.current_parent.tag_name} for {tag_name_lower}")
                    if context.current_parent.parent:
                        context.move_up_one_level()
            
            # In foreign contexts, RAWTEXT elements behave as normal elements
            if tag_name_lower in RAWTEXT_ELEMENTS:
                self.debug(f"Treating {tag_name_lower} as normal element in foreign context")
                new_node = Node(f"math {tag_name}", token.attributes)
                context.current_parent.append_child(new_node)
                context.enter_element(new_node)
                # Reset tokenizer if it entered RAWTEXT mode
                if hasattr(self.parser, 'tokenizer') and self.parser.tokenizer.state == "RAWTEXT":
                    self.parser.tokenizer.state = "DATA"
                    self.parser.tokenizer.rawtext_tag = None
                return True
            
            # Handle MathML elements
            if tag_name_lower == "annotation-xml":
                new_node = Node("math annotation-xml", self._fix_foreign_attribute_case(token.attributes, "math"))
                context.current_parent.append_child(new_node)
                if not token.is_self_closing:
                    context.enter_element(new_node)
                return True

            # Handle HTML elements inside annotation-xml
            if context.current_parent.tag_name == "math annotation-xml":
                encoding = context.current_parent.attributes.get("encoding", "").lower()
                if encoding in ("application/xhtml+xml", "text/html"):
                    # Keep HTML elements nested for these encodings
                    new_node = Node(tag_name_lower, self._fix_foreign_attribute_case(token.attributes, "math"))
                    context.current_parent.append_child(new_node)
                    if not token.is_self_closing:
                        context.enter_element(new_node)
                    return True
                # Handle SVG inside annotation-xml (switch to SVG context)
                if tag_name_lower == "svg":
                    fixed_attrs = self._fix_foreign_attribute_case(token.attributes, "svg")
                    new_node = Node("svg svg", fixed_attrs)
                    context.current_parent.append_child(new_node)
                    context.enter_element(new_node)
                    context.current_context = "svg"
                    return True
                if tag_name_lower in HTML_ELEMENTS:
                    new_node = Node(tag_name_lower, self._fix_foreign_attribute_case(token.attributes, "math"))
                    context.current_parent.append_child(new_node)
                    if not token.is_self_closing:
                        context.enter_element(new_node)
                    return True
            
            # Handle HTML elements inside MathML integration points (mtext, mi, mo, mn, ms)
            mtext_ancestor = context.current_parent.find_ancestor(
                lambda n: n.tag_name in ("math mtext", "math mi", "math mo", "math mn", "math ms"))
            if mtext_ancestor and tag_name_lower in HTML_ELEMENTS:
                # HTML elements inside MathML integration points remain as HTML
                new_node = Node(tag_name_lower, self._fix_foreign_attribute_case(token.attributes, "math"))
                context.current_parent.append_child(new_node)
                if not token.is_self_closing:
                    context.enter_element(new_node)
                return True

            new_node = Node(f"math {tag_name}", self._fix_foreign_attribute_case(token.attributes, "math"))
            context.current_parent.append_child(new_node)
            # In MathML context, even self-closing tags can contain content
            # Elements like <mi/>, <mn/>, <mo/>, <ms/>, <mtext/> should be able to contain text
            if not token.is_self_closing or tag_name_lower in ("mi", "mn", "mo", "ms", "mtext"):
                context.enter_element(new_node)
            return True

        elif context.current_context == "svg":
            # If we're inside an SVG integration point (foreignObject, desc, title),
            # delegate ALL tags to HTML handlers. HTML parsing rules apply within these
            # subtrees per the HTML spec.
            if (
                context.current_parent.tag_name in ("svg foreignObject", "svg desc", "svg title") or
                context.current_parent.has_ancestor_matching(lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title"))
            ):
                # Delegate HTML elements (including table structures) inside integration points
                if tag_name_lower in HTML_ELEMENTS or tag_name_lower in ("table", "tr", "td", "th", "tbody", "thead", "tfoot", "caption"):
                    self.debug("SVG integration point: delegating HTML/table element to HTML handlers")
                    return False
            # Auto-close certain SVG elements when encountering table elements
            if tag_name_lower in ("tr", "td", "th") and context.current_parent.tag_name.startswith("svg "):
                # Find if we're inside an SVG element that should auto-close
                auto_close_elements = ["svg title", "svg desc"]
                if context.current_parent.tag_name in auto_close_elements:
                    self.debug(f"Auto-closing {context.current_parent.tag_name} for {tag_name_lower}")
                    if context.current_parent.parent:
                        context.move_up_one_level()
                        
            # In foreign contexts, RAWTEXT elements behave as normal elements
            if tag_name_lower in RAWTEXT_ELEMENTS:
                self.debug(f"Treating {tag_name_lower} as normal element in foreign context")
                fixed_attrs = self._fix_foreign_attribute_case(token.attributes, "svg")
                new_node = Node(f"svg {tag_name}", fixed_attrs)
                context.current_parent.append_child(new_node)
                context.enter_element(new_node)
                # Reset tokenizer if it entered RAWTEXT mode
                if hasattr(self.parser, 'tokenizer') and self.parser.tokenizer.state == "RAWTEXT":
                    self.parser.tokenizer.state = "DATA"
                    self.parser.tokenizer.rawtext_tag = None
                return True
                
                # Handle case-sensitive SVG elements
            if tag_name_lower == "foreignobject":
                # Create integration point element with svg prefix for proper detection
                new_node = Node("svg foreignObject", self._fix_foreign_attribute_case(token.attributes, "svg"))
                context.current_parent.append_child(new_node)
                if not token.is_self_closing:
                    context.enter_element(new_node)
                # Track in open elements if available
                if hasattr(context, "open_elements"):
                    context.open_elements.push(new_node)
                return True
            if tag_name_lower in SVG_CASE_SENSITIVE_ELEMENTS:
                correct_case = SVG_CASE_SENSITIVE_ELEMENTS[tag_name_lower]
                fixed_attrs = self._fix_foreign_attribute_case(token.attributes, "svg")
                new_node = Node(f"svg {correct_case}", fixed_attrs)
                context.current_parent.append_child(new_node)
                # Only set as current parent if not self-closing
                if not token.is_self_closing:
                    context.enter_element(new_node)
                # Enter HTML parsing rules inside SVG integration points
                # Do not change global foreign context for integration points; delegation is handled elsewhere
                return True            # Handle HTML elements inside foreignObject, desc, or title (integration points)
            elif tag_name_lower in HTML_ELEMENTS:
                # Check if current parent is integration point or has integration point ancestor
                if (context.current_parent.tag_name in ("svg foreignObject", "svg desc", "svg title") or
                    context.current_parent.has_ancestor_matching(
                        lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title")
                    )):
                    # We're in an integration point - let normal HTML handlers handle this
                    self.debug(f"HTML element {tag_name_lower} in SVG integration point, delegating to HTML handlers")
                    return False  # Let other handlers (TableTagHandler, ParagraphTagHandler, etc.) handle it

            new_node = Node(f"svg {tag_name_lower}", self._fix_foreign_attribute_case(token.attributes, "svg"))
            context.current_parent.append_child(new_node)
            # Only set as current parent if not self-closing
            if not token.is_self_closing:
                context.enter_element(new_node)
            return True

        # Enter new context for svg/math tags
        if tag_name_lower == "math":
            new_node = Node(f"math {tag_name}", self._fix_foreign_attribute_case(token.attributes, "math"))
            context.current_parent.append_child(new_node)
            if not token.is_self_closing:
                context.enter_element(new_node)
                context.current_context = "math"
            return True

        if tag_name_lower == "svg":
            fixed_attrs = self._fix_foreign_attribute_case(token.attributes, "svg")
            new_node = Node(f"svg {tag_name}", fixed_attrs)
            context.current_parent.append_child(new_node)
            if not token.is_self_closing:
                context.enter_element(new_node)
                context.current_context = "svg"
            return True

        # Handle MathML elements outside of MathML context (re-enter MathML)
        if tag_name_lower in MATHML_ELEMENTS:
            new_node = Node(f"math {tag_name}", self._fix_foreign_attribute_case(token.attributes, "math"))
            context.current_parent.append_child(new_node)
            if not token.is_self_closing:
                context.enter_element(new_node)
                context.current_context = "math"
            return True

        return False

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        """Decide if this handler should process an end tag.

        We keep handling end tags while in a foreign context or when still inside
        a subtree created by a foreign root (even if current_context was cleared).
        HTML/table end tags inside integration points are delegated to HTML handlers.
        """
        # While explicitly in SVG context
        if context.current_context == "svg":
            in_ip = (
                context.current_parent.tag_name in ("svg foreignObject", "svg desc", "svg title") or
                context.current_parent.has_ancestor_matching(lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title"))
            )
            if in_ip:
                from .constants import HTML_ELEMENTS, TABLE_ELEMENTS
                tl = tag_name.lower()
                if tl in HTML_ELEMENTS or tl in TABLE_ELEMENTS or tl == "table":
                    return False  # delegate to HTML handlers
        # While explicitly in MathML context
        elif context.current_context == "math":
            in_text_ip = context.current_parent.find_ancestor(
                lambda n: n.tag_name in ("math mtext", "math mi", "math mo", "math mn", "math ms")
            ) is not None
            if in_text_ip:
                from .constants import HTML_ELEMENTS
                if tag_name.lower() in HTML_ELEMENTS:
                    return False
            if context.current_parent.tag_name == "math annotation-xml":
                enc = context.current_parent.attributes.get("encoding", "").lower()
                if enc in ("application/xhtml+xml", "text/html"):
                    from .constants import HTML_ELEMENTS
                    if tag_name.lower() in HTML_ELEMENTS:
                        return False
        # If we are still inside a foreign context
        if context.current_context in ("svg", "math"):
            return True
        # Otherwise detect if any foreign ancestor remains (context may have been cleared by breakout)
        ancestor = context.current_parent.find_ancestor(
            lambda n: n.tag_name.startswith("svg ") or n.tag_name.startswith("math ") or n.tag_name in ("svg foreignObject", "math annotation-xml")
        )
        return ancestor is not None

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name.lower()
        # Find matching element (case-insensitive) accounting for foreign prefixes
        matching_element = context.current_parent.find_ancestor(
            lambda n: ((n.tag_name.split(" ", 1)[-1] if " " in n.tag_name else n.tag_name).lower()) == tag_name
        )

        if matching_element:
            # Move out of the matching element
            if matching_element.parent:
                context.move_to_element(matching_element.parent)
            # If we closed an <svg> or <math> root, clear or restore context
            if matching_element.tag_name.startswith("svg ") and matching_element.tag_name.split(" ",1)[-1] == "svg":
                # We closed an <svg> root element
                # After closing, restore context if there's an outer svg/math ancestor
                context.current_context = None
            elif matching_element.tag_name.startswith("math ") and matching_element.tag_name.split(" ",1)[-1] == "math":
                context.current_context = None
            # After moving, recompute foreign context if any ancestor remains
            ancestor = context.current_parent.find_ancestor(
                lambda n: n.tag_name.startswith("svg ") or n.tag_name.startswith("math ")
            )
            if ancestor:
                if ancestor.tag_name.startswith("svg "):
                    context.current_context = "svg"
                elif ancestor.tag_name.startswith("math "):
                    context.current_context = "math"
            return True

        # If no direct matching element but tag is annotation-xml or foreignObject, attempt targeted close
        if tag_name in ("annotation-xml", "foreignobject"):
            special = context.current_parent.find_ancestor(
                lambda n: n.tag_name.endswith(tag_name) if tag_name != "foreignobject" else n.tag_name.endswith("foreignObject")
            )
            if special and special.parent:
                context.move_to_element(special.parent)
                # Recompute context
                ancestor = context.current_parent.find_ancestor(
                    lambda n: n.tag_name.startswith("svg ") or n.tag_name.startswith("math ")
                )
                if ancestor:
                    context.current_context = "svg" if ancestor.tag_name.startswith("svg ") else "math"
                else:
                    context.current_context = None
                return True

    # (Removed heuristic breakout for unmatched HTML end tags inside foreign content to avoid regressions)

        return True  # Ignore if nothing matched

    def should_handle_text(self, text: str, context: "ParseContext") -> bool:
        # Delegate text to HTML handlers inside integration points
        if context.current_context == "svg":
            if (
                context.current_parent.tag_name in ("svg foreignObject", "svg desc", "svg title") or
                context.current_parent.has_ancestor_matching(lambda n: n.tag_name in ("svg foreignObject", "svg desc", "svg title"))
            ):
                return False
        elif context.current_context == "math":
            # MathML text integration points (mtext, mi, mo, mn, ms)
            in_text_ip = context.current_parent.find_ancestor(
                lambda n: n.tag_name in ("math mtext", "math mi", "math mo", "math mn", "math ms")
            ) is not None
            if in_text_ip:
                return False
            # annotation-xml with HTML/XHTML encoding
            if context.current_parent.tag_name == "math annotation-xml":
                encoding = context.current_parent.attributes.get("encoding", "").lower()
                if encoding in ("application/xhtml+xml", "text/html"):
                    return False
        return context.current_context in ("svg", "math")

    def handle_text(self, text: str, context: "ParseContext") -> bool:
        if not self.should_handle_text(text, context):
            return False

        # Check for table foster parenting before other text handling
        if (context.document_state == DocumentState.IN_TABLE and 
            not self._is_in_integration_point(context) and
            not text.isspace()):  # Only foster parent non-whitespace text
            self.debug(f"Foster parenting text '{text}' out of table context")
            self._foster_parent_text(text, context)
            return True

        # In foreign content, text is just appended.
        # Try to merge with previous text node.
        if context.current_parent.children and context.current_parent.children[-1].tag_name == "#text":
            context.current_parent.children[-1].text_content += text
        else:
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
        return True

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

    def _foster_parent_text(self, text: str, context: "ParseContext") -> None:
        """Foster parent text content before the current table"""
        # Find the table element
        table = self.parser.find_current_table(context)
        if not table:
            # No table found, just append normally
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return
        
        # Find the table's parent
        table_parent = table.parent
        if not table_parent:
            # Table has no parent, just append normally
            text_node = Node("#text")
            text_node.text_content = text
            context.current_parent.append_child(text_node)
            return
        
        # Create text node and insert it before the table
        text_node = Node("#text")
        text_node.text_content = text
        table_parent.insert_before(text_node, table)
        self.debug(f"Foster parented text '{text}' before table")

    def should_handle_comment(self, comment: str, context: "ParseContext") -> bool:
        """Handle <![CDATA[...]]> sequences seen as comments by the tokenizer in foreign content.

        In SVG/MathML contexts (but not integration points like foreignObject/desc/title),
        treat CDATA as text. Support incomplete CDATA at EOF by emitting the inner text.
        """
        if context.current_context not in ("svg", "math"):
            return False
        # If inside an integration point that uses HTML parsing, do not special-case CDATA
        current = context.current_parent
        while current:
            if current.tag_name in ("svg foreignObject", "svg desc", "svg title"):
                return False
            current = current.parent
        return comment.startswith("[CDATA[")

    def handle_comment(self, comment: str, context: "ParseContext") -> bool:
        """Convert <![CDATA[...]]> sequences to text content in foreign elements."""
        if not self.should_handle_comment(comment, context):
            return False
        
        inner = ""
        if comment.startswith("[CDATA["):
            if comment.endswith("]]") and len(comment) >= 9:
                inner = comment[7:-2]
            else:
                inner = comment[7:]
        
        # Do not emit empty text for empty CDATA blocks
        if inner == "":
            return True
        
        self.debug(f"Converting CDATA to text: '{inner}' in {context.current_context} context")
        # Add as text content (similar to handle_text)
        if context.current_parent.children and context.current_parent.children[-1].tag_name == "#text":
            context.current_parent.children[-1].text_content += inner
        else:
            text_node = Node("#text")
            text_node.text_content = inner
            context.current_parent.append_child(text_node)
        return True


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

        # Special handling for template elements
        if tag_name == "template":
            return self._handle_template_start(token, context)

        # If we're in table context, foster parent head elements to body
        if context.document_state == DocumentState.IN_TABLE:
            self.debug(f"Head element {tag_name} in table context, foster parenting to body")
            table = self.parser.find_current_table(context)
            if table and table.parent:
                # Foster parent before the table
                new_node = Node(tag_name, token.attributes)
                table_index = table.parent.children.index(table)
                table.parent.children.insert(table_index, new_node)
                
                # For elements that can have content, update current parent
                if tag_name not in VOID_ELEMENTS:
                    context.enter_element(new_node)
                    if tag_name in RAWTEXT_ELEMENTS:
                        context.content_state = ContentState.RAWTEXT
                        self.debug(f"Switched to RAWTEXT state for {tag_name}")
                return True

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
                        context.enter_element(new_node)
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
                context.enter_element(new_node)
                if tag_name in RAWTEXT_ELEMENTS:
                    context.content_state = ContentState.RAWTEXT
                    self.debug(f"Switched to RAWTEXT state for {tag_name}")
            return True

        # Handle head elements in head normally
        else:
            self.debug("Handling element in head context")
            # If we're not in head (and not after head), switch to head
            if context.document_state not in (DocumentState.IN_HEAD, DocumentState.AFTER_HEAD):
                head = self.parser._ensure_head_node()
                self.parser.transition_to_state(context, DocumentState.IN_HEAD, head)
                self.debug("Switched to head state")
            elif context.document_state == DocumentState.AFTER_HEAD:
                # Head elements after </head> should go back to head (foster parenting)
                self.debug("Head element appearing after </head>, foster parenting to head")
                head = self.parser._ensure_head_node()
                if head:
                    context.move_to_element(head)

            # Create and append the new element
            new_node = Node(tag_name, token.attributes)
            if context.current_parent is not None:
                context.current_parent.append_child(new_node)
                self.debug(f"Added {tag_name} to {context.current_parent.tag_name}")
            else:
                self.debug(f"No current parent for {tag_name} in fragment context, skipping")

            # For elements that can have content, update current parent
            if tag_name not in VOID_ELEMENTS:
                context.enter_element(new_node)
                if tag_name in RAWTEXT_ELEMENTS:
                    context.content_state = ContentState.RAWTEXT
                    self.debug(f"Switched to RAWTEXT state for {tag_name}")

        return True

    def _handle_template_start(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle template element start tag with special content document fragment"""
        self.debug("handling template start tag")
        
        # Create the template element
        template_node = Node("template", token.attributes)
        
        # Create the special "content" document fragment
        content_node = Node("content", {})
        template_node.append_child(content_node)
        
        # Add template to the appropriate parent
        if context.document_state == DocumentState.IN_BODY:
            # If we're in body after seeing real content
            if (context.current_parent.tag_name == "html" and
                not self._has_body_content(context.current_parent)):
                # Template appearing before body content should go to head
                head = self.parser._ensure_head_node()
                if head:
                    head.append_child(template_node)
                    self.debug("Added template to head (no body content yet)")
                else:
                    context.current_parent.append_child(template_node)
                    self.debug("Added template to current parent (head not available)")
            else:
                # Template appearing after body content should stay in body
                context.current_parent.append_child(template_node)
                self.debug("Added template to body")
        elif context.document_state == DocumentState.INITIAL:
            # Template at document start should go to head
            head = self.parser._ensure_head_node()
            self.parser.transition_to_state(context, DocumentState.IN_HEAD, head)
            self.debug("Switched to head state for template at document start")
            context.current_parent.append_child(template_node)
            self.debug("Added template to head")
        elif context.document_state == DocumentState.IN_HEAD:
            # Template in head context stays in head
            context.current_parent.append_child(template_node)
            self.debug("Added template to head")
        else:
            # For other states (IN_TABLE, etc.), template stays in current context
            context.current_parent.append_child(template_node)
            self.debug(f"Added template to current parent in {context.document_state} state")
        
        # Set current to the content document fragment
        context.move_to_element(content_node)
        self.debug("Set current parent to template content")
        
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "head" or tag_name == "template"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        self.debug(f"handling end tag {token.tag_name}")
        self.debug(f"current state: {context.document_state}, current parent: {context.current_parent}")

        # Handle head end tag
        if token.tag_name == "head":
            self.debug("handling head end tag")
            if context.document_state == DocumentState.IN_HEAD:
                # Transition to AFTER_HEAD state and move to html parent
                self.parser.transition_to_state(context, DocumentState.AFTER_HEAD)
                if context.current_parent and context.current_parent.tag_name == "head":
                    if context.current_parent.parent:
                        context.move_up_one_level()
                    else:
                        # If head has no parent, set to html node
                        context.move_to_element(self.parser.html_node)
                self.debug(f"transitioned to AFTER_HEAD, current parent: {context.current_parent}")
            elif context.document_state == DocumentState.INITIAL:
                # If we see </head> in INITIAL state, transition to AFTER_HEAD
                # This handles cases like <!doctype html></head> where no <head> was opened
                self.parser.transition_to_state(context, DocumentState.AFTER_HEAD)
                # Ensure html structure exists and move to html parent
                self.parser._ensure_html_node()
                context.move_to_element(self.parser.html_node)
                self.debug(f"transitioned from INITIAL to AFTER_HEAD, current parent: {context.current_parent}")
            return True

        # For template, only close up to the nearest template boundary
        if token.tag_name == "template":
            self.debug("handling template end tag")
            self.debug(f"starting search at: {context.current_parent}")

            # Find nearest template ancestor, stopping at boundaries
            template_ancestor = context.current_parent.find_ancestor("template", stop_at_boundary=True)

            if template_ancestor:
                self.debug(f"found matching template, moving to parent: {template_ancestor.parent}")
                context.move_to_element(template_ancestor.parent)
                return True

            self.debug("no matching template found within boundaries")
            return False

        if context.content_state == ContentState.RAWTEXT:
            self.debug(f"handling RAWTEXT end tag {token.tag_name}")
            # Restore content state
            context.content_state = ContentState.NONE
            # Move up to parent
            if context.current_parent and context.current_parent.parent:
                context.move_up_one_level()
                # If we're in AFTER_HEAD state and current parent is head, 
                # move to html level for subsequent content
                if (context.document_state == DocumentState.AFTER_HEAD and 
                    context.current_parent.tag_name == "head"):
                    context.move_to_element(self.parser.html_node)
                self.debug(f"returned to parent: {context.current_parent}, document state: {context.document_state}")
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

        # Special handling for textarea: ignore first newline if present and it's the first content
        if (context.current_parent.tag_name == "textarea" and 
            not context.current_parent.children and 
            text.startswith("\n")):
            self.debug("Removing initial newline from textarea")
            text = text[1:]
            # If the text was only a newline, don't create a text node
            if not text:
                return True

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
        # Ignore subsequent html start tags - only the first one should set attributes
        if self.parser.html_node and self.parser.html_node.attributes:
            self.debug("Ignoring subsequent html start tag (attributes already set)")
            return True
        # Update html node attributes if it exists and has no attributes yet
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
                self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

        # Any content after </html> should be treated as body content
        elif context.document_state == DocumentState.AFTER_HTML:
            self.debug("Content after </html>, switching to body mode")
            body = self.parser._ensure_body_node(context)
            self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

        return True


class FramesetTagHandler(TagHandler):
    """Handles frameset, frame, and noframes elements"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("frameset", "frame", "noframes")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling {tag_name}")

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
                self.parser.transition_to_state(context, DocumentState.IN_FRAMESET, new_node)
            else:
                # Nested frameset
                self.debug("Creating nested frameset")
                new_node = Node(tag_name, token.attributes)
                context.current_parent.append_child(new_node)
                context.enter_element(new_node)
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
            context.enter_element(new_node)
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
                    context.move_to_element(target.parent)
                else:
                    # Otherwise stay at root level
                    context.move_to_element(self.parser.html_node)
                return True
            return False

        elif tag_name == "noframes":
            if context.current_parent.tag_name == "noframes":
                # Return to frameset
                parent = context.current_parent.parent
                if parent and parent.tag_name == "frameset":
                    context.move_to_element(parent)
                    self.parser.transition_to_state(context, DocumentState.IN_FRAMESET)
                else:
                    self.parser.transition_to_state(context, DocumentState.IN_FRAMESET, self.parser.html_node)
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
            self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

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
                if self.parser.html_node:
                    context.move_to_element(self.parser.html_node)
                else:
                    # Fallback to body if parser's html_node is None
                    context.move_to_element(body)
                self.parser.transition_to_state(context, DocumentState.AFTER_BODY)
            return True
        return False


class BoundaryElementHandler(TagHandler):
    """Handles elements that can affect formatting elements like marquee"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        # Only handle marquee here. Other boundary/special elements (e.g., object,
        # table, td, th, template) are handled by dedicated handlers.
        return tag_name == "marquee"

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        # If we're in a <p> tag, close it first
        p_ancestor = context.current_parent.find_ancestor("p")
        if p_ancestor and p_ancestor.parent:
            self.debug(f"Found p ancestor, closing it first: {p_ancestor}")
            context.move_to_element(p_ancestor.parent)

        # Check if we're inside a formatting element
        formatting_element = context.current_parent.find_ancestor(lambda n: n.tag_name in FORMATTING_ELEMENTS)
        if formatting_element:
            self.debug(f"Found formatting element ancestor: {formatting_element}")
            self.debug(f"Current parent before: {context.current_parent}")

            # Create the boundary element
            new_node = Node(token.tag_name, token.attributes)
            formatting_element.append_child(new_node)
            context.enter_element(new_node)
            self.debug(f"Created boundary element {new_node.tag_name} under {formatting_element.tag_name}")

            # Create an implicit paragraph inside the boundary element
            new_p = Node("p")
            new_node.append_child(new_p)
            context.enter_element(new_p)
            self.debug(f"Created implicit paragraph under {new_node.tag_name}")
            return True

        # Create the boundary element normally
        new_node = Node(token.tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.enter_element(new_node)

        # Create an implicit paragraph inside the boundary element
        new_p = Node("p")
        new_node.append_child(new_p)
        context.enter_element(new_p)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "marquee"

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
        formatting_elements = context.current_parent.collect_ancestors_until(
            stop_at=target,
            predicate=lambda n: n.tag_name in FORMATTING_ELEMENTS
        )
        for fmt_elem in formatting_elements:
            self.debug(f"found formatting element to close: {fmt_elem.tag_name}")

        # Close any formatting elements inside the boundary element
        if formatting_elements:
            self.debug(f"closing formatting elements: {[f.tag_name for f in formatting_elements]}")
            # Move back to the boundary element's parent
            context.move_to_element_with_fallback(target.parent, self.parser.html_node)
            self.debug(f"moved to boundary parent: {context.current_parent}")

            # Look for outer formatting element of same type
            outer_fmt = target.parent.find_ancestor(
                lambda n: (n.tag_name in FORMATTING_ELEMENTS and n.tag_name == formatting_elements[0].tag_name)
            )

            if outer_fmt:
                self.debug(f"found outer formatting element: {outer_fmt}")
                context.move_to_element(outer_fmt)
                self.debug(f"moved to outer formatting element: {context.current_parent}")
        else:
            self.debug("no formatting elements to close")
            context.move_to_element_with_fallback(target.parent, self.parser.html_node)
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
        
        # If the document has already started (any elements have been processed), 
        # ignore unexpected DOCTYPEs per HTML5 spec
        if (context.document_state != DocumentState.INITIAL or 
            len(self.parser.root.children) > 0):
            self.debug("Ignoring unexpected DOCTYPE after document started")
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


class PlaintextHandler(SelectAwareHandler):
    """Handles plaintext element which switches to plaintext mode"""

    def _should_handle_start_impl(self, tag_name: str, context: "ParseContext") -> bool:
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

        # If we're in INITIAL, AFTER_HEAD, or AFTER_BODY state, ensure we have body
        if context.document_state in (DocumentState.INITIAL, DocumentState.AFTER_HEAD, DocumentState.AFTER_BODY):
            body = self.parser._ensure_body_node(context)
            self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

        # Check if we're inside a paragraph and close it (plaintext is a block element)
        if context.current_parent.tag_name == "p":
            self.debug("Closing paragraph before plaintext")
            context.move_up_one_level()

        # Create plaintext node
        new_node = Node("plaintext", token.attributes)

        # If we're in a table but NOT in a valid content area (td, th, caption), foster parent
        if (context.document_state == DocumentState.IN_TABLE and 
            context.current_parent.tag_name not in ("td", "th", "caption")):
            self.debug("Foster parenting plaintext out of table")
            table = self.parser.find_current_table(context)
            if table and table.parent:
                table_index = table.parent.children.index(table)
                table.parent.children.insert(table_index, new_node)
                self.parser.transition_to_state(context, DocumentState.IN_BODY, new_node)
                # Switch to PLAINTEXT mode
                context.content_state = ContentState.PLAINTEXT
                return True
        else:
            context.current_parent.append_child(new_node)
            context.enter_element(new_node)

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

        # Create button normally - adoption agency will handle any formatting elements
        new_button = Node("button", token.attributes)
        context.current_parent.append_child(new_button)
        context.enter_element(new_button)
        return True

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name == "button"

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        button = context.current_parent.find_ancestor("button")
        if button:
            context.move_to_element(button.parent)
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
                    context.move_to_element_with_fallback(menuitem_ancestor.parent, context.current_parent)
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

        # Reconstruct active formatting elements before inserting menuitem, so elements like <b>
        # continue outside closed paragraphs per HTML5 parsing behavior
        if hasattr(self.parser, 'adoption_agency'):
                self.parser.reconstruct_active_formatting_elements(context)

        # Create the menuitem element
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.enter_element(new_node)  # Set as current parent to contain children
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
                context.move_to_element_with_fallback(menuitem.parent, context.current_parent)
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
                    context.move_to_element_with_fallback(menuitem.parent, context.current_parent)
                    return True

        # No menuitem found, treat as stray end tag
        self.debug("No menuitem ancestor found, treating as stray end tag")
        return True


class UnknownElementHandler(TagHandler):
    """Handle unknown/namespace elements with basic start/end tag matching"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        """Only handle unknown elements that contain colons (namespace) or are truly unknown"""
        # Handle namespace elements (contain colon) that aren't handled by other handlers
        if ":" in tag_name:
            return True
        return False

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        """Handle unknown element start tags with default element creation"""
        # This will be handled by default element creation in parser
        return False  # Let default handling create the element

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        """Handle end tags for unknown elements if current parent matches"""
        if ":" in tag_name and context.current_parent.tag_name == tag_name:
            return True
        return False

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        """Handle unknown element end tags by closing the current element"""
        tag_name = token.tag_name
        
        if context.current_parent.tag_name == tag_name:
            # Close the matching element
            if context.current_parent.parent:
                context.move_up_one_level()
                self.debug(f"UnknownElementHandler: closed {tag_name}, current_parent now: {context.current_parent.tag_name}")
            else:
                # At root level, don't change current_parent to avoid issues
                self.debug(f"UnknownElementHandler: {tag_name} at root level, leaving current_parent unchanged")
            return True
            
        return False


class RubyElementHandler(TagHandler):
    """Handles ruby annotation elements with proper auto-closing behavior"""

    def should_handle_start(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("ruby", "rb", "rt", "rp", "rtc")

    def handle_start(self, token: "HTMLToken", context: "ParseContext", has_more_content: bool) -> bool:
        tag_name = token.tag_name
        self.debug(f"handling {tag_name}")

        # If we're in head, implicitly close it and switch to body
        if context.document_state in (DocumentState.INITIAL, DocumentState.IN_HEAD):
            self.debug("Implicitly closing head and switching to body for ruby element")
            body = self.parser._ensure_body_node(context)
            self.parser.transition_to_state(context, DocumentState.IN_BODY, body)

        # Handle auto-closing behavior for ruby elements
        if tag_name in ("rb", "rt", "rp"):
            # These elements auto-close each other and rtc
            self._auto_close_ruby_elements(tag_name, context)
        elif tag_name == "rtc":
            # rtc auto-closes rb, rt, rp
            self._auto_close_ruby_elements(tag_name, context)

        # Create the new element
        new_node = Node(tag_name, token.attributes)
        context.current_parent.append_child(new_node)
        context.enter_element(new_node)
        return True

    def _auto_close_ruby_elements(self, tag_name: str, context: "ParseContext") -> None:
        """Auto-close conflicting ruby elements according to HTML5 spec"""
        elements_to_close = []
        
        if tag_name == "rb":
            # rb auto-closes rb, rt, rp, rtc (all other ruby elements)
            elements_to_close = ["rb", "rt", "rp", "rtc"]
        elif tag_name == "rt":
            # rt auto-closes rb, rp but NOT rtc (rt can be inside rtc)
            elements_to_close = ["rb", "rp"]
        elif tag_name == "rp":
            # rp auto-closes rb, rt but NOT rtc (rp can be inside rtc)
            elements_to_close = ["rb", "rt"]
        elif tag_name == "rtc":
            # rtc auto-closes rb, rt, rp, and other rtc elements
            elements_to_close = ["rb", "rt", "rp", "rtc"]
        
        # Look for elements to auto-close in current context
        element_to_close = context.current_parent.find_ancestor_until(
            lambda n: n.tag_name in elements_to_close,
            stop_at=context.current_parent.find_ancestor("ruby")
        )
        
        if element_to_close:
            self.debug(f"Auto-closing {element_to_close.tag_name} for new {tag_name}")
            context.move_to_element_with_fallback(element_to_close.parent, context.current_parent)

    def should_handle_end(self, tag_name: str, context: "ParseContext") -> bool:
        return tag_name in ("ruby", "rb", "rt", "rp", "rtc")

    def handle_end(self, token: "HTMLToken", context: "ParseContext") -> bool:
        tag_name = token.tag_name
        self.debug(f"handling end tag {tag_name}")

        # Find the nearest matching element
        matching_element = context.current_parent.find_ancestor_until(
            lambda n: n.tag_name == tag_name,
            context.current_parent.find_ancestor("ruby") if tag_name != "ruby" else None
        )
        
        if matching_element:
            # Found matching element, move to its parent
            context.move_to_element_with_fallback(matching_element.parent, context.current_parent)
            self.debug(f"Closed {tag_name}, current_parent now: {context.current_parent.tag_name}")
            return True

        # If no matching element found, ignore the end tag
        self.debug(f"No matching {tag_name} found, ignoring end tag")
        return True
