[← Back to docs](index.md)

# Sanitization & Security

JustHTML includes a built-in, **policy-driven HTML sanitizer** intended for rendering *untrusted HTML safely*.

JustHTML’s sanitizer is validated against the [`justhtml-xss-bench`](https://github.com/EmilStenstrom/justhtml-xss-bench) suite (a headless-browser harness), currently covering **7,000+ real-world XSS vectors**. The benchmark can be used to compare output with established sanitizers like `nh3` and `bleach`.

The sanitizer is **DOM-based** (it runs on the parsed JustHTML tree), and JustHTML is **safe-by-default** when you serialize to HTML or Markdown.

## Quickstart

Most real-world untrusted HTML is a **snippet** (a fragment) rather than a full document. In that case, pass `fragment=True` to avoid implicit document wrappers.

If you *are* sanitizing a full HTML document, safe serialization keeps the document structure (it preserves `<html>`, `<head>`, and `<body>` wrappers by default).

### Safe-by-default serialization

By default, serialization sanitizes:

```python
from justhtml import JustHTML

user_html = '<p>Hello <b>world</b> <script>alert(1)</script> <a href="javascript:alert(1)">bad</a> <a href="https://example.com/?a=1&b=2">ok</a></p>'
doc = JustHTML(user_html, fragment=True)

print(doc.to_html())
print()
print(doc.to_markdown())
```

Output:

```html
<p>Hello <b>world</b>  <a>bad</a> <a href="https://example.com/?a=1&amp;b=2">ok</a></p>

Hello **world** [bad] [ok](https://example.com/?a=1&b=2)
```

### Disable sanitization (only for trusted input)

If you have trusted HTML and want raw output:

```python
from justhtml import JustHTML

user_html = '<p>Hello <b>world</b> <script>alert(1)</script> <a href="javascript:alert(1)">bad</a> <a href="https://example.com/?a=1&b=2">ok</a></p>'
doc = JustHTML(user_html, fragment=True)

print(doc.to_html(safe=False))
print()
print(doc.to_markdown(safe=False))
```

Output:

```html
<p>Hello <b>world</b> <script>alert(1)</script> <a href="javascript:alert(1)">bad</a> <a href="https://example.com/?a=1&amp;b=2">ok</a></p>

Hello **world** alert(1) [bad](javascript:alert(1)) [ok](https://example.com/?a=1&b=2)
```

### Use a custom sanitization policy

```python
from justhtml import JustHTML, SanitizationPolicy, UrlRule

user_html = '<p>Hello <b>world</b> <script>alert(1)</script> <a href="javascript:alert(1)">bad</a> <a href="https://example.com/?a=1&b=2">ok</a></p>'

policy = SanitizationPolicy(
		allowed_tags=["p", "b", "a"],
		allowed_attributes={"*": [], "a": ["href"]},
		url_rules={
				("a", "href"): UrlRule(allowed_schemes=["https"]),
		},
)

doc = JustHTML(user_html, fragment=True)
print(doc.to_html(policy=policy))
```

Output:

```html
<p>Hello <b>world</b>  <a>bad</a> <a href="https://example.com/?a=1&amp;b=2">ok</a></p>
```

You can also sanitize a DOM directly:

```python
from justhtml import JustHTML, sanitize, to_html

user_html = '<p>Hello <b>world</b> <script>alert(1)</script> <a href="javascript:alert(1)">bad</a> <a href="https://example.com/?a=1&b=2">ok</a></p>'
root = JustHTML(user_html, fragment=True).root

clean_root = sanitize(root)
print(to_html(clean_root))
```

Output:

```html
<p>Hello <b>world</b>  <a>bad</a> <a href="https://example.com/?a=1&amp;b=2">ok</a></p>
```

## Threat model (what “safe” means)

In scope:

- Preventing script execution when you sanitize untrusted HTML and then embed the result into an HTML document as markup.

Out of scope (you must handle these separately):

- Using sanitized output in JavaScript string contexts, CSS contexts, URL contexts, or other non-HTML contexts.
- Content security beyond markup execution (e.g. phishing / UI redress).
- Security policies like CSP, sandboxing, and permissions (still recommended for defense-in-depth).

## Default sanitization policy

The built-in default is `DEFAULT_POLICY` (a conservative allowlist).

High-level behavior:

- Disallowed tags are stripped (their children may be kept) but dangerous containers like `script`/`style` have their content dropped.
- Comments and doctypes are dropped.
- Foreign namespaces (SVG/MathML) are dropped.
- Event handlers (`on*`), `srcdoc`, and namespace-style attributes (anything with `:`) are removed.
- Inline styles are disabled by default.

Default allowlists:

- Allowed tags: `a`, `img`, common text/structure tags, headings, lists, and tables (`table`, `thead`, `tbody`, `tfoot`, `tr`, `th`, `td`).
- Allowed attributes:
	- Global: `class`, `id`, `title`, `lang`, `dir`
	- `a`: `href`, `title`
	- `img`: `src`, `alt`, `title`, `width`, `height`, `loading`, `decoding`
	- `th`/`td`: `colspan`, `rowspan`

Default URL rules:

- `a[href]`: allows `http`, `https`, `mailto`, `tel`, plus relative URLs.
- `img[src]`: allows relative URLs only.
- Empty/valueless URL attributes (e.g. `<img src>` / `src=""` / control-only) are dropped.

Example (default image URL behavior):

```python
from justhtml import JustHTML

print(JustHTML('<img src="https://example.com/x" alt="x">').to_html())
print(JustHTML('<img src="/x" alt="x">').to_html())
```

Output:

```html
<img alt="x">
<img src="/x" alt="x">
```

## Proxying URLs (optional)

`UrlRule` can proxy allowed absolute/protocol-relative URLs (for example to centralize tracking protection or enforce allowlists server-side).

```python
from justhtml import JustHTML, SanitizationPolicy, UrlRule

policy = SanitizationPolicy(
		allowed_tags=["a"],
		allowed_attributes={"*": [], "a": ["href"]},
		url_rules={
				("a", "href"): UrlRule(
						allowed_schemes=["https"],
						proxy_url="/proxy",
						proxy_param="url",
				)
		},
)

print(JustHTML('<a href="https://example.com/?a=1&b=2">link</a>').to_html(policy=policy))
```

Output:

```html
<a href="/proxy?url=https%3A%2F%2Fexample.com%2F%3Fa%3D1%26b%3D2">link</a>
```

With proxying enabled, scheme-obfuscation that might be treated as “relative” by the sanitizer but normalized to an absolute URL by a user agent is dropped.

## Inline styles (optional)

Inline styles are disabled by default. To allow them you must:

1) Allow the `style` attribute for the relevant tag via `allowed_attributes`, and
2) Provide a non-empty allowlist via `allowed_css_properties`.

Even then, JustHTML is conservative: it rejects declarations that look like they can load external resources (such as values containing `url(` or `image-set(`), as well as legacy constructs like `expression(`.

```python
from justhtml import JustHTML, SanitizationPolicy

policy = SanitizationPolicy(
		allowed_tags=["p"],
		allowed_attributes={"*": [], "p": ["style"]},
		url_rules={},
		allowed_css_properties={"color", "background-image", "width"},
)

html = '<p style="color: red; background-image: url(https://evil.test/x); width: expression(alert(1));">Hi</p>'
print(JustHTML(html).to_html(policy=policy))
```

Output:

```html
<p style="color: red">Hi</p>
```

## Writing a safe custom policy

When expanding the default policy, prefer adding small, explicit allowlists.

Treat these as a separate security review if you plan to allow them:

- `iframe`, `object`, `embed`
- `meta`, `link`, `base`
- form elements and submission-related attributes
- `srcset` (it contains multiple URLs)

## Defense in depth

Sanitization is one layer. For untrusted HTML, additional defenses are often appropriate:

- Content Security Policy (CSP)
- Sandboxed iframes
- Serving untrusted content from a separate origin

## Reporting issues

If you find a sanitizer bypass, please report it responsibly (see the project’s contributing/security guidance).

## Non-goals

- Guarantee safety for all contexts (e.g., JavaScript strings, CSS contexts, URL contexts).
- Provide a complete browser-grade “content security” solution.
- Support sanitization of `<style>` blocks.
- Support SVG/MathML sanitization by default.
