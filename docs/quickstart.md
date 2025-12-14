[← Back to docs](index.md)

# Quickstart

Get up and running with JustHTML in 5 minutes.

## Installation

```bash
pip install justhtml
```

## Basic Parsing

```python
from justhtml import JustHTML

html = "<html><body><div id='main'><p>Hello, <b>world</b>!</p></div></body></html>"
doc = JustHTML(html)
```

## Parsing Bytes (Encoding Sniffing)

If you pass bytes (for example from a file), JustHTML decodes them using HTML encoding sniffing. If no encoding is found, it falls back to `windows-1252` for browser compatibility.

```python
from justhtml import JustHTML
from pathlib import Path

data = Path("page.html").read_bytes()
doc = JustHTML(data)
print(doc.encoding)
```

See [Encoding & Byte Input](encoding.md) for details and how to override with `encoding=...`.

## Traversing the Tree

The parser returns a tree of `SimpleDomNode` objects:

```python
root = doc.root              # #document
html_node = root.children[0] # <html>
body = html_node.children[1] # <body> (children[0] is <head>)
div = body.children[0]       # <div>

# Each node has:
print(div.name)       # "div"
print(div.attrs)      # {"id": "main"}
print(div.children)   # [<p> node]
print(div.parent)     # <body> node
```

## Querying with CSS Selectors

Use familiar CSS syntax to find elements:

```python
# Find all paragraphs
paragraphs = doc.query("p")

# Find by ID
main_div = doc.query("#main")[0]

# Complex selectors
links = doc.query("nav > ul li a.active")

# Multiple selectors
headings = doc.query("h1, h2, h3")
```

## Serializing to HTML

Convert any node back to HTML:

```python
print(div.to_html())
# Output:
# <div id="main">
#   <p>
#     Hello,
#     <b>world</b>
#     !
#   </p>
# </div>
```

## Strict Mode

Reject malformed HTML instead of silently fixing it:

```python
from justhtml import JustHTML, StrictModeError

try:
    doc = JustHTML("<html><p>Unclosed", strict=True)
except StrictModeError as e:
    print(e)
# Output (Python 3.11+):
#   File "<html>", line 1
#     <html><p>Unclosed
#                      ^
# StrictModeError: Expected closing tag </p> but reached end of file
```

## Streaming API

For large files or when you don't need the full DOM:

```python
from justhtml import stream

for event, data in stream(html):
    if event == "start":
        tag, attrs = data
        print(f"Start: {tag}")
    elif event == "text":
        print(f"Text: {data}")
    elif event == "end":
        print(f"End: {data}")
```

## Next Steps

- [API Reference](api.md) - Complete API documentation
- [CSS Selectors](selectors.md) - All supported selectors
- [Error Codes](errors.md) - Understanding parse errors
