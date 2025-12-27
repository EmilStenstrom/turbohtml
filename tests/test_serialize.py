import unittest

from justhtml import JustHTML
from justhtml.serialize import (
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
        output = doc.root.to_html(safe=False)
        assert "<!DOCTYPE html>" in output
        assert "<title>Test</title>" in output
        assert "<p>Hello</p>" in output

    def test_attributes(self):
        html = '<div id="test" class="foo" data-val="x&y"></div>'
        doc = JustHTML(html)
        output = doc.root.to_html(safe=False)
        assert 'id="test"' in output
        assert 'class="foo"' in output
        assert 'data-val="x&amp;y"' in output  # Check escaping

    def test_text_escaping(self):
        frag = Node("#document-fragment")
        div = Node("div")
        frag.append_child(div)
        div.append_child(Node("#text", data="a<b&c"))
        output = to_html(frag, pretty=False, safe=False)
        assert output == "<div>a&lt;b&amp;c</div>"

    def test_void_elements(self):
        html = "<br><hr><img>"
        doc = JustHTML(html)
        output = doc.root.to_html(safe=False)
        assert "<br>" in output
        assert "<hr>" in output
        assert "<img>" in output
        assert "</br>" not in output

    def test_comments(self):
        html = "<!-- hello world -->"
        doc = JustHTML(html)
        output = doc.root.to_html(safe=False)
        assert "<!-- hello world -->" in output

    def test_document_fragment(self):
        # Manually create a document fragment since parser returns Document
        frag = Node("#document-fragment")
        child = Node("div")
        frag.append_child(child)
        output = to_html(frag, safe=False)
        assert "<div></div>" in output

    def test_text_only_children(self):
        html = "<div>Text only</div>"
        doc = JustHTML(html)
        output = doc.root.to_html(safe=False)
        assert "<div>Text only</div>" in output

    def test_mixed_children(self):
        html = "<div>Text <span>Span</span></div>"
        doc = JustHTML(html)
        div = doc.query("div")[0]
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div>Text <span>Span</span></div>"

    def test_pretty_print_does_not_insert_spaces_in_inline_mixed_content(self):
        html = (
            '<code class="constructorsynopsis cpp">'
            '<span class="methodname">BApplication</span>'
            '(<span class="methodparam">'
            '<span class="modifier">const </span>'
            '<span class="type">char* </span>'
            '<span class="parameter">signature</span>'
            "</span>);"
            "</code>"
        )
        doc = JustHTML(html)
        code = doc.query("code")[0]

        pretty_html = code.to_html(pretty=True, safe=False)
        assert "</span>(<span" in pretty_html

        rendered_text = JustHTML(pretty_html).to_text(separator="", strip=False)
        assert rendered_text == "BApplication(const char* signature);"

    def test_empty_attributes(self):
        html = "<input disabled>"
        doc = JustHTML(html)
        output = doc.root.to_html(safe=False)
        assert "<input disabled>" in output

    def test_none_attributes(self):
        # Manually create node with None attribute value
        node = Node("div")
        node.attrs = {"data-test": None}
        output = to_html(node, safe=False)
        assert "<div data-test></div>" in output

    def test_empty_string_attribute(self):
        html = '<div data-val=""></div>'
        doc = JustHTML(html)
        output = doc.root.to_html(safe=False)
        assert "<div data-val></div>" in output

    def test_serialize_start_tag_quotes(self):
        # Prefer single quotes if the value contains a double quote but no single quote
        tag = serialize_start_tag("span", {"title": 'foo"bar'})
        assert tag == "<span title='foo\"bar'>"

        # Otherwise use double quotes and escape embedded double quotes
        tag = serialize_start_tag("span", {"title": "foo'bar\"baz"})
        assert tag == '<span title="foo\'bar&quot;baz">'

        # Always quote normal attribute values
        assert serialize_start_tag("span", {"title": "foo"}) == '<span title="foo">'

    def test_serialize_end_tag(self):
        assert serialize_end_tag("span") == "</span>"

    def test_serializer_private_helpers_none(self):
        assert _escape_text(None) == ""
        assert _choose_attr_quote(None) == '"'
        assert _escape_attr_value(None, '"') == ""

    def test_mixed_content_whitespace(self):
        html = "<div>   <p></p></div>"
        doc = JustHTML(html)
        output = doc.root.to_html(safe=False)
        assert "<div>" in output
        assert "<p></p>" in output

    def test_pretty_indent_skips_whitespace_text_nodes(self):
        div = Node("div")
        div.append_child(Node("#text", data="\n  "))
        div.append_child(Node("p"))
        div.append_child(Node("#text", data="\n"))
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div>\n  <p></p>\n</div>"

    def test_pretty_indent_children_does_not_indent_inline_elements(self):
        div = Node("div")
        div.append_child(Node("span"))
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div><span></span></div>"

    def test_pretty_indent_children_does_not_indent_comments(self):
        div = Node("div")
        div.append_child(Node("#comment", data="x"))
        div.append_child(Node("p"))
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div><!--x--><p></p></div>"

    def test_whitespace_in_fragment(self):
        frag = Node("#document-fragment")
        # SimpleDomNode constructor: name, attrs=None, data=None, namespace=None
        text_node = Node("#text", data="   ")
        frag.append_child(text_node)
        output = to_html(frag, safe=False)
        assert output == ""

    def test_text_node_pretty_strips_and_renders(self):
        frag = Node("#document-fragment")
        frag.append_child(Node("#text", data="  hi  "))
        output = to_html(frag, pretty=True, safe=False)
        assert output == "hi"

    def test_empty_text_node_is_dropped_when_not_pretty(self):
        div = Node("div")
        div.append_child(Node("#text", data=""))
        output = to_html(div, pretty=False, safe=False)
        assert output == "<div></div>"

    def test_element_with_nested_children(self):
        # Test serialize.py line 82->86: all_text branch when NOT all text
        html = "<div><span>inner</span></div>"
        doc = JustHTML(html)
        output = doc.root.to_html(safe=False)
        assert "<div>" in output
        assert "<span>inner</span>" in output
        assert "</div>" in output

    def test_element_without_attributes(self):
        # Test serialize.py line 82->86: attr_parts is empty (no attributes)
        node = Node("div")
        text_node = Node("#text", data="hello")
        node.append_child(text_node)
        output = to_html(node, safe=False)
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
