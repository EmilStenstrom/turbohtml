import textwrap
import unittest

from justhtml import JustHTML
from justhtml.context import FragmentContext
from justhtml.serialize import (
    _can_unquote_attr_value,
    _choose_attr_quote,
    _collapse_html_whitespace,
    _escape_attr_value,
    _escape_text,
    _normalize_formatting_whitespace,
    _should_pretty_indent_children,
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

    def test_safe_document_serialization_preserves_document_wrappers(self):
        doc = JustHTML("<p>Hi</p>")
        output = doc.to_html(pretty=False)
        assert output == "<html><head></head><body><p>Hi</p></body></html>"

    def test_fragment_parameter_default_context(self):
        doc = JustHTML("<p>Hi</p>", fragment=True)
        assert doc.root.name == "#document-fragment"

        output = doc.to_html(pretty=False, safe=False)
        assert "<html>" not in output
        assert output == "<p>Hi</p>"

    def test_fragment_parameter_respects_explicit_fragment_context(self):
        # <tr> only parses correctly in table-related fragment contexts.
        doc = JustHTML(
            "<tr><td>cell</td></tr>",
            fragment=True,
            fragment_context=FragmentContext("tbody"),
        )
        output = doc.to_html(pretty=False, safe=False)
        assert output == "<tr><td>cell</td></tr>"

    def test_collapse_html_whitespace_vertical_tab(self):
        # \v is not HTML whitespace, so it should be preserved as a non-whitespace character
        # while surrounding whitespace is collapsed.
        text = "  a  \v  b  "
        # Expected: "a \v b" because \v is treated as a regular character,
        # so "  a  " -> "a ", "\v", "  b  " -> " b"
        # Wait, let's trace the logic:
        # "  a  \v  b  "
        # parts: [" ", "a", " ", "\v", " ", "b", " "] (roughly)
        # joined: " a \v b " -> stripped: "a \v b"
        self.assertEqual(_collapse_html_whitespace(text), "a \v b")

    def test_can_unquote_attr_value_coverage(self):
        self.assertFalse(_can_unquote_attr_value(None))
        self.assertTrue(_can_unquote_attr_value("foo"))
        self.assertFalse(_can_unquote_attr_value("foo bar"))
        self.assertFalse(_can_unquote_attr_value("foo=bar"))
        self.assertFalse(_can_unquote_attr_value("foo'bar"))
        self.assertFalse(_can_unquote_attr_value('foo"bar'))
        # < is allowed in unquoted attribute values in HTML5
        self.assertTrue(_can_unquote_attr_value("foo<bar"))

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

    def test_pretty_text_only_element_collapses_whitespace(self):
        doc = JustHTML("<h3>\n\nSorry to interrupt, but we're short on time to hit our goal.\n</h3>")
        h3 = doc.query("h3")[0]
        assert h3.to_html(pretty=True, safe=False) == (
            "<h3>Sorry to interrupt, but we're short on time to hit our goal.</h3>"
        )

    def test_pretty_text_only_div_collapses_whitespace(self):
        html = (
            '<div class="overlay-banner-main-footer-cta">'
            "\n\nWe ask you, sincerely: don't skip this, join the 2% of readers who give.\n"
            "</div>"
        )
        doc = JustHTML(html)
        div = doc.query("div")[0]
        assert div.to_html(pretty=True, safe=False) == (
            '<div class="overlay-banner-main-footer-cta">'
            "We ask you, sincerely: don't skip this, join the 2% of readers who give."
            "</div>"
        )

    def test_pretty_text_only_element_empty_text_is_dropped(self):
        h3 = Node("h3")
        h3.append_child(Node("#text", data=""))
        assert h3.to_html(pretty=True, safe=False) == "<h3></h3>"

    def test_pretty_text_only_script_preserves_whitespace(self):
        doc = JustHTML("<script>\n  var x = 1;\n\n  var y = 2;\n</script>")
        script = doc.query("script")[0]
        assert script.to_html(pretty=True, safe=False) == ("<script>\n  var x = 1;\n\n  var y = 2;\n</script>")

    def test_compact_mode_does_not_normalize_script_text_children(self):
        # Artificial tree to cover serializer branch: skip normalization inside rawtext elements.
        script = Node("script")
        script.append_child(Node("#text", data="a\nb"))
        script.append_child(Node("span"))
        assert script.to_html(pretty=True, safe=False) == "<script>a\nb<span></span></script>"

    def test_mixed_children(self):
        html = "<div>Text <span>Span</span></div>"
        doc = JustHTML(html)
        div = doc.query("div")[0]
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div>Text <span>Span</span></div>"

    def test_mixed_children_normalizes_newlines_in_text_nodes(self):
        html = '<span>100+\n <span class="jsl10n">articles</span></span>'
        doc = JustHTML(html)
        outer = doc.query("span")[0]
        output = outer.to_html(pretty=True, safe=False)
        assert "100+ <span" in output
        assert "100+\n" not in output

        html2 = '<span class="text">\n100+\n <span class="jsl10n">articles</span></span>'
        doc2 = JustHTML(html2)
        outer2 = doc2.query("span")[0]
        output2 = outer2.to_html(pretty=True, safe=False)
        assert ">100+ <span" in output2

    def test_mixed_children_preserves_pure_space_runs(self):
        html = "<p>Hello  <b>world</b></p>"
        doc = JustHTML(html)
        p = doc.query("p")[0]
        assert p.to_html(pretty=True, safe=False) == "<p>Hello  <b>world</b></p>"

    def test_normalize_formatting_whitespace_empty(self):
        assert _normalize_formatting_whitespace("") == ""

    def test_normalize_formatting_whitespace_no_formatting_chars(self):
        assert _normalize_formatting_whitespace("a  b") == "a  b"

    def test_normalize_formatting_whitespace_preserves_double_spaces(self):
        # Contains a newline (so normalization runs), but the double-space run does
        # not include formatting whitespace and should be preserved.
        assert _normalize_formatting_whitespace("a  b\nc") == "a  b c"

    def test_normalize_formatting_whitespace_collapses_newlines_and_tabs(self):
        assert _normalize_formatting_whitespace("a\n\t  b") == "a b"

    def test_normalize_formatting_whitespace_trims_edges_from_newlines(self):
        assert _normalize_formatting_whitespace("\n100+\n ") == "100+ "
        assert _normalize_formatting_whitespace(" hi\n") == " hi"

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

    def test_serialize_start_tag_unquoted_mode_and_escape_lt(self):
        # In unquoted mode, escape '&' always and optionally '<' when configured.
        assert (
            serialize_start_tag(
                "span",
                {"title": "a<b&c"},
                quote_attr_values=False,
                escape_lt_in_attrs=True,
            )
            == "<span title=a&lt;b&amp;c>"
        )

    def test_serialize_start_tag_none_attr_non_minimized(self):
        # When boolean minimization is disabled, None becomes an explicit empty value.
        assert (
            serialize_start_tag(
                "span",
                {"disabled": None},
                minimize_boolean_attributes=False,
            )
            == '<span disabled="">'
        )

    def test_serialize_end_tag(self):
        assert serialize_end_tag("span") == "</span>"

    def test_serializer_private_helpers_none(self):
        assert _escape_text(None) == ""
        assert _choose_attr_quote(None) == '"'
        assert _escape_attr_value(None, '"') == ""

        # Covered for branch completeness: unquote check rejects None.
        assert _can_unquote_attr_value(None) is False

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
        expected = textwrap.dedent(
            """\
            <div>
              <p></p>
            </div>
            """
        ).strip("\n")
        assert output == expected

    def test_pretty_indent_children_does_not_indent_inline_elements(self):
        div = Node("div")
        div.append_child(Node("span"))
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div><span></span></div>"

    def test_pretty_indent_children_does_not_indent_adjacent_inline_elements(self):
        div = Node("div")
        div.append_child(Node("span"))
        div.append_child(Node("em"))
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div><span></span><em></em></div>"

    def test_compact_pretty_collapses_large_whitespace_gaps(self):
        # Two adjacent inline children are rendered in compact mode.
        # For block-ish containers with whitespace separators, compact pretty upgrades
        # to a multiline layout for readability.
        div = Node("div")
        div.append_child(Node("span"))
        div.append_child(Node("#text", data="     "))
        div.append_child(Node("span"))
        output = div.to_html(pretty=True, safe=False)
        expected = textwrap.dedent(
            """\
            <div>
              <span></span>
              <span></span>
            </div>
            """
        ).strip("\n")
        assert output == expected

    def test_compact_pretty_collapses_newline_whitespace_to_single_space(self):
        # Newlines/tabs between inline siblings upgrade to multiline layout.
        div = Node("div")
        div.append_child(Node("span"))
        div.append_child(Node("#text", data="\n  \t"))
        div.append_child(Node("span"))
        output = div.to_html(pretty=True, safe=False)
        expected = textwrap.dedent(
            """\
            <div>
              <span></span>
              <span></span>
            </div>
            """
        ).strip("\n")
        assert output == expected

    def test_should_pretty_indent_children_no_element_children(self):
        children = [Node("#text", data="  "), Node("#text", data="\n")]
        assert _should_pretty_indent_children(children) is True

    def test_compact_pretty_preserves_small_spacing_exactly(self):
        # When there is already whitespace separating element siblings in a block-ish
        # container, prefer multiline formatting over preserving exact whitespace.
        div = Node("div")
        div.append_child(Node("span"))
        div.append_child(Node("#text", data="  "))
        div.append_child(Node("span"))
        output = div.to_html(pretty=True, safe=False)
        expected = textwrap.dedent(
            """\
            <div>
              <span></span>
              <span></span>
            </div>
            """
        ).strip("\n")
        assert output == expected

    def test_compact_pretty_skips_none_children(self):
        div = Node("div")
        # Manually inject a None child to exercise defensive branch.
        div.children = [Node("span"), None, Node("em")]
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div><span></span><em></em></div>"

    def test_compact_pretty_drops_empty_text_children(self):
        div = Node("div")
        div.append_child(Node("span"))
        div.append_child(Node("#text", data=""))
        div.append_child(Node("span"))
        output = div.to_html(pretty=True, safe=False)
        expected = textwrap.dedent(
            """\
            <div>
              <span></span>
              <span></span>
            </div>
            """
        ).strip("\n")
        assert output == expected

    def test_compact_pretty_drops_leading_and_trailing_whitespace(self):
        div = Node("div")
        div.append_child(Node("#text", data=" \n"))
        div.append_child(Node("a"))
        div.append_child(Node("#text", data=" \t\n"))
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div><a></a></div>"

    def test_blockish_compact_multiline_not_used_with_comment_children(self):
        div = Node("div")
        div.append_child(Node("span"))
        div.append_child(Node("#text", data=" "))
        div.append_child(Node("#comment", data="x"))
        div.append_child(Node("#text", data=" "))
        div.append_child(Node("span"))
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div><span></span> <!--x--> <span></span></div>"

    def test_blockish_compact_multiline_not_used_with_non_whitespace_text(self):
        div = Node("div")
        div.append_child(Node("span"))
        div.append_child(Node("#text", data="hi"))
        div.append_child(Node("#text", data=" "))
        div.append_child(Node("span"))
        output = div.to_html(pretty=True, safe=False)
        assert output == "<div><span></span>hi <span></span></div>"

    def test_blockish_compact_multiline_allows_trailing_text(self):
        div = Node("div")
        div.append_child(Node("div"))
        div.append_child(Node("#text", data=" "))
        div.append_child(Node("div"))
        div.append_child(Node("#text", data=" Collapse\n"))

        output = div.to_html(pretty=True, safe=False)
        expected = textwrap.dedent(
            """\
            <div>
              <div></div>
              <div></div>
              Collapse
            </div>
            """
        ).strip("\n")
        assert output == expected

    def test_blockish_compact_multiline_skips_when_inner_lines_are_empty(self):
        # Exercise the multiline eligibility path where it matches, but each
        # child renders to an empty string (so we fall back to compact mode).
        div = Node("div")
        frag1 = Node("#document-fragment")
        frag1.append_child(Node("#text", data="  "))
        frag2 = Node("#document-fragment")
        frag2.append_child(Node("#text", data="\n"))
        div.append_child(frag1)
        div.append_child(Node("#text", data=" "))
        div.append_child(frag2)

        output = div.to_html(pretty=True, safe=False)
        assert output == "<div> </div>"

    def test_blockish_compact_multiline_skips_none_children(self):
        div = Node("div")
        div.children = [Node("span"), Node("#text", data=" "), None, Node("span")]
        output = div.to_html(pretty=True, safe=False)
        expected = textwrap.dedent(
            """\
            <div>
              <span></span>
              <span></span>
            </div>
            """
        ).strip("\n")
        assert output == expected

    def test_compact_mode_collapses_newline_whitespace_for_inline_container(self):
        # For non-block containers, we stay in compact mode and collapse
        # formatting whitespace to a single space.
        outer = Node("span")
        outer.append_child(Node("span"))
        outer.append_child(Node("#text", data="\n  \t"))
        outer.append_child(Node("span"))
        output = outer.to_html(pretty=True, safe=False)
        assert output == "<span><span></span> <span></span></span>"

    def test_indents_single_anchor_child_when_anchor_wraps_block_elements(self):
        container = Node("div")
        link = Node("a")
        link.append_child(Node("div"))
        link.append_child(Node("div"))
        container.append_child(link)

        output = container.to_html(pretty=True, safe=False)
        expected = textwrap.dedent(
            """\
            <div>
              <a>
                <div></div>
                <div></div>
              </a>
            </div>
            """
        ).strip("\n")
        assert output == expected

    def test_single_anchor_child_not_blockish_without_special_grandchildren(self):
        link = Node("a")
        link.children = [None, Node("span")]
        assert _should_pretty_indent_children([link]) is False

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
