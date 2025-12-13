import unittest

from justhtml import JustHTML
from justhtml.serialize import (
    _can_unquote_attr_value,
    _choose_attr_quote,
    _escape_attr_value,
    _escape_text,
    serialize_end_tag,
    serialize_start_tag,
    to_html,
    to_test_format,
)
from justhtml.treebuilder import SimpleDomNode as Node
from justhtml.treebuilder import TemplateNode


class TestSerialize(unittest.TestCase):
    def test_basic_document(self):
        html = "<!DOCTYPE html><html><head><title>Test</title></head><body><p>Hello</p></body></html>"
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert "<!DOCTYPE html>" in output
        assert "<title>Test</title>" in output
        assert "<p>Hello</p>" in output

    def test_attributes(self):
        html = '<div id="test" class="foo" data-val="x&y"></div>'
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert ("id=test" in output) or ('id="test"' in output)
        assert ("class=foo" in output) or ('class="foo"' in output)
        assert ("data-val=x&amp;y" in output) or ('data-val="x&amp;y"' in output)  # Check escaping

    def test_text_escaping(self):
        frag = Node("#document-fragment")
        div = Node("div")
        frag.append_child(div)
        div.append_child(Node("#text", data="a<b&c"))
        output = to_html(frag, pretty=False)
        assert output == "<div>a&lt;b&amp;c</div>"

    def test_void_elements(self):
        html = "<br><hr><img>"
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert "<br>" in output
        assert "<hr>" in output
        assert "<img>" in output
        assert "</br>" not in output

    def test_comments(self):
        html = "<!-- hello world -->"
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert "<!-- hello world -->" in output

    def test_document_fragment(self):
        # Manually create a document fragment since parser returns Document
        frag = Node("#document-fragment")
        child = Node("div")
        frag.append_child(child)
        output = to_html(frag)
        assert "<div></div>" in output

    def test_text_only_children(self):
        html = "<div>Text only</div>"
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert "<div>Text only</div>" in output

    def test_mixed_children(self):
        html = "<div>Text <span>Span</span></div>"
        doc = JustHTML(html)
        output = doc.root.to_html()
        # This might be rendered with indentation
        assert "<div>" in output
        assert "Text" in output
        assert "<span>Span</span>" in output

    def test_empty_attributes(self):
        html = "<input disabled>"
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert "<input disabled>" in output

    def test_none_attributes(self):
        # Manually create node with None attribute value
        node = Node("div")
        node.attrs = {"data-test": None}
        output = to_html(node)
        assert "<div data-test></div>" in output

    def test_empty_string_attribute(self):
        html = '<div data-val=""></div>'
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert "<div data-val></div>" in output

    def test_serialize_start_tag_quotes(self):
        # Prefer single quotes if the value contains a double quote but no single quote
        tag = serialize_start_tag("span", {"title": 'foo"bar'})
        assert tag == "<span title='foo\"bar'>"

        # Otherwise use double quotes and escape embedded double quotes
        tag = serialize_start_tag("span", {"title": "foo'bar\"baz"})
        assert tag == '<span title="foo\'bar&quot;baz">'

        # Unquoted when safe
        assert serialize_start_tag("span", {"title": "foo"}) == "<span title=foo>"
        assert _can_unquote_attr_value("foo<bar") is True
        assert _can_unquote_attr_value("foo>bar") is False
        assert _can_unquote_attr_value('foo"bar') is False
        assert _can_unquote_attr_value("foo bar") is False

    def test_serialize_end_tag(self):
        assert serialize_end_tag("span") == "</span>"

    def test_serializer_private_helpers_none(self):
        assert _escape_text(None) == ""
        assert _choose_attr_quote(None) == '"'
        assert _escape_attr_value(None, '"') == ""
        assert _can_unquote_attr_value(None) is False

    def test_mixed_content_whitespace(self):
        html = "<div>   <p></p></div>"
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert "<div>" in output
        assert "<p></p>" in output

    def test_whitespace_in_fragment(self):
        frag = Node("#document-fragment")
        # SimpleDomNode constructor: name, attrs=None, data=None, namespace=None
        text_node = Node("#text", data="   ")
        frag.append_child(text_node)
        output = to_html(frag)
        assert output == ""

    def test_element_with_nested_children(self):
        # Test serialize.py line 82->86: all_text branch when NOT all text
        html = "<div><span>inner</span></div>"
        doc = JustHTML(html)
        output = doc.root.to_html()
        assert "<div>" in output
        assert "<span>inner</span>" in output
        assert "</div>" in output

    def test_element_without_attributes(self):
        # Test serialize.py line 82->86: attr_parts is empty (no attributes)
        node = Node("div")
        text_node = Node("#text", data="hello")
        node.append_child(text_node)
        output = to_html(node)
        assert output == "<div>hello</div>"

    def test_to_test_format_single_element(self):
        # Test to_test_format on non-document node (line 102)
        node = Node("div")
        output = to_test_format(node)
        assert output == "| <div>"

    def test_to_test_format_template_with_attributes(self):
        # Test template with attributes (line 126)
        template = TemplateNode("template", namespace="html")
        template.attrs = {"id": "t1"}
        child = Node("p")
        template.template_content.append_child(child)
        output = to_test_format(template)
        assert "| <template>" in output
        assert '|   id="t1"' in output
        assert "|   content" in output
        assert "|     <p>" in output


if __name__ == "__main__":
    unittest.main()
