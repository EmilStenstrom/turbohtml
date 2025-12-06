"""HTML serialization utilities for JustHTML DOM nodes."""

# ruff: noqa: PERF401

from justhtml.constants import FOREIGN_ATTRIBUTE_ADJUSTMENTS, VOID_ELEMENTS


def to_html(node, indent=0, indent_size=2, pretty=True):
    """Convert node to HTML string."""
    if node.name == "#document":
        # Document root - just render children
        parts = []
        for child in node.children or []:
            parts.append(_node_to_html(child, indent, indent_size, pretty))
        return "\n".join(parts) if pretty else "".join(parts)
    return _node_to_html(node, indent, indent_size, pretty)


def _node_to_html(node, indent=0, indent_size=2, pretty=True):
    """Helper to convert a node to HTML."""
    prefix = " " * (indent * indent_size) if pretty else ""
    newline = "\n" if pretty else ""
    name = node.name

    # Text node
    if name == "#text":
        text = node.data
        if pretty:
            text = text.strip() if text else ""
            if text:
                return f"{prefix}{text}"
            return ""
        return text or ""

    # Comment node
    if name == "#comment":
        return f"{prefix}<!--{node.data or ''}-->"

    # Doctype
    if name == "!doctype":
        return f"{prefix}<!DOCTYPE html>"

    # Document fragment
    if name == "#document-fragment":
        parts = []
        for child in node.children or []:
            child_html = _node_to_html(child, indent, indent_size, pretty)
            if child_html:
                parts.append(child_html)
        return newline.join(parts) if pretty else "".join(parts)

    # Element node
    attrs = node.attrs or {}

    # Build opening tag
    attr_str = ""
    if attrs:
        attr_parts = []
        for key, value in attrs.items():
            if value is None:
                attr_parts.append(key)
            elif value == "":
                attr_parts.append(key)
            else:
                # Escape quotes in attribute values
                escaped = str(value).replace("&", "&amp;").replace('"', "&quot;")
                attr_parts.append(f'{key}="{escaped}"')
        if attr_parts:  # pragma: no branch
            attr_str = " " + " ".join(attr_parts)

    # Void elements
    if name in VOID_ELEMENTS:
        return f"{prefix}<{name}{attr_str}>"

    # Elements with children
    children = node.children or []
    if not children:
        return f"{prefix}<{name}{attr_str}></{name}>"

    # Check if all children are text-only (inline rendering)
    all_text = all(hasattr(c, "name") and c.name == "#text" for c in children)

    if all_text and pretty:
        return f"{prefix}<{name}{attr_str}>{node.text}</{name}>"

    # Render with child indentation
    parts = [f"{prefix}<{name}{attr_str}>"]
    for child in children:
        child_html = _node_to_html(child, indent + 1, indent_size, pretty)
        if child_html:
            parts.append(child_html)
    parts.append(f"{prefix}</{name}>")
    return newline.join(parts) if pretty else "".join(parts)


def to_test_format(node, indent=0):
    """Convert node to html5lib test format string.

    This format is used by html5lib-tests for validating parser output.
    Uses '| ' prefixes and specific indentation rules.
    """
    if node.name in {"#document", "#document-fragment"}:
        parts = [_node_to_test_format(child, 0) for child in node.children]
        return "\n".join(parts)
    return _node_to_test_format(node, indent)


def _node_to_test_format(node, indent):
    """Helper to convert a node to test format."""
    if node.name == "#comment":
        comment = node.data or ""
        return f"| {' ' * indent}<!-- {comment} -->"

    if node.name == "!doctype":
        return _doctype_to_test_format(node)

    if node.name == "#text":
        text = node.data or ""
        return f'| {" " * indent}"{text}"'

    # Regular element
    line = f"| {' ' * indent}<{_qualified_name(node)}>"
    attribute_lines = _attrs_to_test_format(node, indent)

    # Template special handling
    if node.name == "template" and hasattr(node, "template_content") and node.template_content:
        sections = [line]
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


def _qualified_name(node):
    """Get the qualified name of a node (with namespace prefix if needed)."""
    if node.namespace and node.namespace not in {"html", None}:
        return f"{node.namespace} {node.name}"
    return node.name


def _attrs_to_test_format(node, indent):
    """Format element attributes for test output."""
    if not node.attrs:
        return []

    formatted = []
    padding = " " * (indent + 2)

    # Prepare display names for sorting
    display_attrs = []
    namespace = node.namespace
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


def _doctype_to_test_format(node):
    """Format DOCTYPE node for test output."""
    doctype = node.data

    name = doctype.name or ""
    public_id = doctype.public_id
    system_id = doctype.system_id

    parts = ["| <!DOCTYPE"]
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
