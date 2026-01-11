"""Constructor-time DOM transforms.

These transforms are intended as a migration path for Bleach/html5lib-style
post-processing, but are implemented as DOM (tree) operations to match
JustHTML's architecture.

Safety model: transforms shape the in-memory tree; safe-by-default output is
still enforced by `to_html()`/`to_text()`/`to_markdown()` via sanitization.

Performance: selectors are compiled (parsed) once before application.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from .constants import VOID_ELEMENTS, WHITESPACE_PRESERVING_ELEMENTS
from .linkify import LinkifyConfig, find_links_with_config
from .node import ElementNode, SimpleDomNode, TemplateNode, TextNode
from .sanitize import SanitizationPolicy, _sanitize
from .selector import SelectorMatcher, parse_selector
from .tokens import ParseError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .selector import ParsedSelector


# -----------------
# Public transforms
# -----------------


_ERROR_SINK: ContextVar[list[ParseError] | None] = ContextVar("justhtml_transform_error_sink", default=None)


def emit_error(
    code: str,
    *,
    node: SimpleDomNode | None = None,
    line: int | None = None,
    column: int | None = None,
    category: str = "transform",
    message: str | None = None,
) -> None:
    """Emit a ParseError from within a transform callback.

    Errors are appended to the active sink when transforms are applied (e.g.
    during JustHTML construction). If no sink is active, this is a no-op.
    """

    sink = _ERROR_SINK.get()
    if sink is None:
        return

    if node is not None:
        line = node.origin_line
        column = node.origin_col

    sink.append(
        ParseError(
            str(code),
            line=line,
            column=column,
            category=str(category),
            message=str(message) if message is not None else str(code),
        )
    )


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


@dataclass(frozen=True, slots=True)
class Stage:
    """Group transforms into an explicit stage.

    Stages are intended to make transform passes explicit and readable.

    - Stages can be nested; nested stages are flattened.
    - If at least one Stage is present at the top level of a transform list,
        any top-level transforms around it are automatically grouped into
        implicit stages.
    """

    transforms: tuple[TransformSpec, ...]

    def __init__(self, transforms: list[TransformSpec] | tuple[TransformSpec, ...]) -> None:
        object.__setattr__(self, "transforms", tuple(transforms))


# -----------------
# Compilation
# -----------------


Transform = SetAttrs | Drop | Unwrap | Empty | Edit | Linkify | CollapseWhitespace | PruneEmpty | Sanitize

TransformSpec = Transform | Stage


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


@dataclass(frozen=True, slots=True)
class _CompiledStageBoundary:
    kind: Literal["stage_boundary"]


CompiledTransform = (
    _CompiledSelectorTransform
    | _CompiledLinkifyTransform
    | _CompiledCollapseWhitespaceTransform
    | _CompiledPruneEmptyTransform
    | _CompiledSanitizeTransform
    | _CompiledStageBoundary
)


def _iter_flattened_transforms(specs: list[TransformSpec] | tuple[TransformSpec, ...]) -> list[Transform]:
    out: list[Transform] = []

    def _walk(items: list[TransformSpec] | tuple[TransformSpec, ...]) -> None:
        for item in items:
            if isinstance(item, Stage):
                _walk(item.transforms)
                continue
            out.append(item)

    _walk(specs)
    return out


def _split_into_top_level_stages(specs: list[TransformSpec] | tuple[TransformSpec, ...]) -> list[Stage]:
    # Only enable auto-staging when a Stage is present at the top level.
    has_top_level_stage = any(isinstance(t, Stage) for t in specs)
    if not has_top_level_stage:
        return []

    stages: list[Stage] = []
    pending: list[TransformSpec] = []

    for item in specs:
        if isinstance(item, Stage):
            if pending:
                stages.append(Stage(pending))
                pending = []
            stages.append(item)
            continue

        pending.append(item)

    if pending:
        stages.append(Stage(pending))

    return stages


def compile_transforms(transforms: list[TransformSpec] | tuple[TransformSpec, ...]) -> list[CompiledTransform]:
    if not transforms:
        return []

    flattened = _iter_flattened_transforms(transforms)
    sanitize_count = sum(1 for t in flattened if isinstance(t, Sanitize))
    if sanitize_count > 1:
        raise ValueError("Only one Sanitize transform is supported")

    top_level_stages = _split_into_top_level_stages(transforms)
    if top_level_stages:
        # Stage is a pass boundary. Compile each stage separately and insert a
        # boundary marker so apply_compiled_transforms can flush batches.
        compiled: list[CompiledTransform] = []
        for stage_i, stage in enumerate(top_level_stages):
            if stage_i:
                compiled.append(_CompiledStageBoundary(kind="stage_boundary"))
            for inner in _iter_flattened_transforms(stage.transforms):
                compiled.extend(compile_transforms((inner,)))
        return compiled

    compiled = []
    for t in flattened:
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


def apply_compiled_transforms(
    root: SimpleDomNode,
    compiled: list[CompiledTransform],
    *,
    errors: list[ParseError] | None = None,
) -> None:
    if not compiled:
        return

    token = _ERROR_SINK.set(errors)
    try:
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

        def apply_walk_transforms(root_node: SimpleDomNode, walk_transforms: list[CompiledTransform]) -> None:
            if not walk_transforms:
                return

            linkify_skip_tags: frozenset[str] = frozenset().union(
                *(t.skip_tags for t in walk_transforms if isinstance(t, _CompiledLinkifyTransform))
            )
            whitespace_skip_tags: frozenset[str] = frozenset().union(
                *(t.skip_tags for t in walk_transforms if isinstance(t, _CompiledCollapseWhitespaceTransform))
            )

            # To preserve strict left-to-right semantics while still batching
            # compatible transforms into a single walk, we track the earliest
            # transform index that may run on a node.
            #
            # Example:
            #   transforms=[Drop("a"), Linkify()]
            # Linkify introduces <a> elements. Those <a> nodes must not be
            # processed by earlier transforms (like Drop("a")), because Drop has
            # already run conceptually.
            created_start_index: dict[int, int] = {}

            def _mark_start(n: object, start_index: int) -> None:
                key = id(n)
                created_start_index[key] = max(created_start_index.get(key, 0), start_index)

            def apply_to_children(parent: SimpleDomNode, *, skip_linkify: bool, skip_whitespace: bool) -> None:
                children = parent.children
                if not children:
                    return

                i = 0
                while i < len(children):
                    node = children[i]
                    name = node.name

                    changed = False
                    start_at = created_start_index.get(id(node), 0)
                    for idx in range(start_at, len(walk_transforms)):
                        t = walk_transforms[idx]
                        # CollapseWhitespace
                        if isinstance(t, _CompiledCollapseWhitespaceTransform):
                            if name == "#text" and not skip_whitespace:
                                data = node.data or ""
                                if data:
                                    collapsed = _collapse_html_space_characters(data)
                                    if collapsed != data:
                                        node.data = collapsed
                            continue

                        # Linkify
                        if isinstance(t, _CompiledLinkifyTransform):
                            if name == "#text" and not skip_linkify:
                                data = node.data or ""
                                if data:
                                    matches = find_links_with_config(data, t.config)
                                    if matches:
                                        cursor = 0
                                        for m in matches:
                                            if m.start > cursor:
                                                txt = TextNode(data[cursor : m.start])
                                                _mark_start(txt, idx + 1)
                                                parent.insert_before(txt, node)

                                            ns = parent.namespace or "html"
                                            a = ElementNode("a", {"href": m.href}, ns)
                                            a.append_child(TextNode(m.text))
                                            _mark_start(a, idx + 1)
                                            parent.insert_before(a, node)
                                            cursor = m.end

                                        if cursor < len(data):
                                            tail = TextNode(data[cursor:])
                                            _mark_start(tail, idx + 1)
                                            parent.insert_before(tail, node)

                                        parent.remove_child(node)
                                        changed = True
                                        break
                            continue

                        # Selector transforms
                        t = cast("_CompiledSelectorTransform", t)
                        if name.startswith("#"):
                            continue

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
                                _mark_start(child, idx + 1)
                                parent.insert_before(child, node)
                        parent.remove_child(node)
                        changed = True
                        break

                    if changed:
                        continue

                    if not name.startswith("#"):
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

        def apply_prune_transforms(
            root_node: SimpleDomNode, prune_transforms: list[_CompiledPruneEmptyTransform]
        ) -> None:
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

        pending_walk: list[CompiledTransform] = []

        i = 0
        while i < len(compiled):
            t = compiled[i]
            if isinstance(
                t,
                (
                    _CompiledSelectorTransform,
                    _CompiledLinkifyTransform,
                    _CompiledCollapseWhitespaceTransform,
                ),
            ):
                pending_walk.append(t)
                i += 1
                continue

            apply_walk_transforms(root, pending_walk)
            pending_walk = []

            if isinstance(t, _CompiledStageBoundary):
                i += 1
                continue

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

        apply_walk_transforms(root, pending_walk)
    finally:
        _ERROR_SINK.reset(token)
