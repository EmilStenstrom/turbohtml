from __future__ import annotations

import unittest

from justhtml import JustHTML
from justhtml.node import ElementNode, TextNode
from justhtml.transforms import Linkify, apply_compiled_transforms, compile_transforms


class TestLinkifyTransform(unittest.TestCase):
    def test_linkify_wraps_fuzzy_domain_in_text_node(self) -> None:
        doc = JustHTML("<p>See example.com</p>", transforms=[Linkify()])
        out = doc.to_html(pretty=False, safe=False)
        assert '<a href="http://example.com">example.com</a>' in out

    def test_linkify_wraps_email_in_text_node(self) -> None:
        doc = JustHTML("<p>Mail me: test@example.com</p>", transforms=[Linkify()])
        out = doc.to_html(pretty=False, safe=False)
        assert '<a href="mailto:test@example.com">test@example.com</a>' in out

    def test_linkify_does_not_linkify_inside_existing_anchor(self) -> None:
        doc = JustHTML('<p><a href="/x">example.com</a></p>', transforms=[Linkify()])
        out = doc.to_html(pretty=False, safe=False)
        assert out == '<html><head></head><body><p><a href="/x">example.com</a></p></body></html>'

    def test_linkify_skips_pre_by_default(self) -> None:
        doc = JustHTML("<pre>example.com</pre><p>example.com</p>", transforms=[Linkify()])
        out = doc.to_html(pretty=False, safe=False)
        assert "<pre>example.com</pre>" in out
        assert '<p><a href="http://example.com">example.com</a></p>' in out

    def test_linkify_handles_ampersands_in_query_strings(self) -> None:
        doc = JustHTML("<p>http://a.co?b=1&amp;c=2</p>", transforms=[Linkify()])
        out = doc.to_html(pretty=False, safe=False)
        assert 'href="http://a.co?b=1&amp;c=2"' in out
        assert ">http://a.co?b=1&amp;c=2<" in out

    def test_linkify_preserves_trailing_text_after_match(self) -> None:
        doc = JustHTML("<p>See example.com now</p>", transforms=[Linkify()])
        out = doc.to_html(pretty=False, safe=False)
        assert '<a href="http://example.com">example.com</a> now' in out

    def test_linkify_runs_inside_template_content(self) -> None:
        doc = JustHTML("<template>example.com</template>", transforms=[Linkify()])
        out = doc.to_html(pretty=False, safe=False)
        assert '<template><a href="http://example.com">example.com</a></template>' in out

    def test_apply_compiled_transforms_handles_empty_text_nodes(self) -> None:
        root = ElementNode("div", {}, "html")
        root.append_child(TextNode(""))

        compiled = compile_transforms([Linkify()])
        apply_compiled_transforms(root, compiled)

        assert root.to_html(pretty=False, safe=False) == "<div></div>"
