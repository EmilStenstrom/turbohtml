[← Back to docs](index.md)

# Transforms

JustHTML supports optional **transforms** to modify the parsed DOM tree right after parsing.

This is intended as a migration path for Bleach/html5lib filter pipelines, but implemented as DOM transforms (tree-aware and HTML5-treebuilder-correct).

If you're migrating an existing Bleach setup, see [Migrating from Bleach](bleach-migration.md).

Transforms are applied during construction via the `transforms` keyword argument:

```python
from justhtml import JustHTML

doc = JustHTML("<p>Hello</p>", transforms=[...])
```

## Quick example

```python
from justhtml import JustHTML, SetAttrs, Drop

doc = JustHTML(
    "<p>Hello</p><script>alert(1)</script>",
    transforms=[
        SetAttrs("p", id="greeting"),
        Drop("script"),
    ],
)

# The tree is transformed in memory
print(doc.root.to_html(safe=False))

# Output is still safe by default
print(doc.to_html(pretty=False))
```

## Safety model

- Transforms run **once**, right after parsing, and mutate `doc.root`.
- Safe-by-default output is still enforced by:
  - `JustHTML.to_html(safe=True)`
  - `JustHTML.to_text(safe=True)`
  - `JustHTML.to_markdown(safe=True)`

This means output stays safe even if you mutate the DOM after parsing.

Transforms do not sanitize the in-memory tree. `safe=True` serialization sanitizes a cloned view of the tree right before output.

Raw output for trusted input is available via `safe=False`:

```python
doc.to_html(pretty=False, safe=False)
doc.root.to_html(pretty=False, safe=False)
```

Sanitization can remove or rewrite transform results (for example, unsafe tags, event handler attributes, or unsafe URLs in `href`).

## Ordering

Transforms run in the order they are provided.

Later transforms see earlier changes. If a transform removes a node (for example `Drop` or `Unwrap`), later transforms will not see that node.

```python
from justhtml import JustHTML, Drop, SetAttrs

doc = JustHTML(
    "<p>Hello</p>",
    transforms=[
        SetAttrs("p", id="x"),
        Drop("p"),
    ],
)
```

## Tree shape

Transforms operate on the HTML5 treebuilder result, not the original token stream.

This means elements may already be inserted, moved, or normalized according to HTML parsing rules (for example, `<template>` elements end up in `<head>` in a full document).

## Performance

JustHTML **compiles transforms before applying them**:

- CSS selectors are parsed once up front.
- The tree is then walked with the compiled transforms.

Transforms are applied with a single in-place traversal that supports structural edits.

Transforms are optional; omitting `transforms` keeps constructor behavior unchanged.

## Validation

Transform selectors are validated during construction.
Invalid selectors raise `SelectorError` early, before the document is exposed.

Only the built-in transform objects are supported.
Unsupported transform objects raise `TypeError`.

## Scope

Selector-based transforms (`SetAttrs`, `Drop`, `Unwrap`, `Empty`, `Edit`) apply only to element nodes.
They never match document containers, text nodes, comments, or doctypes.

`Linkify` is different: it scans **text nodes** and wraps detected URLs/emails in `<a>` elements.
It never touches attributes, existing tags, comments, or doctypes.

## Built-in transforms

- [`Linkify(...)`](linkify.md) — Scan text nodes and convert URLs/emails into `<a>` elements.
- `Sanitize(policy=None)` — Sanitize the in-memory tree (must run last, except for trailing `PruneEmpty`).
- `PruneEmpty(selector, strip_whitespace=True)` — Recursively drop empty elements.
- `SetAttrs(selector, **attrs)` — Set/overwrite attributes on matching elements.
- `Drop(selector)` — Remove matching elements and their contents.
- `Unwrap(selector)` — Remove the element but keep its children.
- `Empty(selector)` — Remove all children of matching elements.
- `Edit(selector, callback)` — Run custom logic for matching elements.

### `Linkify(...)`

See [`Linkify(...)`](linkify.md) for full documentation and examples.

### `Sanitize(policy=None)`

Sanitizes the in-memory DOM tree using the same sanitizer as `safe=True` output.

- This is useful if you want to traverse/modify a clean DOM.
- `Sanitize(...)` must be last, except for optional trailing `PruneEmpty(...)` transforms.

`PruneEmpty(...)` after `Sanitize(...)` is useful if sanitization removes unsafe children (for example `<script>`) and leaves a now-empty wrapper element.

### `PruneEmpty(selector, strip_whitespace=True)`

Recursively drops elements that are empty after transforms have run.

"Empty" means there are no element children and no non-whitespace text.

If you want whitespace-only text nodes to count as content (so `<p> </p>` is kept), pass `strip_whitespace=False`.

`PruneEmpty(...)` runs as a post-order walk over the tree and removes elements that are empty at that point in the transform pipeline.

If you want to prune after all other transforms, put `PruneEmpty(...)` at the end (or immediately before `Sanitize(...)`).

Example: remove empty paragraphs after dropping unwanted tags:

```python
from justhtml import Drop, JustHTML, PruneEmpty

doc = JustHTML(
    "<p></p><p><img></p><p><img src=\"/x\"></p>",
    fragment=True,
    transforms=[
        Drop('img:not([src]), img[src=""]'),
        PruneEmpty("p"),
    ],
)

print(doc.to_html(pretty=False, safe=False))
```

Output:

```html
<p><img src="/x"></p>
```

### `SetAttrs(selector, **attrs)`

Sets/overwrites attributes on matching elements.

Attribute values are converted to strings.
Passing `None` creates a boolean attribute (serialized in minimized form by default).

```python
SetAttrs("a", rel="nofollow", target="_blank")
SetAttrs("input", disabled=None)
```

### `Drop(selector)`

Removes matching elements and their contents.

`Drop(...)` supports any selector that the JustHTML selector engine supports, including comma-separated selectors and attribute selectors.

Example: remove scripts and styles:

```python
from justhtml import JustHTML, Drop

doc = JustHTML(
    "<p>Hello</p><script>alert(1)</script><style>p{}</style>",
    fragment=True,
    transforms=[Drop("script, style")],
)

print(doc.to_html(pretty=False, safe=False))
```

Output:

```html
<p>Hello</p>
```

Example: drop elements by class:

```python
from justhtml import JustHTML, Drop

doc = JustHTML(
    '<p>One</p><div class="ad">Buy</div><p>Two</p>',
    fragment=True,
    transforms=[Drop(".ad")],
)

print(doc.to_html(pretty=False, safe=False))
```

Output:

```html
<p>One</p><p>Two</p>
```

Example: drop only some elements based on attributes:

```python
from justhtml import JustHTML, Drop

doc = JustHTML(
    '<p><img><img src=""><img src="/x"></p>',
    fragment=True,
    transforms=[Drop('img:not([src]), img[src=""]')],
)

print(doc.to_html(pretty=False, safe=False))
```

Output:

```html
<p><img src="/x"></p>
```

### `Unwrap(selector)`

Removes the element but keeps its children (hoists contents).

```python
Unwrap("span")
Unwrap("div.wrapper")
```

### `Empty(selector)`

Keeps the element but removes its children.

This also clears `<template>` contents.

```python
Empty("pre")
Empty("template")
```

### `Edit(selector, callback)`

Escape hatch for custom logic. Runs `callback(node)` for each matching element.

`Edit` is useful for transformations that don’t fit the built-ins, such as removing attributes, rewriting URLs, or conditionally dropping nodes.

```python
from justhtml import JustHTML, Edit


def strip_tracking_params(a):
    href = a.attrs.get("href")
    if href:
        a.attrs["href"] = href.split("?", 1)[0]


doc = JustHTML(
    "<a href=\"https://e.com/?utm_source=x\">x</a>",
    transforms=[Edit("a", strip_tracking_params)],
)
```

Removing attributes is typically done via `Edit`:

```python
from justhtml import JustHTML, Edit


def drop_inline_handlers(node):
    node.attrs.pop("onclick", None)
    node.attrs.pop("onload", None)


doc = JustHTML("<a onclick=\"x()\">x</a>", transforms=[Edit("a", drop_inline_handlers)])
```

## Recipes

### Add `rel` to all links

```python
from justhtml import JustHTML, SetAttrs

doc = JustHTML(
    "<p><a href=\"https://example.com\">Example</a></p>",
    transforms=[
        SetAttrs("a", rel="nofollow noreferrer"),
    ],
)
```

### Strip elements but keep their text

```python
from justhtml import JustHTML, Unwrap

doc = JustHTML(
    "<p>Hello <span class=\"x\">world</span></p>",
    transforms=[Unwrap("span.x")],
)
```

### Drop unsafe elements early, while still keeping safe-by-default output

```python
from justhtml import JustHTML, Drop

doc = JustHTML(
    "<p>ok</p><script>alert(1)</script>",
    transforms=[Drop("script")],
)
print(doc.to_html(pretty=False))
```

## Reapplying transforms

Transforms passed to `JustHTML(..., transforms=[...])` run only once, during construction.

Transform compilation and application utilities are available for advanced usage:

```python
from justhtml.transforms import apply_compiled_transforms, compile_transforms

## Acknowledgements

JustHTML's Linkify behavior is validated against the upstream `linkify-it` fixture suite (MIT licensed).

- Fixtures: `tests/linkify-it/fixtures/`
- License: `tests/linkify-it/LICENSE.txt`

compiled = compile_transforms([...])
apply_compiled_transforms(doc.root, compiled)
```
