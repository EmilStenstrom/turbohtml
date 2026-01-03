[← Back to docs](index.md)

# URL Cleaning

This page focuses on **URL cleaning**: how JustHTML validates and rewrites URL-valued attributes like `a[href]`, `img[src]`, and `img[srcset]`.

For tag/attribute allowlists, inline styles, and unsafe-handling modes, see [HTML Cleaning](html-cleaning.md).

## Key idea: URL-like attributes require explicit rules

JustHTML treats a set of attributes as *URL-like* (including `href`, `src`, `srcset`, `poster`, `action`, and a few others).

For safety, these attributes are **only kept** if there is an explicit matching rule in `UrlPolicy(rules=...)` for the `(tag, attr)` pair.

That means:

- Even a relative URL like `/x.png` is dropped if there is no matching `(tag, attr)` rule.
- Rule keys are exact `(tag, attr)` pairs (no wildcards).

Example:

```python
from justhtml import JustHTML, SanitizationPolicy, UrlPolicy

policy = SanitizationPolicy(
    allowed_tags=["img"],
    allowed_attributes={"*": [], "img": ["src"]},
    url_policy=UrlPolicy(rules={}),
)

print(JustHTML('<img src="/x">', fragment=True).to_html(policy=policy))
# => "<img>"
```

## UrlPolicy: global handling of remote URLs

URL behavior is controlled by `UrlPolicy`:

- `url_handling`: what to do with **remote** URLs (absolute `https://...` and protocol-relative `//...`) after they pass `UrlRule` checks.
- `allow_relative`: whether **relative** URLs (like `/path`, `./path`, `../path`, `?q`) are allowed for URL-like attributes that have a matching rule.

```python
from justhtml import UrlPolicy

UrlPolicy(
    url_handling="allow",  # or "strip" / "proxy"
    allow_relative=True,
    rules={},
    url_filter=None,
    proxy=None,
)
```

## UrlRule: validation for a single (tag, attr)

A `UrlRule` controls how a single URL-valued attribute is validated:

```python
from justhtml import UrlRule

UrlRule(
    allow_fragment=True,
    resolve_protocol_relative="https",
    allowed_schemes=set(),
    allowed_hosts=None,
    proxy=None,
)
```

Common patterns:

- Allow only HTTPS links:

```python
UrlRule(allowed_schemes={"https"})
```

- Allow only your own host:

```python
UrlRule(allowed_schemes={"https"}, allowed_hosts={"example.com"})
```

- Allow only relative URLs (block remote loads):

```python
UrlRule(allowed_schemes=set(), resolve_protocol_relative=None)
```

Note: this is how `DEFAULT_POLICY` configures `("img", "src")` by default.

## Blocking remote loads (strip mode)

Some renderers (notably email clients) want to avoid loading remote resources by default.

The built-in `DEFAULT_POLICY` already blocks remote image loads by default (`img[src]` only allows relative URLs). If you want a *global* switch to strip all absolute/protocol-relative URLs after validation, use `url_handling="strip"`.

Use `UrlPolicy(url_handling="strip")`:

- Absolute URLs and protocol-relative URLs are dropped in URL-like attributes.
- Relative URLs are unaffected by `url_handling` and are only kept if `allow_relative=True`.

```python
from justhtml import JustHTML, SanitizationPolicy, UrlPolicy, UrlRule

policy = SanitizationPolicy(
    allowed_tags=["img"],
    allowed_attributes={"*": [], "img": ["src"]},
    url_policy=UrlPolicy(
        url_handling="strip",
        allow_relative=True,
        rules={("img", "src"): UrlRule(allowed_schemes={"http", "https"})},
    ),
)

print(JustHTML('<img src="https://example.com/x">', fragment=True).to_html(policy=policy))
print(JustHTML('<img src="/x">', fragment=True).to_html(policy=policy))
```

Output:

```html
<img>
<img src="/x">
```

## Proxying remote URLs (proxy mode)

Instead of keeping remote URLs, you can rewrite them through a proxy endpoint:

```python
from justhtml import JustHTML, SanitizationPolicy, UrlPolicy, UrlProxy, UrlRule

policy = SanitizationPolicy(
    allowed_tags=["a"],
    allowed_attributes={"*": [], "a": ["href"]},
    url_policy=UrlPolicy(
        url_handling="proxy",
        proxy=UrlProxy(url="/proxy", param="url"),
        rules={
            ("a", "href"): UrlRule(allowed_schemes={"https"}),
        },
    ),
)

print(JustHTML('<a href="https://example.com/?a=1&b=2">link</a>').to_html(policy=policy))
```

Output:

```html
<a href="/proxy?url=https%3A%2F%2Fexample.com%2F%3Fa%3D1%26b%3D2">link</a>
```

Notes:

- URL validation still happens before rewriting (schemes/hosts are still enforced).
- In proxy mode, a proxy must be configured either globally (`UrlPolicy.proxy`) or per rule (`UrlRule.proxy`).

## Protocol-relative URLs

Protocol-relative URLs start with `//`.

By default, they are resolved to `https` before validation. This ensures they are checked against allowed schemes and prevents inheriting an insecure protocol from the embedding page.

You can configure this behavior per rule:

```python
from justhtml import UrlRule

# Default behavior: resolve to https
rule = UrlRule(allowed_schemes=["https"], resolve_protocol_relative="https")

# Resolve to http
rule = UrlRule(allowed_schemes=["http", "https"], resolve_protocol_relative="http")

# Disallow protocol-relative URLs entirely
rule = UrlRule(allowed_schemes=["https"], resolve_protocol_relative=None)
```

## srcset

`srcset` contains **multiple URLs**, so it requires special care.

JustHTML parses the comma-separated candidates and sanitizes each candidate URL using the matching `UrlRule` for `(tag, "srcset")`.

If any candidate is unsafe, the entire attribute is dropped.

## url_filter hook

`UrlPolicy.url_filter` lets you apply a last-mile filter/rewrite (or drop) based on `(tag, attr, value)`.

- Return a string to keep it (possibly rewritten).
- Return `None` to drop the attribute.

This runs before validation.
