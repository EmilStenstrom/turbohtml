"""HTML serialization utilities for JustHTML DOM nodes."""

from __future__ import annotations

# ruff: noqa: PERF401

from typing import Any

from justhtml.constants import FOREIGN_ATTRIBUTE_ADJUSTMENTS, VOID_ELEMENTS


def _escape_text(text: str | None) -> str:
    if not text:
        return ""
    # Minimal, but matches html5lib serializer expectations in core cases.
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _choose_attr_quote(value: str | None) -> str:
    if value is None:
        return '"'
    value = str(value)
    if '"' in value and "'" not in value:
        return "'"
    return '"'


def _escape_attr_value(value: str | None, quote_char: str) -> str:
    if value is None:
        return ""
    value = str(value)
    value = value.replace("&", "&amp;")
    # Note: html5lib's default serializer does not escape '>' in attrs.
    if quote_char == '"':
        return value.replace('"', "&quot;")
    return value.replace("'", "&#39;")


def _can_unquote_attr_value(value: str | None) -> bool:
    if value is None:
        return False
    value = str(value)
    # html5lib's serializer unquotes aggressively; match fixture expectations.
    # Disallow whitespace and characters that would terminate/ambiguate the value.
    for ch in value:
        if ch == ">":
            return False
        if ch in {'"', "'", "="}:
            return False
        if ch in {" ", "\t", "\n", "\f", "\r"}:
            return False
    return True


def serialize_start_tag(name: str, attrs: dict[str, str | None] | None) -> str:
    attrs = attrs or {}
    parts: list[str] = ["<", name]
    if attrs:
        for key, value in attrs.items():
            if value is None or value == "":
                parts.extend([" ", key])
            else:
                if _can_unquote_attr_value(value):
                    escaped = str(value).replace("&", "&amp;")
                    parts.extend([" ", key, "=", escaped])
                else:
                    quote = _choose_attr_quote(value)
                    escaped = _escape_attr_value(value, quote)
                    parts.extend([" ", key, "=", quote, escaped, quote])
    parts.append(">")
    return "".join(parts)


def serialize_end_tag(name: str) -> str:
    return f"</{name}>"


def to_html(node: Any, indent: int = 0, indent_size: int = 2, *, pretty: bool = True) -> str:
    """Convert node to HTML string."""
    if node.name == "#document":
        # Document root - just render children
        parts: list[str] = []
        for child in node.children or []:
            parts.append(_node_to_html(child, indent, indent_size, pretty))
        return "\n".join(parts) if pretty else "".join(parts)
    return _node_to_html(node, indent, indent_size, pretty)


def _node_to_html(node: Any, indent: int = 0, indent_size: int = 2, pretty: bool = True) -> str:
    """Helper to convert a node to HTML."""
    prefix = " " * (indent * indent_size) if pretty else ""
    newline = "\n" if pretty else ""
    name: str = node.name

    # Text node
    if name == "#text":
        text: str | None = node.data
        if pretty:
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
            child_html = _node_to_html(child, indent, indent_size, pretty)
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
    children: list[Any] = node.children or []
    if not children:
        return f"{prefix}{open_tag}{serialize_end_tag(name)}"

    # Check if all children are text-only (inline rendering)
    all_text = all(c.name == "#text" for c in children)

    if all_text and pretty:
        return f"{prefix}{open_tag}{_escape_text(node.to_text(separator='', strip=False))}{serialize_end_tag(name)}"

    # Render with child indentation
    parts = [f"{prefix}{open_tag}"]
    for child in children:
        child_html = _node_to_html(child, indent + 1, indent_size, pretty)
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
