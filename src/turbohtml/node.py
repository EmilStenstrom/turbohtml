from typing import List, Optional, Dict, TYPE_CHECKING

class Node:
    """
    Represents a DOM-like node.
    - tag_name: e.g., 'div', 'p', etc. Use '#text' for text nodes.
    - attributes: dict of tag attributes
    - children: list of child Nodes
    - parent: reference to parent Node (or None for root)
    - next_sibling/previous_sibling: references to adjacent nodes in the tree
    """
    __slots__ = ('tag_name', 'attributes', 'children', 'parent', 'text_content', 
                 'next_sibling', 'previous_sibling')

    def __init__(self, tag_name: str, attributes: Optional[Dict[str, str]] = None):
        self.tag_name = tag_name
        self.attributes = attributes or {}
        self.children: List['Node'] = []
        self.parent: Optional['Node'] = None
        self.text_content = ""  # For text nodes or concatenated text in element nodes
        self.next_sibling: Optional['Node'] = None
        self.previous_sibling: Optional['Node'] = None

    def append_child(self, child: 'Node'):
        if child.parent:
            # Update sibling links in old location
            if child.previous_sibling:
                child.previous_sibling.next_sibling = child.next_sibling
            if child.next_sibling:
                child.next_sibling.previous_sibling = child.previous_sibling
            child.parent.children.remove(child)
        
        # Update sibling links in new location
        if self.children:
            self.children[-1].next_sibling = child
            child.previous_sibling = self.children[-1]
        else:
            child.previous_sibling = None
        
        child.parent = self
        child.next_sibling = None
        self.children.append(child)

    def insert_before(self, new_node: 'Node', reference_node: 'Node'):
        if reference_node not in self.children:
            return
        
        if new_node.parent:
            # Update sibling links in old location
            if new_node.previous_sibling:
                new_node.previous_sibling.next_sibling = new_node.next_sibling
            if new_node.next_sibling:
                new_node.next_sibling.previous_sibling = new_node.previous_sibling
            new_node.parent.children.remove(new_node)
        
        idx = self.children.index(reference_node)
        new_node.parent = self
        self.children.insert(idx, new_node)
        
        # Update sibling pointers
        new_node.next_sibling = reference_node
        new_node.previous_sibling = reference_node.previous_sibling
        reference_node.previous_sibling = new_node
        if new_node.previous_sibling:
            new_node.previous_sibling.next_sibling = new_node
            
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
