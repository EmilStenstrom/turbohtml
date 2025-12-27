"""HTML sanitization policy API.

This module defines the public API for JustHTML sanitization.

Implementation note:
- The sanitizer itself is intentionally conservative and policy-driven.
- For now, `sanitize()` is a no-op stub; the policy engine will be
  implemented next and used by the xss-bench harness.

The goal is that serialization helpers (`to_html`, `to_markdown`) can
produce safe-by-default output for untrusted HTML.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

UrlFilter = Callable[[str, str, str], str | None]


@dataclass(frozen=True, slots=True)
class UrlRule:
    """Rule for a single URL-valued attribute (e.g. a[href], img[src]).

    This is intentionally rendering-oriented.

    - Returning/keeping a URL can still cause network requests when the output
        is rendered (notably for <img src>). Applications like email viewers often
        want to block remote loads by default.
    """

    # Allow relative URLs (including /path, ./path, ../path, ?query).
    allow_relative: bool = True

    # Allow same-document fragments (#foo). Typically safe.
    allow_fragment: bool = True

    # Allow protocol-relative URLs (//example.com). Default False because they
    # are surprising and effectively network URLs.
    allow_protocol_relative: bool = False

    # Allow absolute URLs with these schemes (lowercase), e.g. {"https"}.
    # If empty, all absolute URLs with a scheme are disallowed.
    allowed_schemes: Collection[str] = field(default_factory=set)

    # If provided, absolute URLs are allowed only if the parsed host is in this
    # allowlist.
    allowed_hosts: Collection[str] | None = None

    def __post_init__(self) -> None:
        # Accept lists/tuples from user code, normalize for internal use.
        if not isinstance(self.allowed_schemes, set):
            object.__setattr__(self, "allowed_schemes", set(self.allowed_schemes))
        if self.allowed_hosts is not None and not isinstance(self.allowed_hosts, set):
            object.__setattr__(self, "allowed_hosts", set(self.allowed_hosts))


@dataclass(frozen=True, slots=True)
class SanitizationPolicy:
    """An allow-list driven policy for sanitizing a parsed DOM.

    This API is intentionally small. The implementation will interpret these
    fields strictly.

    - Tags not in `allowed_tags` are disallowed.
    - Attributes not in `allowed_attributes[tag]` (or `allowed_attributes["*"]`)
      are disallowed.
    - URL scheme checks apply to attributes listed in `url_attributes`.

    All tag and attribute names are expected to be ASCII-lowercase.
    """

    allowed_tags: Collection[str]
    allowed_attributes: Mapping[str, Collection[str]]

    # URL handling:
    # - `url_rules` is the data-driven allowlist for URL-valued attributes.
    # - `url_filter` is an optional hook that can drop or rewrite URLs.
    #
    # `url_filter(tag, attr, value)` should return:
    # - a replacement string to keep (possibly rewritten), or
    # - None to drop the attribute.
    url_rules: Mapping[tuple[str, str], UrlRule]
    url_filter: UrlFilter | None = None

    drop_comments: bool = True
    drop_doctype: bool = True
    drop_foreign_namespaces: bool = True

    # If True, disallowed elements are removed but their children may be kept
    # (except for tags in `drop_content_tags`).
    strip_disallowed_tags: bool = True

    # Dangerous containers whose text payload should not be preserved.
    drop_content_tags: Collection[str] = field(default_factory=lambda: {"script", "style"})

    # Link hardening.
    # If non-empty, ensure these tokens are present in <a rel="...">.
    # (The sanitizer will merge tokens; it will not remove existing ones.)
    force_link_rel: Collection[str] = field(default_factory=lambda: {"noopener", "noreferrer"})

    def __post_init__(self) -> None:
        # Normalize to sets so the sanitizer can do fast membership checks.
        if not isinstance(self.allowed_tags, set):
            object.__setattr__(self, "allowed_tags", set(self.allowed_tags))

        if not isinstance(self.allowed_attributes, dict) or any(
            not isinstance(v, set) for v in self.allowed_attributes.values()
        ):
            normalized_attrs: dict[str, set[str]] = {}
            for tag, attrs in self.allowed_attributes.items():
                normalized_attrs[str(tag)] = attrs if isinstance(attrs, set) else set(attrs)
            object.__setattr__(self, "allowed_attributes", normalized_attrs)

        if not isinstance(self.drop_content_tags, set):
            object.__setattr__(self, "drop_content_tags", set(self.drop_content_tags))

        if not isinstance(self.force_link_rel, set):
            object.__setattr__(self, "force_link_rel", set(self.force_link_rel))


DEFAULT_POLICY: SanitizationPolicy = SanitizationPolicy(
    allowed_tags=[
        # Structure
        "p",
        "div",
        "span",
        # Headings
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        # Lists
        "ul",
        "ol",
        "li",
        # Text formatting
        "b",
        "strong",
        "i",
        "em",
        "u",
        "s",
        "sub",
        "sup",
        "small",
        "mark",
        # Quotes/code
        "blockquote",
        "code",
        "pre",
        # Line breaks
        "br",
        "hr",
        # Links and images
        "a",
        "img",
    ],
    allowed_attributes={
        "*": [],
        "a": ["href", "title"],
        "img": ["src", "alt", "title", "width", "height", "loading", "decoding"],
    },
    # Default URL stance:
    # - Links may point to http/https/mailto and relative URLs.
    # - Images default to relative-only to avoid unexpected remote loads in
    #   contexts like HTML email rendering.
    url_rules={
        ("a", "href"): UrlRule(allowed_schemes=["http", "https", "mailto"]),
        ("img", "src"): UrlRule(allowed_schemes=[]),
    },
)


def sanitize(node: Any, *, policy: SanitizationPolicy = DEFAULT_POLICY) -> Any:
    """Return a sanitized view of `node` according to `policy`.

    Current status: API stub.

    The implementation will be a DOM pass that removes/rewrites nodes and
    attributes according to an allowlist policy.

    For now, this function returns the input node unchanged.
    """

    _ = policy
    return node
