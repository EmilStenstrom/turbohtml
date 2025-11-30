# ruff: noqa: INP001

"""
HTML5 test format serialization.

This module converts DOM trees into the HTML5 test format used by html5lib tests.
The test format uses '| ' prefixes and specific indentation rules.
"""

from justhtml.constants import FOREIGN_ATTRIBUTE_ADJUSTMENTS


def node_to_test_format(node, indent=0):
    """Convert a DOM node to HTML5 test format string."""
    if node.name in {"#document", "#document-fragment"}:
        parts = []
        for child in node.children:
            child_output = node_to_test_format(child, 0)
            if child_output:
                parts.append(child_output)
        return "\n".join(parts)

    if node.name == "#comment":
        comment = node.data or ""
        return f"| {' ' * indent}<!-- {comment} -->"

    if node.name == "!doctype":
        return _format_doctype(node)

    if node.name == "#text":
        text = node.data or ""
        return f'| {" " * indent}"{text}"'

    # Regular element
    line = f"| {' ' * indent}<{_qualified_name(node)}>"
    attribute_lines = _format_attributes(node, indent)

    # Template special handling
    if node.name == "template" and hasattr(node, "template_content") and node.template_content:
        sections = [line]
        if attribute_lines:
            sections.extend(attribute_lines)
        content_line = f"| {' ' * (indent + 2)}content"
        sections.append(content_line)
        for child in node.template_content.children:
            child_output = node_to_test_format(child, indent + 4)
            if child_output:
                sections.append(child_output)
        return "\n".join(sections)

    # Regular element with children
    child_lines = []
    if node.children:
        for child in node.children:
            child_output = node_to_test_format(child, indent + 2)
            if child_output:
                child_lines.append(child_output)

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


def _format_attributes(node, indent):
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


def _format_doctype(node):
    """Format DOCTYPE node for test output."""
    doctype = node.data
    if not doctype:
        return "| <!DOCTYPE >"

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
