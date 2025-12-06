import unittest

from justhtml import stream


class TestStream(unittest.TestCase):
    def test_basic_stream(self):
        html = '<div class="container">Hello <b>World</b></div>'
        events = list(stream(html))

        expected = [
            ("start", ("div", {"class": "container"})),
            ("text", "Hello "),
            ("start", ("b", {})),
            ("text", "World"),
            ("end", "b"),
            ("end", "div"),
        ]
        assert events == expected

    def test_comments(self):
        html = "<!-- comment -->"
        events = list(stream(html))
        expected = [("comment", " comment ")]
        assert events == expected

    def test_doctype(self):
        html = "<!DOCTYPE html>"
        events = list(stream(html))
        # Doctype token structure: (name, public_id, system_id)
        expected = [("doctype", ("html", None, None))]
        assert events == expected

    def test_void_elements(self):
        html = "<br><hr>"
        events = list(stream(html))
        expected = [
            ("start", ("br", {})),
            # Tokenizer does not emit end tags for void elements automatically
            ("start", ("hr", {})),
        ]
        assert events == expected

    def test_text_coalescing(self):
        # Tokenizer might emit multiple character tokens. Stream should coalesce.
        html = "abc"
        events = list(stream(html))
        expected = [("text", "abc")]
        assert events == expected

    def test_script_rawtext(self):
        html = "<script>console.log('<');</script>"
        events = list(stream(html))
        expected = [
            ("start", ("script", {})),
            ("text", "console.log('<');"),
            ("end", "script"),
        ]
        assert events == expected

    def test_unmatched_end_tag(self):
        html = "</div>"
        events = list(stream(html))
        expected = [("end", "div")]
        assert events == expected
