[← Back to docs](index.md)

# Sanitization (Design Proposal)

> **Warning**
> This is a future design proposal. JustHTML does **not** currently include a built-in HTML sanitizer, and nothing in this document is implemented yet.

This document proposes adding an optional, *rendering-oriented* HTML sanitizer to JustHTML.

The motivating use case is rendering **untrusted HTML** (e.g., user-generated content, scraped HTML) safely by default, without depending on `html5lib`.

This is a design idea for future work; it is not implemented yet.

## Summary

- Add a sanitizer that operates on the parsed JustHTML DOM (not regex/string-based).
- Provide a conservative, security-focused default policy.
- Support `<a>` and `<img>` by default (for meaning-preserving scraped content).
- Keep the scope narrow: **no CSS sanitization** and **no SVG/MathML** in the default policy.

## Goals

- Prevent script execution when sanitized output is inserted into an HTML document as markup.
- Avoid common foot-guns by providing a safe default configuration.
- Keep sanitization logic small, auditable, and testable.
- Avoid changes to the HTML5 parsing algorithm and keep tokenizer performance unchanged.

## Non-goals

- Guarantee safety for all contexts (e.g., JavaScript strings, CSS contexts, URL contexts).
- Provide a complete browser-grade “content security” solution.
- Support rich sanitization of inline CSS (style attributes or `<style>`).
- Support SVG/MathML sanitization by default.

## Threat Model (What “safe” means)

**In scope**: preventing XSS via untrusted HTML that is sanitized and then embedded into an HTML document as markup.

**Out of scope**:
- If the sanitized HTML is inserted into a JavaScript string, an attribute context, or a URL context without proper escaping.
- Network/remote resource concerns beyond markup execution (e.g., tracking pixels). Allowing `<img>` implies remote loads can occur; applications may need additional controls.

## Proposed API

### Option A: Default-on safe mode

```python
from justhtml import JustHTML

# Default behavior: safe rendering output.
doc = JustHTML(user_html)  # safe mode by default
html = doc.to_html()
```

Add an escape hatch:

```python
from justhtml import JustHTML

doc = JustHTML(html, safe=False)  # raw parse, no sanitization
```

### Option B: Explicit modes

```python
JustHTML(html, mode="safe")
JustHTML(html, mode="raw")
JustHTML(html, mode=SanitizerPolicy(...))
```

### Option C: Separate helper (lowest surprise)

```python
from justhtml import JustHTML
from justhtml.sanitize import sanitize

root = JustHTML(html, fragment_context=...).root
clean_root = sanitize(root)  # returns a sanitized clone
```

**Tradeoff**:
- Default-on (A) prevents common mistakes but can surprise users expecting faithful parsing.
- Separate helper (C) avoids surprise but makes it easy to forget sanitization.

If JustHTML targets rendering untrusted HTML as its primary audience, Option A or B is recommended.

## Design Principles

- **Parse first, sanitize second**: the tokenizer and tree builder remain spec-driven; sanitization is a separate DOM pass.
- **Allowlist policy**: define what is allowed; remove everything else.
- **Normalization before validation**: URL scheme checks must occur after normalization (entity decoding + stripping control chars).
- **Conservative defaults**: small allowlists, strict URL schemes.
- **No exceptions on hot paths**: sanitizer should use deterministic control flow.

## Default Policy (Proposed)

This is a conservative policy intended for untrusted HTML rendering.

### Allowed namespaces

- HTML only.
- Drop all elements not in the HTML namespace.

### Allowed tags

Suggested initial set:

- Structure: `p`, `div`, `span`
- Headings: `h1`…`h6`
- Lists: `ul`, `ol`, `li`
- Text formatting: `b`, `strong`, `i`, `em`, `u`, `s`, `sub`, `sup`, `small`, `mark`
- Quotes/code: `blockquote`, `code`, `pre`
- Line breaks: `br`, `hr`
- Links: `a`
- Images: `img`

Explicitly *not* allowed by default:

- Scripting/embedding: `script`, `iframe`, `object`, `embed`, `applet`
- Metadata: `base`, `meta`, `link`
- Forms: `form`, `input`, `button`, `textarea`, `select`, `option`
- Styling: `style`

### Allowed attributes

- Global: none (initially). Consider allowing `title` globally.
- `a`: `href`, `title` (and optionally `rel` but sanitizer likely sets/overrides it)
- `img`: `src`, `alt`, `title`, `width`, `height`, `loading`, `decoding`

Always removed regardless of allowlists:

- Event handlers: any attribute name starting with `on` (case-insensitive)
- `style`
- `srcdoc`

### URL-valued attribute rules

Attributes treated as URL-valued (initial):

- `a[href]`
- `img[src]`

Default allowed schemes:

- `http`, `https`, `mailto` (optionally `tel`)

Additionally allow:

- Relative URLs (no scheme) including `/path`, `./path`, `../path`, `#fragment`, and `?query`.

Disallow by default:

- `javascript:`
- `data:` (even for images, because it can embed SVG payloads and increases edge-case surface)
- `file:`, `blob:`, and any unknown scheme

### `srcset`

`srcset` is a common bypass surface because it contains **multiple URLs**.

Two safe options:

- **Drop `srcset` by default** (simple and safe).
- Or implement a proper `srcset` parser and sanitize each candidate URL; keep only safe candidates.

The default should be “drop unless properly parsed and sanitized”.

## Sanitization Algorithm

Sanitization should operate on the DOM produced by `TreeBuilder`.

Two implementation strategies:

1. **In-place mutation**: walk the existing tree and remove/modify nodes.
2. **Clone-and-filter**: build a new sanitized tree from the old tree.

Clone-and-filter is often easier to reason about and avoids subtle issues with traversal while mutating.

### Handling disallowed elements

Policy choice:

- **Strip tag, keep children** for most disallowed tags (preserves visible content).
- **Drop subtree** for explicitly dangerous containers (e.g., `script`, `style`) to avoid carrying their text payload into output.

This should be configurable (like Bleach’s `strip=True/False`) but default behavior should be conservative.

### Comments

Drop `#comment` nodes by default.

### Templates

If templates (`<template>`) are supported, sanitize both:

- the template element’s attributes
- its `template_content` subtree

## URL Normalization Details

To robustly detect obfuscated schemes:

- Decode character references (numeric/named) in the attribute value.
- Strip ASCII control characters and whitespace commonly used for obfuscation.
- Lowercase scheme for comparison.

Then:

- If the normalized value begins with a scheme (`[a-z][a-z0-9+.-]*:`), require it to be in the allowed scheme list.
- Otherwise treat it as relative/fragment and allow.

If any step fails or yields ambiguity, drop the attribute.

## Optional Features (Explicit Opt-in)

These features increase security scope and should not be part of the default policy.

### CSS sanitization

If inline `style` is ever supported:

- Require an explicit `css_sanitizer` implementation.
- Use a real CSS parser (e.g., `tinycss2`) and an allowlist of properties.
- Explicitly sanitize or remove `url(...)` references.

If `style` is allowed but no CSS sanitizer is provided, `style` should be stripped (not passed through).

### SVG/MathML support

SVG/MathML are powerful and have many edge cases.

Default safe policy should drop foreign namespaces entirely.

If support is added later, it should be behind explicit enablement and include a separate allowlist and tests for namespace-ejection patterns.

## Testing Strategy

A sanitizer is only as good as its tests.

Recommended test categories:

- **Tag/attribute stripping**: `<script>`, `onerror`, `onclick`, `srcdoc`, unknown tags.
- **URL scheme checks**: `javascript:`, `data:`, obfuscated schemes using entities/control chars.
- **Idempotency**: `sanitize(sanitize(html)) == sanitize(html)`.
- **Namespace handling**: ensure SVG/MathML are removed under default policy.
- **`srcset` behavior**: ensure it is dropped (or sanitized correctly if implemented).

Also consider maintaining a small corpus of known XSS payloads (hand-curated) and running them as regression tests.

## Security Reporting / Maintenance

If JustHTML includes a built-in sanitizer (especially default-on), it becomes a security-sensitive feature.

To keep the burden manageable:

- Keep default scope narrow (no CSS, no SVG).
- Provide a clear SECURITY.md with disclosure instructions and response expectations.
- Be explicit about non-goals and safe usage contexts.

## Open Questions

- Should safe mode be default-on (`safe=True`) or explicit (`mode="safe"`)?
- Should relative URLs be allowed by default (likely yes for scraped content)?
- Should `data:` ever be supported for images under opt-in (e.g., allow only `data:image/png|jpeg|gif|webp` and still disallow SVG)?
- Should sanitized output automatically enforce `rel="nofollow ugc"` on links?
