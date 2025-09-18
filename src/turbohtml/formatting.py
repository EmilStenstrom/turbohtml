"""Formatting reconstruction utilities extracted from parser.

This module hosts the active formatting elements reconstruction algorithm so the
core parser can remain a thin orchestrator. Handlers (and the parser itself)
invoke the public function here instead of a parser method.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from .parser import TurboHTML
    from .context import ParseContext, DocumentState

from .node import Node
from .context import DocumentState


def reconstruct_active_formatting_elements(parser: "TurboHTML", context: "ParseContext") -> None:
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
        # Reuse existing current_parent for <nobr> when structurally identical & empty
        if (
            entry.element.tag_name == "nobr"
            and context.current_parent
            and context.current_parent.tag_name == entry.element.tag_name
            and context.current_parent.attributes == entry.element.attributes
            and not any(ch.tag_name == "#text" for ch in context.current_parent.children)
        ):
            entry.element = context.current_parent
            context.open_elements.push(context.current_parent)
            if getattr(parser, "env_debug", False):  # avoid calling parser.debug in hot path unless needed
                parser.debug(
                    f"Reconstructed (reused) formatting element {context.current_parent.tag_name} (no clone)"
                )
            continue
        clone = Node(entry.element.tag_name, entry.element.attributes.copy())
        if context.document_state in (
            DocumentState.IN_TABLE,
            DocumentState.IN_TABLE_BODY,
            DocumentState.IN_ROW,
        ):
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
        if getattr(parser, "env_debug", False):
            parser.debug(f"Reconstructed formatting element {clone.tag_name}")
