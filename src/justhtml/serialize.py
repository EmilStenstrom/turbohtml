"""HTML serialization utilities for JustHTML DOM nodes."""

# ruff: noqa: PERF401

from __future__ import annotations

from typing import Any

from .constants import FOREIGN_ATTRIBUTE_ADJUSTMENTS, SPECIAL_ELEMENTS, VOID_ELEMENTS
from .sanitize import DEFAULT_POLICY, SanitizationPolicy, sanitize


def _escape_text(text: str | None) -> str:
    if not text:
        return ""
    # Minimal, but matches html5lib serializer expectations in core cases.
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _choose_attr_quote(value: str | None, forced_quote_char: str | None = None) -> str:
    if forced_quote_char in {'"', "'"}:
        return forced_quote_char
    if value is None:
        return '"'
    value = str(value)
    if '"' in value and "'" not in value:
        return "'"
    return '"'


def _escape_attr_value(value: str | None, quote_char: str, *, escape_lt_in_attrs: bool = False) -> str:
    if value is None:
        return ""
    value = str(value)
    value = value.replace("&", "&amp;")
    if escape_lt_in_attrs:
        value = value.replace("<", "&lt;")
    # Note: html5lib's default serializer does not escape '>' in attrs.
    if quote_char == '"':
        return value.replace('"', "&quot;")
    return value.replace("'", "&#39;")


def _can_unquote_attr_value(value: str | None) -> bool:
    if value is None:
        return False
    value = str(value)
    for ch in value:
        if ch == ">":
            return False
        if ch in {'"', "'", "="}:
            return False
        if ch in {" ", "\t", "\n", "\f", "\r"}:
            return False
    return True


def _serializer_minimize_attr_value(name: str, value: str | None, minimize_boolean_attributes: bool) -> bool:
    if not minimize_boolean_attributes:
        return False
    if value is None or value == "":
        return True
    return str(value).lower() == str(name).lower()


def serialize_start_tag(
    name: str,
    attrs: dict[str, str | None] | None,
    *,
    quote_attr_values: bool = True,
    minimize_boolean_attributes: bool = True,
    quote_char: str | None = None,
    escape_lt_in_attrs: bool = False,
    use_trailing_solidus: bool = False,
    is_void: bool = False,
) -> str:
    attrs = attrs or {}
    parts: list[str] = ["<", name]
    if attrs:
        for key, value in attrs.items():
            if _serializer_minimize_attr_value(key, value, minimize_boolean_attributes):
                parts.extend([" ", key])
                continue

            if value is None:
                parts.extend([" ", key, '=""'])
                continue

            value_str = str(value)
            if value_str == "":
                parts.extend([" ", key, '=""'])
                continue

            if not quote_attr_values and _can_unquote_attr_value(value_str):
                escaped = value_str.replace("&", "&amp;")
                if escape_lt_in_attrs:
                    escaped = escaped.replace("<", "&lt;")
                parts.extend([" ", key, "=", escaped])
            else:
                quote = _choose_attr_quote(value_str, quote_char)
                escaped = _escape_attr_value(value_str, quote, escape_lt_in_attrs=escape_lt_in_attrs)
                parts.extend([" ", key, "=", quote, escaped, quote])

    if use_trailing_solidus and is_void:
        parts.append(" />")
    else:
        parts.append(">")
    return "".join(parts)


def serialize_end_tag(name: str) -> str:
    return f"</{name}>"


def to_html(
    node: Any,
    indent: int = 0,
    indent_size: int = 2,
    *,
    pretty: bool = True,
    safe: bool = True,
    policy: SanitizationPolicy | None = None,
) -> str:
    """Convert node to HTML string."""
    if safe:
        node = sanitize(node, policy=policy or DEFAULT_POLICY)
    if node.name == "#document":
        # Document root - just render children
        parts: list[str] = []
        for child in node.children or []:
            parts.append(_node_to_html(child, indent, indent_size, pretty, in_pre=False))
        return "\n".join(parts) if pretty else "".join(parts)
    return _node_to_html(node, indent, indent_size, pretty, in_pre=False)


_PREFORMATTED_ELEMENTS: set[str] = {"pre", "textarea"}


def _is_whitespace_text_node(node: Any) -> bool:
    return node.name == "#text" and (node.data or "").strip() == ""


def _should_pretty_indent_children(children: list[Any]) -> bool:
    has_comment = False
    has_non_whitespace_text = False
    for child in children:
        name = child.name
        if name == "#comment":
            has_comment = True
            break
        if name == "#text":
            if (child.data or "").strip():
                has_non_whitespace_text = True
                break

    if has_comment or has_non_whitespace_text:
        return False

    for child in children:
        name = child.name
        if name in {"#text", "#comment"}:
            continue
        # Only indent safely when children are known "blockish" HTML elements.
        # If we guess wrong and indent inline elements, we can introduce rendering spaces.
        if name not in SPECIAL_ELEMENTS:
            return False
    return True


def _node_to_html(node: Any, indent: int = 0, indent_size: int = 2, pretty: bool = True, *, in_pre: bool) -> str:
    """Helper to convert a node to HTML."""
    prefix = " " * (indent * indent_size) if pretty and not in_pre else ""
    name: str = node.name
    content_pre = in_pre or name in _PREFORMATTED_ELEMENTS
    newline = "\n" if pretty and not content_pre else ""

    # Text node
    if name == "#text":
        text: str | None = node.data
        if pretty and not in_pre:
            text = text.strip() if text else ""
            if text:
                return f"{prefix}{_escape_text(text)}"
            return ""
        return _escape_text(text) if text else ""

    # Comment node
    if name == "#comment":
        return f"{prefix}<!--{node.data or ''}-->"

    # Doctype
    if name == "!doctype":
        return f"{prefix}<!DOCTYPE html>"

    # Document fragment
    if name == "#document-fragment":
        parts: list[str] = []
        for child in node.children or []:
            child_html = _node_to_html(child, indent, indent_size, pretty, in_pre=in_pre)
            if child_html:
                parts.append(child_html)
        return newline.join(parts) if pretty else "".join(parts)

    # Element node
    attrs: dict[str, str | None] = node.attrs or {}

    # Build opening tag
    open_tag = serialize_start_tag(name, attrs)

    # Void elements
    if name in VOID_ELEMENTS:
        return f"{prefix}{open_tag}"

    # Elements with children
    # Template special handling: HTML templates store contents in `template_content`.
    if name == "template" and node.namespace in {None, "html"} and node.template_content:
        children: list[Any] = node.template_content.children or []
    else:
        children = node.children or []
    if not children:
        return f"{prefix}{open_tag}{serialize_end_tag(name)}"

    # Check if all children are text-only (inline rendering)
    all_text = all(c.name == "#text" for c in children)

    if all_text and pretty and not content_pre:
        return f"{prefix}{open_tag}{_escape_text(node.to_text(separator='', strip=False))}{serialize_end_tag(name)}"

    if pretty and content_pre:
        inner = "".join(
            _node_to_html(child, indent + 1, indent_size, pretty, in_pre=True)
            for child in children
            if child is not None
        )
        return f"{prefix}{open_tag}{inner}{serialize_end_tag(name)}"

    if pretty and not content_pre and not _should_pretty_indent_children(children):
        inner = "".join(
            _node_to_html(child, 0, indent_size, pretty=False, in_pre=content_pre)
            for child in children
            if child is not None
        )
        return f"{prefix}{open_tag}{inner}{serialize_end_tag(name)}"

    # Render with child indentation
    parts = [f"{prefix}{open_tag}"]
    for child in children:
        if pretty and not content_pre and _is_whitespace_text_node(child):
            continue
        child_html = _node_to_html(child, indent + 1, indent_size, pretty, in_pre=content_pre)
        if child_html:
            parts.append(child_html)
    parts.append(f"{prefix}{serialize_end_tag(name)}")
    return newline.join(parts) if pretty else "".join(parts)


def to_test_format(node: Any, indent: int = 0) -> str:
    """Convert node to html5lib test format string.

    This format is used by html5lib-tests for validating parser output.
    Uses '| ' prefixes and specific indentation rules.
    """
    if node.name in {"#document", "#document-fragment"}:
        parts = [_node_to_test_format(child, 0) for child in node.children]
        return "\n".join(parts)
    return _node_to_test_format(node, indent)


def _node_to_test_format(node: Any, indent: int) -> str:
    """Helper to convert a node to test format."""
    if node.name == "#comment":
        comment: str = node.data or ""
        return f"| {' ' * indent}<!-- {comment} -->"

    if node.name == "!doctype":
        return _doctype_to_test_format(node)

    if node.name == "#text":
        text: str = node.data or ""
        return f'| {" " * indent}"{text}"'

    # Regular element
    line = f"| {' ' * indent}<{_qualified_name(node)}>"
    attribute_lines = _attrs_to_test_format(node, indent)

    # Template special handling (only HTML namespace templates have template_content)
    if node.name == "template" and node.namespace in {None, "html"} and node.template_content:
        sections: list[str] = [line]
        if attribute_lines:
            sections.extend(attribute_lines)
        content_line = f"| {' ' * (indent + 2)}content"
        sections.append(content_line)
        sections.extend(_node_to_test_format(child, indent + 4) for child in node.template_content.children)
        return "\n".join(sections)

    # Regular element with children
    child_lines = [_node_to_test_format(child, indent + 2) for child in node.children] if node.children else []

    sections = [line]
    if attribute_lines:
        sections.extend(attribute_lines)
    sections.extend(child_lines)
    return "\n".join(sections)


def _qualified_name(node: Any) -> str:
    """Get the qualified name of a node (with namespace prefix if needed)."""
    if node.namespace and node.namespace not in {"html", None}:
        return f"{node.namespace} {node.name}"
    return str(node.name)


def _attrs_to_test_format(node: Any, indent: int) -> list[str]:
    """Format element attributes for test output."""
    if not node.attrs:
        return []

    formatted: list[str] = []
    padding = " " * (indent + 2)

    # Prepare display names for sorting
    display_attrs: list[tuple[str, str]] = []
    namespace: str | None = node.namespace
    for attr_name, attr_value in node.attrs.items():
        value = attr_value or ""
        display_name = attr_name
        if namespace and namespace not in {None, "html"}:
            lower_name = attr_name.lower()
            if lower_name in FOREIGN_ATTRIBUTE_ADJUSTMENTS:
                display_name = attr_name.replace(":", " ")
        display_attrs.append((display_name, value))

    # Sort by display name for canonical test output
    display_attrs.sort(key=lambda x: x[0])

    for display_name, value in display_attrs:
        formatted.append(f'| {padding}{display_name}="{value}"')
    return formatted


def _doctype_to_test_format(node: Any) -> str:
    """Format DOCTYPE node for test output."""
    doctype = node.data

    name: str = doctype.name or ""
    public_id: str | None = doctype.public_id
    system_id: str | None = doctype.system_id

    parts: list[str] = ["| <!DOCTYPE"]
    if name:
        parts.append(f" {name}")
    else:
        parts.append(" ")

    if public_id is not None or system_id is not None:
        pub = public_id if public_id is not None else ""
        sys = system_id if system_id is not None else ""
        parts.append(f' "{pub}"')
        parts.append(f' "{sys}"')

    parts.append(">")
    return "".join(parts)
