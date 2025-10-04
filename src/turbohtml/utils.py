"""Parsing utility functions.

Helper functions used across multiple modules (handlers, formatting, etc.)
that don't belong to any specific domain (foster parenting, formatting, adoption).
"""

from turbohtml.node import Node
from turbohtml.context import DocumentState
from turbohtml.constants import FORMATTING_ELEMENTS


def get_body(root):
    """Find existing body node in the document tree."""
    if not root:
        return None
    # Find html node first
    html_node = None
    for child in root.children:
        if child.tag_name == "html":
            html_node = child
            break
    if not html_node:
        return None
    # Find body in html node
    for child in html_node.children:
        if child.tag_name == "body":
            return child
    return None


def has_root_frameset(root):
    """Return True if <html> (when present) has a direct <frameset> child."""
    if not root:
        return False
    # Find html node first
    html_node = None
    for child in root.children:
        if child.tag_name == "html":
            html_node = child
            break
    return bool(
        html_node
        and any(ch.tag_name == "frameset" for ch in html_node.children)
    )


def ensure_body(root, document_state, fragment_context=None):
    """Return existing <body> or create one (unless frameset/fragment constraints block it)."""
    if fragment_context:
        if fragment_context == "html":
            head = None
            body = None

            for child in root.children:
                if child.tag_name == "head":
                    head = child
                elif child.tag_name == "body":
                    body = child

            if not head:
                head = Node("head")
                root.append_child(head)

            if not body:
                body = Node("body")
                root.append_child(body)

            return body
        else:
            return None
    if document_state == DocumentState.IN_FRAMESET:
        return None
    body = get_body(root)
    if not body:
        # Find html node to append body to
        html_node = None
        for child in root.children:
            if child.tag_name == "html":
                html_node = child
                break
        if html_node:
            body = Node("body")
            html_node.append_child(body)
    return body


def find_current_table(context):
    """Find the current table element from the open elements stack when in table context."""
    # Always search open elements stack first (even in IN_BODY) so foster-parenting decisions
    # can detect an open table that the insertion mode no longer reflects (foreign breakout, etc.).
    for element in reversed(context.open_elements._stack):
        if element.tag_name == "table":
            return element

    # Fallback: traverse ancestors from current parent (rare recovery)
    current = context.current_parent
    while current:
        if current.tag_name == "table":
            return current
        current = current.parent
    return None


def reconstruct_active_formatting_elements(parser, context):
    """Reconstruct active formatting elements inside the current parent.

    Spec-compliant reconstruction algorithm that maintains formatting element context
    across block boundaries and table foster parenting scenarios.
    """
    afe = context.active_formatting_elements
    if afe.is_empty():
        return
    afe_list = list(afe)
    if not afe_list:
        return
    index_to_reconstruct_from = None
    for i, entry in enumerate(afe_list):
        if entry.element is None:
            continue
        if not context.open_elements.contains(entry.element):
            index_to_reconstruct_from = i
            break
    if index_to_reconstruct_from is None:
        return
    afe_list = list(afe)
    if index_to_reconstruct_from is None:  # defensive repeat (unchanged)
        return
    for entry in afe_list[index_to_reconstruct_from:]:
        if entry.element is None:
            continue
        if context.open_elements.contains(entry.element):
            continue
        # Suppress redundant sibling <nobr> reconstruction at block/body level
        if (
            entry.element.tag_name == "nobr"
            and context.current_parent.tag_name in ("body", "div", "section", "article", "p")
            and context.current_parent.children
            and context.current_parent.children[-1].tag_name == "nobr"
        ):
            continue
        # Reuse existing current_parent for <nobr> only when it is empty (no children) to avoid
        # collapsing expected sibling <nobr> wrappers that follow immediately after text or <br>.
        if (
            entry.element.tag_name == "nobr"
            and context.current_parent
            and context.current_parent.tag_name == entry.element.tag_name
            and context.current_parent.attributes == entry.element.attributes
            and not context.current_parent.children  # strictly empty
        ):
            entry.element = context.current_parent
            context.open_elements.push(context.current_parent)
            if parser.env_debug:
                parser.debug(
                    f"Reconstructed (reused) formatting element {context.current_parent.tag_name} (empty reuse)"
                )
            continue
        clone = Node(entry.element.tag_name, entry.element.attributes.copy())
        if context.document_state in (
            DocumentState.IN_TABLE,
            DocumentState.IN_TABLE_BODY,
            DocumentState.IN_ROW,
        ):
            table_node = find_current_table(context)
            inside_table_subtree = False
            cur_parent = context.current_parent
            while cur_parent:
                if cur_parent is table_node:
                    inside_table_subtree = True
                    break
                cur_parent = cur_parent.parent
            if (
                table_node
                and not inside_table_subtree
                and context.current_parent.tag_name in FORMATTING_ELEMENTS
                and table_node.parent is not None
            ):
                foster_parent = table_node.parent
                try:
                    insert_at = foster_parent.children.index(table_node)
                except ValueError:
                    insert_at = len(foster_parent.children)
                foster_parent.insert_child_at(insert_at, clone)
            else:
                first_table_idx = None
                for idx, child in enumerate(context.current_parent.children):
                    if child.tag_name == "table":
                        first_table_idx = idx
                        break
                if first_table_idx is not None:
                    context.current_parent.children.insert(first_table_idx, clone)
                    clone.parent = context.current_parent
                else:
                    context.current_parent.append_child(clone)
        else:
            context.current_parent.append_child(clone)
        context.open_elements.push(clone)
        entry.element = clone
        context.move_to_element(clone)
        # Track anchor reconstruction index for immediate re-adoption suppression. We only care about <a>.
        if clone.tag_name == 'a':
            context.anchor_last_reconstruct_index = parser.get_token_position()
            context.anchor_suppress_once_done = False
        if parser.env_debug:
            parser.debug(f"Reconstructed formatting element {clone.tag_name}")


def reconstruct_if_needed(parser, context, *, force=False):
    """Central reconstruction guard.

    Conditions (when not forced):
      * There exists an active formatting entry whose element is not on the open stack (ignoring markers & <nobr> per spec nuance).
      * Not inside template content boundary (template content handled separately).
      * If in a table insertion mode, only reconstruct when current insertion point is inside a cell ('td'/'th') or caption.
    force=True bypasses checks (used for post-adoption pending reconstruction to match previous behavior).
    Returns True if reconstruction executed.
    """
    if force:
        reconstruct_active_formatting_elements(parser, context)
        return True
    afe = context.active_formatting_elements
    # Direct access: ActiveFormattingElements always defines _stack
    if not afe or not afe._stack:
        return False
    # Template content skip
    cur = context.current_parent
    while cur:
        if cur.tag_name == 'content' and cur.parent and cur.parent.tag_name == 'template':
            return False
        cur = cur.parent
    # Table mode cell/caption restriction
    if context.document_state in (
        DocumentState.IN_TABLE,
        DocumentState.IN_TABLE_BODY,
        DocumentState.IN_ROW,
    ):
        in_cell_or_caption = bool(context.current_parent.find_ancestor(lambda n: n.tag_name in ('td','th','caption')))
        if not in_cell_or_caption:
            return False
    open_stack = context.open_elements._stack
    for entry in afe._stack:
        el = entry.element
        if el is None:
            continue
        # Spec: 'nobr' participates in reconstruction; only special parse error when another nobr exists in scope.
        # We approximate by allowing reconstruction; duplicate handling (Noah's Ark clause) already limits overgrowth.
        if el not in open_stack:
            reconstruct_active_formatting_elements(parser, context)
            return True
    return False


def get_head(parser):
    """Get the existing <head> element from the HTML node, if present."""
    html_node = parser.html_node
    if not html_node or parser.fragment_context:
        return None
    for ch in html_node.children:
        if ch.tag_name == "head":
            return ch
    return None


def ensure_head(parser):
    """Return existing <head> or create/insert one under <html>.

    Safe in fragment mode (returns None). New head is inserted before the first
    non-comment/text child to preserve ordering.
    """
    html_node = parser.html_node
    if not html_node or parser.fragment_context:
        return None
    existing = get_head(parser)
    if existing:
        return existing
    head = Node("head")
    insert_index = len(html_node.children)
    for i, child in enumerate(html_node.children):
        if child.tag_name not in ("#comment", "#text") and child.tag_name != "head":
            insert_index = i
            break
    if insert_index == len(html_node.children):
        html_node.append_child(head)
    else:
        html_node.insert_child_at(insert_index, head)
    return head


def in_template_content(context):
    """Check if the current insertion point is inside template content."""
    p = context.current_parent
    if not p:
        return False
    if p.tag_name == "content" and p.parent and p.parent.tag_name == "template":
        return True
    cur = p.parent
    while cur:
        if cur.tag_name == "content" and cur.parent and cur.parent.tag_name == "template":
            return True
        cur = cur.parent
    return False
