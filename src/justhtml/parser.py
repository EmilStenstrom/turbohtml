"""Minimal JustHTML parser entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .encoding import decode_html
from .tokenizer import Tokenizer, TokenizerOpts
from .treebuilder import TreeBuilder

if TYPE_CHECKING:
    from .context import FragmentContext
    from .node import SimpleDomNode
    from .tokens import ParseError


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
        debug: bool = False,
        encoding: str | None = None,
        fragment_context: FragmentContext | None = None,
        iframe_srcdoc: bool = False,
        strict: bool = False,
        tokenizer_opts: TokenizerOpts | None = None,
        tree_builder: TreeBuilder | None = None,
    ) -> None:
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

        # Enable error collection if strict mode is on
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

        self.tokenizer = Tokenizer(self.tree_builder, opts, collect_errors=should_collect)
        # Link tokenizer to tree_builder for position info
        self.tree_builder.tokenizer = self.tokenizer

        self.tokenizer.run(html_str)
        self.root = self.tree_builder.finish()

        # Merge errors from both tokenizer and tree builder
        self.errors = self.tokenizer.errors + self.tree_builder.errors

        # In strict mode, raise on first error
        if strict and self.errors:
            raise StrictModeError(self.errors[0])

    def query(self, selector: str) -> list[Any]:
        """Query the document using a CSS selector. Delegates to root.query()."""
        return self.root.query(selector)

    def to_html(self, pretty: bool = True, indent_size: int = 2) -> str:
        """Serialize the document to HTML. Delegates to root.to_html()."""
        return self.root.to_html(indent=0, indent_size=indent_size, pretty=pretty)

    def to_text(self, separator: str = " ", strip: bool = True) -> str:
        """Return the document's concatenated text.

        Delegates to `root.to_text(separator=..., strip=...)`.
        """
        return self.root.to_text(separator=separator, strip=strip)

    def to_markdown(self) -> str:
        """Return a GitHub Flavored Markdown representation.

        Delegates to `root.to_markdown()`.
        """
        return self.root.to_markdown()
