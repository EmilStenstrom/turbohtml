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

    @property
    def text(self) -> str:
        """
        Recursively gather text from this node and its children.
        For an element node, text is concatenated from all text children.
        For a #text node, text_content holds the raw text.
        """
        if self.tag_name == '#text':
            return self.text_content
        return "".join(child.text if child.tag_name == '#text' else child.text
                       for child in self.children)

    def query(self, selector: str) -> Optional['Node']:
        """
        Return the *first* node matching a basic CSS selector:
          - #id
          - .class
          - tag
        """
        results = self._match_selector(selector, first_only=True)
        return results[0] if results else None

    def query_all(self, selector: str) -> List['Node']:
        """
        Return all nodes matching a basic CSS selector:
          - #id
          - .class
          - tag
        """
        return self._match_selector(selector, first_only=False)

    def _match_selector(self, selector: str, first_only: bool) -> List['Node']:
        matched = []

        # If selector is #id
        if selector.startswith('#'):
            needed_id = selector[1:]
            self._dfs_find(lambda n: n.attributes.get('id') == needed_id, matched, first_only)
        # If selector is .class
        elif selector.startswith('.'):
            needed_class = selector[1:]
            self._dfs_find(
                lambda n: 'class' in n.attributes and needed_class in n.attributes['class'].split(),
                matched, first_only
            )
        else:
            # Assume it's a tag selector
            needed_tag = selector.lower()
            self._dfs_find(lambda n: n.tag_name.lower() == needed_tag, matched, first_only)

        return matched

    def _dfs_find(self, predicate, found_list, first_only):
        """
        Depth-first search for nodes that match a given predicate.
        """
        if predicate(self):
            found_list.append(self)
            if first_only:
                return
        for child in self.children:
            if first_only and found_list:
                # Already found
                return
            child._dfs_find(predicate, found_list, first_only)

    def __repr__(self):
        if self.tag_name == '#text':
            return f"Node(#text='{self.text_content[:30]}')"
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
