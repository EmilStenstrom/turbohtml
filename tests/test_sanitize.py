from __future__ import annotations

import unittest

from justhtml import JustHTML
from justhtml.node import SimpleDomNode, TemplateNode, TextNode
from justhtml.sanitize import (
    CSS_PRESET_TEXT,
    DEFAULT_POLICY,
    SanitizationPolicy,
    UrlRule,
    _css_value_may_load_external_resource,
    _is_valid_css_property_name,
    _sanitize_inline_style,
    _sanitize_url_value,
    sanitize,
)
from justhtml.serialize import to_html


class TestSanitizePlumbing(unittest.TestCase):
    def test_public_api_exports_exist(self) -> None:
        assert isinstance(DEFAULT_POLICY, SanitizationPolicy)
        assert callable(sanitize)

    def test_urlrule_and_policy_normalize_inputs(self) -> None:
        rule = UrlRule(allowed_schemes=["https"], allowed_hosts=["example.com"])
        assert isinstance(rule.allowed_schemes, set)
        assert isinstance(rule.allowed_hosts, set)

        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": []},
            url_rules={},
            drop_content_tags=["script", "style"],
            force_link_rel=["noopener"],
            allowed_css_properties=["color"],
        )
        assert isinstance(policy.allowed_tags, set)
        assert isinstance(policy.allowed_attributes, dict)
        assert isinstance(policy.drop_content_tags, set)
        assert isinstance(policy.force_link_rel, set)
        assert isinstance(policy.allowed_css_properties, set)

    def test_policy_rejects_invalid_unsafe_handling(self) -> None:
        with self.assertRaises(ValueError):
            SanitizationPolicy(
                allowed_tags=["div"],
                allowed_attributes={"*": [], "div": []},
                url_rules={},
                allowed_css_properties=["color"],
                unsafe_handling="nope",  # type: ignore[arg-type]
            )

    def test_is_valid_css_property_name(self) -> None:
        assert _is_valid_css_property_name("border-top") is True
        assert _is_valid_css_property_name("") is False
        assert _is_valid_css_property_name("co_lor") is False

    def test_sanitize_inline_style_edge_cases(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": ["style"]},
            url_rules={},
            allowed_css_properties={"color"},
        )

        assert _sanitize_inline_style(policy=policy, value="") is None

        assert _sanitize_inline_style(policy=policy, value="margin: 0") is None

        value = "color; co_lor: red; margin: 0; color: ; COLOR: red"
        assert _sanitize_inline_style(policy=policy, value=value) == "color: red"

    def test_sanitize_inline_style_returns_none_when_allowlist_empty(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": []},
            url_rules={},
            allowed_css_properties=set(),
        )

        assert _sanitize_inline_style(policy=policy, value="color: red") is None

    def test_css_preset_text_is_conservative(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": ["style"]},
            url_rules={},
            allowed_css_properties=CSS_PRESET_TEXT,
        )

        html = '<div style="color: red; position: fixed; top: 0">x</div>'
        out = JustHTML(html, fragment=True).to_html(policy=policy)
        assert out == '<div style="color: red">x</div>'

    def test_style_attribute_is_dropped_when_nothing_survives(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": ["style"]},
            url_rules={},
            allowed_css_properties=CSS_PRESET_TEXT,
        )

        html = '<div style="position: fixed">x</div>'
        out = JustHTML(html, fragment=True).to_html(policy=policy)
        assert out == "<div>x</div>"

    def test_css_value_may_load_external_resource(self) -> None:
        assert _css_value_may_load_external_resource("url(https://evil.example/x)") is True
        assert _css_value_may_load_external_resource("URL(https://evil.example/x)") is True
        assert _css_value_may_load_external_resource("u r l (https://evil.example/x)") is True
        assert _css_value_may_load_external_resource("u\\72l(https://evil.example/x)") is True
        assert _css_value_may_load_external_resource("u/**/rl(https://evil.example/x)") is True
        assert _css_value_may_load_external_resource("u/*x*/rl(https://evil.example/x)") is True
        assert _css_value_may_load_external_resource("IMAGE-SET(foo)") is True
        assert _css_value_may_load_external_resource("image/**/-set(foo)") is True
        assert _css_value_may_load_external_resource("expression(alert(1))") is True
        assert _css_value_may_load_external_resource("ex/**/pression(alert(1))") is True
        assert _css_value_may_load_external_resource("progid:DXImageTransform.Microsoft.AlphaImageLoader") is True
        assert _css_value_may_load_external_resource("AlphaImageLoader") is True
        assert _css_value_may_load_external_resource("behavior: url(x)") is True
        assert _css_value_may_load_external_resource("-moz-binding: url(x)") is True
        assert _css_value_may_load_external_resource("color: red /*") is True
        assert _css_value_may_load_external_resource("a" * 64) is False
        assert _css_value_may_load_external_resource("red") is False

    def test_sanitize_url_value_keeps_non_empty_relative_url(self) -> None:
        policy = DEFAULT_POLICY
        rule = UrlRule(allowed_schemes=[], allow_relative=True)
        assert _sanitize_url_value(policy=policy, rule=rule, tag="img", attr="src", value="/x.png") == "/x.png"
        assert _sanitize_url_value(policy=policy, rule=rule, tag="img", attr="src", value="\x00") is None

    def test_policy_accepts_pre_normalized_sets(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags={"div"},
            allowed_attributes={"*": set(), "div": {"id"}},
            url_rules={},
            drop_content_tags={"script"},
            force_link_rel={"noopener"},
        )
        assert policy.allowed_tags == {"div"}
        assert policy.allowed_attributes["div"] == {"id"}

        rule = UrlRule(allowed_schemes={"https"}, allowed_hosts=None)
        assert rule.allowed_schemes == {"https"}

    def test_sanitize_handles_nested_document_containers(self) -> None:
        # This is intentionally a "plumbing" test: these container nodes are not
        # produced by the parser as nested children, but the sanitizer supports
        # them for manually constructed DOMs.
        policy = SanitizationPolicy(
            allowed_tags=[],
            allowed_attributes={"*": []},
            url_rules={},
        )
        root = SimpleDomNode("#document-fragment")
        nested = SimpleDomNode("#document-fragment")
        nested.append_child(TextNode("t"))
        root.append_child(nested)

        out = sanitize(root, policy=policy)
        assert to_html(out, pretty=False, safe=False) == "t"

    def test_sanitize_template_subtree_without_template_content_branch(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["template"],
            allowed_attributes={"*": [], "template": []},
            url_rules={},
        )
        root = SimpleDomNode("#document-fragment")
        root.append_child(TemplateNode("template", namespace=None))
        out = sanitize(root, policy=policy)
        assert to_html(out, pretty=False, safe=False) == "<template></template>"

    def test_sanitize_attribute_edge_cases_do_not_crash(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": ["id"], "div": ["disabled"]},
            url_rules={},
        )
        n = SimpleDomNode("div", attrs={"": "x", "   ": "y", "id": None, "disabled": None})
        out = sanitize(n, policy=policy)
        html = to_html(out, pretty=False, safe=False)
        assert html in {"<div disabled id></div>", "<div id disabled></div>"}

    def test_sanitize_lowercases_attribute_names(self) -> None:
        # The parser already lowercases attribute names; build a manual node to
        # ensure sanitize() is robust to unexpected input.
        n = SimpleDomNode("a", attrs={"HREF": "https://example.com"})
        out = sanitize(n)
        html = to_html(out, pretty=False, safe=False)
        assert 'href="https://example.com"' in html

    def test_sanitize_text_root_is_cloned(self) -> None:
        out = sanitize(TextNode("x"))
        assert to_html(out, pretty=False, safe=False) == "x"

    def test_sanitize_root_comment_and_doctype_nodes_do_not_crash(self) -> None:
        # Another plumbing-only test: root comment/doctype nodes aren't typical
        # parser outputs, but sanitize() accepts any node.
        policy_keep = SanitizationPolicy(
            allowed_tags=[],
            allowed_attributes={"*": []},
            url_rules={},
            drop_comments=False,
            drop_doctype=False,
        )

        c = SimpleDomNode("#comment", data="x")
        d = SimpleDomNode("!doctype", data="html")

        assert to_html(sanitize(c, policy=policy_keep), pretty=False, safe=False) == "<!--x-->"
        assert to_html(sanitize(d, policy=policy_keep), pretty=False, safe=False) == "<!DOCTYPE html>"

        # Default policy drops these root nodes (turned into empty fragments).
        assert to_html(sanitize(c), pretty=False, safe=False) == ""
        assert to_html(sanitize(d), pretty=False, safe=False) == ""

        def test_sanitize_default_policy_differs_for_document_vs_fragment(self) -> None:
            root = JustHTML("<p>Hi</p>").root
            out = sanitize(root)
            assert to_html(out, pretty=False, safe=False) == "<html><head></head><body><p>Hi</p></body></html>"

    def test_sanitize_root_element_edge_cases(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": []},
            url_rules={},
        )

        foreign = SimpleDomNode("div", namespace="svg")
        assert to_html(sanitize(foreign, policy=policy), pretty=False, safe=False) == ""

        disallowed_subtree_drop = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": []},
            url_rules={},
            strip_disallowed_tags=False,
        )
        span = SimpleDomNode("span")
        span.append_child(TextNode("x"))
        assert to_html(sanitize(span, policy=disallowed_subtree_drop), pretty=False, safe=False) == ""

        drop_content = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": []},
            url_rules={},
            drop_content_tags={"script"},
        )
        script = SimpleDomNode("script")
        script.append_child(TextNode("alert(1)"))
        assert to_html(sanitize(script, policy=drop_content), pretty=False, safe=False) == ""

        template_policy = SanitizationPolicy(
            allowed_tags=["template"],
            allowed_attributes={"*": [], "template": []},
            url_rules={},
        )
        tpl = TemplateNode("template", namespace="html")
        assert tpl.template_content is not None
        tpl.template_content.append_child(TextNode("T"))
        assert to_html(sanitize(tpl, policy=template_policy), pretty=False, safe=False) == "<template>T</template>"

        tpl_no_content = TemplateNode("template", namespace=None)
        assert (
            to_html(sanitize(tpl_no_content, policy=template_policy), pretty=False, safe=False)
            == "<template></template>"
        )


class TestSanitizeUnsafe(unittest.TestCase):
    def test_sanitize_unsafe_raises(self) -> None:
        html = "<script>alert(1)</script>"
        node = JustHTML(html, fragment=True).root

        # Default behavior: script is removed
        sanitized = sanitize(node)
        assert to_html(sanitized) == ""

        # New behavior: raise exception
        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={},
            url_rules={},
            unsafe_handling="raise",
        )

        with self.assertRaisesRegex(ValueError, "Unsafe tag"):
            sanitize(node, policy=policy)

    def test_sanitize_unsafe_attribute_raises(self) -> None:
        html = '<p onclick="alert(1)">Hello</p>'
        node = JustHTML(html, fragment=True).root

        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={"p": set()},
            url_rules={},
            unsafe_handling="raise",
        )

        with self.assertRaisesRegex(ValueError, "Unsafe attribute"):
            sanitize(node, policy=policy)

    def test_sanitize_unsafe_url_raises(self) -> None:
        html = '<a href="javascript:alert(1)">Link</a>'
        node = JustHTML(html, fragment=True).root

        policy = SanitizationPolicy(
            allowed_tags={"a"},
            allowed_attributes={"a": {"href"}},
            url_rules={("a", "href"): UrlRule(allowed_schemes={"https"})},
            unsafe_handling="raise",
        )

        with self.assertRaisesRegex(ValueError, "Unsafe URL"):
            sanitize(node, policy=policy)

    def test_sanitize_unsafe_namespaced_attribute_raises(self) -> None:
        html = '<p xlink:href="foo">Hello</p>'
        node = JustHTML(html, fragment=True).root
        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={"p": set()},
            url_rules={},
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe attribute.*namespaced"):
            sanitize(node, policy=policy)

    def test_sanitize_unsafe_srcdoc_attribute_raises(self) -> None:
        html = '<iframe srcdoc="<script>"></iframe>'
        node = JustHTML(html, fragment=True).root
        policy = SanitizationPolicy(
            allowed_tags={"iframe"},
            allowed_attributes={"iframe": {"srcdoc"}},  # Even if allowed, srcdoc is dangerous
            url_rules={},
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe attribute.*srcdoc"):
            sanitize(node, policy=policy)

    def test_sanitize_unsafe_disallowed_attribute_raises(self) -> None:
        html = '<p foo="bar">Hello</p>'
        node = JustHTML(html, fragment=True).root
        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={"p": set()},  # No attributes allowed
            url_rules={},
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe attribute.*not allowed"):
            sanitize(node, policy=policy)

    def test_sanitize_unsafe_inline_style_raises(self) -> None:
        html = '<p style="background: url(javascript:alert(1))">Hello</p>'
        node = JustHTML(html, fragment=True).root
        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={"p": {"style"}},
            allowed_css_properties={"background"},
            url_rules={},
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe inline style"):
            sanitize(node, policy=policy)

    def test_sanitize_unsafe_root_tag_raises(self) -> None:
        # Test disallowed tag as root
        html = "<div>Content</div>"
        node = JustHTML(html, fragment=True).root
        # node is a div (because fragment=True parses into a list of nodes, but JustHTML.root wraps them?
        # Wait, JustHTML(fragment=True).root is a DocumentFragment containing the nodes.
        # sanitize() on a DocumentFragment iterates children.
        # To test root handling, we need to pass the element directly.

        div = node.children[0]
        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={},
            url_rules={},
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*not allowed"):
            sanitize(div, policy=policy)

    def test_sanitize_unsafe_root_dropped_content_raises(self) -> None:
        html = "<script>alert(1)</script>"
        node = JustHTML(html, fragment=True).root
        script = node.children[0]

        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={},
            url_rules={},
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*dropped content"):
            sanitize(script, policy=policy)

    def test_sanitize_unsafe_child_dropped_content_raises(self) -> None:
        html = "<div><script>alert(1)</script></div>"
        node = JustHTML(html, fragment=True).root
        div = node.children[0]

        policy = SanitizationPolicy(
            allowed_tags={"div"},
            allowed_attributes={"div": set()},
            url_rules={},
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*dropped content"):
            sanitize(div, policy=policy)

    def test_sanitize_unsafe_child_disallowed_tag_raises(self) -> None:
        html = "<div><foo></foo></div>"
        node = JustHTML(html, fragment=True).root
        div = node.children[0]

        policy = SanitizationPolicy(
            allowed_tags={"div"},
            allowed_attributes={"div": set()},
            url_rules={},
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*not allowed"):
            sanitize(div, policy=policy)

    def test_sanitize_unsafe_root_foreign_namespace_raises(self) -> None:
        # <svg> puts elements in SVG namespace
        html = "<svg><title>foo</title></svg>"
        node = JustHTML(html, fragment=True).root
        svg = node.children[0]

        policy = SanitizationPolicy(
            allowed_tags={"svg"},  # Even if allowed, foreign namespaces might be dropped
            allowed_attributes={"svg": set()},
            url_rules={},
            drop_foreign_namespaces=True,
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*foreign namespace"):
            sanitize(svg, policy=policy)

    def test_sanitize_unsafe_child_foreign_namespace_raises(self) -> None:
        html = "<div><svg></svg></div>"
        node = JustHTML(html, fragment=True).root
        div = node.children[0]

        policy = SanitizationPolicy(
            allowed_tags={"div"},
            allowed_attributes={"div": set()},
            url_rules={},
            drop_foreign_namespaces=True,
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*foreign namespace"):
            sanitize(div, policy=policy)

    def test_sanitize_unsafe_root_disallowed_no_strip_raises(self) -> None:
        html = "<x-foo></x-foo>"
        node = JustHTML(html, fragment=True).root
        xfoo = node.children[0]

        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={},
            url_rules={},
            strip_disallowed_tags=False,  # Don't strip, just drop
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*not allowed"):
            sanitize(xfoo, policy=policy)


if __name__ == "__main__":
    unittest.main()
