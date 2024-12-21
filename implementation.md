Certainly! Structuring your HTML5 parser effectively is crucial for maintainability, scalability, and adherence to the WHATWG HTML5 specification. Below is a suggested code structure that aligns with your **Design Goals** outlined in `architecture.md`. This structure organizes the parser into modular components, each responsible for a specific aspect of the parsing process.

## Proposed Code Structure

```
turbohtml/
├── turbohtml/
│   ├── __init__.py
│   ├── parser.py
│   ├── tokenizer.py
│   ├── tree_builder.py
│   ├── node.py
│   ├── query.py
│   ├── utils.py
│   ├── constants.py
│   └── errors.py
├── tests/
│   ├── test_parser.py
│   ├── test_tokenizer.py
│   ├── test_tree_builder.py
│   ├── test_query.py
│   └── ...
├── cython/
│   ├── tokenizer_cy.pyx
│   ├── tree_builder_cy.pyx
│   └── setup.py
├── README.md
├── requirements.txt
└── setup.py
```

### 1. **Module Breakdown**

#### `turbohtml/__init__.py`
Initialize the package and expose the main `TurboHTML` class.

```python
from .parser import TurboHTML

__all__ = ['TurboHTML']
```

#### `turbohtml/constants.py`
Define all constant sets and configurations to maintain readability and ease of updates.

```python
from typing import Set

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

AUTO_CLOSING_TRIGGERS: Set[str] = {
    'address', 'article', 'aside', 'blockquote', 'details', 'div', 'dl',
    'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'header', 'hr', 'main', 'nav', 'ol', 'p', 'pre',
    'section', 'table', 'ul'
}

SELF_CLOSING_ELEMENTS: Set[str] = {
    'button', 'a', 'select', 'textarea', 'option', 'optgroup'
}
```

#### `turbohtml/errors.py`
Define custom exceptions and error handling mechanisms.

```python
class ParsingError(Exception):
    """Base class for parsing-related errors."""
    pass

class UnexpectedTagError(ParsingError):
    """Raised when an unexpected tag is encountered."""
    def __init__(self, message: str, position: tuple):
        super().__init__(f"{message} at position {position}")
        self.position = position
```

#### `turbohtml/node.py`
Implement the `Node` class representing each element in the DOM tree.

```python
from typing import List, Dict, Optional

class Node:
    def __init__(self, tag_name: str, attributes: Optional[Dict[str, str]] = None, parent: Optional['Node'] = None):
        self.tag_name = tag_name
        self.attributes = attributes or {}
        self.children: List['Node'] = []
        self.text_content: str = ""
        self.parent = parent

    def append_child(self, child: 'Node') -> None:
        child.parent = self
        self.children.append(child)

    def __getitem__(self, attr: str) -> Optional[str]:
        return self.attributes.get(attr)

    def query(self, selector: str) -> Optional['Node']:
        # Simplified selector matching
        if selector.startswith('#'):
            return self._query_by_id(selector[1:])
        elif selector.startswith('.'):
            return self._query_by_class(selector[1:])
        else:
            return self._query_by_tag(selector)

    def query_all(self, selector: str) -> List['Node']:
        matches = []
        if selector.startswith('#'):
            matches = self._query_all_by_id(selector[1:])
        elif selector.startswith('.'):
            matches = self._query_all_by_class(selector[1:])
        else:
            matches = self._query_all_by_tag(selector)
        return matches

    def _query_by_id(self, id_value: str) -> Optional['Node']:
        if self.attributes.get('id') == id_value:
            return self
        for child in self.children:
            result = child._query_by_id(id_value)
            if result:
                return result
        return None

    def _query_all_by_id(self, id_value: str) -> List['Node']:
        results = []
        if self.attributes.get('id') == id_value:
            results.append(self)
        for child in self.children:
            results.extend(child._query_all_by_id(id_value))
        return results

    def _query_by_class(self, class_value: str) -> Optional['Node']:
        classes = self.attributes.get('class', '').split()
        if class_value in classes:
            return self
        for child in self.children:
            result = child._query_by_class(class_value)
            if result:
                return result
        return None

    def _query_all_by_class(self, class_value: str) -> List['Node']:
        results = []
        classes = self.attributes.get('class', '').split()
        if class_value in classes:
            results.append(self)
        for child in self.children:
            results.extend(child._query_all_by_class(class_value))
        return results

    def _query_by_tag(self, tag_name: str) -> Optional['Node']:
        if self.tag_name.lower() == tag_name.lower():
            return self
        for child in self.children:
            result = child._query_by_tag(tag_name)
            if result:
                return result
        return None

    def _query_all_by_tag(self, tag_name: str) -> List['Node']:
        results = []
        if self.tag_name.lower() == tag_name.lower():
            results.append(self)
        for child in self.children:
            results.extend(child._query_all_by_tag(tag_name))
        return results

    @property
    def text(self) -> str:
        return self._get_text()

    def _get_text(self) -> str:
        texts = [self.text_content]
        for child in self.children:
            texts.append(child._get_text())
        return ''.join(texts)
```

#### `turbohtml/tokenizer.py`
Implement the `Tokenizer` class based on the HTML5 specification, potentially optimized with Cython or Rust.

```python
import re
from typing import Optional, Tuple
from .constants import VOID_ELEMENTS, SELF_CLOSING_ELEMENTS

class Token:
    def __init__(self, type_: str, data: Optional[str] = None, attributes: Optional[dict] = None):
        self.type = type_
        self.data = data
        self.attributes = attributes or {}

class Tokenizer:
    def __init__(self, html: str):
        self.html = html
        self.position = 0
        self.length = len(html)
        self.tokens = []
        self._tokenize()

    def _tokenize(self) -> None:
        tag_re = re.compile(r'<(/?)(\w+)([^>]*)>', re.ASCII)
        pos = 0
        while pos < self.length:
            match = tag_re.search(self.html, pos)
            if not match:
                # Text token
                data = self.html[pos:].strip()
                if data:
                    self.tokens.append(Token(type_='text', data=data))
                break
            start, end = match.span()
            if start > pos:
                # Text before the tag
                data = self.html[pos:start].strip()
                if data:
                    self.tokens.append(Token(type_='text', data=data))
            is_closing, tag_name, attr_string = match.groups()
            if is_closing:
                self.tokens.append(Token(type_='end_tag', data=tag_name.lower()))
            else:
                attributes = self._parse_attributes(attr_string)
                type_ = 'self_closing_tag' if tag_name.lower() in VOID_ELEMENTS or attr_string.strip().endswith('/') else 'start_tag'
                self.tokens.append(Token(type_=type_, data=tag_name.lower(), attributes=attributes))
            pos = end

    def _parse_attributes(self, attr_string: str) -> dict:
        attr_re = re.compile(r'(\w+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+)))?')
        attributes = {}
        for match in attr_re.finditer(attr_string):
            attr_name, val1, val2, val3 = match.groups()
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name.lower()] = attr_value
        return attributes

    def next_token(self) -> Optional[Token]:
        if self.position < len(self.tokens):
            token = self.tokens[self.position]
            self.position += 1
            return token
        return None
```

#### `turbohtml/tree_builder.py`
Implement the `TreeBuilder` class that constructs the DOM tree from tokens.

```python
from typing import Optional, Tuple
from .node import Node
from .tokenizer import Token, Tokenizer
from .constants import HTML_ELEMENTS, AUTO_CLOSING_TRIGGERS, SELF_CLOSING_ELEMENTS
from .errors import ParsingError, UnexpectedTagError

class TreeBuilder:
    def __init__(self, tokenizer: Tokenizer):
        self.tokenizer = tokenizer
        self.root = Node('document')
        self.current_parent = self.root
        self.open_elements_stack = [self.root]

    def build_tree(self) -> Node:
        while True:
            token = self.tokenizer.next_token()
            if not token:
                break
            self._process_token(token)
        return self.root

    def _process_token(self, token: Token) -> None:
        if token.type == 'start_tag':
            self._handle_start_tag(token)
        elif token.type == 'end_tag':
            self._handle_end_tag(token)
        elif token.type == 'text':
            self._handle_text(token)
        elif token.type == 'self_closing_tag':
            self._handle_self_closing_tag(token)
        else:
            raise ParsingError(f"Unknown token type: {token.type}")

    def _handle_start_tag(self, token: Token) -> None:
        tag_name = token.data
        attributes = token.attributes
        # Handle auto-closing of certain tags
        if tag_name in AUTO_CLOSING_TRIGGERS:
            self._close_auto_closing_tags(tag_name)
        # Create new node
        new_node = Node(tag_name, attributes)
        self.current_parent.append_child(new_node)
        # Update current parent
        if tag_name not in SELF_CLOSING_ELEMENTS and tag_name not in VOID_ELEMENTS:
            self.open_elements_stack.append(new_node)
            self.current_parent = new_node

    def _handle_end_tag(self, token: Token) -> None:
        tag_name = token.data
        # Find the most recent ancestor with the same tag name
        for i in range(len(self.open_elements_stack)-1, -1, -1):
            node = self.open_elements_stack[i]
            if node.tag_name == tag_name:
                # Pop elements from the stack
                while len(self.open_elements_stack) > i + 1:
                    self.open_elements_stack.pop()
                self.current_parent = self.open_elements_stack[-1]
                return
        # If not found, raise an error or ignore based on spec
        raise UnexpectedTagError(f"Unexpected end tag: </{tag_name}>", (0, 0))

    def _handle_text(self, token: Token) -> None:
        text = token.data
        if self.current_parent.text_content:
            self.current_parent.text_content += " " + text
        else:
            self.current_parent.text_content = text

    def _handle_self_closing_tag(self, token: Token) -> None:
        tag_name = token.data
        attributes = token.attributes
        new_node = Node(tag_name, attributes)
        self.current_parent.append_child(new_node)
        # Self-closing tags do not change the current parent

    def _close_auto_closing_tags(self, tag_name: str) -> None:
        while self.open_elements_stack and self.open_elements_stack[-1].tag_name in AUTO_CLOSING_TRIGGERS:
            self.open_elements_stack.pop()
            self.current_parent = self.open_elements_stack[-1]
```

#### `turbohtml/tokenizer_cy.pyx` (Cython Optimization)
Optimize the tokenizer using Cython for performance-critical tasks.

```cython
# cython: language_level=3
import re
cdef class FastTokenizer:
    def __init__(self, html: str):
        self.html = html
        self.tokens = []
        self._tokenize()

    cpdef _tokenize(self):
        cdef re.Pattern tag_re = re.compile(r'<(/?)(\w+)([^>]*)>', re.ASCII)
        cdef int pos = 0
        cdef int start, end
        cdef re.Match match
        while pos < len(self.html):
            match = tag_re.search(self.html, pos)
            if not match:
                data = self.html[pos:].strip()
                if data:
                    self.tokens.append(('text', data, {}))
                break
            start, end = match.span()
            if start > pos:
                data = self.html[pos:start].strip()
                if data:
                    self.tokens.append(('text', data, {}))
            is_closing = match.group(1) == '/'
            tag_name = match.group(2).lower()
            attr_string = match.group(3)
            if is_closing:
                self.tokens.append(('end_tag', tag_name, {}))
            else:
                attributes = self._parse_attributes(attr_string)
                type_ = 'self_closing_tag' if tag_name in VOID_ELEMENTS or attr_string.strip().endswith('/') else 'start_tag'
                self.tokens.append((type_, tag_name, attributes))
            pos = end

    cpdef dict _parse_attributes(self, str attr_string):
        cdef dict attributes = {}
        cdef re.Pattern attr_re = re.compile(r'(\w+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+)))?')
        for match in attr_re.finditer(attr_string):
            attr_name, val1, val2, val3 = match.groups()
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name.lower()] = attr_value
        return attributes

    cpdef tuple next_token(self):
        if pos < len(self.tokens):
            token = self.tokens[self.position]
            self.position += 1
            return token
        return None
```

#### `turbohtml/parser.py`
Integrate the `Tokenizer` and `TreeBuilder` to provide a seamless parsing experience.

```python
from .tokenizer import Tokenizer
from .tree_builder import TreeBuilder
from .node import Node

class TurboHTML:
    def __init__(self, html: str, handle_foreign_elements: bool = True):
        """
        Initialize the HTML parser.

        Args:
            html: The HTML string to parse
            handle_foreign_elements: Whether to handle SVG/MathML elements
        """
        self.html = html
        self.handle_foreign_elements = handle_foreign_elements
        self.has_doctype = False

        # Initialize Tokenizer
        self.tokenizer = Tokenizer(html)

        # Initialize TreeBuilder
        self.tree_builder = TreeBuilder(self.tokenizer)

        # Build the DOM tree
        self.root = self.tree_builder.build_tree()

    def query(self, selector: str) -> Optional[Node]:
        """Return the first node matching the selector."""
        return self.root.query(selector)

    def query_all(self, selector: str) -> list[Node]:
        """Return all nodes matching the selector."""
        return self.root.query_all(selector)

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"
```

#### `turbohtml/query.py`
Implement advanced querying capabilities, potentially leveraging optimized Cython/Rust components.

```python
from typing import List
from .node import Node

class QueryEngine:
    def __init__(self, root: Node):
        self.root = root

    def query(self, selector: str) -> Optional[Node]:
        return self.root.query(selector)

    def query_all(self, selector: str) -> List[Node]:
        return self.root.query_all(selector)

    # Additional methods for complex selectors can be added here
```

#### `turbohtml/utils.py`
Utility functions and helpers to support various parser operations.

```python
from typing import Optional

def normalize_whitespace(text: str) -> str:
    """Normalize whitespace by collapsing multiple spaces into one."""
    return ' '.join(text.split())

def escape_html(text: str) -> str:
    """Escape special HTML characters in text."""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#039;"))
```

### 2. **Cython Optimization Strategy**

To achieve the **Small and Fast** goal, critical components such as the `Tokenizer` and parts of the `TreeBuilder` can be optimized using Cython. Here's how you can structure and integrate these optimizations:

#### `cython/tokenizer_cy.pyx`
Optimize the tokenizer with Cython for faster parsing.

```cython
# cython: language_level=3
import re
from libc.stdlib cimport malloc, free
from libcpp.string cimport string

cdef class CythonTokenizer:
    def __init__(self, html: str):
        self.html = html
        self.tokens = []
        self._tokenize()

    cdef void _tokenize(self):
        cdef str tag_re_pattern = r'<(/?)(\w+)([^>]*)>'
        cdef re.Pattern tag_re = re.compile(tag_re_pattern, re.ASCII)
        cdef int pos = 0
        cdef re.Match match
        while pos < len(self.html):
            match = tag_re.search(self.html, pos)
            if not match:
                data = self.html[pos:].strip()
                if data:
                    self.tokens.append(('text', data, {}))
                break
            start, end = match.span()
            if start > pos:
                data = self.html[pos:start].strip()
                if data:
                    self.tokens.append(('text', data, {}))
            is_closing = match.group(1) == '/'
            tag_name = match.group(2).lower()
            attr_string = match.group(3)
            if is_closing:
                self.tokens.append(('end_tag', tag_name, {}))
            else:
                attributes = self._parse_attributes(attr_string)
                type_ = 'self_closing_tag' if tag_name in VOID_ELEMENTS or attr_string.strip().endswith('/') else 'start_tag'
                self.tokens.append((type_, tag_name, attributes))
            pos = end

    cdef dict _parse_attributes(self, str attr_string):
        cdef dict attributes = {}
        cdef re.Pattern attr_re = re.compile(r'(\w+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+)))?')
        cdef re.Match match
        for match in attr_re.finditer(attr_string):
            attr_name, val1, val2, val3 = match.groups()
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name.lower()] = attr_value
        return attributes

    cpdef tuple next_token(self):
        if self.position < len(self.tokens):
            token = self.tokens[self.position]
            self.position += 1
            return token
        return None
```

#### `cython/setup.py`
Setup script to compile Cython modules.

```python
from setuptools import setup
from Cython.Build import cythonize

setup(
    name='turbohtml_cython',
    ext_modules=cythonize(["turbohtml/cython/tokenizer_cy.pyx", "turbohtml/cython/tree_builder_cy.pyx"]),
    zip_safe=False,
)
```

### 3. **Handling Foreign Content (SVG/MathML)**

Ensure that your `TreeBuilder` correctly handles foreign content by integrating context-aware parsing. You might consider separating foreign content handling into its own module for clarity.

#### `turbohtml/foreign_content.py`
Handle foreign elements like SVG and MathML.

```python
from typing import Optional, Tuple
from .node import Node
from .constants import HTML_ELEMENTS

class ForeignContentHandler:
    def __init__(self):
        pass

    def handle_foreign_start_tag(self, tag_name: str, current_parent: Node, context: Optional[str]) -> Tuple[Node, Optional[str]]:
        tag_name_lower = tag_name.lower()
        if tag_name_lower == 'svg':
            return current_parent, 'svg'
        # Add handling for MathML if needed
        return current_parent, context

    def handle_foreign_end_tag(self, tag_name: str, current_parent: Node, context: Optional[str]) -> Tuple[Node, Optional[str]]:
        tag_name_lower = tag_name.lower()
        if tag_name_lower == 'svg' and context == 'svg':
            return current_parent.parent, None
        # Add handling for MathML if needed
        return current_parent, context

    def exit_foreign_content(self, tag_name: str, current_parent: Node, context: Optional[str]) -> Tuple[Node, Optional[str]]:
        if context == 'svg' and tag_name in HTML_ELEMENTS:
            # Traverse up to find the root SVG element
            svg_root = current_parent
            while svg_root and not svg_root.tag_name.startswith('svg'):
                svg_root = svg_root.parent
            if svg_root and svg_root.parent:
                return svg_root.parent, None
        return current_parent, context
```

### 4. **Enhanced Query Methods**

Implement a more robust query engine to support complex CSS selectors. This can be integrated into the `query.py` module.

```python
from typing import List, Optional
from .node import Node

class QueryEngine:
    def __init__(self, root: Node):
        self.root = root

    def query(self, selector: str) -> Optional[Node]:
        """Return the first node matching the selector."""
        parser = SelectorParser(selector)
        return parser.find_first(self.root)

    def query_all(self, selector: str) -> List[Node]:
        """Return all nodes matching the selector."""
        parser = SelectorParser(selector)
        return parser.find_all(self.root)

class SelectorParser:
    def __init__(self, selector: str):
        self.selector = selector
        # Implement parsing logic here

    def find_first(self, root: Node) -> Optional[Node]:
        """Find the first matching node."""
        # Implement search logic here
        pass

    def find_all(self, root: Node) -> List[Node]:
        """Find all matching nodes."""
        # Implement search logic here
        pass
```

### 5. **Parser Integration and Error Handling**

Ensure that the `TurboHTML` parser gracefully handles errors and integrates all components seamlessly.

```python
from .tokenizer import Tokenizer
from .tree_builder import TreeBuilder
from .node import Node
from .foreign_content import ForeignContentHandler
from .errors import ParsingError

class TurboHTML:
    def __init__(self, html: str, handle_foreign_elements: bool = True):
        """
        Initialize the HTML parser.

        Args:
            html: The HTML string to parse
            handle_foreign_elements: Whether to handle SVG/MathML elements
        """
        self.html = html
        self.handle_foreign_elements = handle_foreign_elements
        self.has_doctype = False

        # Initialize Tokenizer
        self.tokenizer = Tokenizer(html)

        # Initialize Foreign Content Handler
        self.foreign_handler = ForeignContentHandler()

        # Initialize TreeBuilder
        self.tree_builder = TreeBuilder(self.tokenizer, self.foreign_handler)

        # Build the DOM tree
        try:
            self.root = self.tree_builder.build_tree()
        except ParsingError as e:
            # Handle parsing errors or log them
            print(f"Parsing Error: {e}")
            self.root = Node('document')  # Fallback to an empty document

    def query(self, selector: str) -> Optional[Node]:
        """Return the first node matching the selector."""
        return self.root.query(selector)

    def query_all(self, selector: str) -> list[Node]:
        """Return all nodes matching the selector."""
        return self.root.query_all(selector)

    def __repr__(self) -> str:
        return f"<TurboHTML root={self.root}>"
```

### 6. **Testing and Validation**

Place all your test cases in the `tests/` directory, ensuring comprehensive coverage of the HTML5 specification.

#### `tests/test_parser.py`
Example test case using `unittest`.

```python
import unittest
from turbohtml import TurboHTML
from turbohtml.node import Node

class TestTurboHTMLParser(unittest.TestCase):
    def test_simple_parsing(self):
        html = "<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Hello World</h1></body></html>"
        parser = TurboHTML(html)
        title = parser.query('title')
        self.assertIsNotNone(title)
        self.assertEqual(title.text, "Test")
        header = parser.query('h1')
        self.assertIsNotNone(header)
        self.assertEqual(header.text, "Hello World")

    def test_nested_elements(self):
        html = "<div><p>Paragraph <span>with span</span></p></div>"
        parser = TurboHTML(html)
        span = parser.query('span')
        self.assertIsNotNone(span)
        self.assertEqual(span.text, "with span")

    def test_malformed_html(self):
        html = "<div><p>Unclosed div"
        parser = TurboHTML(html)
        div = parser.query('div')
        self.assertIsNotNone(div)
        self.assertEqual(len(div.children), 1)
        p = div.query('p')
        self.assertIsNotNone(p)
        self.assertEqual(p.text, "Unclosed div")

if __name__ == '__main__':
    unittest.main()
```

## Additional Recommendations

1. **Documentation**:
   - Maintain comprehensive docstrings for all classes and methods.
   - Update `README.md` with usage examples and installation instructions.

2. **Performance Optimization**:
   - Profile the parser to identify bottlenecks.
   - Optimize the most frequently called methods using Cython or Rust.
   - Consider using generator-based tokenization to handle streaming data.

3. **Error Reporting**:
   - Implement detailed error reporting aligned with the HTML5 spec.
   - Allow users to access a list of parsing errors post-parsing.

4. **Extensibility**:
   - Design the parser to be easily extensible for supporting additional features like CSS parsing or JavaScript execution in the future.

5. **Asynchronous Parsing**:
   - Implement asynchronous parsing to handle large or streaming HTML content efficiently.

6. **Continuous Testing**:
   - Integrate your test suite with Continuous Integration (CI) tools to ensure ongoing compliance with the HTML5 specification as the parser evolves.

By following this structured approach, you can develop a robust, efficient, and compliant HTML5 parser that meets your project's goals. Let me know if you need further assistance with specific modules or implementation details!