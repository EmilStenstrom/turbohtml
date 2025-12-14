# JustHTML Documentation

A pure Python HTML5 parser that just works.

## Contents

- **[Quickstart](quickstart.md)** - Get up and running in 5 minutes
- **[API Reference](api.md)** - Complete public API documentation
- **[Extracting Text](text.md)** - `to_text()` and `to_markdown()`
- **[CSS Selectors](selectors.md)** - Query elements with familiar CSS syntax
- **[Fragment Parsing](fragments.md)** - Parse HTML fragments in context
- **[Streaming](streaming.md)** - Memory-efficient parsing for large files
- **[Encoding & Byte Input](encoding.md)** - How byte streams are decoded (including `windows-1252` fallback)
- **[Error Codes](errors.md)** - Parse error codes and their meanings
- **[Correctness Testing](correctness.md)** - How we verify 100% HTML5 compliance

## Why JustHTML?

| Feature | JustHTML |
|---------|----------|
| HTML5 Compliance | ✅ 100% (passes all 9,200+ official tests) |
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

## Installation

```bash
pip install justhtml
```

Requires Python 3.10+.
