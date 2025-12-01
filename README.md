# JustHTML

A pure Python HTML5 parser that just works. No C extensions to compile. No system dependencies to install. No complex API to learn.

## Why us this?

### 1. Just... Correct ✅
It implements the official WHATWG HTML5 specification exactly. If a browser can parse it, JustHTML can parse it. It handles all the complex error-handling rules that browsers use.

- **Verified Compliance**: Passes all 8,500+ tests in the official [html5lib-tests](https://github.com/html5lib/html5lib-tests) suite (used by browser vendors).
- **100% Coverage**: Every single line and branch of code is covered by integration tests.
- **Fuzz Tested**: Has parsed 3 million randomized broken HTML documents to ensure it never crashes or hangs (see benchmarks/fuzz.py).
- **Living Standard**: It tracks the living standard, not a snapshot from 2012.

### 2. Just... Python 🐍
JustHTML has **zero dependencies**. It's pure Python.

- **Just Install**: No C extensions to compile, no system libraries (like libxml2) required. Works on PyPy, WASM (Pyodide) (yes, it's in the test matrix), and anywhere Python runs.
- **No dependency upgrade hassle**: Some libraries depend on a large set of libraries, all which require upgrades to avoid security issues.
- **Debuggable**: It's just Python code. You can step through it with a debugger to understand exactly how your HTML is being parsed.
- **Returns plain python objects**: Other parsers return lxml or etree trees which means you have another API to learn. JustHTML returns a set of nested objects you can iterate over. Simple.

### 3. Just... Fast Enough ⚡

If you need to parse terabytes of data, use a C or Rust parser (like `html5ever`). They are 10x-20x faster.

But for most use cases, JustHTML is **fast enough**. It parses the Wikipedia homepage in ~0.1s. It is the fastest pure-Python HTML5 parser available, outperforming `html5lib` and `BeautifulSoup`.

### Comparison to other parsers

| Parser | Spec Compliant? | Pure Python? | Speed | Notes |
|--------|:---------------:|:------------:|-------|-------|
| **JustHTML** | ✅ Yes | ✅ Yes | ⚡ Fast | It just works. Correct, easy to install, and fast enough. |
| `html.parser` | ❌ No | ✅ Yes | ⚡ Fast | Standard library. Chokes on malformed HTML. |
| `lxml` | ❌ No | ❌ No | 🚀 Very Fast | C-based. Fast but not spec-compliant (different output than browsers). |
| `html5lib` | ✅ Yes | ✅ Yes | 🐢 Slow | The reference implementation. Very correct but quite slow. |
| `BeautifulSoup` | N/A | N/A | 🐢 Slow | Wrapper around other parsers. Slower and more memory hungry than the underlying parser. |
| `gumbo` / `html5ever` | ✅ Yes | ❌ No | 🚀 Very Fast | C/Rust based. Fast and correct, but requires compiling extensions. |

## Installation

Requires Python 3.10 or later.

```bash
pip install justhtml
```

## Example usage

### Python API

```python
from justhtml import JustHTML

html = "<html><body><div id='main'><p>Hello, <b>world</b>!</p></div></body></html>"
doc = JustHTML(html)

# 1. Traverse the tree
# The tree is made of SimpleDomNode objects.
# Each node has .name, .attrs, .children, and .parent
root = doc.root              # #document
html_node = root.children[0] # html
body = html_node.children[1] # body (children[0] is head)
div = body.children[0]       # div

print(f"Tag: {div.name}")
print(f"Attributes: {div.attrs}")

# 2. Pretty-print HTML
# You can serialize any node back to HTML
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

### Command Line Interface

You can also use JustHTML from the command line to pretty-print HTML files:

```bash
# Parse a file
python -m justhtml index.html

# Parse from stdin (great for piping)
curl -s https://example.com | python -m justhtml -
```

## Develop locally and run the tests

1. Clone the repository:
   ```bash
   git clone git@github.com:EmilStenstrom/justhtml.git
   cd justhtml
   ```

2. Install the library locally:
   ```bash
   pip install -e ".[dev]"
   ```

3. Run the tests:
   ```bash
   python run_tests.py
   ```

   For verbose output showing diffs on failures:
   ```bash
   python run_tests.py -v
   ```

4. Run the benchmarks:
   ```bash
   python benchmarks/performance.py
   ```

## License

MIT. Free to use for commercial and non-commercial use.
