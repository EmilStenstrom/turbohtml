# fast_html.py
#
# Minimal HTML parser built from scratch:
# - Partially HTML5 compliant tokenizer
# - Lightweight DOM (Node)
# - Basic CSS-like query methods: tag, #id, .class

import re
from typing import List, Optional, Dict, Tuple, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from .node import Node

# Simple regular expressions for tokenization
TAG_OPEN_RE = re.compile(r'<(!?)(/)?([a-zA-Z0-9][-a-zA-Z0-9:]*)(.*?)>')
ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)"|\s*=\s*\'([^\']*)\'|\s*=\s*([^>\s]+)|)(?=\s|$)')
COMMENT_RE = re.compile(r'<!--(.*?)-->', re.DOTALL)

class ForeignContentHandler:
    """Handles SVG and other foreign element contexts."""
    def __init__(self):
        self.HTML_ELEMENTS = {
            'b', 'big', 'blockquote', 'body', 'br', 'center', 'code',
            'dd', 'div', 'dl', 'dt', 'em', 'embed', 'h1', 'h2', 'h3', 'h4',
            'h5', 'h6', 'head', 'hr', 'i', 'img', 'li', 'listing',
            'menu', 'meta', 'nobr', 'ol', 'p', 'pre', 's', 'small',
            'span', 'strong', 'strike', 'sub', 'sup', 'table', 'tt',
            'u', 'ul', 'var'
        }
        # Elements that can be both HTML and SVG/MathML
        self.DUAL_NAMESPACE_ELEMENTS = {'main', 'title'}

        # Update SVG_CASE_SENSITIVE_ELEMENTS to be a mapping of lowercase to correct case
        self.SVG_CASE_SENSITIVE_ELEMENTS = {
            'foreignobject': 'foreignObject',
            'animatemotion': 'animateMotion',
            'animatetransform': 'animateTransform',
            'clippath': 'clipPath',
            'feblend': 'feBlend',
            'fecolormatrix': 'feColorMatrix',
            'fecomponenttransfer': 'feComponentTransfer',
            'fecomposite': 'feComposite',
            'feconvolvematrix': 'feConvolveMatrix',
            'fediffuselight': 'feDiffuseLighting',
            'fedisplacementmap': 'feDisplacementMap',
            'fedistantlight': 'feDistantLight',
            'fedropshadow': 'feDropShadow',
            'feflood': 'feFlood',
            'fefunca': 'feFuncA',
            'fefuncb': 'feFuncB',
            'fefuncg': 'feFuncG',
            'fefuncr': 'feFuncR',
            'fegaussianblur': 'feGaussianBlur',
            'feimage': 'feImage',
            'femergenode': 'feMergeNode',
            'femorphology': 'feMorphology',
            'feoffset': 'feOffset',
            'fepointlight': 'fePointLight',
            'fespecularlighting': 'feSpecularLighting',
            'fespotlight': 'feSpotLight',
            'fetile': 'feTile',
            'feturbulence': 'feTurbulence',
            'lineargradient': 'linearGradient',
            'radialgradient': 'radialGradient',
            'textpath': 'textPath'
        }

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
                if tag_name_lower in self.HTML_ELEMENTS:
                    return Node(tag_name_lower, attributes)
            
            return Node(f'math {tag_name}', attributes)
        elif context == 'svg':
            # Handle case-sensitive SVG elements
            if tag_name_lower in self.SVG_CASE_SENSITIVE_ELEMENTS:
                correct_case = self.SVG_CASE_SENSITIVE_ELEMENTS[tag_name_lower]
                node = Node(f'svg {correct_case}', attributes)
                # Special handling for foreignObject
                if tag_name_lower == 'foreignobject':
                    return node
            # Handle HTML elements inside foreignObject
            elif tag_name_lower in self.HTML_ELEMENTS:
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
            if tag_name_lower in self.HTML_ELEMENTS:
                return self.find_html_ancestor(current_parent), None
            
        # Enter MathML context
        if tag_name_lower == 'math':
            return current_parent, 'math'
            
        # Existing SVG handling...
        if context == 'svg':
            if tag_name_lower in self.HTML_ELEMENTS:
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

    def handle_comment(self, comment_text: str, current_parent: 'Node') -> Optional['Node']:
        """Handle comments in foreign content contexts."""
        if current_parent.tag_name == 'math annotation-xml':
            comment_node = Node('#comment')
            comment_node.text_content = comment_text.strip()
            return comment_node
        return None


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

    def __getitem__(self, key: str) -> Optional[str]:
        """Allows dict-like attribute access, e.g., node['href']."""
        return self.attributes.get(key)

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


class TurboHTML:
    """
    Main parser interface.
    - Instantiation with HTML string automatically triggers parsing.
    - Provides a root Node that represents the DOM tree.
    """
    # Constants and sets
    VOID_ELEMENTS: Set[str] = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr'
    }

    FORMATTING_ELEMENTS: Set[str] = {
        'a', 'b', 'big', 'code', 'em', 'font', 'i', 'nobr', 'p', 's',
        'small', 'strike', 'strong', 'tt', 'u'
    }

    BOUNDARY_ELEMENTS: Set[str] = {
        'applet', 'button', 'marquee', 'object', 'table', 'td', 'th'
    }

    HTML_ELEMENTS: Set[str] = {
        'b', 'big', 'blockquote', 'body', 'br', 'center', 'code',
        'dd', 'div', 'dl', 'dt', 'em', 'embed', 'h1', 'h2', 'h3', 'h4',
        'h5', 'h6', 'head', 'hr', 'i', 'img', 'li', 'listing',
        'menu', 'meta', 'nobr', 'ol', 'p', 'pre', 's', 'small',
        'span', 'strong', 'strike', 'sub', 'sup', 'table', 'tt',
        'u', 'ul', 'var'
    }

    # Elements that can contain tables according to HTML5 spec
    TABLE_CONTAINING_ELEMENTS: Set[str] = {
        'button', 'ruby', 'math', 'svg'
    }

    # Update our element categories according to spec
    SPECIAL_ELEMENTS: Set[str] = {
        'address', 'applet', 'area', 'article', 'aside', 'base', 'basefont',
        'bgsound', 'blockquote', 'body', 'br', 'button', 'caption', 'center',
        'col', 'colgroup', 'dd', 'details', 'dir', 'div', 'dl', 'dt', 'embed',
        'fieldset', 'figcaption', 'figure', 'footer', 'form', 'frame', 'frameset',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'header', 'hgroup', 'hr',
        'html', 'iframe', 'img', 'input', 'keygen', 'li', 'link', 'listing',
        'main', 'marquee', 'menu', 'meta', 'nav', 'noembed', 'noframes',
        'noscript', 'object', 'ol', 'p', 'param', 'plaintext', 'pre', 'script',
        'section', 'select', 'source', 'style', 'summary', 'table', 'tbody',
        'td', 'template', 'textarea', 'tfoot', 'th', 'thead', 'title', 'tr',
        'track', 'ul', 'wbr', 'xmp'
    }

    # Elements that can contain tables (from foster parenting rules)
    FOSTER_PARENT_ELEMENTS: Set[str] = {
        'table', 'tbody', 'tfoot', 'thead', 'tr'
    }

    # Elements that can properly contain tables
    TABLE_CONTAINING_ELEMENTS: Set[str] = {
        'html', 'body', 'div', 'form', 'button', 'ruby', 'td', 'th'
    }

    BLOCK_ELEMENTS = {
        'address', 'article', 'aside', 'blockquote', 'details', 'dialog', 'dd', 'div',
        'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2',
        'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr', 'li', 'main', 'nav', 'ol',
        'p', 'pre', 'section', 'table', 'ul', 'summary'
    }

    RAW_TEXT_ELEMENTS = {'script', 'style', 'textarea', 'title', 'plaintext'}
    HEAD_ELEMENTS = {'base', 'basefont', 'bgsound', 'link', 'meta', 'title', 'script', 'style', 'template'}

    def __init__(self, html: str, handle_foreign_elements: bool = True):
        """Initialize the HTML parser.
        
        Args:
            html: The HTML string to parse
            handle_foreign_elements: Whether to handle SVG/MathML elements
        """
        self.html = html
        self.foreign_handler = ForeignContentHandler() if handle_foreign_elements else None
        self.has_doctype = False

        # Create basic HTML structure
        self.root = Node('document')
        self.html_node = Node('html')
        self.head_node = Node('head')
        self.body_node = Node('body')
        
        self.root.append_child(self.html_node)
        self.html_node.append_child(self.head_node)
        self.html_node.append_child(self.body_node)
        
        self.current_parent = self.body_node
        self._parse()

        # Elements that can contain tables
        self.table_containing_elements = {
            'button', 'ruby', 'math', 'svg'
        }

    # Public methods
    def query_all(self, selector: str) -> List[Node]:
        """Query all nodes matching the selector."""
        return self.root.query_all(selector)

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"

    # Core parsing methods
    def _parse(self) -> None:
        """Main parsing loop."""
        index = 0
        length = len(self.html)
        current_parent = self.current_parent
        current_context = None
        has_form = False

        while index < length:
            # Look for comments first
            comment_match = COMMENT_RE.search(self.html, index)
            if comment_match and not self.html[index:comment_match.start()].strip():
                # Only handle comment if there's no non-whitespace text before it
                if self.foreign_handler:
                    node = self.foreign_handler.handle_comment(comment_match.group(1), current_parent)
                    if node:
                        current_parent.append_child(node)
                index = comment_match.end()
                continue

            # Look for next tag
            tag_open_match = TAG_OPEN_RE.search(self.html, index)
            if not tag_open_match:
                # Handle remaining text
                if index < length:
                    text = self.html[index:]
                    self._handle_text_between_tags(text, current_parent)
                break

            start_idx = tag_open_match.start()
            if start_idx > index:
                # Handle text between tags
                text = self.html[index:start_idx]
                if self.foreign_handler and current_parent.tag_name == 'math annotation-xml':
                    node = self.foreign_handler.handle_text(text, current_parent)
                    if node:
                        current_parent.append_child(node)
                else:
                    self._handle_text_between_tags(text, current_parent)

            start_tag_idx, end_tag_idx, tag_info = self._extract_tag_info(tag_open_match)
            
            if tag_info.is_closing:
                current_parent, current_context = self._handle_closing_tag(
                    tag_info.tag_name, current_parent, current_context
                )
            elif tag_info.is_doctype:
                self._handle_doctype(tag_info)
            else:
                # Skip nested form tags
                if tag_info.tag_name.lower() == 'form':
                    if has_form:
                        index = end_tag_idx
                        continue
                    has_form = True
                    
                current_parent, current_context = self._handle_opening_tag(
                    tag_info, current_parent, current_context
                )
            
            index = end_tag_idx

        # Update the current_parent for future reference
        self.current_parent = current_parent

    def _handle_opening_tag(self, tag_info: "TagInfo", current_parent: Node, 
                            current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """Handle opening/self-closing tags with special cases."""
        tag_name = tag_info.tag_name.lower()
        attributes = self._parse_attributes(tag_info.attr_string)

        # Special handling for head tag - reuse existing head node
        if tag_name == 'head':
            return self.head_node, current_context

        # Move certain elements to head ONLY if we're not in a special context
        if tag_name in self.HEAD_ELEMENTS and self.head_node:
            if current_parent != self.head_node and current_context is None:
                new_node = self._create_node(tag_name, attributes, self.head_node, None)
                self.head_node.append_child(new_node)
                return current_parent, current_context

        # Handle raw text elements
        if tag_name in self.RAW_TEXT_ELEMENTS:
            new_node = self._create_node(tag_name, attributes, current_parent, current_context)
            current_parent.append_child(new_node)
            return new_node, 'rawtext'

        # Special handling for option tags
        if tag_name == 'option':
            # Find the nearest option parent
            temp_parent = current_parent
            while temp_parent:
                if temp_parent.tag_name.lower() == 'option':
                    # If there are elements between options, nest it
                    if any(child.tag_name.lower() != 'option' 
                          for child in temp_parent.children):
                        new_node = self._create_node(tag_name, attributes, current_parent, current_context)
                        current_parent.append_child(new_node)
                        return new_node, current_context
                    # Otherwise make it a sibling
                    new_node = self._create_node(tag_name, attributes, temp_parent.parent, current_context)
                    temp_parent.parent.append_child(new_node)
                    return new_node, current_context
                temp_parent = temp_parent.parent

        # Special handling for <table> inside <p>
        if tag_name == 'table' and current_parent.tag_name.lower() == 'p':
            # Create a new <p> as a child of the original <p>
            new_p = Node('p')
            current_parent.append_child(new_p)
            # Create and append table to original <p>
            new_node = self._create_node(tag_name, attributes, current_parent, current_context)
            current_parent.append_child(new_node)
            return new_node, current_context

        # Handle auto-closing first
        current_parent = self._handle_auto_closing(tag_name, current_parent)

        # Then handle foreign elements if enabled
        if self.foreign_handler:
            current_parent, current_context = self.foreign_handler.handle_context(
                tag_name, current_parent, current_context
            )

        # Create node with proper namespace
        new_node = self._create_node(tag_name, attributes, current_parent, current_context)

        # Append the new node to current parent
        current_parent.append_child(new_node)

        # For non-void elements, make the new node the current parent
        if tag_name not in self.VOID_ELEMENTS:
            current_parent = new_node

        return current_parent, current_context

    def _create_node(self, tag_name: str, attributes: dict, 
                    current_parent: Node, current_context: Optional[str]) -> Node:
        """Create a new node with proper namespace handling."""
        if self.foreign_handler:
            return self.foreign_handler.create_node(tag_name, attributes, current_parent, current_context)
        return Node(tag_name.lower(), attributes)

    # Foreign element handling
    def _handle_foreign_elements(self, tag_name: str, current_parent: Node,
                               current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """Handle SVG and other foreign element contexts."""
        tag_name_lower = tag_name.lower()
        
        # Check if we need to break out of SVG context
        if current_context == 'svg':
            # Break out of SVG context for HTML elements, except inside foreignObject
            if tag_name_lower in self.HTML_ELEMENTS:
                # Check if we're inside a foreignObject
                temp_parent = current_parent
                while temp_parent:
                    if temp_parent.tag_name == 'svg foreignObject':
                        # Keep HTML elements inside foreignObject
                        return current_parent, current_context
                    if temp_parent.tag_name == 'body':
                        break
                    temp_parent = temp_parent.parent
                
                # If not in foreignObject, break out to body
                temp_parent = current_parent
                while temp_parent and temp_parent.tag_name.lower() != 'body':
                    temp_parent = temp_parent.parent
                if temp_parent:
                    return temp_parent, None
        
        # Check if we're entering SVG context
        if tag_name_lower == 'svg':
            return current_parent, 'svg'

        # Stay in SVG context
        if current_context == 'svg':
            return current_parent, current_context

        return current_parent, current_context

    # Table handling
    def _handle_table_tag(self, tag_info, current_parent):
        """Handle table tags according to HTML5 foster parenting rules"""
        tag_name = tag_info.tag_name
        attributes = self._parse_attributes(tag_info.attr_string)

        # Special handling for p tags
        if current_parent.tag_name.lower() == 'p':
            # Close the current <p> tag
            original_p = current_parent
            current_parent = current_parent.parent

            # Create a new <p> inside the original <p>
            new_p = Node('p')
            original_p.append_child(new_p)

            # Create the table inside the original <p>
            new_table = Node(tag_name, attributes)
            original_p.append_child(new_table)

            # Return the original <p> as the current context
            return original_p, None

        # Normal table handling
        new_table = Node(tag_name, attributes)
        current_parent.append_child(new_table)
        return new_table, 'table'

    def _find_foster_parent(self, current_parent):
        """Find the appropriate foster parent according to HTML5 spec"""
        # Go up until we find an element that can properly contain a table
        temp_parent = current_parent
        while temp_parent:
            if temp_parent.tag_name.lower() in self.TABLE_CONTAINING_ELEMENTS:
                return temp_parent
            if temp_parent.parent:
                return temp_parent.parent
            temp_parent = temp_parent.parent
        return self.body_node  # Fallback to body if no suitable parent found

    def _handle_closing_tag(self, tag_name: str, current_parent: Node, 
                           current_context: Optional[str]) -> Tuple[Node, Optional[str]]:
        """Handle closing tags with special cases for table voodoo."""
        tag_name_lower = tag_name.lower()

        # Handle foreign elements if enabled
        if self.foreign_handler:
            current_parent, current_context = self.foreign_handler.handle_foreign_end_tag(
                tag_name, current_parent, current_context
            )

        # Special case for </p>
        if tag_name_lower == 'p':
            # Find the original p tag
            original_p = None
            temp_parent = current_parent
            while temp_parent:
                if temp_parent.tag_name.lower() == 'p':
                    original_p = temp_parent
                    break
                temp_parent = temp_parent.parent

            if original_p:
                if current_parent.tag_name.lower() == 'button':
                    # For <p><button></p> case - create new <p> inside button
                    new_p = Node('p')
                    current_parent.append_child(new_p)
                    return new_p, current_context
                elif current_parent.tag_name.lower() == 'table':
                    # For <p><table></p> case - don't create a new p
                    return original_p.parent, current_context
                
            # Normal </p> handling
            return original_p.parent if original_p else current_parent, current_context

        # Normal closing tag handling
        temp_parent = current_parent
        while temp_parent and temp_parent.tag_name.lower() != tag_name_lower:
            temp_parent = temp_parent.parent
        
        if temp_parent:
            return temp_parent.parent, current_context

        return current_parent, current_context

    # Helper methods
    def _handle_text_between_tags(self, text: str, current_parent: Node) -> None:
        """Handle text found between tags."""
        # Special handling for pre tags
        if current_parent.tag_name.lower() == 'pre':
            # Only strip the first newline after <pre>
            if current_parent.children == [] and text.startswith('\n'):
                text = text[1:]
            text_node = Node('#text')
            text_node.text_content = text
            current_parent.append_child(text_node)
            return

        # Special handling for raw text elements
        if current_parent.tag_name.lower() in self.RAW_TEXT_ELEMENTS:
            text_node = Node('#text')
            text_node.text_content = text
            current_parent.append_child(text_node)
            return

        if self.foreign_handler:
            node = self.foreign_handler.handle_text(text, current_parent)
            if node:
                current_parent.append_child(node)
                return

        # Default text handling
        if text:  # Remove the strip() to handle all text
            text_node = Node('#text')
            text_node.text_content = text.strip()  # Only strip when setting content
            if text_node.text_content:  # Only append if there's content after stripping
                current_parent.append_child(text_node)

    def _handle_remaining_text(self, text: str, current_parent: Node) -> None:
        """Handle any remaining text after the last tag."""
        # For annotation-xml, preserve non-empty whitespace
        if current_parent.tag_name == 'math annotation-xml':
            if text:  # Only create text node if there's actual content
                text_node = Node('#text')
                text_node.text_content = text
                current_parent.append_child(text_node)
            return

        # For other elements, strip whitespace as before
        text = text.strip()
        if text:
            text_node = Node('#text')
            text_node.text_content = text
            current_parent.append_child(text_node)

    def _handle_doctype(self, tag_info: "TagInfo") -> None:
        """Handle DOCTYPE declaration."""
        self.has_doctype = True
        doctype_node = Node('!doctype')
        self.root.children.insert(0, doctype_node)  # Insert DOCTYPE as first child

    def _get_ancestors(self, node: Node) -> list[Node]:
        """Helper method to get all ancestors of a node."""
        ancestors = []
        current = node
        while current:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """
        Parse attributes from a string using the ATTR_RE pattern.
        """
        attr_string = attr_string.strip().rstrip('/')
        matches = ATTR_RE.findall(attr_string)
        attributes = {}
        for attr_name, val1, val2, val3 in matches:
            # Depending on which group matched, pick the correct value
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name] = attr_value
        return attributes

    def query(self, selector: str) -> Optional[Node]:
        """Shortcut to query the root node."""
        return self.root.query(selector)

    def _find_next_tag(self, html: str, start_index: int):
        """Find the next HTML tag in the string."""
        return TAG_OPEN_RE.search(html, start_index)

    def _extract_tag_info(self, match) -> tuple[int, int, "TagInfo"]:
        """Extract tag information from a regex match."""
        class TagInfo:
            def __init__(self, is_exclamation, is_closing, tag_name, attr_string):
                self.is_exclamation = is_exclamation
                self.is_closing = is_closing
                self.tag_name = tag_name
                self.attr_string = attr_string
                self.is_doctype = (is_exclamation and tag_name.lower() == 'doctype')

        return (
            match.start(),
            match.end(),
            TagInfo(
                match.group(1) == '!',
                match.group(2) == '/',
                match.group(3),
                match.group(4).strip()
            )
        )

    def _handle_auto_closing(self, tag_name: str, current_parent: Node) -> Node:
        """Handle tags that cause auto-closing of parent tags."""
        tag_name_lower = tag_name.lower()

        # Handle nested nobr tags
        if tag_name_lower == 'nobr':
            nobr_ancestor = next(
                (p for p in self._get_ancestors(current_parent)
                 if p.tag_name.lower() == 'nobr'),
                None
            )
            if nobr_ancestor:
                return nobr_ancestor.parent

        # Special handling for button inside button
        if tag_name_lower == 'button':
            button_ancestor = next(
                (p for p in self._get_ancestors(current_parent)
                 if p.tag_name.lower() == 'button'),
                None
            )
            if button_ancestor:
                return button_ancestor.parent

        # Special handling for option inside option
        if tag_name_lower == 'option':
            option_ancestor = next(
                (p for p in self._get_ancestors(current_parent)
                 if p.tag_name.lower() == 'option'),
                None
            )
            if option_ancestor:
                return option_ancestor.parent

        # Handle other auto-closing cases
        if current_parent.tag_name.lower() == 'p' and tag_name_lower in self.BLOCK_ELEMENTS:
            return current_parent.parent

        return current_parent

    def handle_tag(self, tag_info, current_parent):
        tag_name = tag_info.tag_name.lower()

        if tag_name == 'summary':
            return self._handle_summary_tag(tag_info, current_parent)

        # Existing handling logic for other tags...

    def _handle_summary_tag(self, tag_info, current_parent):
        """Handle summary tags according to HTML5 rules"""
        tag_name = tag_info.tag_name
        attributes = self._parse_attributes(tag_info.attr_string)

        # If the current parent is not a <details>, close the current parent
        while current_parent and current_parent.tag_name.lower() != 'details':
            current_parent = current_parent.parent

        # If no <details> ancestor is found, use the body as the parent
        if not current_parent:
            current_parent = self.root

        # Create the summary node
        new_summary = Node(tag_name, attributes)
        current_parent.append_child(new_summary)

        return new_summary, None

    def _find_descendants(self, node: Node, predicate) -> List[Node]:
        """Find all descendants that match the predicate."""
        results = []
        def _recurse(current):
            if predicate(current):
                results.append(current)
            for child in current.children:
                _recurse(child)
        _recurse(node)
        return results

    def _is_inside_table(self, node: Node) -> bool:
        """Check if the current node is inside a table element."""
        while node:
            if node.tag_name.lower() == 'table':
                return True
            node = node.parent
        return False


# ------------------------------------------------------------------------
# Usage Example (Uncomment and run to see it in action)
# ------------------------------------------------------------------------
if __name__ == "__main__":
    sample_html = """
    <!DOCTYPE html>
    <html>
      <head><title>Test Page</title></head>
      <body>
        <h1 id="main-title" class="title">Hello World</h1>
        <p class="intro">Welcome to this test.</p>
        <img src="image.png" />
        <a href="https://example.com" class="link main-link">Click Here</a>
      </body>
    </html>
    """

    parser = TurboHTML(sample_html)
    # print("Title text:", parser.query('title').text)
    # print("H1 text:", parser.query('h1').text)
    # print("Link href:", parser.query('.main-link')['href'])
    all_links = parser.query_all('.link')
    # print("All link nodes:", all_links)
    # print("Root node representation:", parser.root)
