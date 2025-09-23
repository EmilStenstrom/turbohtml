"""Unified insertion API (phase 1 skeleton).

Provides a single function `insert_node` used by handlers instead of the
heterogeneous direct append/push logic. Initially opt-in via feature flag
to avoid destabilizing all handlers at once.
"""
from __future__ import annotations

from typing import Optional

from .flags import NEW_INSERTION_API
from .foster import foster_parent, needs_foster_parenting
from .formatting import reconstruct_active_formatting_elements
from .constants import VOID_ELEMENTS
from .node import Node


def insert_node(
    parser,  # TurboHTML instance
    context,  # ParseContext
    node: Node,
    *,
    push: bool = False,
    override_parent: Optional[Node] = None,
    consider_reconstruct: bool = False,
) -> Node:
    """Insert `node` at the appropriate place.

    This is intentionally minimal for phase 1; it will expand to cover
    all start-tag insertion semantics later.
    """
    if not NEW_INSERTION_API:
        # Fallback: legacy path (direct append)
        parent = override_parent or context.current_parent
        parent.append_child(node)
        if push:
            context.open_elements.push(node)
        return node

    # Reconstruction (character or phrasing entry point) if requested
    if consider_reconstruct:
        reconstruct_active_formatting_elements(parser, context)

    target_parent = override_parent or context.current_parent
    before = None
    if needs_foster_parenting(target_parent):
        target_parent, before = foster_parent(target_parent, context.open_elements, parser.root)

    if before is not None and before.parent is target_parent:
        target_parent.insert_before(node, before)
    else:
        target_parent.append_child(node)

    if push and node.tag_name not in VOID_ELEMENTS:
        context.open_elements.push(node)
        context.enter_element(node)
    return node
