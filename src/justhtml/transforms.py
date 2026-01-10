"""Constructor-time DOM transforms.

These transforms are intended as a migration path for Bleach/html5lib-style
post-processing, but are implemented as DOM (tree) operations to match
JustHTML's architecture.

Safety model: transforms shape the in-memory tree; safe-by-default output is
still enforced by `to_html()`/`to_text()`/`to_markdown()` via sanitization.

Performance: selectors are compiled (parsed) once before application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from .node import SimpleDomNode, TemplateNode
from .selector import SelectorMatcher, parse_selector

if TYPE_CHECKING:
    from collections.abc import Callable

    from .selector import ParsedSelector


# -----------------
# Public transforms
# -----------------


@dataclass(frozen=True, slots=True)
class SetAttrs:
    selector: str
    attrs: dict[str, str | None]

    def __init__(self, selector: str, **attrs: str | None) -> None:
        object.__setattr__(self, "selector", str(selector))
        object.__setattr__(self, "attrs", dict(attrs))


@dataclass(frozen=True, slots=True)
class Drop:
    selector: str

    def __init__(self, selector: str) -> None:
        object.__setattr__(self, "selector", str(selector))


@dataclass(frozen=True, slots=True)
class Unwrap:
    selector: str

    def __init__(self, selector: str) -> None:
        object.__setattr__(self, "selector", str(selector))


@dataclass(frozen=True, slots=True)
class Empty:
    selector: str

    def __init__(self, selector: str) -> None:
        object.__setattr__(self, "selector", str(selector))


@dataclass(frozen=True, slots=True)
class Edit:
    selector: str
    callback: Callable[[SimpleDomNode], None]

    def __init__(self, selector: str, callback: Callable[[SimpleDomNode], None]) -> None:
        object.__setattr__(self, "selector", str(selector))
        object.__setattr__(self, "callback", callback)


# -----------------
# Compilation
# -----------------


Transform = SetAttrs | Drop | Unwrap | Empty | Edit


@dataclass(frozen=True, slots=True)
class _CompiledSelectorTransform:
    kind: Literal["setattrs", "drop", "unwrap", "empty", "edit"]
    selector_str: str
    selector: ParsedSelector
    payload: dict[str, str | None] | Callable[[SimpleDomNode], None] | None


CompiledTransform = _CompiledSelectorTransform


def compile_transforms(transforms: list[Transform] | tuple[Transform, ...]) -> list[CompiledTransform]:
    compiled: list[CompiledTransform] = []
    for t in transforms:
        if isinstance(t, SetAttrs):
            compiled.append(
                _CompiledSelectorTransform(
                    kind="setattrs",
                    selector_str=t.selector,
                    selector=parse_selector(t.selector),
                    payload=t.attrs,
                )
            )
            continue
        if isinstance(t, Drop):
            compiled.append(
                _CompiledSelectorTransform(
                    kind="drop",
                    selector_str=t.selector,
                    selector=parse_selector(t.selector),
                    payload=None,
                )
            )
            continue
        if isinstance(t, Unwrap):
            compiled.append(
                _CompiledSelectorTransform(
                    kind="unwrap",
                    selector_str=t.selector,
                    selector=parse_selector(t.selector),
                    payload=None,
                )
            )
            continue
        if isinstance(t, Empty):
            compiled.append(
                _CompiledSelectorTransform(
                    kind="empty",
                    selector_str=t.selector,
                    selector=parse_selector(t.selector),
                    payload=None,
                )
            )
            continue
        if isinstance(t, Edit):
            compiled.append(
                _CompiledSelectorTransform(
                    kind="edit",
                    selector_str=t.selector,
                    selector=parse_selector(t.selector),
                    payload=t.callback,
                )
            )
            continue

        raise TypeError(f"Unsupported transform: {type(t).__name__}")

    return compiled


# -----------------
# Application
# -----------------


def apply_compiled_transforms(root: SimpleDomNode, compiled: list[CompiledTransform]) -> None:
    if not compiled:
        return

    matcher = SelectorMatcher()

    def apply_to_children(parent: SimpleDomNode) -> None:
        children = parent.children
        if not children:
            return

        i = 0
        while i < len(children):
            node = children[i]
            name = node.name
            is_element = not name.startswith("#")

            # Apply transforms to this node in order. Some transforms may remove/replace.
            changed = False
            for t in compiled:
                if not is_element:
                    break

                if not matcher.matches(node, t.selector):
                    continue

                if t.kind == "setattrs":
                    patch = cast("dict[str, str | None]", t.payload)
                    attrs = node.attrs
                    for k, v in patch.items():
                        attrs[str(k)] = None if v is None else str(v)
                    continue

                if t.kind == "edit":
                    cb = cast("Callable[[SimpleDomNode], None]", t.payload)
                    cb(node)
                    continue

                if t.kind == "empty":
                    if node.children:
                        for child in node.children:
                            child.parent = None
                        node.children = []
                    # Also empty template content if present.
                    if type(node) is TemplateNode and node.template_content is not None:
                        tc = node.template_content
                        for child in tc.children or []:
                            child.parent = None
                        tc.children = []
                    continue

                if t.kind == "drop":
                    parent.remove_child(node)
                    changed = True
                    break

                # t.kind == "unwrap".
                if node.children:
                    moved = list(node.children)
                    node.children = []
                    for child in moved:
                        parent.insert_before(child, node)
                parent.remove_child(node)
                changed = True
                break

            if changed:
                # Don't advance; re-process at same index.
                continue

            # Descend into element children.
            if is_element and node.children:
                apply_to_children(node)

            i += 1

    apply_to_children(root)
