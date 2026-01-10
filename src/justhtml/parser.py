"""Minimal JustHTML parser entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .context import FragmentContext
from .encoding import decode_html
from .tokenizer import Tokenizer, TokenizerOpts
from .transforms import apply_compiled_transforms, compile_transforms
from .treebuilder import TreeBuilder

if TYPE_CHECKING:
    from collections.abc import Callable

    from .node import SimpleDomNode
    from .sanitize import SanitizationPolicy
    from .tokens import ParseError
    from .transforms import Transform


class StrictModeError(SyntaxError):
    """Raised when strict mode encounters a parse error.

    Inherits from SyntaxError to provide Python 3.11+ enhanced error display
    with source location highlighting.
    """

    error: ParseError

    def __init__(self, error: ParseError) -> None:
        self.error = error
        # Use the ParseError's as_exception() to get enhanced display
        exc = error.as_exception()
        super().__init__(exc.msg)
        # Copy SyntaxError attributes for enhanced display
        self.filename = exc.filename
        self.lineno = exc.lineno
        self.offset = exc.offset
        self.text = exc.text
        self.end_lineno = getattr(exc, "end_lineno", None)
        self.end_offset = getattr(exc, "end_offset", None)


class JustHTML:
    __slots__ = ("debug", "encoding", "errors", "fragment_context", "root", "tokenizer", "tree_builder")

    debug: bool
    encoding: str | None
    errors: list[ParseError]
    fragment_context: FragmentContext | None
    root: SimpleDomNode
    tokenizer: Tokenizer
    tree_builder: TreeBuilder

    def __init__(
        self,
        html: str | bytes | bytearray | memoryview | None,
        *,
        collect_errors: bool = False,
        track_node_locations: bool = False,
        debug: bool = False,
        encoding: str | None = None,
        fragment: bool = False,
        fragment_context: FragmentContext | None = None,
        iframe_srcdoc: bool = False,
        strict: bool = False,
        tokenizer_opts: TokenizerOpts | None = None,
        tree_builder: TreeBuilder | None = None,
        transforms: list[Transform] | None = None,
    ) -> None:
        if fragment_context is not None:
            fragment = True

        if fragment and fragment_context is None:
            fragment_context = FragmentContext("div")

        # Compile transforms early so invalid selectors fail fast.
        compiled_transforms = None
        if transforms:
            compiled_transforms = compile_transforms(tuple(transforms))

        self.debug = bool(debug)
        self.fragment_context = fragment_context
        self.encoding = None

        html_str: str
        if isinstance(html, (bytes, bytearray, memoryview)):
            html_str, chosen = decode_html(bytes(html), transport_encoding=encoding)
            self.encoding = chosen
        elif html is not None:
            html_str = str(html)
        else:
            html_str = ""

        # Enable error collection if strict mode is on.
        # Node location tracking is opt-in to avoid slowing down the common case.
        should_collect = collect_errors or strict

        self.tree_builder = tree_builder or TreeBuilder(
            fragment_context=fragment_context,
            iframe_srcdoc=iframe_srcdoc,
            collect_errors=should_collect,
        )
        opts = tokenizer_opts or TokenizerOpts()

        # For RAWTEXT fragment contexts, set initial tokenizer state and rawtext tag
        if fragment_context and not fragment_context.namespace:
            rawtext_elements = {"textarea", "title", "style"}
            tag_name = fragment_context.tag_name.lower()
            if tag_name in rawtext_elements:
                opts.initial_state = Tokenizer.RAWTEXT
                opts.initial_rawtext_tag = tag_name
            elif tag_name in ("plaintext", "script"):
                opts.initial_state = Tokenizer.PLAINTEXT

        self.tokenizer = Tokenizer(
            self.tree_builder,
            opts,
            collect_errors=should_collect,
            track_node_locations=bool(track_node_locations),
        )
        # Link tokenizer to tree_builder for position info
        self.tree_builder.tokenizer = self.tokenizer

        self.tokenizer.run(html_str)
        self.root = self.tree_builder.finish()

        if compiled_transforms is not None:
            apply_compiled_transforms(self.root, compiled_transforms)

        if should_collect:
            # Merge errors from both tokenizer and tree builder.
            # Public API: users expect errors to be ordered by input position.
            merged_errors = self.tokenizer.errors + self.tree_builder.errors
            self.errors = self._sorted_errors(merged_errors)
        else:
            self.errors = []

        # In strict mode, raise on first error
        if strict and self.errors:
            raise StrictModeError(self.errors[0])

    def query(self, selector: str) -> list[Any]:
        """Query the document using a CSS selector. Delegates to root.query()."""
        return self.root.query(selector)

    @staticmethod
    def _sorted_errors(errors: list[ParseError]) -> list[ParseError]:
        indexed_errors = enumerate(errors)
        return [
            e
            for _, e in sorted(
                indexed_errors,
                key=lambda t: (
                    t[1].line if t[1].line is not None else 1_000_000_000,
                    t[1].column if t[1].column is not None else 1_000_000_000,
                    t[0],
                ),
            )
        ]

    def _set_security_errors(self, errors: list[ParseError]) -> None:
        if not self.errors and not errors:
            return

        base = [e for e in self.errors if e.category != "security"]
        self.errors = self._sorted_errors(base + errors)

    def _with_security_error_collection(
        self,
        policy: SanitizationPolicy | None,
        serialize: Callable[[], str],
    ) -> str:
        if policy is not None and policy.unsafe_handling == "collect":
            policy.reset_collected_security_errors()
            out = serialize()
            self._set_security_errors(policy.collected_security_errors())
            return out

        # Avoid stale security errors if a previous serialization used collect.
        self._set_security_errors([])
        return serialize()

    def to_html(
        self,
        pretty: bool = True,
        indent_size: int = 2,
        *,
        safe: bool = True,
        policy: SanitizationPolicy | None = None,
    ) -> str:
        """Serialize the document to HTML.

        - `safe=True` sanitizes untrusted content before serialization.
        - `policy` overrides the default sanitization policy.
        """
        if not safe:
            return self.root.to_html(
                indent=0,
                indent_size=indent_size,
                pretty=pretty,
                safe=False,
                policy=policy,
            )

        return self._with_security_error_collection(
            policy,
            lambda: self.root.to_html(
                indent=0,
                indent_size=indent_size,
                pretty=pretty,
                safe=True,
                policy=policy,
            ),
        )

    def to_text(
        self,
        separator: str = " ",
        strip: bool = True,
        *,
        safe: bool = True,
        policy: SanitizationPolicy | None = None,
    ) -> str:
        """Return the document's concatenated text.

        - `safe=True` sanitizes untrusted content before text extraction.
        - `policy` overrides the default sanitization policy.

        Delegates to `root.to_text(...)`.
        """
        if not safe:
            return self.root.to_text(separator=separator, strip=strip, safe=False, policy=policy)

        return self._with_security_error_collection(
            policy,
            lambda: self.root.to_text(separator=separator, strip=strip, safe=True, policy=policy),
        )

    def to_markdown(self, *, safe: bool = True, policy: SanitizationPolicy | None = None) -> str:
        """Return a GitHub Flavored Markdown representation.

        - `safe=True` sanitizes untrusted content before conversion.
        - `policy` overrides the default sanitization policy.
        """
        if not safe:
            return self.root.to_markdown(safe=False, policy=policy)

        return self._with_security_error_collection(
            policy,
            lambda: self.root.to_markdown(safe=True, policy=policy),
        )
