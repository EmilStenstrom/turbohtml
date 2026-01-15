"""HTML sanitization policy API.

This module defines the public API for JustHTML sanitization.

The sanitizer operates on the parsed JustHTML DOM and is intentionally
policy-driven.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit

from .tokens import ParseError

UrlFilter = Callable[[str, str, str], str | None]


class UnsafeHtmlError(ValueError):
    """Raised when unsafe HTML is encountered and unsafe_handling='raise'."""


UnsafeHandling = Literal["strip", "raise", "collect"]


UrlHandling = Literal["allow", "strip", "proxy"]


@dataclass(frozen=True, slots=True)
class UrlProxy:
    url: str
    param: str = "url"

    def __post_init__(self) -> None:
        proxy_url = str(self.url)
        if not proxy_url:
            raise ValueError("UrlProxy.url must be a non-empty string")
        object.__setattr__(self, "url", proxy_url)
        object.__setattr__(self, "param", str(self.param))


@dataclass(frozen=True, slots=True)
class UrlRule:
    """Rule for a single URL-valued attribute (e.g. a[href], img[src]).

    This is intentionally rendering-oriented.

    - Returning/keeping a URL can still cause network requests when the output
        is rendered (notably for <img src>). Applications like email viewers often
        want to block remote loads by default.
    """

    # Allow same-document fragments (#foo). Typically safe.
    allow_fragment: bool = True

    # If set, protocol-relative URLs (//example.com) are resolved to this scheme
    # (e.g. "https") before checking allowed_schemes.
    # If None, protocol-relative URLs are disallowed.
    resolve_protocol_relative: str | None = "https"

    # Allow absolute URLs with these schemes (lowercase), e.g. {"https"}.
    # If empty, all absolute URLs with a scheme are disallowed.
    allowed_schemes: Collection[str] = field(default_factory=set)

    # If provided, absolute URLs are allowed only if the parsed host is in this
    # allowlist.
    allowed_hosts: Collection[str] | None = None

    # Optional per-rule handling override.
    # If None, the URL is kept ("allow") after it passes validation.
    handling: UrlHandling | None = None

    # Optional per-rule override of UrlPolicy.default_allow_relative.
    # If None, UrlPolicy.default_allow_relative is used.
    allow_relative: bool | None = None

    # Optional proxy override for absolute/protocol-relative URLs.
    # Used when the effective URL handling is "proxy".
    proxy: UrlProxy | None = None

    def __post_init__(self) -> None:
        # Accept lists/tuples from user code, normalize for internal use.
        if not isinstance(self.allowed_schemes, set):
            object.__setattr__(self, "allowed_schemes", set(self.allowed_schemes))
        if self.allowed_hosts is not None and not isinstance(self.allowed_hosts, set):
            object.__setattr__(self, "allowed_hosts", set(self.allowed_hosts))

        if self.proxy is not None and not isinstance(self.proxy, UrlProxy):
            raise TypeError("UrlRule.proxy must be a UrlProxy or None")

        if self.handling is not None:
            mode = str(self.handling)
            if mode not in {"allow", "strip", "proxy"}:
                raise ValueError("Invalid UrlRule.handling. Expected one of: 'allow', 'strip', 'proxy'")
            object.__setattr__(self, "handling", mode)

        if self.allow_relative is not None:
            object.__setattr__(self, "allow_relative", bool(self.allow_relative))


@dataclass(frozen=True, slots=True)
class UrlPolicy:
    # Default handling for URL-like attributes after they pass UrlRule checks.
    # - "allow": keep the URL as-is
    # - "strip": drop the attribute
    # - "proxy": rewrite the URL through a proxy (UrlPolicy.proxy or UrlRule.proxy)
    default_handling: UrlHandling = "strip"

    # Default allowance for relative URLs (including /path, ./path, ../path, ?query)
    # for URL-like attributes that have a matching UrlRule.
    default_allow_relative: bool = True

    # Rule configuration for URL-valued attributes.
    allow_rules: Mapping[tuple[str, str], UrlRule] = field(default_factory=dict)

    # Optional hook that can drop or rewrite URLs.
    # url_filter(tag, attr, value) should return:
    # - a replacement string to keep (possibly rewritten), or
    # - None to drop the attribute.
    url_filter: UrlFilter | None = None

    # Default proxy config used when a rule is handled with "proxy" and
    # the rule does not specify its own UrlRule.proxy override.
    proxy: UrlProxy | None = None

    def __post_init__(self) -> None:
        mode = str(self.default_handling)
        if mode not in {"allow", "strip", "proxy"}:
            raise ValueError("Invalid default_handling. Expected one of: 'allow', 'strip', 'proxy'")
        object.__setattr__(self, "default_handling", mode)

        object.__setattr__(self, "default_allow_relative", bool(self.default_allow_relative))

        if not isinstance(self.allow_rules, dict):
            object.__setattr__(self, "allow_rules", dict(self.allow_rules))

        if self.proxy is not None and not isinstance(self.proxy, UrlProxy):
            raise TypeError("UrlPolicy.proxy must be a UrlProxy or None")

        # Validate proxy configuration for any rules that are in proxy mode.
        for rule in self.allow_rules.values():
            if not isinstance(rule, UrlRule):
                raise TypeError("UrlPolicy.allow_rules values must be UrlRule")
            if rule.handling == "proxy" and self.proxy is None and rule.proxy is None:
                raise ValueError("UrlRule.handling='proxy' requires a UrlPolicy.proxy or a per-rule UrlRule.proxy")


def _proxy_url_value(*, proxy: UrlProxy, value: str) -> str:
    sep = "&" if "?" in proxy.url else "?"
    return f"{proxy.url}{sep}{proxy.param}={quote(value, safe='')}"


@dataclass(slots=True)
class UnsafeHandler:
    """Centralized handler for security findings.

    This is intentionally a small stateful object so multiple sanitization-
    related passes/transforms can share the same unsafe-handling behavior and
    (in collect mode) append into the same error list.
    """

    unsafe_handling: UnsafeHandling

    # Optional external sink (e.g. a JustHTML document's .errors list).
    # When set and unsafe_handling == "collect", security findings are written
    # into that list so multiple components can share a single sink.
    sink: list[ParseError] | None = None

    _errors: list[ParseError] | None = None

    def reset(self) -> None:
        if self.unsafe_handling != "collect":
            self._errors = None
            return

        if self.sink is None:
            self._errors = []
            return

        # Remove previously collected security findings from the shared sink to
        # avoid accumulating duplicates across multiple runs.
        errors = self.sink
        write_i = 0
        for e in errors:
            if e.category == "security":
                continue
            errors[write_i] = e
            write_i += 1
        del errors[write_i:]

    def collected(self) -> list[ParseError]:
        src = self.sink if self.sink is not None else self._errors
        if not src:
            return []

        if self.sink is not None:
            out = [e for e in src if e.category == "security"]
        else:
            out = list(src)
        out.sort(
            key=lambda e: (
                e.line if e.line is not None else 1_000_000_000,
                e.column if e.column is not None else 1_000_000_000,
            )
        )
        return out

    def handle(self, msg: str, *, node: Any | None = None) -> None:
        mode = self.unsafe_handling
        if mode == "strip":
            return
        if mode == "raise":
            raise UnsafeHtmlError(msg)
        if mode == "collect":
            dest = self.sink
            if dest is None:
                if self._errors is None:
                    self._errors = []
                dest = self._errors

            line: int | None = None
            column: int | None = None
            if node is not None:
                # Best-effort: use node origin metadata when enabled.
                # This stays allocation-light and avoids any input re-parsing.
                line = node.origin_line
                column = node.origin_col

            dest.append(
                ParseError(
                    "unsafe-html",
                    line=line,
                    column=column,
                    category="security",
                    message=msg,
                )
            )
            return
        raise AssertionError(f"Unhandled unsafe_handling: {mode!r}")


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

    # URL handling.
    url_policy: UrlPolicy = field(default_factory=UrlPolicy)

    drop_comments: bool = True
    drop_doctype: bool = True
    drop_foreign_namespaces: bool = True

    # Dangerous containers whose text payload should not be preserved.
    drop_content_tags: Collection[str] = field(default_factory=lambda: {"script", "style"})

    # Inline style allowlist.
    # Only applies when the `style` attribute is allowed for a tag.
    # If empty, inline styles are effectively disabled (style attributes are dropped).
    allowed_css_properties: Collection[str] = field(default_factory=set)

    # Link hardening.
    # If non-empty, ensure these tokens are present in <a rel="...">.
    # (The sanitizer will merge tokens; it will not remove existing ones.)
    force_link_rel: Collection[str] = field(default_factory=set)

    # Determines how unsafe input is handled.
    #
    # - "strip": Default. Remove/drop unsafe constructs and keep going.
    # - "raise": Raise UnsafeHtmlError on the first unsafe construct.
    #
    # This is intentionally a string mode (instead of a boolean) so we can add
    # more behaviors over time without changing the API shape.
    unsafe_handling: UnsafeHandling = "strip"

    _unsafe_handler: UnsafeHandler = field(
        default_factory=lambda: UnsafeHandler("strip"),
        init=False,
        repr=False,
        compare=False,
    )

    # Internal caches to avoid per-node allocations in hot paths.
    _allowed_attrs_global: frozenset[str] = field(
        default_factory=frozenset,
        init=False,
        repr=False,
        compare=False,
    )
    _allowed_attrs_by_tag: dict[str, frozenset[str]] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )

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

        if not isinstance(self.allowed_css_properties, set):
            object.__setattr__(self, "allowed_css_properties", set(self.allowed_css_properties))

        if not isinstance(self.force_link_rel, set):
            object.__setattr__(self, "force_link_rel", set(self.force_link_rel))

        unsafe_handling = str(self.unsafe_handling)
        if unsafe_handling not in {"strip", "raise", "collect"}:
            raise ValueError("Invalid unsafe_handling. Expected one of: 'strip', 'raise', 'collect'")
        object.__setattr__(self, "unsafe_handling", unsafe_handling)

        # Centralize unsafe-handling logic so multiple passes can share it.
        handler = UnsafeHandler(cast("UnsafeHandling", unsafe_handling))
        handler.reset()
        object.__setattr__(self, "_unsafe_handler", handler)

        # Normalize rel tokens once so _sanitize_attrs() can stay allocation-light.
        # (Downstream code expects lowercase tokens and ignores empty/whitespace.)
        if self.force_link_rel:
            normalized_force_link_rel = {t.strip().lower() for t in self.force_link_rel if str(t).strip()}
            object.__setattr__(self, "force_link_rel", normalized_force_link_rel)

        style_allowed = any("style" in attrs for attrs in self.allowed_attributes.values())
        if style_allowed and not self.allowed_css_properties:
            raise ValueError(
                "SanitizationPolicy allows the 'style' attribute but allowed_css_properties is empty. "
                "Either remove 'style' from allowed_attributes or set allowed_css_properties (for example CSS_PRESET_TEXT)."
            )

        allowed_attributes = self.allowed_attributes
        allowed_global = frozenset(allowed_attributes.get("*", ()))
        by_tag: dict[str, frozenset[str]] = {}
        for tag, attrs in allowed_attributes.items():
            if tag == "*":
                continue
            by_tag[tag] = frozenset(allowed_global.union(attrs))
        object.__setattr__(self, "_allowed_attrs_global", allowed_global)
        object.__setattr__(self, "_allowed_attrs_by_tag", by_tag)

    def reset_collected_security_errors(self) -> None:
        self._unsafe_handler.reset()

    def collected_security_errors(self) -> list[ParseError]:
        return self._unsafe_handler.collected()

    def handle_unsafe(self, msg: str, *, node: Any | None = None) -> None:
        self._unsafe_handler.handle(msg, node=node)


_URL_NORMALIZE_STRIP_TABLE = {i: None for i in range(0x21)}
_URL_NORMALIZE_STRIP_TABLE[0x7F] = None


DEFAULT_POLICY: SanitizationPolicy = SanitizationPolicy(
    allowed_tags=[
        # Text / structure
        "p",
        "br",
        # Structure
        "div",
        "span",
        "blockquote",
        "pre",
        "code",
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
        # Tables
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
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
        # Line breaks
        "hr",
        # Links and images
        "a",
        "img",
    ],
    allowed_attributes={
        "*": ["class", "id", "title", "lang", "dir"],
        "a": ["href", "title"],
        "img": ["src", "alt", "title", "width", "height", "loading", "decoding"],
        "th": ["colspan", "rowspan"],
        "td": ["colspan", "rowspan"],
    },
    url_policy=UrlPolicy(
        default_handling="allow",
        allow_rules={
            ("a", "href"): UrlRule(
                allowed_schemes=["http", "https", "mailto", "tel"],
                resolve_protocol_relative="https",
            ),
            ("img", "src"): UrlRule(
                allowed_schemes=[],
                resolve_protocol_relative=None,
            ),
        },
    ),
    allowed_css_properties=set(),
)


# A conservative preset for allowing a small amount of inline styling.
# This is intentionally focused on text-level styling and avoids layout/
# positioning properties that are commonly abused for UI redress.
CSS_PRESET_TEXT: frozenset[str] = frozenset(
    {
        "background-color",
        "color",
        "font-size",
        "font-style",
        "font-weight",
        "letter-spacing",
        "line-height",
        "text-align",
        "text-decoration",
        "text-transform",
        "white-space",
        "word-break",
        "word-spacing",
        "word-wrap",
    }
)


DEFAULT_DOCUMENT_POLICY: SanitizationPolicy = SanitizationPolicy(
    allowed_tags=sorted(set(DEFAULT_POLICY.allowed_tags) | {"html", "head", "body", "title"}),
    allowed_attributes=DEFAULT_POLICY.allowed_attributes,
    url_policy=DEFAULT_POLICY.url_policy,
    drop_comments=DEFAULT_POLICY.drop_comments,
    drop_doctype=DEFAULT_POLICY.drop_doctype,
    drop_foreign_namespaces=DEFAULT_POLICY.drop_foreign_namespaces,
    drop_content_tags=DEFAULT_POLICY.drop_content_tags,
    allowed_css_properties=DEFAULT_POLICY.allowed_css_properties,
    force_link_rel=DEFAULT_POLICY.force_link_rel,
)


def _is_valid_css_property_name(name: str) -> bool:
    # Conservative: allow only ASCII letters/digits/hyphen.
    # This keeps parsing deterministic and avoids surprises with escapes.
    if not name:
        return False
    for ch in name:
        if "a" <= ch <= "z" or "0" <= ch <= "9" or ch == "-":
            continue
        return False
    return True


def _css_value_may_load_external_resource(value: str) -> bool:
    # Extremely conservative check: drop any declaration value that contains a
    # CSS function call that can load external resources.
    #
    # We intentionally do not try to parse full CSS (escapes, comments, strings,
    # etc.). Instead, we reject values that contain backslashes (common escape
    # obfuscation) or that *look* like they contain url(…) / image-set(…). This
    # ensures style attributes can't be used to trigger network requests even
    # when users allow potentially dangerous properties.
    if "\\" in value:
        return True

    # Scan while ignoring ASCII whitespace/control chars and CSS comments.
    # Keep a small rolling buffer to avoid extra allocations.
    buf: list[str] = []
    max_len = len("alphaimageloader")

    i = 0
    n = len(value)
    while i < n:
        ch = value[i]

        # Treat CSS comments as ignorable, so obfuscation like u/**/rl( is caught.
        if ch == "/" and i + 1 < n and value[i + 1] == "*":
            i += 2
            while i + 1 < n:
                if value[i] == "*" and value[i + 1] == "/":
                    i += 2
                    break
                i += 1
            else:
                # Unterminated comments are invalid CSS; be conservative.
                return True
            continue

        o = ord(ch)
        if o <= 0x20 or o == 0x7F:
            i += 1
            continue

        if "A" <= ch <= "Z":
            lower_ch = chr(o + 0x20)
        else:
            lower_ch = ch

        buf.append(lower_ch)
        if len(buf) > max_len:
            buf.pop(0)

        # Check for url( and image-set( anywhere in the normalized stream.
        if len(buf) >= 4 and buf[-4:] == ["u", "r", "l", "("]:
            return True
        if len(buf) >= 10 and buf[-10:] == [
            "i",
            "m",
            "a",
            "g",
            "e",
            "-",
            "s",
            "e",
            "t",
            "(",
        ]:
            return True

        # IE-only but still worth blocking defensively.
        if len(buf) >= 11 and buf[-11:] == [
            "e",
            "x",
            "p",
            "r",
            "e",
            "s",
            "s",
            "i",
            "o",
            "n",
            "(",
        ]:
            return True

        # Legacy IE CSS filters that can fetch remote resources.
        if len(buf) >= 7 and buf[-7:] == ["p", "r", "o", "g", "i", "d", ":"]:
            return True
        if len(buf) >= 16 and buf[-16:] == [
            "a",
            "l",
            "p",
            "h",
            "a",
            "i",
            "m",
            "a",
            "g",
            "e",
            "l",
            "o",
            "a",
            "d",
            "e",
            "r",
        ]:
            return True

        # Legacy bindings/behaviors that can pull remote content.
        if len(buf) >= 9 and buf[-9:] == ["b", "e", "h", "a", "v", "i", "o", "r", ":"]:
            return True
        if len(buf) >= 12 and buf[-12:] == [
            "-",
            "m",
            "o",
            "z",
            "-",
            "b",
            "i",
            "n",
            "d",
            "i",
            "n",
            "g",
        ]:
            return True

        i += 1

    return False


def _sanitize_inline_style(*, policy: SanitizationPolicy, value: str) -> str | None:
    allowed = policy.allowed_css_properties
    if not allowed:
        return None

    v = str(value)
    if not v:
        return None

    out_parts: list[str] = []
    for decl in v.split(";"):
        d = decl.strip()
        if not d:
            continue
        colon = d.find(":")
        if colon <= 0:
            continue

        prop = d[:colon].strip().lower()
        if not _is_valid_css_property_name(prop):
            continue
        if prop not in allowed:
            continue

        prop_value = d[colon + 1 :].strip()
        if not prop_value:
            continue

        if _css_value_may_load_external_resource(prop_value):
            continue

        out_parts.append(f"{prop}: {prop_value}")

    if not out_parts:
        return None
    return "; ".join(out_parts)


def _normalize_url_for_checking(value: str) -> str:
    # Strip whitespace/control chars commonly used for scheme obfuscation.
    # Note: do not strip backslashes; they are not whitespace/control chars,
    # and removing them can turn invalid schemes into valid ones.
    return value.translate(_URL_NORMALIZE_STRIP_TABLE)


def _is_valid_scheme(scheme: str) -> bool:
    first = scheme[0]
    if not ("a" <= first <= "z" or "A" <= first <= "Z"):
        return False
    for ch in scheme[1:]:
        if "a" <= ch <= "z" or "A" <= ch <= "Z" or "0" <= ch <= "9" or ch in "+-.":
            continue
        return False
    return True


def _has_scheme(value: str) -> bool:
    idx = value.find(":")
    if idx <= 0:
        return False
    # Scheme must appear before any path/query/fragment separator.
    end = len(value)
    for sep in ("/", "?", "#"):
        j = value.find(sep)
        if j != -1 and j < end:
            end = j
    if idx >= end:
        return False
    return _is_valid_scheme(value[:idx])


def _has_invalid_scheme_like_prefix(value: str) -> bool:
    idx = value.find(":")
    if idx <= 0:
        return False

    end = len(value)
    for sep in ("/", "?", "#"):
        j = value.find(sep)
        if j != -1 and j < end:
            end = j
    if idx >= end:
        return False

    return not _is_valid_scheme(value[:idx])


def _sanitize_url_value(
    *,
    policy: SanitizationPolicy,
    rule: UrlRule,
    tag: str,
    attr: str,
    value: str,
) -> str | None:
    return _sanitize_url_value_inner(policy=policy, rule=rule, tag=tag, attr=attr, value=value, apply_filter=True)


def _effective_proxy(*, url_policy: UrlPolicy, rule: UrlRule) -> UrlProxy | None:
    return rule.proxy if rule.proxy is not None else url_policy.proxy


def _effective_url_handling(*, url_policy: UrlPolicy, rule: UrlRule) -> UrlHandling:
    # URL-like attributes are allowlisted via UrlPolicy.allow_rules. When they are
    # allowlisted and the URL passes validation, the default action is to keep the URL.
    return rule.handling if rule.handling is not None else "allow"


def _effective_allow_relative(*, url_policy: UrlPolicy, rule: UrlRule) -> bool:
    return rule.allow_relative if rule.allow_relative is not None else url_policy.default_allow_relative


def _sanitize_url_value_inner(
    *,
    policy: SanitizationPolicy,
    rule: UrlRule,
    tag: str,
    attr: str,
    value: str,
    apply_filter: bool,
) -> str | None:
    v = value
    url_policy = policy.url_policy
    mode = _effective_url_handling(url_policy=url_policy, rule=rule)
    allow_relative = _effective_allow_relative(url_policy=url_policy, rule=rule)

    if apply_filter and url_policy.url_filter is not None:
        rewritten = url_policy.url_filter(tag, attr, v)
        if rewritten is None:
            return None
        v = rewritten

    stripped = str(v).strip()
    normalized = _normalize_url_for_checking(stripped)
    if not normalized:
        # If normalization removes everything, the value was empty/whitespace/
        # control-only. Drop it rather than keeping weird control characters.
        return None

    if normalized.startswith("#"):
        if not rule.allow_fragment:
            return None
        if mode == "strip":
            return None
        if mode == "proxy":
            proxy = _effective_proxy(url_policy=url_policy, rule=rule)
            return None if proxy is None else _proxy_url_value(proxy=proxy, value=stripped)
        return stripped

    if mode == "proxy" and _has_invalid_scheme_like_prefix(normalized):
        # If proxying is enabled, do not treat scheme-obfuscation as a relative URL.
        # Some user agents normalize backslashes and other characters during navigation.
        return None

    if normalized.startswith("//"):
        if not rule.resolve_protocol_relative:
            return None

        # Resolve to absolute URL for checking.
        resolved_scheme = rule.resolve_protocol_relative.lower()
        resolved_url = f"{resolved_scheme}:{normalized}"

        parsed = urlsplit(resolved_url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in rule.allowed_schemes:
            return None

        if rule.allowed_hosts is not None:
            host = (parsed.hostname or "").lower()
            if not host or host not in rule.allowed_hosts:
                return None

        if mode == "strip":
            return None
        if mode == "proxy":
            proxy = _effective_proxy(url_policy=url_policy, rule=rule)
            return None if proxy is None else _proxy_url_value(proxy=proxy, value=resolved_url)
        return resolved_url

    if _has_scheme(normalized):
        parsed = urlsplit(normalized)
        scheme = (parsed.scheme or "").lower()
        if scheme not in rule.allowed_schemes:
            return None
        if rule.allowed_hosts is not None:
            host = (parsed.hostname or "").lower()
            if not host or host not in rule.allowed_hosts:
                return None
        if mode == "strip":
            return None
        if mode == "proxy":
            proxy = _effective_proxy(url_policy=url_policy, rule=rule)
            return None if proxy is None else _proxy_url_value(proxy=proxy, value=stripped)
        return stripped

    if not allow_relative:
        return None

    if mode == "strip":
        return None
    if mode == "proxy":
        proxy = _effective_proxy(url_policy=url_policy, rule=rule)
        return None if proxy is None else _proxy_url_value(proxy=proxy, value=stripped)
    return stripped


def _sanitize_srcset_value(
    *,
    policy: SanitizationPolicy,
    rule: UrlRule,
    tag: str,
    attr: str,
    value: str,
) -> str | None:
    # Apply the URL filter once to the whole attribute value.
    url_policy = policy.url_policy
    v = value
    if url_policy.url_filter is not None:
        rewritten = url_policy.url_filter(tag, attr, v)
        if rewritten is None:
            return None
        v = rewritten

    stripped = str(v).strip()
    if not stripped:
        return None

    out_candidates: list[str] = []
    for raw_candidate in stripped.split(","):
        c = raw_candidate.strip()
        if not c:
            continue

        parts = c.split(None, 1)
        url_token = parts[0]
        desc = parts[1].strip() if len(parts) == 2 else ""

        sanitized_url = _sanitize_url_value_inner(
            policy=policy,
            rule=rule,
            tag=tag,
            attr=attr,
            value=url_token,
            apply_filter=False,
        )
        if sanitized_url is None:
            return None

        out_candidates.append(f"{sanitized_url} {desc}".strip())

    return None if not out_candidates else ", ".join(out_candidates)


_URL_LIKE_ATTRS: frozenset[str] = frozenset(
    {
        # Common URL-valued attributes.
        "href",
        "src",
        "srcset",
        "poster",
        "action",
        "formaction",
        "data",
        "cite",
        "background",
        # Can trigger requests/pings.
        "ping",
    }
)


def _url_is_external(normalized_url: str) -> bool:
    if not normalized_url:
        return False
    if normalized_url.startswith("#"):
        return False
    if normalized_url.startswith("//"):
        return True
    return _has_scheme(normalized_url)


def _srcset_contains_external_url(value: str) -> bool:
    # Minimal srcset scanner: parse comma-separated candidates, taking the URL
    # up to the first whitespace of each candidate.
    i = 0
    n = len(value)
    while i < n:
        # Skip whitespace and commas.
        while i < n and value[i] in "\t\n\r\f ,":
            i += 1
        if i >= n:
            break

        start = i
        while i < n and value[i] not in "\t\n\r\f ,":
            i += 1
        candidate = value[start:i]

        normalized = _normalize_url_for_checking(candidate.strip())
        if _url_is_external(normalized):
            return True

        # Skip the rest of the candidate (descriptors) until the next comma.
        while i < n and value[i] != ",":
            i += 1
        if i < n and value[i] == ",":
            i += 1

    return False


def _sanitize_attrs(
    *,
    policy: SanitizationPolicy,
    tag: str,
    attrs: dict[str, str | None] | None,
    node: Any | None = None,
) -> dict[str, str | None]:
    if not attrs:
        attrs = {}

    allowed = policy._allowed_attrs_by_tag.get(tag) or policy._allowed_attrs_global

    out: dict[str, str | None] = {}
    for raw_name, raw_value in attrs.items():
        if not raw_name:
            continue

        name = raw_name
        # Optimization: assume name is already a string and stripped (from tokenizer)
        if not name.islower():
            name = name.lower()

        # Disallow namespace-ish attributes by default.
        if ":" in name:
            policy.handle_unsafe(f"Unsafe attribute '{name}' (namespaced)", node=node)
            continue

        # Always drop event handlers.
        if name.startswith("on"):
            policy.handle_unsafe(f"Unsafe attribute '{name}' (event handler)", node=node)
            continue

        # Dangerous attribute contexts.
        if name == "srcdoc":
            policy.handle_unsafe(f"Unsafe attribute '{name}'", node=node)
            continue

        if name not in allowed and not (tag == "a" and name == "rel" and policy.force_link_rel):
            policy.handle_unsafe(f"Unsafe attribute '{name}' (not allowed)", node=node)
            continue

        if raw_value is None:
            out[name] = None
            continue

        value = raw_value

        if name in _URL_LIKE_ATTRS:
            rule = policy.url_policy.allow_rules.get((tag, name))
            if rule is None:
                policy.handle_unsafe(f"Unsafe URL in attribute '{name}' (no rule)", node=node)
                continue

            if name == "srcset":
                sanitized = _sanitize_srcset_value(policy=policy, rule=rule, tag=tag, attr=name, value=value)
            else:
                sanitized = _sanitize_url_value(policy=policy, rule=rule, tag=tag, attr=name, value=value)

            if sanitized is None:
                policy.handle_unsafe(f"Unsafe URL in attribute '{name}'", node=node)
                continue

            out[name] = sanitized
        elif name == "style":
            sanitized_style = _sanitize_inline_style(policy=policy, value=value)
            if sanitized_style is None:
                policy.handle_unsafe(f"Unsafe inline style in attribute '{name}'", node=node)
                continue
            out[name] = sanitized_style
        else:
            out[name] = value

    # Link hardening (merge tokens; do not remove existing ones).
    if tag == "a" and policy.force_link_rel:
        existing_raw = out.get("rel")
        existing: list[str] = []
        if isinstance(existing_raw, str) and existing_raw:
            for tok in existing_raw.split():
                t = tok.strip().lower()
                if t and t not in existing:
                    existing.append(t)
        for tok in sorted(policy.force_link_rel):
            if tok not in existing:
                existing.append(tok)
        out["rel"] = " ".join(existing)

    return out


def _append_sanitized_subtree(*, policy: SanitizationPolicy, original: Any, parent_out: Any) -> None:
    stack: list[tuple[Any, Any]] = [(original, parent_out)]
    while stack:
        current, out_parent = stack.pop()
        name: str = current.name

        if name == "#text":
            out_parent.append_child(current.clone_node(deep=False))
            continue

        if name == "#comment":
            if policy.drop_comments:
                continue
            out_parent.append_child(current.clone_node(deep=False))
            continue

        if name == "!doctype":
            if policy.drop_doctype:
                continue
            out_parent.append_child(current.clone_node(deep=False))
            continue

        # Document containers.
        if name.startswith("#"):
            clone = current.clone_node(deep=False)
            clone.children.clear()
            out_parent.append_child(clone)
            children = current.children or []
            stack.extend((child, clone) for child in reversed(children))
            continue

        # Element.
        tag = str(name).lower()
        if policy.drop_foreign_namespaces:
            ns = current.namespace
            if ns not in (None, "html"):
                policy.handle_unsafe(f"Unsafe tag '{tag}' (foreign namespace)", node=current)
                continue

        if tag in policy.drop_content_tags:
            policy.handle_unsafe(f"Unsafe tag '{tag}' (dropped content)", node=current)
            continue

        if tag not in policy.allowed_tags:
            policy.handle_unsafe(f"Unsafe tag '{tag}' (not allowed)", node=current)
            children = current.children or []
            stack.extend((child, out_parent) for child in reversed(children))

            if tag == "template" and current.namespace in (None, "html") and current.template_content:
                tc_children = current.template_content.children or []
                stack.extend((child, out_parent) for child in reversed(tc_children))
            continue

        # Filter attributes first to avoid copying them in clone_node.
        sanitized_attrs = _sanitize_attrs(policy=policy, tag=tag, attrs=current.attrs, node=current)
        clone = current.clone_node(deep=False, override_attrs=sanitized_attrs)

        out_parent.append_child(clone)

        # Template content is a separate subtree.
        if tag == "template" and current.namespace in (None, "html"):
            if current.template_content and clone.template_content:
                clone.template_content.children.clear()
                tc_children = current.template_content.children or []
                stack.extend((child, clone.template_content) for child in reversed(tc_children))

        children = current.children or []
        stack.extend((child, clone) for child in reversed(children))


def _sanitize(node: Any, *, policy: SanitizationPolicy | None = None) -> Any:
    """Return a sanitized clone of `node`.

    Private implementation detail.

    If `policy` is not provided, JustHTML uses a conservative default policy.
    For full documents (`#document` roots) it preserves `<html>`, `<head>`, and
    `<body>` wrappers; for fragments it prefers snippet-shaped output.
    """

    if policy is None:
        policy = DEFAULT_DOCUMENT_POLICY if node.name == "#document" else DEFAULT_POLICY

    # Root handling.
    root_name: str = node.name

    if root_name == "#text":
        return node.clone_node(deep=False)

    if root_name == "#comment":
        out_root = node.clone_node(deep=False)
        if policy.drop_comments:
            out_root.name = "#document-fragment"
        return out_root

    if root_name == "!doctype":
        out_root = node.clone_node(deep=False)
        if policy.drop_doctype:
            out_root.name = "#document-fragment"
        return out_root

    # Containers.
    if root_name.startswith("#"):
        out_root = node.clone_node(deep=False)
        out_root.children.clear()
        for child in node.children or []:
            _append_sanitized_subtree(policy=policy, original=child, parent_out=out_root)
        return out_root

    # Element root: keep element if allowed, otherwise unwrap into a fragment.
    tag = str(root_name).lower()
    if policy.drop_foreign_namespaces and node.namespace not in (None, "html"):
        policy.handle_unsafe(f"Unsafe tag '{tag}' (foreign namespace)", node=node)
        out_root = node.clone_node(deep=False)
        out_root.name = "#document-fragment"
        out_root.children.clear()
        out_root.attrs.clear()
        return out_root

    if tag in policy.drop_content_tags:
        policy.handle_unsafe(f"Unsafe tag '{tag}' (dropped content)", node=node)
        out_root = node.clone_node(deep=False)
        out_root.name = "#document-fragment"
        out_root.children.clear()
        out_root.attrs.clear()
        return out_root

    if tag not in policy.allowed_tags:
        policy.handle_unsafe(f"Unsafe tag '{tag}' (not allowed)", node=node)
        out_root = node.clone_node(deep=False)
        out_root.name = "#document-fragment"
        out_root.children.clear()
        out_root.attrs.clear()
        for child in node.children or []:
            _append_sanitized_subtree(policy=policy, original=child, parent_out=out_root)

        if tag == "template" and node.namespace in (None, "html") and node.template_content:
            for child in node.template_content.children or []:
                _append_sanitized_subtree(policy=policy, original=child, parent_out=out_root)
        return out_root

    out_root = node.clone_node(deep=False)
    out_root.children.clear()
    out_root.attrs = _sanitize_attrs(policy=policy, tag=tag, attrs=node.attrs, node=node)
    for child in node.children or []:
        _append_sanitized_subtree(policy=policy, original=child, parent_out=out_root)

    if tag == "template" and node.namespace in (None, "html"):
        if node.template_content and out_root.template_content:
            out_root.template_content.children.clear()
            for child in node.template_content.children or []:
                _append_sanitized_subtree(policy=policy, original=child, parent_out=out_root.template_content)

    return out_root
