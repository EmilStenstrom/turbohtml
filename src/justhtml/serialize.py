"""HTML serialization utilities for JustHTML DOM nodes."""

# ruff: noqa: PERF401

from __future__ import annotations

from typing import Any

from .constants import FOREIGN_ATTRIBUTE_ADJUSTMENTS, SPECIAL_ELEMENTS, VOID_ELEMENTS
from .sanitize import DEFAULT_DOCUMENT_POLICY, DEFAULT_POLICY, SanitizationPolicy, sanitize


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
    # value is assumed to be a string
    if '"' in value and "'" not in value:
        return "'"
    return '"'


def _escape_attr_value(value: str | None, quote_char: str, *, escape_lt_in_attrs: bool = False) -> str:
    if value is None:
        return ""
    # value is assumed to be a string
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
    if value == name:
        return True
    return value.lower() == name


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
        if policy is None and node.name == "#document":
            node = sanitize(node, policy=DEFAULT_DOCUMENT_POLICY)
        else:
            node = sanitize(node, policy=policy or DEFAULT_POLICY)
    if node.name == "#document":
        # Document root - just render children
        parts: list[str] = []
        for child in node.children or []:
            parts.append(_node_to_html(child, indent, indent_size, pretty, in_pre=False))
        return "\n".join(parts) if pretty else "".join(parts)
    return _node_to_html(node, indent, indent_size, pretty, in_pre=False)


_PREFORMATTED_ELEMENTS: set[str] = {"pre", "textarea", "code"}

# Elements whose text content must not be normalized (e.g. scripts/styles).
_RAWTEXT_ELEMENTS: set[str] = {"script", "style"}


def _collapse_html_whitespace(text: str) -> str:
    """Collapse HTML whitespace runs to a single space and trim edges.

    This matches how HTML rendering treats most whitespace in text nodes, and is
    used only for pretty-printing in non-preformatted contexts.
    """
    if not text:
        return ""

    parts: list[str] = []
    in_whitespace = False
    for ch in text:
        if ch in {" ", "\t", "\n", "\f", "\r"}:
            if not in_whitespace:
                parts.append(" ")
                in_whitespace = True
            continue

        parts.append(ch)
        in_whitespace = False

    collapsed = "".join(parts)
    return collapsed.strip(" ")


def _normalize_formatting_whitespace(text: str) -> str:
    """Normalize formatting whitespace within a text node.

    Converts newlines/tabs/CR/FF to regular spaces and collapses runs that
    include such formatting whitespace to a single space.

    Pure space runs are preserved as-is (so existing double-spaces remain).
    """
    if not text:
        return ""

    if "\n" not in text and "\r" not in text and "\t" not in text and "\f" not in text:
        return text

    starts_with_formatting = text[0] in {"\n", "\r", "\t", "\f"}
    ends_with_formatting = text[-1] in {"\n", "\r", "\t", "\f"}

    out: list[str] = []
    in_ws = False
    saw_formatting_ws = False

    for ch in text:
        if ch == " ":
            if in_ws:
                # Only collapse if this whitespace run included formatting whitespace.
                if saw_formatting_ws:
                    continue
                out.append(" ")
                continue
            in_ws = True
            saw_formatting_ws = False
            out.append(" ")
            continue

        if ch in {"\n", "\r", "\t", "\f"}:
            if in_ws:
                saw_formatting_ws = True
                continue
            in_ws = True
            saw_formatting_ws = True
            out.append(" ")
            continue

        in_ws = False
        saw_formatting_ws = False
        out.append(ch)

    normalized = "".join(out)
    if starts_with_formatting and normalized.startswith(" "):
        normalized = normalized[1:]
    if ends_with_formatting and normalized.endswith(" "):
        normalized = normalized[:-1]
    return normalized


def _is_whitespace_text_node(node: Any) -> bool:
    return node.name == "#text" and (node.data or "").strip() == ""


def _should_pretty_indent_children(children: list[Any]) -> bool:
    for child in children:
        if child is None:
            continue
        name = child.name
        if name == "#comment":
            return False
        if name == "#text" and (child.data or "").strip():
            return False

    element_children: list[Any] = [
        child for child in children if child is not None and child.name not in {"#text", "#comment"}
    ]
    if not element_children:
        return True
    if len(element_children) == 1:
        only_child = element_children[0]
        if only_child.name in SPECIAL_ELEMENTS:
            return True
        if only_child.name == "a":
            # If an anchor wraps block-ish content (valid HTML5), treat it as block-ish
            # for pretty-printing so the parent can indent it on its own line.
            for grandchild in only_child.children or []:
                if grandchild is None:
                    continue
                if grandchild.name in SPECIAL_ELEMENTS:
                    return True
        return False

    # Safe indentation rule: only insert inter-element whitespace when we won't
    # be placing it between two adjacent inline/phrasing elements.
    prev_is_special = element_children[0].name in SPECIAL_ELEMENTS
    for child in element_children[1:]:
        current_is_special = child.name in SPECIAL_ELEMENTS
        if not prev_is_special and not current_is_special:
            return False
        prev_is_special = current_is_special
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
    if name == "template" and node.namespace in {None, "html"} and node.template_content is not None:
        children: list[Any] = node.template_content.children or []
    else:
        children = node.children or []
    if not children:
        return f"{prefix}{open_tag}{serialize_end_tag(name)}"

    # Check if all children are text-only (inline rendering)
    all_text = all(c.name == "#text" for c in children)

    if all_text and pretty and not content_pre:
        # Serializer controls sanitization at the to_html() entry point; avoid
        # implicit re-sanitization during rendering.
        text_content = node.to_text(separator="", strip=False, safe=False)
        if name not in _RAWTEXT_ELEMENTS:
            text_content = _collapse_html_whitespace(text_content)
        return f"{prefix}{open_tag}{_escape_text(text_content)}{serialize_end_tag(name)}"

    if pretty and content_pre:
        inner = "".join(
            _node_to_html(child, indent + 1, indent_size, pretty, in_pre=True)
            for child in children
            if child is not None
        )
        return f"{prefix}{open_tag}{inner}{serialize_end_tag(name)}"

    if pretty and not content_pre and not _should_pretty_indent_children(children):
        # For block-ish elements that contain only element children and whitespace-only
        # text nodes, we can still format each child on its own line (only when there
        # is already whitespace separating element siblings).
        if name in SPECIAL_ELEMENTS:
            has_comment = False
            has_element = False
            has_whitespace_between_elements = False

            first_element_index: int | None = None
            last_element_index: int | None = None

            previous_was_element = False
            saw_whitespace_since_last_element = False
            for i, child in enumerate(children):
                if child is None:
                    continue
                if child.name == "#comment":
                    has_comment = True
                    break
                if child.name == "#text":
                    # Track whether there is already whitespace between element siblings.
                    if previous_was_element and not (child.data or "").strip():
                        saw_whitespace_since_last_element = True
                    continue

                has_element = True
                if first_element_index is None:
                    first_element_index = i
                last_element_index = i
                if previous_was_element and saw_whitespace_since_last_element:
                    has_whitespace_between_elements = True
                previous_was_element = True
                saw_whitespace_since_last_element = False

            can_indent_non_whitespace_text = True
            if has_element and first_element_index is not None and last_element_index is not None:
                for i, child in enumerate(children):
                    if child is None or child.name != "#text":
                        continue
                    if not (child.data or "").strip():
                        continue
                    # Only allow non-whitespace text *after* the last element.
                    # Leading text or text between elements could gain new spaces
                    # due to indentation/newlines.
                    if i < first_element_index or first_element_index < i < last_element_index:
                        can_indent_non_whitespace_text = False
                        break

            if has_element and has_whitespace_between_elements and not has_comment and can_indent_non_whitespace_text:
                inner_lines: list[str] = []
                for child in children:
                    if child is None:
                        continue
                    if child.name == "#text":
                        text = _collapse_html_whitespace(child.data or "")
                        if text:
                            inner_lines.append(f"{' ' * ((indent + 1) * indent_size)}{_escape_text(text)}")
                        continue
                    child_html = _node_to_html(child, indent + 1, indent_size, pretty=True, in_pre=content_pre)
                    if child_html:
                        inner_lines.append(child_html)
                if inner_lines:
                    inner = "\n".join(inner_lines)
                    return f"{prefix}{open_tag}\n{inner}\n{prefix}{serialize_end_tag(name)}"

        inner_parts: list[str] = []

        first_non_none_index: int | None = None
        last_non_none_index: int | None = None
        for i, child in enumerate(children):
            if child is None:
                continue
            if first_non_none_index is None:
                first_non_none_index = i
            last_non_none_index = i

        for i, child in enumerate(children):
            if child is None:
                continue

            if child.name == "#text":
                data = child.data or ""
                if not data.strip():
                    # Drop leading/trailing formatting whitespace in compact mode.
                    if i == first_non_none_index or i == last_non_none_index:
                        continue
                    # Preserve intentional small spacing, but collapse large formatting gaps.
                    if "\n" in data or "\r" in data or "\t" in data or len(data) > 2:
                        inner_parts.append(" ")
                        continue

                if not content_pre and name not in _RAWTEXT_ELEMENTS:
                    data = _normalize_formatting_whitespace(data)
                child_html = _escape_text(data) if data else ""
            else:
                # Even when we can't safely insert whitespace *between* siblings, we can
                # still pretty-print each element subtree to improve readability.
                child_html = _node_to_html(child, 0, indent_size, pretty=True, in_pre=content_pre)
            if child_html:
                inner_parts.append(child_html)

        return f"{prefix}{open_tag}{''.join(inner_parts)}{serialize_end_tag(name)}"

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
    if node.name == "template" and node.namespace in {None, "html"} and node.template_content is not None:
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
