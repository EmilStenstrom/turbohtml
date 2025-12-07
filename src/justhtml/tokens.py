class Tag:
    __slots__ = ("attrs", "kind", "name", "self_closing")

    START = 0
    END = 1

    def __init__(self, kind, name, attrs, self_closing=False):
        self.kind = kind
        self.name = name
        self.attrs = attrs if attrs is not None else {}
        self.self_closing = bool(self_closing)


class CharacterTokens:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class CommentToken:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class Doctype:
    __slots__ = ("force_quirks", "name", "public_id", "system_id")

    def __init__(self, name=None, public_id=None, system_id=None, force_quirks=False):
        self.name = name
        self.public_id = public_id
        self.system_id = system_id
        self.force_quirks = bool(force_quirks)


class DoctypeToken:
    __slots__ = ("doctype",)

    def __init__(self, doctype):
        self.doctype = doctype


class EOFToken:
    __slots__ = ()


class TokenSinkResult:
    __slots__ = ()

    Continue = 0
    Plaintext = 1


class ParseError:
    """Represents a parse error with location information."""

    __slots__ = ("_end_column", "_source_html", "code", "column", "line", "message")

    def __init__(self, code, line=None, column=None, message=None, source_html=None, end_column=None):
        self.code = code
        self.line = line
        self.column = column
        self.message = message or code
        self._source_html = source_html
        self._end_column = end_column

    def __repr__(self):
        if self.line is not None and self.column is not None:
            return f"ParseError({self.code!r}, line={self.line}, column={self.column})"
        return f"ParseError({self.code!r})"

    def __str__(self):
        if self.line is not None and self.column is not None:
            if self.message != self.code:
                return f"({self.line},{self.column}): {self.code} - {self.message}"
            return f"({self.line},{self.column}): {self.code}"
        if self.message != self.code:
            return f"{self.code} - {self.message}"
        return self.code

    def __eq__(self, other):
        if not isinstance(other, ParseError):
            return NotImplemented
        return self.code == other.code and self.line == other.line and self.column == other.column

    __hash__ = None  # Unhashable since we define __eq__

    def as_exception(self, end_column=None):
        """Convert to a SyntaxError-like exception with source highlighting.

        This uses Python 3.11+ enhanced error display to show the exact
        location in the HTML source where the error occurred.

        Args:
            end_column: Optional end column for highlighting a range.
                       If None, attempts to highlight the full tag at the error position.

        Returns:
            A SyntaxError instance configured to display the error location.
        """
        if self.line is None or self.column is None or not self._source_html:
            # Fall back to regular exception if we don't have location info
            exc = SyntaxError(self.message)
            exc.msg = self.message
            return exc

        # Split HTML into lines
        lines = self._source_html.split("\n")
        if self.line < 1 or self.line > len(lines):
            # Invalid line number
            exc = SyntaxError(self.message)
            exc.msg = self.message
            return exc

        # Get the line with the error (1-indexed line -> 0-indexed array)
        error_line = lines[self.line - 1]

        # Create SyntaxError with location information
        exc = SyntaxError(self.message)
        exc.filename = "<html>"
        exc.lineno = self.line
        exc.offset = self.column
        exc.text = error_line
        exc.msg = self.message

        # Set end position for highlighting
        # Use stored end_column if provided, otherwise use parameter, otherwise auto-detect
        if self._end_column is not None:
            exc.end_lineno = self.line
            exc.end_offset = self._end_column
        elif end_column is not None:
            exc.end_lineno = self.line
            exc.end_offset = end_column
        else:
            # Try to find and highlight the full tag at this position
            col_idx = self.column - 1  # Convert to 0-indexed

            # Look backwards for '<' if we're not already on it
            start_idx = col_idx
            if start_idx < len(error_line) and error_line[start_idx] == "<":
                # Already at '<', use this position
                pass
            else:
                # Look backwards for '<'
                found_tag_start = False
                while start_idx > 0 and error_line[start_idx - 1] != "<":
                    start_idx -= 1
                    if col_idx - start_idx > 10:  # Don't look too far back
                        start_idx = col_idx
                        break

                # If we found a '<' before our position, use it as start
                if start_idx > 0 and error_line[start_idx - 1] == "<":
                    start_idx -= 1
                    found_tag_start = True

                # If we didn't find a tag start, use original position
                if not found_tag_start:
                    start_idx = col_idx

            # Look forward for '>' to find end of tag
            end_idx = col_idx
            while end_idx < len(error_line) and error_line[end_idx] != ">":
                end_idx += 1
            if end_idx < len(error_line) and error_line[end_idx] == ">":
                end_idx += 1  # Include the '>'

            # Set the highlighting range (convert back to 1-indexed)
            exc.end_lineno = self.line
            exc.offset = start_idx + 1
            exc.end_offset = end_idx + 1

        return exc
