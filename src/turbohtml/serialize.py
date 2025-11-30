"""HTML serialization utilities for TurboHTML DOM nodes."""

# HTML5 void elements (no closing tag)
VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


def to_html(node, indent=0, indent_size=2):
    """Convert node to pretty-printed HTML string."""
    if node.name == "#document":
        # Document root - just render children
        parts = []
        for child in node.children or []:
            parts.append(_node_to_html(child, indent, indent_size))
        return "\n".join(parts)
    else:
        return _node_to_html(node, indent, indent_size)


def _node_to_html(node, indent=0, indent_size=2):
    """Helper to convert a node to HTML."""
    prefix = " " * (indent * indent_size)

    # Text node
    if hasattr(node, "name") and node.name == "#text":
        text = node.data.strip() if node.data else ""
        if text:
            return f"{prefix}{text}"
        return ""

    # Comment node
    if hasattr(node, "name") and node.name == "#comment":
        return f"{prefix}<!--{node.data or ''}-->"

    # Doctype
    if hasattr(node, "name") and node.name == "!doctype":
        return f"{prefix}<!DOCTYPE html>"

    # Document fragment
    if hasattr(node, "name") and node.name == "#document-fragment":
        parts = []
        for child in node.children or []:
            child_html = _node_to_html(child, indent, indent_size)
            if child_html:
                parts.append(child_html)
        return "\n".join(parts)

    # Element node
    name = node.name
    attrs = node.attrs or {}

    # Build opening tag
    attr_str = ""
    if attrs:
        attr_parts = []
        for key, value in attrs.items():
            if value is None or value == "":
                attr_parts.append(key)
            else:
                # Escape quotes in attribute values
                escaped = str(value).replace('"', "&quot;")
                attr_parts.append(f'{key}="{escaped}"')
        if attr_parts:
            attr_str = " " + " ".join(attr_parts)

    # Void elements
    if name in VOID_ELEMENTS:
        return f"{prefix}<{name}{attr_str}>"

    # Elements with children
    children = node.children or []
    if not children:
        return f"{prefix}<{name}{attr_str}></{name}>"

    # Check if all children are text-only (inline rendering)
    all_text = all(
        hasattr(c, "name") and c.name == "#text"
        for c in children
    )

    if all_text:
        text = "".join(c.data or "" for c in children)
        return f"{prefix}<{name}{attr_str}>{text}</{name}>"

    # Render with child indentation
    parts = [f"{prefix}<{name}{attr_str}>"]
    for child in children:
        child_html = _node_to_html(child, indent + 1, indent_size)
        if child_html:
            parts.append(child_html)
    parts.append(f"{prefix}</{name}>")
    return "\n".join(parts)
