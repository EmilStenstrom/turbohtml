# JustHTML

A pure Python HTML5 parser that just works. No C extensions to compile. No system dependencies to install. No complex API to learn.

[📖 Full documentation](docs/index.md) | [🛝 Try it in the Playground](https://emilstenstrom.github.io/justhtml/playground/)

## Why use JustHTML?

- **Just... Correct ✅** — Spec-perfect HTML5 parsing with browser-grade error recovery — passes the official 9k+ [html5lib-tests](https://github.com/html5lib/html5lib-tests) suite, with 100% line+branch coverage. ([Correctness](docs/correctness.md))

  ```python
  JustHTML("<p><b>Hello", fragment=True).root.to_html()
  # => <p><b>Hello</b></p>
  ```

- **Just... Python 🐍** — Pure Python, zero dependencies — no C extensions or system libraries, easy to debug, and works anywhere Python runs (including PyPy and Pyodide). ([Quickstart](docs/quickstart.md))

  ```bash
  python -m pip show justhtml | grep -E '^Requires:'
  # Requires: [intentionally left blank]
  ```

- **Just... Secure 🔒** — Safe-by-default output for untrusted HTML — built-in Bleach-style allowlist sanitization on `to_html()` / `to_markdown()` (override with `safe=False`), plus URL/CSS rules. ([Sanitization & Security](docs/sanitization.md))

  ```python
  JustHTML(
      "<p>Hello<script>alert(1)</script> "
      "<a href=\"javascript:alert(1)\">bad</a> "
      "<a href=\"https://example.com/?a=1&b=2\">ok</a></p>",
      fragment=True,
  ).root.to_html()
  # => <p>Hello <a>bad</a> <a href="https://example.com/?a=1&amp;b=2">ok</a></p>
  ```

- **Just... Query 🔍** — CSS selectors out of the box — one method (`query()`), familiar syntax (combinators, groups, pseudo-classes), and plain Python nodes as results. ([CSS Selectors](docs/selectors.md))

  ```python
  JustHTML(
      "<main><p class=\"x\">Hi</p><p>Bye</p></main>",
      fragment=True,
  ).query("main p.x")[0].to_html()
  # => <p class="x">Hi</p>
  ```

- **Just... Fast Enough ⚡** — Fast for the common case (fastest pure-Python HTML5 parser available); for terabytes, use a C/Rust parser like `html5ever`. ([Benchmarks](benchmarks/performance.py))

  ```bash
  TIMEFORMAT='%3R s' time curl -Ls https://en.wikipedia.org/wiki/HTML \
    | python -m justhtml - > /dev/null
  # 0.365 s
  ```

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


*Compliance scores from a strict run of the [html5lib-tests](https://github.com/html5lib/html5lib-tests) tree-construction fixtures (1,743 non-script tests). See [benchmarks/correctness.py](benchmarks/correctness.py) and [docs/correctness.md](docs/correctness.md) for details*.

Browser engine agreement (tree-construction, pass/(pass+fail), 2025-12-30):

| Engine | Tests Passed | Agreement | Notes |
|--------|-------------|-----------|-------|
| Chromium | 1763/1770 | 99.6% | DOMParser / contextual fragment (via Playwright) |
| WebKit | 1741/1770 | 98.4% | DOMParser / contextual fragment (via Playwright) |
| Firefox | 1727/1770 | 97.6% | DOMParser / contextual fragment (via Playwright) |

*Browser numbers from [`justhtml-html5lib-tests-bench`](https://github.com/EmilStenstrom/justhtml-html5lib-tests-bench) on the upstream `html5lib-tests/tree-construction` corpus (excluding 12 scripting-enabled cases).*


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

- **Just... Correct ✅** — Spec-perfect HTML5 parsing with browser-grade error recovery — passes the official 9k+ [html5lib-tests](https://github.com/html5lib/html5lib-tests) suite, with 100% line+branch coverage. ([Correctness](/EmilStenstrom/justhtml/blob/main/docs/correctness.md))
- **Just... Python 🐍** — Pure Python, zero dependencies — no C extensions or system libraries, easy to debug, and works anywhere Python runs (including PyPy and Pyodide). ([Quickstart](/EmilStenstrom/justhtml/blob/main/docs/quickstart.md))
- **Just... Secure 🔒** — Safe-by-default output for untrusted HTML — built-in Bleach-style allowlist sanitization on `to_html()` / `to_markdown()` (override with `safe=False`), plus URL/CSS rules. ([Sanitization & Security](/EmilStenstrom/justhtml/blob/main/docs/sanitization.md))
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
