from __future__ import annotations

import unittest

from justhtml import JustHTML, SetAttrs
from justhtml.context import FragmentContext
from justhtml.transforms import Linkify


class TestTransformsSanitizeIntegration(unittest.TestCase):
    def test_safe_serialization_strips_unsafe_attrs_without_mutating_dom(self) -> None:
        doc = JustHTML(
            "<p>example.com</p>",
            fragment_context=FragmentContext("div"),
            transforms=[Linkify(), SetAttrs("a", onclick="x()")],
        )

        safe_html = doc.to_html(pretty=False, safe=True)
        assert safe_html == '<p><a href="http://example.com">example.com</a></p>'

        # `safe=True` sanitizes a cloned view of the tree; the in-memory DOM still
        # contains transform-introduced attributes.
        unsafe_html = doc.to_html(pretty=False, safe=False)
        assert unsafe_html == '<p><a href="http://example.com" onclick="x()">example.com</a></p>'

    def test_safe_serialization_strips_disallowed_href_schemes_from_linkify(self) -> None:
        doc = JustHTML(
            "<p>ftp://example.com</p>",
            fragment_context=FragmentContext("div"),
            transforms=[Linkify()],
        )

        assert doc.to_html(pretty=False, safe=False) == ('<p><a href="ftp://example.com">ftp://example.com</a></p>')
        assert doc.to_html(pretty=False, safe=True) == "<p><a>ftp://example.com</a></p>"

    def test_safe_serialization_resolves_protocol_relative_links(self) -> None:
        doc = JustHTML(
            "<p>//example.com</p>",
            fragment_context=FragmentContext("div"),
            transforms=[Linkify()],
        )

        assert doc.to_html(pretty=False, safe=False) == '<p><a href="//example.com">//example.com</a></p>'
        assert doc.to_html(pretty=False, safe=True) == '<p><a href="https://example.com">//example.com</a></p>'
