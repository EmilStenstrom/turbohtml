from __future__ import annotations

import unittest

import justhtml
from justhtml import JustHTML
from justhtml.node import SimpleDomNode, TemplateNode, TextNode
from justhtml.sanitize import (
    CSS_PRESET_TEXT,
    DEFAULT_POLICY,
    SanitizationPolicy,
    UnsafeHandler,
    UrlPolicy,
    UrlProxy,
    UrlRule,
    _css_value_may_load_external_resource,
    _is_valid_css_property_name,
    _sanitize_inline_style,
    _sanitize_url_value,
    _srcset_contains_external_url,
    _url_is_external,
)
from justhtml.sanitize import (
    _sanitize as sanitize,
)
from justhtml.serialize import to_html
from justhtml.tokens import ParseError


class TestSanitizePlumbing(unittest.TestCase):
    def test_public_api_exports_exist(self) -> None:
        assert isinstance(DEFAULT_POLICY, SanitizationPolicy)
        assert "sanitize" not in justhtml.__all__
        assert "Sanitize" in justhtml.__all__
        assert callable(sanitize)

    def test_urlproxy_rejects_empty_url(self) -> None:
        with self.assertRaises(ValueError):
            UrlProxy(url="")

    def test_urlrule_and_policy_normalize_inputs(self) -> None:
        rule = UrlRule(allowed_schemes=["https"], allowed_hosts=["example.com"])
        assert isinstance(rule.allowed_schemes, set)
        assert isinstance(rule.allowed_hosts, set)

        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": []},
            url_policy=UrlPolicy(allow_rules={}),
            drop_content_tags=["script", "style"],
            force_link_rel=["noopener"],
            allowed_css_properties=["color"],
        )
        assert isinstance(policy.allowed_tags, set)
        assert isinstance(policy.allowed_attributes, dict)
        assert isinstance(policy.drop_content_tags, set)
        assert isinstance(policy.force_link_rel, set)
        assert isinstance(policy.allowed_css_properties, set)

    def test_urlrule_rejects_non_urlproxy_instance(self) -> None:
        with self.assertRaises(TypeError):
            UrlRule(proxy="/proxy")  # type: ignore[arg-type]

    def test_policy_rejects_invalid_unsafe_handling(self) -> None:
        with self.assertRaises(ValueError):
            SanitizationPolicy(
                allowed_tags=["div"],
                allowed_attributes={"*": [], "div": []},
                url_policy=UrlPolicy(allow_rules={}),
                allowed_css_properties=["color"],
                unsafe_handling="nope",  # type: ignore[arg-type]
            )

    def test_url_policy_rejects_invalid_url_handling(self) -> None:
        with self.assertRaises(ValueError):
            UrlPolicy(default_handling="nope")  # type: ignore[arg-type]

    def test_url_policy_coerces_rules_to_dict(self) -> None:
        url_policy = UrlPolicy(
            allow_rules=[(("a", "href"), UrlRule(allowed_schemes={"https"}))],
        )
        assert isinstance(url_policy.allow_rules, dict)

    def test_url_policy_rejects_non_urlproxy_instance(self) -> None:
        with self.assertRaises(TypeError):
            UrlPolicy(proxy="/proxy")  # type: ignore[arg-type]

    def test_url_policy_proxy_mode_requires_proxy_config(self) -> None:
        with self.assertRaises(ValueError):
            UrlPolicy(
                allow_rules={("a", "href"): UrlRule(handling="proxy", allowed_schemes={"https"})},
            )

    def test_is_valid_css_property_name(self) -> None:
        assert _is_valid_css_property_name("border-top") is True
        assert _is_valid_css_property_name("") is False
        assert _is_valid_css_property_name("co_lor") is False

    def test_sanitize_inline_style_edge_cases(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": ["style"]},
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
            allowed_css_properties=set(),
        )

        assert _sanitize_inline_style(policy=policy, value="color: red") is None

    def test_css_preset_text_is_conservative(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": ["style"]},
            url_policy=UrlPolicy(allow_rules={}),
            allowed_css_properties=CSS_PRESET_TEXT,
        )

        html = '<div style="color: red; position: fixed; top: 0">x</div>'
        out = JustHTML(html, fragment=True).to_html(policy=policy)
        assert out == '<div style="color: red">x</div>'

    def test_style_attribute_is_dropped_when_nothing_survives(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": ["style"]},
            url_policy=UrlPolicy(allow_rules={}),
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
        rule = UrlRule(allowed_schemes=[])
        assert _sanitize_url_value(policy=policy, rule=rule, tag="img", attr="src", value="/x.png") == "/x.png"
        assert _sanitize_url_value(policy=policy, rule=rule, tag="img", attr="src", value="\x00") is None

    def test_url_like_attributes_require_explicit_rules(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["src"]},
            url_policy=UrlPolicy(allow_rules={}),
        )
        out = JustHTML('<img src="/x">', fragment=True).to_html(policy=policy)
        assert out == "<img>"

    def test_url_policy_remote_strip_blocks_remote_but_keeps_relative(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["src"]},
            url_policy=UrlPolicy(
                default_handling="strip",
                default_allow_relative=True,
                allow_rules={("img", "src"): UrlRule(allowed_schemes={"https"})},
            ),
        )

        out = JustHTML('<img src="https://example.com/x">', fragment=True).to_html(policy=policy)
        assert out == '<img src="https://example.com/x">'

        out = JustHTML('<img src="/x">', fragment=True).to_html(policy=policy)
        assert out == '<img src="/x">'

    def test_url_rule_handling_strip_drops_absolute_url(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["src"]},
            url_policy=UrlPolicy(
                allow_rules={
                    ("img", "src"): UrlRule(
                        handling="strip",
                        allowed_schemes={"https"},
                    )
                },
            ),
        )

        out = JustHTML('<img src="https://example.com/x">', fragment=True).to_html(policy=policy)
        assert out == "<img>"

    def test_url_rule_handling_strip_drops_relative_url(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["src"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                allow_rules={
                    ("img", "src"): UrlRule(
                        handling="strip",
                        allowed_schemes=set(),
                        resolve_protocol_relative=None,
                    )
                },
            ),
        )

        out = JustHTML('<img src="/x">', fragment=True).to_html(policy=policy)
        assert out == "<img>"

    def test_url_rule_relative_only_blocks_remote_but_keeps_relative(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["src"]},
            url_policy=UrlPolicy(
                default_handling="allow",
                default_allow_relative=True,
                allow_rules={
                    ("img", "src"): UrlRule(
                        allowed_schemes=set(),
                        resolve_protocol_relative=None,
                    )
                },
            ),
        )

        out = JustHTML('<img src="https://example.com/x">', fragment=True).to_html(policy=policy)
        assert out == "<img>"

        out = JustHTML('<img src="/x">', fragment=True).to_html(policy=policy)
        assert out == '<img src="/x">'

    def test_url_rule_can_override_global_strip(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["src"]},
            url_policy=UrlPolicy(
                default_allow_relative=False,
                allow_rules={
                    ("img", "src"): UrlRule(
                        allow_relative=True,
                        allowed_schemes=set(),
                        resolve_protocol_relative=None,
                    )
                },
            ),
        )

        out = JustHTML('<img src="/x">', fragment=True).to_html(policy=policy)
        assert out == '<img src="/x">'

        out = JustHTML('<img src="https://example.com/x">', fragment=True).to_html(policy=policy)
        assert out == "<img>"

    def test_url_policy_remote_strip_blocks_protocol_relative(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["src"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                allow_rules={
                    ("img", "src"): UrlRule(
                        handling="strip",
                        allowed_schemes={"https"},
                        resolve_protocol_relative="https",
                    )
                },
            ),
        )

        out = JustHTML('<img src="//example.com/x">', fragment=True).to_html(policy=policy)
        assert out == "<img>"

    def test_url_policy_remote_proxy_rewrites_protocol_relative(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["src"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                proxy=UrlProxy(url="/proxy"),
                allow_rules={
                    ("img", "src"): UrlRule(
                        handling="proxy",
                        allowed_schemes={"https"},
                        resolve_protocol_relative="https",
                    )
                },
            ),
        )

        out = JustHTML('<img src="//example.com/x">', fragment=True).to_html(policy=policy)
        assert out == '<img src="/proxy?url=https%3A%2F%2Fexample.com%2Fx">'

    def test_url_policy_remote_proxy_global_and_img_override(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["a", "img"],
            allowed_attributes={"*": [], "a": ["href"], "img": ["src"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                proxy=UrlProxy(url="/proxy", param="url"),
                allow_rules={
                    ("a", "href"): UrlRule(handling="proxy", allowed_schemes={"https"}),
                    ("img", "src"): UrlRule(
                        handling="proxy",
                        allowed_schemes={"https"},
                        proxy=UrlProxy(url="/image-proxy", param="url"),
                    ),
                },
            ),
        )

        out = JustHTML('<a href="https://example.com/x">x</a>', fragment=True).to_html(policy=policy)
        assert out == '<a href="/proxy?url=https%3A%2F%2Fexample.com%2Fx">x</a>'

        out = JustHTML('<img src="https://example.com/x">', fragment=True).to_html(policy=policy)
        assert out == '<img src="/image-proxy?url=https%3A%2F%2Fexample.com%2Fx">'

    def test_url_policy_proxy_does_not_bypass_scheme_checks(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["a"],
            allowed_attributes={"*": [], "a": ["href"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                proxy=UrlProxy(url="/proxy"),
                allow_rules={
                    ("a", "href"): UrlRule(
                        handling="proxy",
                        allowed_schemes=set(),
                    )
                },
            ),
        )

        out = JustHTML('<a href="https://example.com/x">x</a>', fragment=True).to_html(policy=policy)
        assert out == "<a>x</a>"

    def test_url_policy_proxy_rewrites_fragment_urls(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["a"],
            allowed_attributes={"*": [], "a": ["href"]},
            url_policy=UrlPolicy(
                proxy=UrlProxy(url="/proxy"),
                allow_rules={
                    ("a", "href"): UrlRule(
                        handling="proxy",
                        allowed_schemes={"https"},
                        allow_fragment=True,
                    )
                },
            ),
        )

        out = JustHTML('<a href="#x">x</a>', fragment=True).to_html(policy=policy)
        assert out == '<a href="/proxy?url=%23x">x</a>'

    def test_url_policy_strip_drops_fragment_urls(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["a"],
            allowed_attributes={"*": [], "a": ["href"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                allow_rules={
                    ("a", "href"): UrlRule(
                        handling="strip",
                        allowed_schemes={"https"},
                        allow_fragment=True,
                    )
                },
            ),
        )

        out = JustHTML('<a href="#x">x</a>', fragment=True).to_html(policy=policy)
        assert out == "<a>x</a>"

    def test_url_is_external_helper(self) -> None:
        assert _url_is_external("") is False
        assert _url_is_external("#x") is False
        assert _url_is_external("/x") is False
        assert _url_is_external("//example.com/x") is True
        assert _url_is_external("https://example.com/x") is True

    def test_srcset_external_scanner_helper(self) -> None:
        assert _srcset_contains_external_url("/a 1x, /b 2x") is False
        assert _srcset_contains_external_url("\t ,  \n") is False
        assert _srcset_contains_external_url("https://example.com/a 1x, /b 2x") is True

    def test_url_policy_proxy_rewrites_remote_srcset_candidates(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["srcset"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                proxy=UrlProxy(url="/proxy"),
                allow_rules={("img", "srcset"): UrlRule(handling="proxy", allowed_schemes={"https"})},
            ),
        )

        out = JustHTML('<img srcset="https://example.com/a 1x, /b 2x">', fragment=True).to_html(policy=policy)
        assert out == '<img srcset="/proxy?url=https%3A%2F%2Fexample.com%2Fa 1x, /proxy?url=%2Fb 2x">'

    def test_srcset_is_dropped_if_url_filter_drops_value(self) -> None:
        def url_filter(tag: str, attr: str, value: str) -> str | None:
            assert tag == "img"
            assert attr == "srcset"
            assert value
            return None

        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["srcset"]},
            url_policy=UrlPolicy(
                default_handling="allow",
                default_allow_relative=True,
                allow_rules={("img", "srcset"): UrlRule(allowed_schemes={"https"})},
                url_filter=url_filter,
            ),
        )

        out = JustHTML('<img srcset="https://example.com/a 1x">', fragment=True).to_html(policy=policy)
        assert out == "<img>"

    def test_srcset_is_dropped_if_empty(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["srcset"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                allow_rules={("img", "srcset"): UrlRule(allowed_schemes={"https"})},
            ),
        )

        out = JustHTML('<img srcset="  \t\n  ">', fragment=True).to_html(policy=policy)
        assert out == "<img>"

    def test_srcset_url_filter_can_rewrite_value(self) -> None:
        def url_filter(tag: str, attr: str, value: str) -> str | None:
            assert tag == "img"
            assert attr == "srcset"
            assert value == "ignored"
            return "https://example.com/a 1x"

        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["srcset"]},
            url_policy=UrlPolicy(
                default_handling="allow",
                default_allow_relative=True,
                allow_rules={("img", "srcset"): UrlRule(allowed_schemes={"https"})},
                url_filter=url_filter,
            ),
        )

        out = JustHTML('<img srcset="ignored">', fragment=True).to_html(policy=policy)
        assert out == '<img srcset="https://example.com/a 1x">'

    def test_srcset_skips_empty_candidates(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["srcset"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                proxy=UrlProxy(url="/proxy"),
                allow_rules={("img", "srcset"): UrlRule(handling="proxy", allowed_schemes={"https"})},
            ),
        )

        out = JustHTML('<img srcset=", https://example.com/a 1x">', fragment=True).to_html(policy=policy)
        assert out == '<img srcset="/proxy?url=https%3A%2F%2Fexample.com%2Fa 1x">'

    def test_srcset_is_dropped_if_any_candidate_is_invalid(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["img"],
            allowed_attributes={"*": [], "img": ["srcset"]},
            url_policy=UrlPolicy(
                default_allow_relative=True,
                proxy=UrlProxy(url="/proxy"),
                allow_rules={("img", "srcset"): UrlRule(handling="proxy", allowed_schemes={"https"})},
            ),
        )

        out = JustHTML('<img srcset="http://example.com/a 1x, https://example.com/b 2x">', fragment=True).to_html(
            policy=policy
        )
        assert out == "<img>"

    def test_policy_accepts_pre_normalized_sets(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags={"div"},
            allowed_attributes={"*": set(), "div": {"id"}},
            url_policy=UrlPolicy(allow_rules={}),
            drop_content_tags={"script"},
            force_link_rel={"noopener"},
        )
        assert policy.allowed_tags == {"div"}
        assert policy.allowed_attributes["div"] == {"id"}

        rule = UrlRule(allowed_schemes={"https"}, allowed_hosts=None)
        assert rule.allowed_schemes == {"https"}

    def test_url_rule_rejects_invalid_url_handling_override(self) -> None:
        with self.assertRaises(ValueError):
            UrlRule(handling="nope")

    def test_url_policy_rejects_non_urlrule_values(self) -> None:
        with self.assertRaises(TypeError):
            UrlPolicy(allow_rules={("a", "href"): "not-a-rule"})

    def test_sanitize_handles_nested_document_containers(self) -> None:
        # This is intentionally a "plumbing" test: these container nodes are not
        # produced by the parser as nested children, but the sanitizer supports
        # them for manually constructed DOMs.
        policy = SanitizationPolicy(
            allowed_tags=[],
            allowed_attributes={"*": []},
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
        )
        root = SimpleDomNode("#document-fragment")
        root.append_child(TemplateNode("template", namespace=None))
        out = sanitize(root, policy=policy)
        assert to_html(out, pretty=False, safe=False) == "<template></template>"

    def test_sanitize_attribute_edge_cases_do_not_crash(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": ["id"], "div": ["disabled"]},
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
        )

        foreign = SimpleDomNode("div", namespace="svg")
        assert to_html(sanitize(foreign, policy=policy), pretty=False, safe=False) == ""

        disallowed_subtree_drop = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": []},
            url_policy=UrlPolicy(allow_rules={}),
        )
        span = SimpleDomNode("span")
        span.append_child(TextNode("x"))
        assert to_html(sanitize(span, policy=disallowed_subtree_drop), pretty=False, safe=False) == "x"

        drop_content = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": [], "div": []},
            url_policy=UrlPolicy(allow_rules={}),
            drop_content_tags={"script"},
        )
        script = SimpleDomNode("script")
        script.append_child(TextNode("alert(1)"))
        assert to_html(sanitize(script, policy=drop_content), pretty=False, safe=False) == ""

        template_policy = SanitizationPolicy(
            allowed_tags=["template"],
            allowed_attributes={"*": [], "template": []},
            url_policy=UrlPolicy(allow_rules={}),
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
    def test_unsafe_handler_collect_initializes_on_first_use(self) -> None:
        # Cover the centralized handler's fast path when used standalone
        # (without an explicit reset call).
        h = UnsafeHandler("collect")
        h.handle("Unsafe tag 'x'", node=None)
        errs = h.collected()
        assert len(errs) == 1
        assert errs[0].category == "security"

    def test_unsafe_handler_collected_filters_shared_sink(self) -> None:
        h = UnsafeHandler("collect")
        sink = [
            ParseError("unexpected-null-character", category="tokenizer"),
            ParseError("unsafe-html", category="security"),
        ]
        h.sink = sink
        errs = h.collected()
        assert len(errs) == 1
        assert errs[0].category == "security"

    def test_collect_mode_can_run_with_no_security_findings(self) -> None:
        doc = JustHTML("<p>ok</p>", fragment=True)

        policy = SanitizationPolicy(
            allowed_tags=set(DEFAULT_POLICY.allowed_tags),
            allowed_attributes=DEFAULT_POLICY.allowed_attributes,
            url_policy=DEFAULT_POLICY.url_policy,
            allowed_css_properties=DEFAULT_POLICY.allowed_css_properties,
            force_link_rel=DEFAULT_POLICY.force_link_rel,
            unsafe_handling="collect",
        )

        _ = doc.to_html(pretty=False, policy=policy)
        assert doc.errors == []

    def test_policy_collect_helpers_cover_empty_paths(self) -> None:
        # Non-collect policy: collection helpers are no-ops.
        policy_strip = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={},
            url_policy=UrlPolicy(allow_rules={}),
            unsafe_handling="strip",
        )
        policy_strip.reset_collected_security_errors()
        assert policy_strip.collected_security_errors() == []

        # Collect policy: calling handle_unsafe directly records a security finding.
        policy_collect = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={},
            url_policy=UrlPolicy(allow_rules={}),
            unsafe_handling="collect",
        )
        policy_collect.reset_collected_security_errors()
        policy_collect.handle_unsafe("Unsafe tag 'x'", node=None)
        errs = policy_collect.collected_security_errors()
        assert len(errs) == 1
        assert errs[0].category == "security"
        assert errs[0].line is None
        assert errs[0].column is None

    def test_sanitize_unsafe_collects_security_errors(self) -> None:
        html = "<script>alert(1)</script>"
        node = JustHTML(html, fragment=True, track_node_locations=True).root

        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={},
            url_policy=UrlPolicy(allow_rules={}),
            unsafe_handling="collect",
        )

        out = sanitize(node, policy=policy)
        assert to_html(out) == ""

        errors = policy.collected_security_errors()
        assert len(errors) == 1
        assert errors[0].category == "security"
        assert errors[0].code == "unsafe-html"
        assert "Unsafe tag 'script'" in errors[0].message

    def test_collect_mode_merges_into_doc_errors(self) -> None:
        html = "<p>\x00</p><script>alert(1)</script>"
        doc = JustHTML(html, fragment=True, collect_errors=True, track_node_locations=True)
        assert any(e.category == "tokenizer" for e in doc.errors)

        policy = SanitizationPolicy(
            allowed_tags=set(DEFAULT_POLICY.allowed_tags),
            allowed_attributes=DEFAULT_POLICY.allowed_attributes,
            url_policy=DEFAULT_POLICY.url_policy,
            allowed_css_properties=DEFAULT_POLICY.allowed_css_properties,
            force_link_rel=DEFAULT_POLICY.force_link_rel,
            unsafe_handling="collect",
        )

        _ = doc.to_html(pretty=False, policy=policy)
        assert any(e.category == "security" for e in doc.errors)

        # Repeated calls should not accumulate duplicates.
        before = len([e for e in doc.errors if e.category == "security"])
        _ = doc.to_html(pretty=False, policy=policy)
        after = len([e for e in doc.errors if e.category == "security"])
        assert before == after

    def test_collect_mode_merges_into_doc_errors_text_and_markdown(self) -> None:
        doc = JustHTML("<p>ok</p><script>alert(1)</script>", fragment=True, track_node_locations=True)

        policy = SanitizationPolicy(
            allowed_tags=set(DEFAULT_POLICY.allowed_tags),
            allowed_attributes=DEFAULT_POLICY.allowed_attributes,
            url_policy=DEFAULT_POLICY.url_policy,
            allowed_css_properties=DEFAULT_POLICY.allowed_css_properties,
            force_link_rel=DEFAULT_POLICY.force_link_rel,
            unsafe_handling="collect",
        )

        _ = doc.to_text(policy=policy)
        assert any(e.category == "security" for e in doc.errors)

        _ = doc.to_markdown(policy=policy)
        assert any(e.category == "security" for e in doc.errors)

    def test_justhtml_serialization_clears_stale_security_errors_and_safe_false_paths(self) -> None:
        doc = JustHTML("<p>ok</p><script>alert(1)</script>", fragment=True, track_node_locations=True)

        policy = SanitizationPolicy(
            allowed_tags=set(DEFAULT_POLICY.allowed_tags),
            allowed_attributes=DEFAULT_POLICY.allowed_attributes,
            url_policy=DEFAULT_POLICY.url_policy,
            allowed_css_properties=DEFAULT_POLICY.allowed_css_properties,
            force_link_rel=DEFAULT_POLICY.force_link_rel,
            unsafe_handling="collect",
        )

        _ = doc.to_html(pretty=False, policy=policy)
        assert any(e.category == "security" for e in doc.errors)

        # Safe serialization with no collect should clear security errors.
        _ = doc.to_html(pretty=False, policy=None)
        assert not any(e.category == "security" for e in doc.errors)

        # Cover safe=False branches (these should not crash).
        _ = doc.to_html(pretty=False, safe=False)
        _ = doc.to_text(safe=False)
        _ = doc.to_markdown(safe=False)

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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={("a", "href"): UrlRule(allowed_schemes={"https"})}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
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
            url_policy=UrlPolicy(allow_rules={}),
            drop_foreign_namespaces=True,
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*foreign namespace"):
            sanitize(div, policy=policy)

    def test_sanitize_unsafe_root_disallowed_raises(self) -> None:
        html = "<x-foo></x-foo>"
        node = JustHTML(html, fragment=True).root
        xfoo = node.children[0]

        policy = SanitizationPolicy(
            allowed_tags={"p"},
            allowed_attributes={},
            url_policy=UrlPolicy(allow_rules={}),
            unsafe_handling="raise",
        )
        with self.assertRaisesRegex(ValueError, "Unsafe tag.*not allowed"):
            sanitize(xfoo, policy=policy)


if __name__ == "__main__":
    unittest.main()
