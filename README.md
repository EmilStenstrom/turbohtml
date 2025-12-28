# JustHTML

A pure Python HTML5 parser that just works. No C extensions to compile. No system dependencies to install. No complex API to learn.

**[📖 Read the full documentation here](docs/index.md)**

## Why use JustHTML?

### 1. Just... Correct ✅
Spec-perfect HTML5 parsing with browser-grade error recovery — passes the official 9k+ [html5lib-tests](https://github.com/html5lib/html5lib-tests) suite, with 100% line+branch coverage.
Read more: [Correctness](docs/correctness.md)

### 2. Just... Python 🐍
Pure Python, zero dependencies — no C extensions or system libraries, easy to debug, and works anywhere Python runs (including PyPy and Pyodide).
Read more: [Quickstart](docs/quickstart.md)

### 3. Just... Secure 🔒
Safe-by-default output for untrusted HTML — built-in Bleach-style allowlist sanitization on `to_html()` / `to_markdown()` (override with `safe=False`), plus URL/CSS rules.
Read more: [Sanitization & Security](docs/sanitization.md)

### 4. Just... Query 🔍
CSS selectors out of the box — one method (`query()`), familiar syntax (combinators, groups, pseudo-classes), and plain Python nodes as results.
Read more: [CSS Selectors](docs/selectors.md)

### 5. Just... Fast Enough ⚡

If you need to parse terabytes of data, use a C or Rust parser (like `html5ever`). They are 10x-20x faster.

But for most use cases, JustHTML is **fast enough**. It parses the Wikipedia homepage in ~0.1s. It is the fastest pure-Python HTML5 parser available, outperforming `html5lib` and `BeautifulSoup`.

Read more: [Benchmarks](benchmarks/performance.py)

## Comparison to other parsers

| Parser | HTML5 Compliance | Pure Python? | Speed | Query API | Notes |
|--------|:----------------:|:------------:|-------|-----------|-------|
| **JustHTML** | ✅ **100%** | ✅ Yes | ⚡ Fast | ✅ CSS selectors | It just works. Correct, easy to install, and fast enough. |
| `html5lib` | 🟡 88% | ✅ Yes | 🐢 Slow | ❌ None | The reference implementation. Very correct but quite slow. |
| `html5_parser` | 🟡 84% | ❌ No | 🚀 Very Fast | 🟡 XPath (lxml) | C-based (Gumbo). Fast and mostly correct. |
| `selectolax` | 🟡 68% | ❌ No | 🚀 Very Fast | ✅ CSS selectors | C-based (Lexbor). Very fast but less compliant. |
| `BeautifulSoup` | 🔴 4% | ✅ Yes | 🐢 Slow | 🟡 Custom API | Wrapper around `html.parser`. Not spec compliant. |
| `html.parser` | 🔴 4% | ✅ Yes | ⚡ Fast | ❌ None | Standard library. Chokes on malformed HTML. |
| `lxml` | 🔴 1% | ❌ No | 🚀 Very Fast | 🟡 XPath | C-based (libxml2). Fast but not HTML5 compliant. |

*Compliance scores from a strict run of the [html5lib-tests](https://github.com/html5lib/html5lib-tests) tree-construction fixtures (1,743 non-script tests). See `benchmarks/correctness.py` and `docs/correctness.md` for details*.

## Installation

Requires Python 3.10 or later.

```bash
pip install justhtml
```

## Quick Example

```python
from justhtml import JustHTML

doc = JustHTML("<html><body><p class='intro'>Hello!</p></body></html>")

# Query with CSS selectors
for p in doc.query("p.intro"):
    print(p.name)        # "p"
    print(p.attrs)       # {"class": "intro"}
    print(p.to_html())   # <p class="intro">Hello!</p>
```

See the **[Quickstart Guide](docs/quickstart.md)** for more examples including tree traversal, streaming, and strict mode.

## Command Line

If you installed JustHTML (for example with `pip install justhtml` or `pip install -e .`), you can use the `justhtml` command.
If you don't have it available, use the equivalent `python -m justhtml ...` form instead.

```bash
# Pretty-print an HTML file
justhtml index.html

# Parse from stdin
curl -s https://example.com | justhtml -

# Select nodes and output text
justhtml index.html --selector "main p" --format text

# Select nodes and output Markdown (subset of GFM)
justhtml index.html --selector "article" --format markdown

# Select nodes and output HTML
justhtml index.html --selector "a" --format html
```

```bash
# Example: extract Markdown from GitHub README HTML
curl -s https://github.com/EmilStenstrom/justhtml/ | justhtml - --selector '.markdown-body' --format markdown | head -n 15
```

Output:

```text
# JustHTML

[](#justhtml)

A pure Python HTML5 parser that just works. No C extensions to compile. No system dependencies to install. No complex API to learn.

**[📖 Read the full documentation here](/EmilStenstrom/justhtml/blob/main/docs/index.md)**

## Why use JustHTML?

[](#why-use-justhtml)

### 1. Just... Correct ✅

[](#1-just-correct-)

### 3. Just... Secure 🔒
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Acknowledgments

JustHTML started as a Python port of [html5ever](https://github.com/servo/html5ever), the HTML5 parser from Mozilla's Servo browser engine. While the codebase has since evolved significantly, html5ever's clean architecture and spec-compliant approach were invaluable as a starting point. Thank you to the Servo team for their excellent work.

Correctness and conformance work is heavily guided by the [html5lib](https://github.com/html5lib/html5lib-python) ecosystem and especially the official [html5lib-tests](https://github.com/html5lib/html5lib-tests) fixtures used across implementations.

The sanitization API and threat-model expectations are informed by established Python sanitizers like [Bleach](https://github.com/mozilla/bleach) and [nh3](https://github.com/messense/nh3).

The CSS selector query API is inspired by the ergonomics of [lxml.cssselect](https://lxml.de/cssselect.html).

## License

MIT. Free to use both for commercial and non-commercial use.
