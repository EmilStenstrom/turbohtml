[← Back to docs](index.md)

# API Reference

Complete documentation for the JustHTML public API.

## JustHTML

The main parser class.

```python
from justhtml import JustHTML
```

### Constructor

```python
JustHTML(html, strict=False, collect_errors=False, encoding=None, fragment_context=None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `html` | `str \| bytes \| bytearray \| memoryview` | required | HTML input to parse. Bytes are decoded using HTML encoding sniffing. |
| `strict` | `bool` | `False` | Raise `StrictModeError` on first parse error |
| `collect_errors` | `bool` | `False` | Collect all parse errors (enables `errors` property) |
| `encoding` | `str \| None` | `None` | Transport-supplied encoding label used as an override for byte input. See [Encoding & Byte Input](encoding.md). |
| `fragment_context` | `FragmentContext` | `None` | Parse as fragment inside this context element |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `root` | `SimpleDomNode` | The document root (`#document` or `#document-fragment`) |
| `errors` | `list[ParseError]` | Parse errors (only if `collect_errors=True`) |

### Methods

#### `to_text()`

Return the document's concatenated text.

```python
doc = JustHTML("<p>Hello <b>world</b></p>")
doc.to_text()  # "Hello world"  (separator=" ", strip=True)
```

Parameters:

- `separator` (default: `" "`): join string between text nodes
- `strip` (default: `True`): strip each text node and drop empties

#### `to_markdown()`

Return a pragmatic subset of GitHub Flavored Markdown (GFM).

Tables (`<table>`) and images (`<img>`) are preserved as raw HTML.

```python
doc = JustHTML("<h1>Title</h1><p>Hello <b>world</b></p>")
doc.to_markdown()  # "# Title\n\nHello **world**"
```

#### `query(selector)`

Find all elements matching a CSS selector.

```python
doc.query("div.container > p")  # Returns list of matching nodes
```

---

## SimpleDomNode

Represents an element, text, comment, or document node.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `name` | `str` | Tag name (e.g., `"div"`) or `"#text"`, `"#comment"`, `"#document"` |
| `attrs` | `dict` | Attribute dictionary (empty for non-elements) |
| `children` | `list` | Child nodes |
| `parent` | `SimpleDomNode` | Parent node (or `None` for root) |
| `text` | `str` | Node-local text value. For text nodes this is the node data, otherwise `""`. Use `to_text()` for textContent semantics. |

### Methods

#### `to_html(indent=2)`

Serialize the node to HTML string.

```python
node.to_html()           # Pretty-printed with 2-space indent
node.to_html(indent=0)   # Compact, no indentation
node.to_html(indent=4)   # 4-space indent
```

#### `query(selector)`

Find descendants matching a CSS selector.

```python
div.query("p.intro")  # Search within this node
```

#### `to_text()`

Return the node's concatenated text.

```python
node.to_text()
```

#### `to_markdown()`

Return a pragmatic subset of GitHub Flavored Markdown (GFM) for this subtree.

```python
node.to_markdown()
```

---

## stream

Memory-efficient streaming parser.

```python
from justhtml import stream

for event, data in stream(html):
    ...
```

`stream()` accepts the same input types as `JustHTML`. If you pass bytes, it will decode using HTML encoding sniffing.
To override the encoding for byte input, pass `encoding=...`.

### Events

| Event | Data | Description |
|-------|------|-------------|
| `"start"` | `(tag_name, attrs_dict)` | Opening tag |
| `"end"` | `tag_name` | Closing tag |
| `"text"` | `text_content` | Text content |
| `"comment"` | `comment_text` | HTML comment |
| `"doctype"` | `doctype_name` | DOCTYPE declaration |

---

## FragmentContext

Specifies the context element for fragment parsing. See [Fragment Parsing](fragments.md) for detailed usage.

```python
from justhtml.context import FragmentContext
```

### Constructor

```python
FragmentContext(tag_name, namespace=None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tag_name` | `str` | required | Context element tag name (e.g., `"div"`, `"tbody"`) |
| `namespace` | `str \| None` | `None` | `None` for HTML, `"svg"` for SVG, `"math"` for MathML |

### Example

```python
from justhtml import JustHTML
from justhtml.context import FragmentContext

# Parse table rows in correct context
ctx = FragmentContext("tbody")
doc = JustHTML("<tr><td>cell</td></tr>", fragment_context=ctx)
```

---

## ParseError

Represents a parse error with location information.

```python
from justhtml import ParseError
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `code` | `str` | Error code (e.g., `"eof-in-tag"`) |
| `line` | `int` | Line number (1-indexed) |
| `column` | `int` | Column number (1-indexed) |
| `message` | `str` | Human-readable error message |

### Methods

#### `as_exception()`

Convert to a `SyntaxError` with source highlighting (Python 3.11+).

```python
error.as_exception()  # Returns SyntaxError
```

---

## StrictModeError

Exception raised when parsing with `strict=True`.

```python
from justhtml import StrictModeError
```

Inherits from `SyntaxError`, so it displays source location in tracebacks.

---

## Standalone Functions

### `query(node, selector)`

Query a node without using the method syntax.

```python
from justhtml import query
results = query(doc.root, "div.main")
```

### `matches(node, selector)`

Check if a node matches a selector.

```python
from justhtml import matches
if matches(node, "div.active"):
    ...
```

### `to_html(node, indent=2)`

Serialize a node to HTML.

```python
from justhtml import to_html
html_string = to_html(node)
```

---

## SelectorError

Exception raised for invalid CSS selectors.

```python
from justhtml import SelectorError

try:
    doc.query("div[invalid")
except SelectorError as e:
    print(e)
```
