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

from .constants import VOID_ELEMENTS, WHITESPACE_PRESERVING_ELEMENTS
from .linkify import LinkifyConfig, find_links_with_config
from .node import ElementNode, SimpleDomNode, TemplateNode, TextNode
from .sanitize import SanitizationPolicy, _sanitize
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


@dataclass(frozen=True, slots=True)
class Linkify:
    """Linkify URLs/emails in text nodes.

    This transform scans DOM text nodes (not raw HTML strings) and wraps detected
    links in `<a href="...">...</a>`.
    """

    skip_tags: frozenset[str]
    fuzzy_ip: bool
    extra_tlds: frozenset[str]

    def __init__(
        self,
        *,
        skip_tags: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (
            "a",
            *WHITESPACE_PRESERVING_ELEMENTS,
        ),
        fuzzy_ip: bool = False,
        extra_tlds: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
    ) -> None:
        object.__setattr__(self, "skip_tags", frozenset(str(t).lower() for t in skip_tags))
        object.__setattr__(self, "fuzzy_ip", bool(fuzzy_ip))
        object.__setattr__(self, "extra_tlds", frozenset(str(t).lower() for t in extra_tlds))


def _collapse_html_space_characters(text: str) -> str:
    """Collapse runs of HTML whitespace characters to a single space.

    This mirrors html5lib's whitespace filter behavior: it does not trim.
    """

    # Fast path: no formatting whitespace and no double spaces.
    if "\t" not in text and "\n" not in text and "\r" not in text and "\f" not in text and "  " not in text:
        return text

    out: list[str] = []
    in_ws = False

    for ch in text:
        if ch == " " or ch == "\t" or ch == "\n" or ch == "\r" or ch == "\f":
            if in_ws:
                continue
            out.append(" ")
            in_ws = True
            continue

        out.append(ch)
        in_ws = False
    return "".join(out)


@dataclass(frozen=True, slots=True)
class CollapseWhitespace:
    """Collapse whitespace in text nodes.

    Collapses runs of HTML whitespace characters (space, tab, LF, CR, FF) into a
    single space.

    This is similar to `html5lib.filters.whitespace.Filter`.
    """

    skip_tags: frozenset[str]

    def __init__(
        self,
        *,
        skip_tags: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (
            *WHITESPACE_PRESERVING_ELEMENTS,
            "title",
        ),
    ) -> None:
        object.__setattr__(self, "skip_tags", frozenset(str(t).lower() for t in skip_tags))


@dataclass(frozen=True, slots=True)
class Sanitize:
    """Sanitize the in-memory tree.

    This transform replaces the current tree with a sanitized clone using the
    same sanitizer that powers `safe=True` serialization.

    Notes:
    - This runs once at parse/transform time.
        - If you apply transforms after `Sanitize`, they may reintroduce unsafe
            content. Use safe serialization (`safe=True`) if you need output safety.
    """

    policy: SanitizationPolicy | None

    def __init__(self, policy: SanitizationPolicy | None = None) -> None:
        object.__setattr__(self, "policy", policy)


@dataclass(frozen=True, slots=True)
class PruneEmpty:
    """Recursively drop empty elements.

    This transform removes elements that are empty at that point in the
    transform pipeline.

    "Empty" means:
    - no element children, and
    - no non-whitespace text nodes (unless `strip_whitespace=False`).

    Comments/doctypes are ignored when determining emptiness.

    Notes:
    - Pruning uses a post-order traversal to be correct.
    """

    selector: str
    strip_whitespace: bool

    def __init__(self, selector: str, *, strip_whitespace: bool = True) -> None:
        object.__setattr__(self, "selector", str(selector))
        object.__setattr__(self, "strip_whitespace", bool(strip_whitespace))


# -----------------
# Compilation
# -----------------


Transform = SetAttrs | Drop | Unwrap | Empty | Edit | Linkify | CollapseWhitespace | PruneEmpty | Sanitize


@dataclass(frozen=True, slots=True)
class _CompiledCollapseWhitespaceTransform:
    kind: Literal["collapse_whitespace"]
    skip_tags: frozenset[str]


@dataclass(frozen=True, slots=True)
class _CompiledSelectorTransform:
    kind: Literal["setattrs", "drop", "unwrap", "empty", "edit"]
    selector_str: str
    selector: ParsedSelector
    payload: dict[str, str | None] | Callable[[SimpleDomNode], None] | None


@dataclass(frozen=True, slots=True)
class _CompiledLinkifyTransform:
    kind: Literal["linkify"]
    skip_tags: frozenset[str]
    config: LinkifyConfig


@dataclass(frozen=True, slots=True)
class _CompiledSanitizeTransform:
    kind: Literal["sanitize"]
    policy: SanitizationPolicy | None


@dataclass(frozen=True, slots=True)
class _CompiledPruneEmptyTransform:
    kind: Literal["prune_empty"]
    selector_str: str
    selector: ParsedSelector
    strip_whitespace: bool


CompiledTransform = (
    _CompiledSelectorTransform
    | _CompiledLinkifyTransform
    | _CompiledCollapseWhitespaceTransform
    | _CompiledPruneEmptyTransform
    | _CompiledSanitizeTransform
)


def compile_transforms(transforms: list[Transform] | tuple[Transform, ...]) -> list[CompiledTransform]:
    if transforms:
        sanitize_count = sum(1 for t in transforms if isinstance(t, Sanitize))
        if sanitize_count:
            if sanitize_count > 1:
                raise ValueError("Only one Sanitize transform is supported")

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

        if isinstance(t, Linkify):
            compiled.append(
                _CompiledLinkifyTransform(
                    kind="linkify",
                    skip_tags=t.skip_tags,
                    config=LinkifyConfig(fuzzy_ip=t.fuzzy_ip, extra_tlds=t.extra_tlds),
                )
            )
            continue

        if isinstance(t, CollapseWhitespace):
            compiled.append(
                _CompiledCollapseWhitespaceTransform(
                    kind="collapse_whitespace",
                    skip_tags=t.skip_tags,
                )
            )
            continue

        if isinstance(t, PruneEmpty):
            compiled.append(
                _CompiledPruneEmptyTransform(
                    kind="prune_empty",
                    selector_str=t.selector,
                    selector=parse_selector(t.selector),
                    strip_whitespace=t.strip_whitespace,
                )
            )
            continue

        if isinstance(t, Sanitize):
            compiled.append(_CompiledSanitizeTransform(kind="sanitize", policy=t.policy))
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

    def apply_sanitize_transform(root_node: SimpleDomNode, t: _CompiledSanitizeTransform) -> None:
        sanitized = _sanitize(root_node, policy=t.policy)

        def _detach_children(n: SimpleDomNode) -> None:
            if n.children:
                for child in n.children:
                    child.parent = None

        def _reparent_children(n: SimpleDomNode) -> None:
            if n.children:
                for child in n.children:
                    child.parent = n

        # Overwrite the root node in-place so callers keep their reference.
        # This supports the common case (document/document-fragment root) as well
        # as advanced usage where callers pass an element root.
        if type(root_node) is TextNode:
            root_node.data = sanitized.data
            return

        _detach_children(root_node)

        if type(root_node) is TemplateNode:
            root_node.name = sanitized.name
            root_node.namespace = sanitized.namespace
            root_node.attrs = sanitized.attrs
            root_node.children = sanitized.children
            root_node.template_content = sanitized.template_content
            _reparent_children(root_node)
            return

        if type(root_node) is ElementNode:
            root_node.name = sanitized.name
            root_node.namespace = sanitized.namespace
            root_node.attrs = sanitized.attrs
            root_node.children = sanitized.children
            root_node.template_content = sanitized.template_content
            _reparent_children(root_node)
            return

        root_node.name = sanitized.name
        root_node.namespace = sanitized.namespace
        root_node.data = sanitized.data
        root_node.attrs = sanitized.attrs
        root_node.children = sanitized.children
        _reparent_children(root_node)

    def apply_selector_and_linkify_transforms(
        root_node: SimpleDomNode,
        selector_transforms: list[_CompiledSelectorTransform],
        linkify_transforms: list[_CompiledLinkifyTransform],
        whitespace_transforms: list[_CompiledCollapseWhitespaceTransform],
    ) -> None:
        if not selector_transforms and not linkify_transforms and not whitespace_transforms:
            return

        linkify_skip_tags: frozenset[str] = (
            frozenset().union(*(t.skip_tags for t in linkify_transforms)) if linkify_transforms else frozenset()
        )

        whitespace_skip_tags: frozenset[str] = (
            frozenset().union(*(t.skip_tags for t in whitespace_transforms)) if whitespace_transforms else frozenset()
        )

        def apply_to_children(parent: SimpleDomNode, *, skip_linkify: bool, skip_whitespace: bool) -> None:
            children = parent.children
            if not children:
                return

            i = 0
            while i < len(children):
                node = children[i]
                name = node.name
                is_element = not name.startswith("#")

                if name == "#text" and not skip_whitespace and whitespace_transforms:
                    data = node.data or ""
                    if data:
                        collapsed = data
                        for _wt in whitespace_transforms:
                            collapsed = _collapse_html_space_characters(collapsed)
                        if collapsed != data:
                            node.data = collapsed

                # Linkify applies to text nodes, context-aware.
                if name == "#text" and not skip_linkify and linkify_transforms:
                    data = node.data or ""
                    if data:
                        rewritten = False
                        for lt in linkify_transforms:
                            matches = find_links_with_config(data, lt.config)
                            if not matches:
                                continue

                            cursor = 0
                            for m in matches:
                                if m.start > cursor:
                                    parent.insert_before(TextNode(data[cursor : m.start]), node)

                                ns = parent.namespace or "html"
                                a = ElementNode("a", {"href": m.href}, ns)
                                a.append_child(TextNode(m.text))
                                parent.insert_before(a, node)
                                cursor = m.end

                            if cursor < len(data):
                                parent.insert_before(TextNode(data[cursor:]), node)

                            parent.remove_child(node)
                            rewritten = True
                            break

                        if rewritten:
                            continue

                changed = False
                for t in selector_transforms:
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
                    continue

                if is_element:
                    tag = node.name.lower()
                    child_skip = skip_linkify or (tag in linkify_skip_tags)
                    child_skip_ws = skip_whitespace or (tag in whitespace_skip_tags)

                    if node.children:
                        apply_to_children(node, skip_linkify=child_skip, skip_whitespace=child_skip_ws)

                    if type(node) is TemplateNode and node.template_content is not None:
                        apply_to_children(
                            node.template_content, skip_linkify=child_skip, skip_whitespace=child_skip_ws
                        )

                i += 1

        if type(root_node) is not TextNode:
            apply_to_children(root_node, skip_linkify=False, skip_whitespace=False)

    def apply_prune_transforms(root_node: SimpleDomNode, prune_transforms: list[_CompiledPruneEmptyTransform]) -> None:
        def _is_effectively_empty_element(n: SimpleDomNode, *, strip_whitespace: bool) -> bool:
            if n.namespace == "html" and n.name.lower() in VOID_ELEMENTS:
                return False

            def _has_content(children: list[SimpleDomNode] | None) -> bool:
                if not children:
                    return False
                for ch in children:
                    nm = ch.name
                    if nm == "#text":
                        data = getattr(ch, "data", "") or ""
                        if strip_whitespace:
                            if str(data).strip():
                                return True
                        else:
                            if str(data) != "":
                                return True
                        continue
                    if nm.startswith("#"):
                        continue
                    return True
                return False

            if _has_content(n.children):
                return False

            if type(n) is TemplateNode and n.template_content is not None:
                if _has_content(n.template_content.children):
                    return False

            return True

        stack: list[tuple[SimpleDomNode, bool]] = [(root_node, False)]
        while stack:
            node, visited = stack.pop()
            if not visited:
                stack.append((node, True))

                children = node.children or []
                stack.extend((child, False) for child in reversed(children) if isinstance(child, SimpleDomNode))

                if type(node) is TemplateNode and node.template_content is not None:
                    stack.append((node.template_content, False))
                continue

            if node.parent is None:
                continue
            if node.name.startswith("#"):
                continue

            for pt in prune_transforms:
                if matcher.matches(node, pt.selector):
                    if _is_effectively_empty_element(node, strip_whitespace=pt.strip_whitespace):
                        node.parent.remove_child(node)
                        break

    pending_selector: list[_CompiledSelectorTransform] = []
    pending_linkify: list[_CompiledLinkifyTransform] = []
    pending_whitespace: list[_CompiledCollapseWhitespaceTransform] = []

    i = 0
    while i < len(compiled):
        t = compiled[i]
        if isinstance(t, _CompiledSelectorTransform):
            pending_selector.append(t)
            i += 1
            continue
        if isinstance(t, _CompiledLinkifyTransform):
            pending_linkify.append(t)
            i += 1
            continue
        if isinstance(t, _CompiledCollapseWhitespaceTransform):
            pending_whitespace.append(t)
            i += 1
            continue

        apply_selector_and_linkify_transforms(root, pending_selector, pending_linkify, pending_whitespace)
        pending_selector = []
        pending_linkify = []
        pending_whitespace = []

        if isinstance(t, _CompiledSanitizeTransform):
            apply_sanitize_transform(root, t)
            i += 1
            continue

        if isinstance(t, _CompiledPruneEmptyTransform):
            prune_batch: list[_CompiledPruneEmptyTransform] = [t]
            i += 1
            while i < len(compiled) and isinstance(compiled[i], _CompiledPruneEmptyTransform):
                prune_batch.append(cast("_CompiledPruneEmptyTransform", compiled[i]))
                i += 1
            apply_prune_transforms(root, prune_batch)
            continue

        raise TypeError(f"Unsupported compiled transform: {type(t).__name__}")

    apply_selector_and_linkify_transforms(root, pending_selector, pending_linkify, pending_whitespace)
