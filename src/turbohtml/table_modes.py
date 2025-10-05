"""Table insertion mode helpers (extraction phase 1).

This module centralizes predicates and tiny helpers for table-related
logic. Initial phase: NO behavior changes. We only re-express existing
compound conditions so future refactors can relocate side-effects here.

Later phases will introduce a process_table_token() dispatcher that
implements the spec transitions. For now we expose:
    - should_foster_parent(tag_name, token_attrs, context, parser)
    - fragment_table_insert(tag_name, token, context, parser)
    - fragment_table_section_insert(tag_name, token, context, parser)
    - restore_insertion_open_cell(context)

Each function mirrors logic currently embedded in parser._handle_start_tag.
"""
from turbohtml.constants import (
    TABLE_CELL_TAGS,
    TABLE_PRELUDE_TAGS,
    TABLE_ROW_TAGS,
    TABLE_SECTION_TAGS,
)
from turbohtml.context import DocumentState
from turbohtml.node import Node

# Elements treated specially in table mode when deciding foster parenting.
# Mirrors exclusions in parser._handle_start_tag condition.
TABLE_ELEMENTS_CANON = {
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "colgroup",
    "col",
}

HEAD_ELEMENTS_CANON = {"head", "base", "basefont", "bgsound", "link", "meta", "title", "style"}


def _in_template_content(context):
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


def _in_integration_point(context):
    cur = context.current_parent
    while cur:
        if cur.tag_name in ("svg foreignObject", "svg desc", "svg title"):
            return True
        if cur.tag_name == "math annotation-xml" and cur.attributes and any(
            attr.name.lower() == "encoding" and attr.value.lower() in ("text/html", "application/xhtml+xml")
            for attr in cur.attributes
        ):
            return True
        cur = cur.parent
    return False

def should_foster_parent(tag_name, attrs, context, parser):
    """Mirror the existing foster parenting compound condition.

    This returns True only when the parser would currently foster parent the element.
    Side-effects (moving insertion point, salvage) stay in parser for phase 1.
    """
    if context.document_state not in (
        DocumentState.IN_TABLE,
        DocumentState.IN_TABLE_BODY,
        DocumentState.IN_ROW,
    ):
        return False
    if tag_name in TABLE_ELEMENTS_CANON:
        return False
    if tag_name in HEAD_ELEMENTS_CANON:
        return False
    # Template or integration points short-circuit
    if _in_template_content(context) or _in_integration_point(context):
        return False
    # Inside an existing cell forbids fostering
    if context.current_parent.tag_name in TABLE_CELL_TAGS:
        return False
    if context.current_parent.find_ancestor(lambda n: n.tag_name in TABLE_CELL_TAGS):
        return False
    # Hidden input exemption (matches inline logic)
    if tag_name == "input":
        t = (attrs.get("type", "") or "").lower()
        if t == "hidden" and attrs.get("type", "") == attrs.get("type", "").strip():
            return False
    return True


def restore_insertion_open_cell(context):
    """If a cell element (<td>/<th>) is still open on the stack but insertion point drifted
    outside it (e.g., foreign content breakout), reposition to that cell. Returns the cell or None.
    """
    for el in reversed(context.open_elements):
        if el.tag_name in ("td", "th"):
            context.move_to_element(el)
            return el
    return None


__all__ = [
    "TABLE_CELL_TAGS",
    "TABLE_PRELUDE_TAGS",
    "TABLE_ROW_TAGS",
    "TABLE_SECTION_TAGS",
    "fragment_table_insert",
    "fragment_table_section_insert",
    "should_foster_parent",
]


def fragment_table_insert(tag_name, token, context, parser):
    """Handle start tag insertion when fragment_context == 'table'.

    Returns True if handled (caller should return early).
    """
    if parser.fragment_context != "table":
        return False
    if tag_name not in (
        "caption",
        "colgroup",
        "col",
        "tbody",
        "tfoot",
        "thead",
        "tr",
        "td",
        "th",
    ):
        return False

    # Relocate insertion point to fragment root (top ancestor)
    top = context.current_parent
    while top.parent:
        top = top.parent
    context.move_to_element(top)
    root = top

    def _find_last(name):
        for ch in reversed(root.children):
            if ch.tag_name == name:
                return ch
        return None

    if tag_name == "caption":
        caption = Node("caption", token.attributes)
        root.append_child(caption)
        context.open_elements.push(caption)
        context.move_to_element(caption)
        context.transition_to_state(DocumentState.IN_CAPTION, caption)
        return True
    if tag_name == "colgroup":
        cg = Node("colgroup", token.attributes)
        root.append_child(cg)
        context.open_elements.push(cg)
        return True
    if tag_name == "col":
        cg = _find_last("colgroup")
        if not cg:
            cg = Node("colgroup")
            root.append_child(cg)
        col = Node("col", token.attributes)
        cg.append_child(col)
        return True
    if tag_name in ("tbody", "thead", "tfoot"):
        section = Node(tag_name, token.attributes)
        root.append_child(section)
        context.open_elements.push(section)
        context.transition_to_state(DocumentState.IN_TABLE_BODY, section)
        return True
    if tag_name == "tr":
        container = None
        for ch in reversed(root.children):
            if ch.tag_name in ("tbody", "thead", "tfoot"):
                container = ch
                break
        if not container:
            container = Node("tbody")
            root.append_child(container)
        tr = Node("tr", token.attributes)
        container.append_child(tr)
        context.open_elements.push(tr)
        context.move_to_element(tr)
        context.transition_to_state(DocumentState.IN_ROW, tr)
        return True
    if tag_name in ("td", "th"):
        container = None
        for ch in reversed(root.children):
            if ch.tag_name in ("tbody", "thead", "tfoot"):
                container = ch
                break
        if not container:
            container = Node("tbody")
            root.append_child(container)
        last_tr = None
        for ch in reversed(container.children):
            if ch.tag_name == "tr":
                last_tr = ch
                break
        if not last_tr:
            last_tr = Node("tr")
            container.append_child(last_tr)
        cell = Node(tag_name, token.attributes)
        last_tr.append_child(cell)
        context.open_elements.push(cell)
        context.move_to_element(cell)
        context.transition_to_state(DocumentState.IN_CELL, cell)
        return True
    return False


def fragment_table_section_insert(tag_name, token, context, parser):
    """Handle start tags when fragment_context in (tbody, thead, tfoot).

    Replicates the inline logic from parser._handle_start_tag. Returns True if handled.
    """
    if parser.fragment_context not in ("tbody", "thead", "tfoot"):
        return False
    if tag_name not in ("tr", "td", "th"):
        return False
    # Reposition to fragment root
    top = context.current_parent
    while top.parent:
        top = top.parent
    root = top
    if tag_name == "tr":
        # Nested table row handling (spec parity for fragment tbody/thead/tfoot contexts):
        # If current insertion point is inside a table section (tbody/thead/tfoot) whose parent is a
        # <table> that itself is descendant of a cell (<td>/<th>) already inserted as a child of the
        # fragment root row, then this <tr> belongs to the nested table, not as a new root-level row.
        # We detect this BEFORE forcing reposition to fragment root so that nested table rows are
        # properly nested (WHATWG innerHTML test case: <td><table><tbody><a><tr>...). This is structural
        # and does not rely on test names: it simply prefers the nearest table section ancestor when
        # present instead of synthesizing/siblinging at the fragment root.
        nested_section = None
        cur = context.current_parent
        while cur and cur.tag_name != "document-fragment":
            if cur.tag_name in ("tbody", "thead", "tfoot") and cur.parent and cur.parent.tag_name == "table":
                nested_section = cur
                break
            cur = cur.parent
        if nested_section is not None:
            tr = Node("tr", token.attributes)
            nested_section.append_child(tr)
            context.open_elements.push(tr)
            context.move_to_element(tr)
            context.transition_to_state(DocumentState.IN_ROW, tr)
            return True
        # Fallback: root-level row insertion (previous behavior)
        tr = Node("tr", token.attributes)
        root.append_child(tr)
        context.open_elements.push(tr)
        context.move_to_element(tr)
        context.transition_to_state(DocumentState.IN_ROW, tr)
        return True
    # td/th path
    last_tr = None
    for ch in reversed(root.children):
        if ch.tag_name == "tr":
            last_tr = ch
            break
    if not last_tr:
        last_tr = Node("tr")
        root.append_child(last_tr)
    cell = Node(tag_name, token.attributes)
    last_tr.append_child(cell)
    context.open_elements.push(cell)
    context.move_to_element(cell)
    context.transition_to_state(DocumentState.IN_CELL, cell)
    return True
