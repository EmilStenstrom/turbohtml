# JustHTML Documentation

A pure Python HTML5 parser that just works.

## Contents

- **[Quickstart](quickstart.md)** - Get up and running in 5 minutes
- **[API Reference](api.md)** - Complete public API documentation
- **[Command Line](cli.md)** - Use `justhtml` to extract HTML, text, or Markdown
- **[Extracting Text](text.md)** - `to_text()` and `to_markdown()`
- **[CSS Selectors](selectors.md)** - Query elements with familiar CSS syntax
- **[Fragment Parsing](fragments.md)** - Parse HTML fragments in context
- **[Sanitization & Security](sanitization.md)** - Safe-by-default HTML/Markdown output and policy configuration
- **[Streaming](streaming.md)** - Memory-efficient parsing for large files
- **[Encoding & Byte Input](encoding.md)** - How byte streams are decoded (including `windows-1252` fallback)
- **[Error Codes](errors.md)** - Parse error codes and their meanings
- **[Correctness Testing](correctness.md)** - How we verify 100% HTML5 compliance

## Why JustHTML?

| Feature | JustHTML |
|---------|----------|
| HTML5 Compliance | ✅ 100% (passes all 9k+ official tests) |
| Pure Python | ✅ Zero dependencies |
| Query API | ✅ CSS selectors |
| Speed | ⚡ Fastest pure-Python HTML5 parser |

## Quick Example

```python
from justhtml import JustHTML

doc = JustHTML("<html><body><p class='intro'>Hello!</p></body></html>")

# Query with CSS selectors
for p in doc.query("p.intro"):
    print(p.to_html())
```

Output:

```html
<p class="intro">Hello!</p>
```

## A few more examples

### 1) Parse and query

```python
from justhtml import JustHTML

doc = JustHTML("<main><p>Hello</p><p class='x'>World</p></main>")

for p in doc.query("main p.x"):
    print(p.to_html())
```

Output:

```html
<p class="x">World</p>
```

### 2) Extract text or Markdown

```python
from justhtml import JustHTML

doc = JustHTML("<h1>Title</h1><p>Hello <b>world</b></p>")

print("Text:", doc.to_text())
print("Markdown:\n" + doc.to_markdown())
```

Output:

```html
Text: Title Hello world
Markdown:
# Title

Hello **world**
```

### 3) Stream without building a tree

```python
from justhtml import stream

html = "<p>Hello</p><p>world</p>"
for event, data in stream(html):
    if event == "text":
        print(data)
```

Output:

```html
Hello
world
```

Prefer the CLI? See [Command Line](cli.md).

## Installation

```bash
pip install justhtml
```

Requires Python 3.10+.
