"""Formatting reconstruction utilities extracted from parser.

This module hosts the active formatting elements reconstruction algorithm so the
core parser can remain a thin orchestrator. Handlers (and the parser itself)
invoke the public function here instead of a parser method.
"""
from __future__ import annotations

from .node import Node
from .context import DocumentState
from .constants import FORMATTING_ELEMENTS


def reconstruct_active_formatting_elements(parser, context):
    """Reconstruct active formatting elements inside the current parent.

    Mirrors the former TurboHTML.reconstruct_active_formatting_elements method. Kept
    as a pure function (parser passed explicitly) to avoid growing the parser surface.
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
            table_node = parser.find_current_table(context)
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
            context.anchor_last_reconstruct_index = context.index
            context.anchor_suppress_once_done = False
        if parser.env_debug:
            parser.debug(f"Reconstructed formatting element {clone.tag_name}")
