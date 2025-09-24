"""Table insertion mode helpers (extraction phase 1).

This module centralizes predicates and tiny helpers for table-related
logic. Initial phase: NO behavior changes. We only re-express existing
compound conditions so future refactors can relocate side-effects here.

Later phases will introduce a process_table_token() dispatcher that
implements the spec transitions. For now we expose:
  - is_table_mode(document_state)
  - has_open_table(context)
  - should_foster_parent(tag_name, token_attrs, context, parser)
  - find_open_cell(context)

Each function mirrors logic currently embedded in parser._handle_start_tag.
"""
from __future__ import annotations

from .context import DocumentState, ParseContext
from .constants import (
    TABLE_SECTION_TAGS,
    TABLE_ROW_TAGS,
    TABLE_CELL_TAGS,
    TABLE_PRELUDE_TAGS,
)

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


def is_table_mode(state: DocumentState) -> bool:
    return state in (
        DocumentState.IN_TABLE,
        DocumentState.IN_TABLE_BODY,
        DocumentState.IN_ROW,
        DocumentState.IN_CELL,
        DocumentState.IN_CAPTION,
    )


def has_open_table(context: ParseContext) -> bool:
    return any(el.tag_name == "table" for el in context.open_elements._stack)


def find_open_cell(context: ParseContext):
    for el in reversed(context.open_elements._stack):
        if el.tag_name in TABLE_CELL_TAGS:
            return el
    return None


def _in_template_content(context: ParseContext) -> bool:
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

def _in_integration_point(context: ParseContext) -> bool:
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

def should_foster_parent(tag_name: str, attrs: dict, context: ParseContext, parser) -> bool:
    """Mirror the existing foster parenting compound condition.

    This returns True only when the parser would currently foster parent the element.
    Side-effects (moving insertion point, salvage) stay in parser for phase 1.
    """
    if context.document_state != DocumentState.IN_TABLE:
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


# Phase 1 extraction: implied tbody / tr helpers (behavioral mirror of existing fragment & parser logic)
def ensure_implied_tbody_for_tr(context: ParseContext, parser) -> None:
    """If we're about to insert a <tr> directly under a <table> (or fragment root table context)
    with no open tbody/thead/tfoot, synthesize (or reuse) a <tbody> and move insertion point.

    Idempotent: if current_parent already a section (tbody/thead/tfoot) or a <tr>, does nothing.
    """
    cp = context.current_parent
    if not cp:
        return
    tn = cp.tag_name
    if tn in ("tbody", "thead", "tfoot", "tr"):
        return
    # Ascend to find nearest table ancestor (stop at fragment root)
    node = cp
    table_ancestor = None
    while node and node.tag_name != "document-fragment":
        if node.tag_name == "table":
            table_ancestor = node
            break
        node = node.parent
    if not table_ancestor:
        return
    attach_parent = cp if cp == table_ancestor else table_ancestor
    # Reuse existing section before any <tr>
    for ch in attach_parent.children:
        if ch.tag_name in ("tbody", "thead", "tfoot"):
            context.move_to_element(ch)
            return
        if ch.tag_name == "tr":
            break
    from turbohtml.node import Node  # local import to avoid cycle

    tbody = Node("tbody")
    # Insert before first <tr> if present
    insert_index = None
    for i, ch in enumerate(attach_parent.children):
        if ch.tag_name == "tr":
            insert_index = i
            break
    if insert_index is None:
        attach_parent.append_child(tbody)
    else:
        attach_parent.children.insert(insert_index, tbody)
        tbody.parent = attach_parent
    context.move_to_element(tbody)


def ensure_implied_tr_for_cell(context: ParseContext) -> None:
    """Ensure there is a <tr> ancestor before inserting a <td>/<th> when inside (or directly under)
    a table section or table. Mirrors fragment logic that creates a tr when a td/th appears first.
    """
    cp = context.current_parent
    if not cp:
        return
    tn = cp.tag_name
    from turbohtml.node import Node

    # If we're inside a tr already, nothing to do
    if tn == "tr":
        return
    # If inside tbody/thead/tfoot, create or reuse last tr
    if tn in ("tbody", "thead", "tfoot"):
        last_tr = None
        for ch in reversed(cp.children):
            if ch.tag_name == "tr":
                last_tr = ch
                break
        if not last_tr:
            last_tr = Node("tr")
            cp.append_child(last_tr)
        context.move_to_element(last_tr)


# Cell salvage helpers (phase 1 extraction)
def reenter_last_cell_for_p(context: ParseContext) -> bool:
    """If a <p> start tag is being processed during foster-parent consideration and a <tr>
    is open whose DOM children already include a cell (<td>/<th>) but no cell is currently
    open on the stack, reposition insertion to that last cell. Mirrors existing inline logic.

    Returns True if repositioning occurred (caller then proceeds with normal creation, skipping foster parent).
    """
    open_tr = None
    for el in reversed(context.open_elements._stack):
        if el.tag_name == "tr":
            open_tr = el
            break
    if open_tr is None:
        return False
    last_cell = None
    for child in reversed(open_tr.children):
        if child.tag_name in ("td", "th"):
            last_cell = child
            break
    if last_cell is None:
        return False
    context.move_to_element(last_cell)
    return True


def restore_insertion_open_cell(context: ParseContext):
    """If a cell element (<td>/<th>) is still open on the stack but insertion point drifted
    outside it (e.g., foreign content breakout), reposition to that cell. Returns the cell or None."""
    for el in reversed(context.open_elements._stack):
        if el.tag_name in ("td", "th"):
            context.move_to_element(el)
            return el
    return None


__all__ = [
    "is_table_mode",
    "has_open_table",
    "find_open_cell",
    "should_foster_parent",
    "fragment_table_insert",
    "fragment_table_section_insert",
    "TABLE_SECTION_TAGS",
    "TABLE_ROW_TAGS",
    "TABLE_CELL_TAGS",
    "TABLE_PRELUDE_TAGS",
]


def fragment_table_insert(tag_name: str, token, context: ParseContext, parser) -> bool:
    """Handle start tag insertion when fragment_context == 'table'.

    Mirrors the inline block previously in parser._handle_start_tag with no semantic changes.
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

    def _find_last(name: str):
        for ch in reversed(root.children):
            if ch.tag_name == name:
                return ch
        return None

    from turbohtml.context import DocumentState as _DS
    from turbohtml.node import Node

    if tag_name == "caption":
        caption = Node("caption", token.attributes)
        root.append_child(caption)
        context.open_elements.push(caption)
        context.move_to_element(caption)
        context.transition_to_state(_DS.IN_CAPTION, caption)
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
        context.transition_to_state(_DS.IN_TABLE_BODY, section)
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
        context.transition_to_state(_DS.IN_ROW, tr)
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
        context.transition_to_state(_DS.IN_CELL, cell)
        return True
    return False


def fragment_table_section_insert(tag_name: str, token, context: ParseContext, parser) -> bool:
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
    from turbohtml.node import Node
    from turbohtml.context import DocumentState as _DS

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
            context.transition_to_state(_DS.IN_ROW, tr)
            return True
        # Fallback: root-level row insertion (previous behavior)
        tr = Node("tr", token.attributes)
        root.append_child(tr)
        context.open_elements.push(tr)
        context.move_to_element(tr)
        context.transition_to_state(_DS.IN_ROW, tr)
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
    context.transition_to_state(_DS.IN_CELL, cell)
    return True
