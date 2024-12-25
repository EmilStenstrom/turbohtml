from typing import Optional, Tuple, TYPE_CHECKING
from .node import Node
from .constants import HTML_ELEMENTS, DUAL_NAMESPACE_ELEMENTS, SVG_CASE_SENSITIVE_ELEMENTS

if TYPE_CHECKING:
    from .node import Node

class ForeignContentHandler:
    """Handles SVG and other foreign element contexts."""

    def create_node(self, tag_name: str, attributes: dict, 
                   current_parent: 'Node', context: Optional[str]) -> 'Node':
        """Create a node with proper namespace handling."""
        tag_name_lower = tag_name.lower()
        
        if context == 'math':
            # Handle MathML elements
            if tag_name_lower == 'annotation-xml':
                return Node('math annotation-xml', attributes)
            
            # Handle HTML elements inside annotation-xml
            if current_parent.tag_name == 'math annotation-xml':
                encoding = current_parent.attributes.get('encoding', '').lower()
                if encoding in ('application/xhtml+xml', 'text/html'):
                    # Keep HTML elements nested for these encodings
                    return Node(tag_name_lower, attributes)
                if tag_name_lower in HTML_ELEMENTS:
                    return Node(tag_name_lower, attributes)
            
            return Node(f'math {tag_name}', attributes)
        elif context == 'svg':
            # Handle case-sensitive SVG elements
            if tag_name_lower in SVG_CASE_SENSITIVE_ELEMENTS:
                correct_case = SVG_CASE_SENSITIVE_ELEMENTS[tag_name_lower]
                node = Node(f'svg {correct_case}', attributes)
                # Special handling for foreignObject
                if tag_name_lower == 'foreignobject':
                    return node
            # Handle HTML elements inside foreignObject
            elif tag_name_lower in HTML_ELEMENTS:
                temp_parent = current_parent
                while temp_parent:
                    if temp_parent.tag_name == 'svg foreignObject':
                        return Node(tag_name_lower, attributes)
                    temp_parent = temp_parent.parent
            return Node(f'svg {tag_name_lower}', attributes)
        
        return Node(tag_name_lower, attributes)

    def handle_context(self, tag_name: str, current_parent: 'Node', 
                      context: Optional[str]) -> Tuple['Node', Optional[str]]:
        """Handle foreign element context changes."""
        tag_name_lower = tag_name.lower()
        
        # Handle HTML elements inside annotation-xml
        if current_parent.tag_name == 'math annotation-xml':
            encoding = current_parent.attributes.get('encoding', '').lower()
            if encoding in ('application/xhtml+xml', 'text/html'):
                # Keep the context for these encodings
                return current_parent, context
            if tag_name_lower in HTML_ELEMENTS:
                return self.find_html_ancestor(current_parent), None
            
        # Enter MathML context
        if tag_name_lower == 'math':
            return current_parent, 'math'
            
        # Existing SVG handling...
        if context == 'svg':
            if tag_name_lower in HTML_ELEMENTS:
                temp_parent = current_parent
                while temp_parent:
                    if temp_parent.tag_name == 'svg foreignObject':
                        return current_parent, context
                    temp_parent = temp_parent.parent
                return self.find_html_ancestor(current_parent), None
                
        if tag_name_lower == 'svg':
            return current_parent, 'svg'

        return current_parent, context

    def handle_foreign_end_tag(self, tag_name: str, current_parent: 'Node', 
                             context: Optional[str]) -> Tuple['Node', Optional[str]]:
        """Handle closing tags in foreign element contexts."""
        tag_name_lower = tag_name.lower()
        
        if context == 'math' and tag_name_lower == 'math':
            return current_parent.parent, None
        elif context == 'svg' and tag_name_lower == 'svg':
            return current_parent.parent, None
        
        return current_parent, context

    def find_html_ancestor(self, node: 'Node') -> 'Node':
        """Find the nearest HTML ancestor node."""
        temp_parent = node
        while temp_parent:
            if not temp_parent.tag_name.startswith(('svg ', 'math ')):
                return temp_parent
            if temp_parent.parent:
                temp_parent = temp_parent.parent
            else:
                break
        return node  # Fallback to current node if no HTML ancestor found

    def handle_text(self, text: str, current_parent: 'Node') -> Optional['Node']:
        """Handle text nodes in foreign content contexts."""
        if current_parent.tag_name == 'math annotation-xml':
            # Only create text node if we're directly in annotation-xml
            text_node = Node('#text')
            text_node.text_content = text
            return text_node
        return None
