# JustHTML

A pure Python HTML5 parser that just works. No C extensions to compile. No system dependencies to install. No complex API to learn.

**[📖 Read the full documentation here](docs/index.md)**

## Why use JustHTML?

### 1. Just... Correct ✅
It implements the official WHATWG HTML5 specification exactly. If a browser can parse it, JustHTML can parse it. It handles all the complex error-handling rules that browsers use.

- **Verified Compliance**: Passes all 9,200+ tests in the official [html5lib-tests](https://github.com/html5lib/html5lib-tests) suite (used by browser vendors).
- **100% Coverage**: Every line and branch of code is covered by integration tests.
- **Fuzz Tested**: Has parsed 6 million randomized broken HTML documents to ensure it never crashes or hangs (see benchmarks/fuzz.py).
- **Living Standard**: It tracks the living standard, not a snapshot from 2012.

### 2. Just... Python 🐍
JustHTML has **zero dependencies**. It's pure Python.

- **Just Install**: No C extensions to compile, no system libraries (like libxml2) required. Works on PyPy, WASM (Pyodide) (yes, it's in the test matrix), and anywhere Python runs.
- **No dependency upgrade hassle**: Some libraries depend on a large set of libraries, all which require upgrades to avoid security issues.
- **Debuggable**: It's just Python code. You can step through it with a debugger to understand exactly how your HTML is being parsed.
- **Returns plain python objects**: Other parsers return lxml or etree trees which means you have another API to learn. JustHTML returns a set of nested objects you can iterate over. Simple.

### 3. Just... Query 🔍
Find elements with CSS selectors. Just one method to learn - `query()` - and it uses CSS syntax you already know.

```python
doc.query("div.container > p.intro")  # Familiar CSS syntax
doc.query("#main, .sidebar")          # Selector groups
doc.query("li:nth-child(2n+1)")       # Pseudo-classes
```

### 4. Just... Fast Enough ⚡

If you need to parse terabytes of data, use a C or Rust parser (like `html5ever`). They are 10x-20x faster.

But for most use cases, JustHTML is **fast enough**. It parses the Wikipedia homepage in ~0.1s. It is the fastest pure-Python HTML5 parser available, outperforming `html5lib` and `BeautifulSoup`.

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

*Compliance scores from running the [html5lib-tests](https://github.com/html5lib/html5lib-tests) suite (1,743 tree-construction tests). See `benchmarks/correctness.py`.*

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
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Acknowledgments

JustHTML started as a Python port of [html5ever](https://github.com/servo/html5ever), the HTML5 parser from Mozilla's Servo browser engine. While the codebase has since evolved significantly, html5ever's clean architecture and spec-compliant approach were invaluable as a starting point. Thank you to the Servo team for their excellent work.

## License

MIT. Free to use both for commercial and non-commercial use.
