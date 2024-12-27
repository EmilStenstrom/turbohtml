from typing import List, Optional, Dict, TYPE_CHECKING

class Node:
    """
    Represents a DOM-like node.
    - tag_name: e.g., 'div', 'p', etc. Use '#text' for text nodes.
    - attributes: dict of tag attributes
    - children: list of child Nodes
    - parent: reference to parent Node (or None for root)
    """
    __slots__ = ('tag_name', 'attributes', 'children', 'parent', 'text_content')

    def __init__(self, tag_name: str, attributes: Optional[Dict[str, str]] = None):
        self.tag_name = tag_name
        self.attributes = attributes or {}
        self.children: List['Node'] = []
        self.parent: Optional['Node'] = None
        self.text_content = ""  # For text nodes or concatenated text in element nodes

    def append_child(self, child: 'Node'):
        self.children.append(child)
        child.parent = self

    def __repr__(self):
        if self.tag_name == '#text':
            return f"Node(#text='{self.text_content[:30]}')"
        if self.tag_name == '#comment':
            return f"Node(#comment='{self.text_content[:30]}')"
        return f"Node(<{self.tag_name}>, children={len(self.children)})"

    def to_test_format(self, indent=0):
        if self.tag_name == 'document':
            result = []
            for child in self.children:
                result.append(child.to_test_format(0))
            return '\n'.join(result)
        if self.tag_name == '#text':
            return f'| {" " * indent}"{self.text_content}"'
        if self.tag_name == '#comment':
            return f'| {" " * indent}<!-- {self.text_content} -->'
        if self.tag_name == '!doctype':
            return '| <!DOCTYPE html>'

        # Start with the tag name
        result = f'| {" " * indent}<{self.tag_name}>'

        # Add attributes on their own line if present
        if self.attributes:
            for key, value in self.attributes.items():
                result += f'\n| {" " * (indent+2)}{key}="{value}"'

        # Add children
        for child in self.children:
            result += '\n' + child.to_test_format(indent + 2)
        return result
