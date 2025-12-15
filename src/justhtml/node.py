from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .selector import query
from .serialize import to_html

if TYPE_CHECKING:
    from .tokens import Doctype


def _markdown_escape_text(s: str) -> str:
    if not s:
        return ""
    # Pragmatic: escape the few characters that commonly change Markdown meaning.
    # Keep this minimal to preserve readability.
    out: list[str] = []
    for ch in s:
        if ch in "\\`*_[]":
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _markdown_code_span(s: str | None) -> str:
    if s is None:
        s = ""
    # Use a backtick fence longer than any run of backticks inside.
    longest = 0
    run = 0
    for ch in s:
        if ch == "`":
            run += 1
            if run > longest:
                longest = run
        else:
            run = 0
    fence = "`" * (longest + 1)
    # CommonMark requires a space if the content starts/ends with backticks.
    needs_space = s.startswith("`") or s.endswith("`")
    if needs_space:
        return f"{fence} {s} {fence}"
    return f"{fence}{s}{fence}"


class _MarkdownBuilder:
    __slots__ = ("_buf", "_newline_count", "_pending_space")

    _buf: list[str]
    _newline_count: int
    _pending_space: bool

    def __init__(self) -> None:
        self._buf = []
        self._newline_count = 0
        self._pending_space = False

    def _rstrip_last_segment(self) -> None:
        if not self._buf:
            return
        last = self._buf[-1]
        stripped = last.rstrip(" \t")
        if stripped != last:
            self._buf[-1] = stripped

    def newline(self, count: int = 1) -> None:
        for _ in range(count):
            self._pending_space = False
            self._rstrip_last_segment()
            self._buf.append("\n")
            # Track newlines to make it easy to insert blank lines.
            if self._newline_count < 2:
                self._newline_count += 1

    def ensure_newlines(self, count: int) -> None:
        while self._newline_count < count:
            self.newline(1)

    def raw(self, s: str) -> None:
        if not s:
            return

        # If we've collapsed whitespace and the next output is raw (e.g. "**"),
        # we still need to emit a single separating space.
        if self._pending_space:
            first = s[0]
            if first not in " \t\n\r\f" and self._buf and self._newline_count == 0:
                self._buf.append(" ")
            self._pending_space = False

        self._buf.append(s)
        if "\n" in s:
            # Count trailing newlines (cap at 2 for blank-line semantics).
            trailing = 0
            i = len(s) - 1
            while i >= 0 and s[i] == "\n":
                trailing += 1
                i -= 1
            self._newline_count = min(2, trailing)
            if trailing:
                self._pending_space = False
        else:
            self._newline_count = 0

    def text(self, s: str, preserve_whitespace: bool = False) -> None:
        if not s:
            return

        if preserve_whitespace:
            self.raw(s)
            return

        for ch in s:
            if ch in " \t\n\r\f":
                self._pending_space = True
                continue

            if self._pending_space:
                if self._buf and self._newline_count == 0:
                    self._buf.append(" ")
                self._pending_space = False

            self._buf.append(ch)
            self._newline_count = 0

    def finish(self) -> str:
        out = "".join(self._buf)
        return out.strip(" \t\n")


# Type alias for any node type
NodeType = "SimpleDomNode | ElementNode | TemplateNode | TextNode"


def _to_text_collect(node: Any, parts: list[str], strip: bool) -> None:
    name: str = node.name

    if name == "#text":
        data: str | None = node.data
        if not data:
            return
        if strip:
            data = data.strip()
            if not data:
                return
        parts.append(data)
        return

    if node.children:
        for child in node.children:
            _to_text_collect(child, parts, strip=strip)

    if isinstance(node, ElementNode) and node.template_content:
        _to_text_collect(node.template_content, parts, strip=strip)


class SimpleDomNode:
    __slots__ = ("attrs", "children", "data", "name", "namespace", "parent")

    name: str
    parent: SimpleDomNode | ElementNode | TemplateNode | None
    attrs: dict[str, str | None] | None
    children: list[Any] | None
    data: str | Doctype | None
    namespace: str | None

    def __init__(
        self,
        name: str,
        attrs: dict[str, str | None] | None = None,
        data: str | Doctype | None = None,
        namespace: str | None = None,
    ) -> None:
        self.name = name
        self.parent = None
        self.data = data

        if name.startswith("#") or name == "!doctype":
            self.namespace = namespace
            if name == "#comment" or name == "!doctype":
                self.children = None
                self.attrs = None
            else:
                self.children = []
                self.attrs = attrs if attrs is not None else {}
        else:
            self.namespace = namespace or "html"
            self.children = []
            self.attrs = attrs if attrs is not None else {}

    def append_child(self, node: Any) -> None:
        if self.children is not None:
            self.children.append(node)
            node.parent = self

    def remove_child(self, node: Any) -> None:
        if self.children is not None:
            self.children.remove(node)
            node.parent = None

    def to_html(self, indent: int = 0, indent_size: int = 2, pretty: bool = True) -> str:
        """Convert node to HTML string."""
        return to_html(self, indent, indent_size, pretty=pretty)

    def query(self, selector: str) -> list[Any]:
        """
        Query this subtree using a CSS selector.

        Args:
            selector: A CSS selector string

        Returns:
            A list of matching nodes

        Raises:
            ValueError: If the selector is invalid
        """
        result: list[Any] = query(self, selector)
        return result

    @property
    def text(self) -> str:
        """Return the node's own text value.

        For text nodes this is the node data. For other nodes this is an empty
        string. Use `to_text()` to get textContent semantics.
        """
        if self.name == "#text":
            data = self.data
            if isinstance(data, str):
                return data
            return ""
        return ""

    def to_text(self, separator: str = " ", strip: bool = True) -> str:
        """Return the concatenated text of this node's descendants.

        - `separator` controls how text nodes are joined (default: a single space).
        - `strip=True` strips each text node and drops empty segments.

        Template element contents are included via `template_content`.
        """
        parts: list[str] = []
        _to_text_collect(self, parts, strip=strip)
        if not parts:
            return ""
        return separator.join(parts)

    def to_markdown(self) -> str:
        """Return a GitHub Flavored Markdown representation of this subtree.

        This is a pragmatic HTML->Markdown converter intended for readability.
        - Tables and images are preserved as raw HTML.
        - Unknown elements fall back to rendering their children.
        """
        builder = _MarkdownBuilder()
        _to_markdown_walk(self, builder, preserve_whitespace=False, list_depth=0)
        return builder.finish()

    def insert_before(self, node: Any, reference_node: Any | None) -> None:
        """
        Insert a node before a reference node.

        Args:
            node: The node to insert
            reference_node: The node to insert before. If None, append to end.

        Raises:
            ValueError: If reference_node is not a child of this node
        """
        if self.children is None:
            raise ValueError(f"Node {self.name} cannot have children")

        if reference_node is None:
            self.append_child(node)
            return

        try:
            index = self.children.index(reference_node)
            self.children.insert(index, node)
            node.parent = self
        except ValueError:
            raise ValueError("Reference node is not a child of this node") from None

    def replace_child(self, new_node: Any, old_node: Any) -> Any:
        """
        Replace a child node with a new node.

        Args:
            new_node: The new node to insert
            old_node: The child node to replace

        Returns:
            The replaced node (old_node)

        Raises:
            ValueError: If old_node is not a child of this node
        """
        if self.children is None:
            raise ValueError(f"Node {self.name} cannot have children")

        try:
            index = self.children.index(old_node)
        except ValueError:
            raise ValueError("The node to be replaced is not a child of this node") from None

        self.children[index] = new_node
        new_node.parent = self
        old_node.parent = None
        return old_node

    def has_child_nodes(self) -> bool:
        """Return True if this node has children."""
        return bool(self.children)

    def clone_node(self, deep: bool = False) -> SimpleDomNode:
        """
        Clone this node.

        Args:
            deep: If True, recursively clone children.

        Returns:
            A new node that is a copy of this node.
        """
        clone = SimpleDomNode(
            self.name,
            self.attrs.copy() if self.attrs else None,
            self.data,
            self.namespace,
        )
        if deep and self.children:
            for child in self.children:
                clone.append_child(child.clone_node(deep=True))
        return clone


class ElementNode(SimpleDomNode):
    __slots__ = ("template_content",)

    template_content: SimpleDomNode | None
    children: list[Any]
    attrs: dict[str, str | None]

    def __init__(self, name: str, attrs: dict[str, str | None] | None, namespace: str | None) -> None:
        self.name = name
        self.parent = None
        self.data = None
        self.namespace = namespace
        self.children = []
        self.attrs = attrs if attrs is not None else {}
        self.template_content = None

    def clone_node(self, deep: bool = False) -> ElementNode:
        clone = ElementNode(self.name, self.attrs.copy() if self.attrs else {}, self.namespace)
        if deep:
            for child in self.children:
                clone.append_child(child.clone_node(deep=True))
        return clone


class TemplateNode(ElementNode):
    __slots__ = ()

    def __init__(
        self,
        name: str,
        attrs: dict[str, str | None] | None = None,
        data: str | None = None,  # noqa: ARG002
        namespace: str | None = None,
    ) -> None:
        super().__init__(name, attrs, namespace)
        if self.namespace == "html":
            self.template_content = SimpleDomNode("#document-fragment")
        else:
            self.template_content = None

    def clone_node(self, deep: bool = False) -> TemplateNode:
        clone = TemplateNode(
            self.name,
            self.attrs.copy() if self.attrs else {},
            None,
            self.namespace,
        )
        if deep:
            if self.template_content:
                clone.template_content = self.template_content.clone_node(deep=True)
            for child in self.children:
                clone.append_child(child.clone_node(deep=True))
        return clone


class TextNode:
    __slots__ = ("data", "name", "namespace", "parent")

    data: str | None
    name: str
    namespace: None
    parent: SimpleDomNode | ElementNode | TemplateNode | None

    def __init__(self, data: str | None) -> None:
        self.data = data
        self.parent = None
        self.name = "#text"
        self.namespace = None

    @property
    def text(self) -> str:
        """Return the text content of this node."""
        return self.data or ""

    def to_text(self, separator: str = " ", strip: bool = True) -> str:  # noqa: ARG002
        # Parameters are accepted for API consistency; they don't affect leaf nodes.
        if self.data is None:
            return ""
        if strip:
            return self.data.strip()
        return self.data

    def to_markdown(self) -> str:
        builder = _MarkdownBuilder()
        builder.text(_markdown_escape_text(self.data or ""), preserve_whitespace=False)
        return builder.finish()

    @property
    def children(self) -> list[Any]:
        """Return empty list for TextNode (leaf node)."""
        return []

    def has_child_nodes(self) -> bool:
        """Return False for TextNode."""
        return False

    def clone_node(self, deep: bool = False) -> TextNode:  # noqa: ARG002
        return TextNode(self.data)


_MARKDOWN_BLOCK_ELEMENTS: frozenset[str] = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "nav",
        "aside",
        "blockquote",
        "pre",
        "ul",
        "ol",
        "li",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
    }
)


def _to_markdown_walk(node: Any, builder: _MarkdownBuilder, preserve_whitespace: bool, list_depth: int) -> None:
    name: str = node.name

    if name == "#text":
        if preserve_whitespace:
            builder.raw(node.data or "")
        else:
            builder.text(_markdown_escape_text(node.data or ""), preserve_whitespace=False)
        return

    if name == "br":
        builder.newline(1)
        return

    # Comments/doctype don't contribute.
    if name == "#comment" or name == "!doctype":
        return

    # Document containers contribute via descendants.
    if name.startswith("#"):
        if node.children:
            for child in node.children:
                _to_markdown_walk(child, builder, preserve_whitespace, list_depth)
        return

    tag = name.lower()

    # Preserve <img> and <table> as HTML.
    if tag == "img":
        builder.raw(node.to_html(indent=0, indent_size=2, pretty=False))
        return

    if tag == "table":
        builder.ensure_newlines(2 if builder._buf else 0)
        builder.raw(node.to_html(indent=0, indent_size=2, pretty=False))
        builder.ensure_newlines(2)
        return

    # Headings.
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        builder.ensure_newlines(2 if builder._buf else 0)
        level = int(tag[1])
        builder.raw("#" * level)
        builder.raw(" ")
        if node.children:
            for child in node.children:
                _to_markdown_walk(child, builder, preserve_whitespace=False, list_depth=list_depth)
        builder.ensure_newlines(2)
        return

    # Horizontal rule.
    if tag == "hr":
        builder.ensure_newlines(2 if builder._buf else 0)
        builder.raw("---")
        builder.ensure_newlines(2)
        return

    # Code blocks.
    if tag == "pre":
        builder.ensure_newlines(2 if builder._buf else 0)
        code = node.to_text(separator="", strip=False)
        builder.raw("```")
        builder.newline(1)
        if code:
            builder.raw(code.rstrip("\n"))
            builder.newline(1)
        builder.raw("```")
        builder.ensure_newlines(2)
        return

    # Inline code.
    if tag == "code" and not preserve_whitespace:
        code = node.to_text(separator="", strip=False)
        builder.raw(_markdown_code_span(code))
        return

    # Paragraph-like blocks.
    if tag == "p":
        builder.ensure_newlines(2 if builder._buf else 0)
        if node.children:
            for child in node.children:
                _to_markdown_walk(child, builder, preserve_whitespace=False, list_depth=list_depth)
        builder.ensure_newlines(2)
        return

    # Blockquotes.
    if tag == "blockquote":
        builder.ensure_newlines(2 if builder._buf else 0)
        inner = _MarkdownBuilder()
        if node.children:
            for child in node.children:
                _to_markdown_walk(child, inner, preserve_whitespace=False, list_depth=list_depth)
        text = inner.finish()
        if text:
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if i:
                    builder.newline(1)
                builder.raw("> ")
                builder.raw(line)
        builder.ensure_newlines(2)
        return

    # Lists.
    if tag in {"ul", "ol"}:
        builder.ensure_newlines(2 if builder._buf else 0)
        ordered = tag == "ol"
        idx = 1
        for child in node.children or []:
            if child.name.lower() != "li":
                continue
            if idx > 1:
                builder.newline(1)
            indent = "  " * list_depth
            marker = f"{idx}. " if ordered else "- "
            builder.raw(indent)
            builder.raw(marker)
            # Render list item content inline-ish.
            for li_child in child.children or []:
                _to_markdown_walk(li_child, builder, preserve_whitespace=False, list_depth=list_depth + 1)
            idx += 1
        builder.ensure_newlines(2)
        return

    # Emphasis/strong.
    if tag in {"em", "i"}:
        builder.raw("*")
        for child in node.children or []:
            _to_markdown_walk(child, builder, preserve_whitespace=False, list_depth=list_depth)
        builder.raw("*")
        return

    if tag in {"strong", "b"}:
        builder.raw("**")
        for child in node.children or []:
            _to_markdown_walk(child, builder, preserve_whitespace=False, list_depth=list_depth)
        builder.raw("**")
        return

    # Links.
    if tag == "a":
        href = ""
        if node.attrs and "href" in node.attrs and node.attrs["href"] is not None:
            href = str(node.attrs["href"])

        builder.raw("[")
        for child in node.children or []:
            _to_markdown_walk(child, builder, preserve_whitespace=False, list_depth=list_depth)
        builder.raw("]")
        if href:
            builder.raw("(")
            builder.raw(href)
            builder.raw(")")
        return

    # Containers / unknown tags: recurse into children.
    next_preserve = preserve_whitespace or (tag in {"textarea", "script", "style"})
    if node.children:
        for child in node.children:
            _to_markdown_walk(child, builder, next_preserve, list_depth)

    if isinstance(node, ElementNode) and node.template_content:
        _to_markdown_walk(node.template_content, builder, next_preserve, list_depth)

    # Add spacing after block containers to keep output readable.
    if tag in _MARKDOWN_BLOCK_ELEMENTS:
        builder.ensure_newlines(2)
