"""Foster parenting (HTML5 tree construction) centralized implementation.

This module encapsulates logic for choosing the appropriate parent and
insertion position when character data or mis-positioned elements appear
in a table-related context where direct insertion would violate the spec.

The algorithm intentionally avoids performing the actual DOM mutation;
it returns a (parent, before_sibling) tuple for callers to act upon.

Spec Reference (abbrev): When inserting a node and the current node is a
table-related element (table, tbody, tfoot, thead, tr) and the element to
insert is not allowed there, the node should be foster parented: inserted
before the table element in its parent, or if the table has no parent,
after the table in the open elements stack context.

We implement character and element cases with a shared path.
"""
from __future__ import annotations

TABLE_CONTEXT = {"table", "tbody", "tfoot", "thead", "tr"}


def find_table_in_scope(open_elements):  # small helper, not hot path
    # Reverse iterate so we get the most recently opened table consistent with spec phrasing
    for el in reversed(open_elements):
        if el.tag_name == "table":
            return el
    return None


def foster_parent(target_parent, open_elements, root):
    """Return (parent, before) for foster-parented insertion.

    Args:
        target_parent: Current insertion parent (context.current_parent)
        open_elements: OpenElementsStack instance
        root: Root document node (fallback)

    """
    table = find_table_in_scope(open_elements)
    if not table:
        # No table => normal append to current parent
        return target_parent, None

    table_parent = table.parent
    if table_parent is None:
        # Table is root-level (fragment maybe) – spec: append after table; emulate by
        # selecting root (or target_parent if root mismatch) and inserting after table.
        # We surface this as parent=root, before=None and let caller append; semantic diff
        # is acceptable for now (rare path). A refinement could expose explicit 'after' slot.
        return target_parent if target_parent.tag_name != "table" else root, None

    # Normal path: insert before the table in its parent
    return table_parent, table


def needs_foster_parenting(current_parent):
    return current_parent.tag_name in TABLE_CONTEXT
