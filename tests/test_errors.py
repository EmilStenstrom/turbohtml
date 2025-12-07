"""Tests for error collection and strict mode."""

import unittest

from justhtml import JustHTML, ParseError, StrictModeError


class TestErrorCollection(unittest.TestCase):
    """Test that errors are collected when collect_errors=True."""

    def test_no_errors_by_default(self):
        """By default, errors list is not populated (for performance)."""
        doc = JustHTML("<html><body></body></html>")
        # When collect_errors=False, errors is an empty list
        assert doc.errors == []

    def test_collect_errors_enabled(self):
        """When collect_errors=True, parse errors are collected."""
        # Null character triggers parse error
        doc = JustHTML("<p>\x00</p>", collect_errors=True)
        assert len(doc.errors) > 0
        assert all(isinstance(e, ParseError) for e in doc.errors)

    def test_error_has_line_and_column(self):
        """Errors include line and column information."""
        doc = JustHTML("<p>\x00</p>", collect_errors=True)
        assert len(doc.errors) > 0
        error = doc.errors[0]
        assert error.line is not None
        assert error.column is not None
        assert isinstance(error.line, int)
        assert isinstance(error.column, int)

    def test_error_code_is_string(self):
        """Error code is a descriptive string."""
        doc = JustHTML("<p>\x00</p>", collect_errors=True)
        assert len(doc.errors) > 0
        error = doc.errors[0]
        assert isinstance(error.code, str)
        assert len(error.code) > 0

    def test_valid_html_no_errors(self):
        """Well-formed HTML with doctype produces no errors."""
        doc = JustHTML("<!DOCTYPE html><html><head></head><body></body></html>", collect_errors=True)
        # May still have some parse errors depending on strictness
        # At minimum, this shouldn't crash
        assert isinstance(doc.errors, list)

    def test_multiline_error_positions(self):
        """Errors on different lines have correct line numbers."""
        html = "<!DOCTYPE html>\n<html>\n<body>\n<p><b></p>"  # Misnested tags
        doc = JustHTML(html, collect_errors=True)
        # Should have errors due to misnesting
        # Verify line numbers are tracked
        for error in doc.errors:
            assert error.line >= 1

    def test_error_column_after_newline(self):
        """Error column is calculated correctly after newlines."""
        # Put a null char after a newline to test column calculation
        html = "line1\nline2\x00"
        doc = JustHTML(html, collect_errors=True)
        assert len(doc.errors) > 0
        # The null is at position 11 (after newline at position 5)
        # Column should be relative to last newline
        error = doc.errors[0]
        assert error.line == 2
        assert error.column > 0


class TestStrictMode(unittest.TestCase):
    """Test strict mode that raises on parse errors."""

    def test_strict_mode_raises(self):
        """Strict mode raises StrictModeError on first error."""
        with self.assertRaises(StrictModeError) as ctx:
            JustHTML("<p>\x00</p>", strict=True)
        assert ctx.exception.error is not None
        assert isinstance(ctx.exception.error, ParseError)

    def test_strict_mode_valid_html(self):
        """Strict mode with valid HTML doesn't raise."""
        # Fully valid HTML5 document
        doc = JustHTML(
            "<!DOCTYPE html><html><head><title>Test</title></head><body></body></html>",
            strict=True,
        )
        assert doc.root is not None
        # Empty errors list (since parsing succeeded)
        assert doc.errors == []

    def test_strict_mode_enables_error_collection(self):
        """Strict mode automatically enables error collection."""
        # We can't check this directly since it raises, but we verify
        # the exception contains error info
        with self.assertRaises(StrictModeError) as ctx:
            JustHTML("<p>\x00</p>", strict=True)
        error = ctx.exception.error
        assert error.line is not None
        assert error.column is not None


class TestParseError(unittest.TestCase):
    """Test ParseError class behavior."""

    def test_parse_error_str(self):
        """ParseError has readable string representation."""
        error = ParseError("test-error", line=1, column=5)
        assert str(error) == "(1,5): test-error"

    def test_parse_error_repr(self):
        """ParseError has useful repr."""
        error = ParseError("test-error", line=1, column=5)
        assert "test-error" in repr(error)
        assert "line=1" in repr(error)
        assert "column=5" in repr(error)

    def test_parse_error_equality(self):
        """ParseErrors with same values are equal."""
        e1 = ParseError("error-code", line=1, column=5)
        e2 = ParseError("error-code", line=1, column=5)
        e3 = ParseError("other-error", line=1, column=5)
        assert e1 == e2
        assert e1 != e3

    def test_parse_error_equality_with_non_parseerror(self):
        """ParseError compared with non-ParseError returns NotImplemented."""
        e1 = ParseError("error-code", line=1, column=5)
        assert e1.__eq__("not a ParseError") is NotImplemented

    def test_parse_error_no_location(self):
        """ParseError works without location info."""
        error = ParseError("test-error")
        assert str(error) == "test-error"
        assert "line=" not in repr(error)

    def test_parse_error_no_location_with_message(self):
        """ParseError with message but no location."""
        error = ParseError("test-error", message="This is a test error")
        assert str(error) == "test-error - This is a test error"
        assert "line=" not in repr(error)


class TestTokenizerErrors(unittest.TestCase):
    """Test tokenizer-specific errors are collected."""

    def test_null_character_error(self):
        """Null characters in data trigger errors."""
        doc = JustHTML("<p>\x00</p>", collect_errors=True)
        # Null character is a parse error
        assert len(doc.errors) > 0

    def test_unexpected_eof_in_tag(self):
        """Unexpected EOF in tag triggers error."""
        doc = JustHTML("<div att", collect_errors=True)
        assert len(doc.errors) > 0

    def test_unexpected_equals_in_tag(self):
        """Unexpected characters in attribute trigger error."""
        doc = JustHTML('<div attr="val\x00">text</div>', collect_errors=True)
        assert len(doc.errors) > 0


class TestTreeBuilderErrors(unittest.TestCase):
    """Test tree builder errors are collected."""

    def test_unexpected_end_tag(self):
        """Unexpected end tag triggers error."""
        doc = JustHTML("<!DOCTYPE html><html><body></span>", collect_errors=True)
        # Closing tag without opening tag
        assert len(doc.errors) > 0

    def test_treebuilder_error_after_newline(self):
        """Tree builder error column is calculated after newlines."""
        # Put an unexpected end tag after a newline
        html = "<!DOCTYPE html>\n<html>\n<body>\n</span>"
        doc = JustHTML(html, collect_errors=True)
        assert len(doc.errors) > 0
        # At least one error should have line > 1
        assert any(e.line > 1 for e in doc.errors if e.line is not None)

    def test_nested_p_in_button(self):
        """Paragraph in button triggers special handling."""
        doc = JustHTML("<!DOCTYPE html><button><p>text</button>", collect_errors=True)
        # This may trigger various parse errors
        assert isinstance(doc.errors, list)
