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
JustHTML(html, strict=False, collect_errors=False)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `html` | `str` | required | The HTML string to parse |
| `strict` | `bool` | `False` | Raise `StrictModeError` on first parse error |
| `collect_errors` | `bool` | `False` | Collect all parse errors (enables `errors` property) |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `root` | `SimpleDomNode` | The document root node (`#document`) |
| `errors` | `list[ParseError]` | Parse errors (only if `collect_errors=True`) |

### Methods

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

---

## stream

Memory-efficient streaming parser.

```python
from justhtml import stream

for event, data in stream(html):
    ...
```

### Events

| Event | Data | Description |
|-------|------|-------------|
| `"start"` | `(tag_name, attrs_dict)` | Opening tag |
| `"end"` | `tag_name` | Closing tag |
| `"text"` | `text_content` | Text content |
| `"comment"` | `comment_text` | HTML comment |
| `"doctype"` | `doctype_name` | DOCTYPE declaration |

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
