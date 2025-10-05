"""Foster parenting (HTML5 tree construction) centralized implementation.

This module provides the core algorithm for determining WHERE to foster parent
elements in table contexts, without performing the actual DOM insertion.

The foster_parent() function returns a (parent, before) tuple that callers
use to position elements correctly according to HTML5 spec requirements.

Spec Reference: When inserting a node and the current node is a table-related
element (table, tbody, tfoot, thead, tr) and the element to insert is not
allowed there, the node should be foster parented: inserted before the table
element in its parent, or appended to the foster parent if no parent exists.
"""
from __future__ import annotations

TABLE_CONTEXT = {"table", "tbody", "tfoot", "thead", "tr"}


def find_table_in_scope(open_elements):
    """Find the most recently opened table element in open elements stack."""
    for el in reversed(open_elements):
        if el.tag_name == "table":
            return el
    return None


def foster_parent(target_parent, open_elements, root):
    """Return (parent, before) for foster-parented insertion.

    Core algorithm for finding the correct foster parent location. Does NOT
    perform any DOM mutations - only returns where to insert.

    Args:
        target_parent: Current insertion parent (context.current_parent)
        open_elements: OpenElementsStack instance
        root: Root document node (fallback)

    Returns:
        (parent_node, before_sibling): Insert child into parent_node before before_sibling
                                       If before_sibling is None, append to parent_node
    """
    table = find_table_in_scope(open_elements)
    if not table:
        # No table => normal append to current parent
        return target_parent, None

    table_parent = table.parent
    if table_parent is None:
        # Table is root-level (fragment maybe) - spec: append after table
        # Return target_parent or root as fallback
        return target_parent if target_parent.tag_name != "table" else root, None

    # Normal path: insert before the table in its parent
    return table_parent, table


def needs_foster_parenting(current_parent):
    """Check if current parent requires foster parenting for child elements."""
    return current_parent.tag_name in TABLE_CONTEXT
