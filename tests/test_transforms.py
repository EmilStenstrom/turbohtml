from __future__ import annotations

import unittest

from justhtml import JustHTML, SelectorError
from justhtml.node import ElementNode, SimpleDomNode, TemplateNode, TextNode
from justhtml.sanitize import SanitizationPolicy, UrlPolicy, UrlRule
from justhtml.transforms import (
    AllowlistAttrs,
    AllowStyleAttrs,
    CollapseWhitespace,
    Decide,
    DecideAction,
    Drop,
    DropAttrs,
    DropForeignNamespaces,
    DropUrlAttrs,
    Edit,
    EditAttrs,
    EditDocument,
    Empty,
    Linkify,
    MergeAttrs,
    PruneEmpty,
    Sanitize,
    SetAttrs,
    Stage,
    Unwrap,
    _glob_match,
    apply_compiled_transforms,
    compile_transforms,
    emit_error,
)


class TestTransforms(unittest.TestCase):
    def test_glob_match_star_matches_everything(self) -> None:
        assert _glob_match("*", "anything") is True
        # Ensure the trailing-'*' consumption loop is exercised too.
        assert _glob_match("**", "") is True

    def test_glob_match_returns_false_on_wildcard_mismatch(self) -> None:
        # Exercise the internal mismatch path for wildcard patterns.
        assert _glob_match("a?c", "axd") is False

    def test_compile_transforms_rejects_unknown_transform_type(self) -> None:
        with self.assertRaises(TypeError):
            compile_transforms([object()])

    def test_rewriteattrs_selector_star_uses_all_nodes_fast_path(self) -> None:
        root = SimpleDomNode("#document-fragment")
        root.append_child(ElementNode("div", {"a": "1"}, "html"))

        def cb(node: SimpleDomNode) -> dict[str, str | None] | None:
            out = dict(node.attrs)
            out["b"] = "2"
            return out

        compiled = compile_transforms([EditAttrs("*", cb)])
        apply_compiled_transforms(root, compiled)
        assert root.children[0].attrs.get("b") == "2"

    def test_compile_transforms_fuses_adjacent_rewriteattrs_with_same_selector(self) -> None:
        root = SimpleDomNode("#document-fragment")
        root.append_child(ElementNode("div", {"a": "1"}, "html"))

        def cb1(node: SimpleDomNode) -> dict[str, str | None] | None:
            out = dict(node.attrs)
            out["b"] = "2"
            return out

        def cb2(node: SimpleDomNode) -> dict[str, str | None] | None:
            out = dict(node.attrs)
            out["c"] = "3"
            return out

        compiled = compile_transforms([EditAttrs("*", cb1), EditAttrs("*", cb2)])
        # Fused into a single rewrite-attrs transform.
        assert sum(1 for t in compiled if getattr(t, "kind", None) == "rewrite_attrs") == 1

        apply_compiled_transforms(root, compiled)
        assert root.children[0].attrs == {"a": "1", "b": "2", "c": "3"}

    def test_constructor_accepts_transforms_and_applies_setattrs(self) -> None:
        doc = JustHTML("<p>Hello</p>", transforms=[SetAttrs("p", id="x")])
        assert doc.to_html(pretty=False, safe=False) == '<html><head></head><body><p id="x">Hello</p></body></html>'

    def test_constructor_compiles_selectors_and_raises_early(self) -> None:
        with self.assertRaises(SelectorError):
            JustHTML("<p>Hello</p>", transforms=[SetAttrs("div[invalid", id="x")])

    def test_drop_removes_nodes(self) -> None:
        doc = JustHTML("<p>ok</p><script>alert(1)</script>", transforms=[Drop("script")])
        assert doc.to_html(pretty=False, safe=False) == "<html><head></head><body><p>ok</p></body></html>"

    def test_unwrap_hoists_children(self) -> None:
        doc = JustHTML("<p>Hello <span>world</span></p>", transforms=[Unwrap("span")])
        assert doc.to_html(pretty=False, safe=False) == "<html><head></head><body><p>Hello world</p></body></html>"

    def test_unwrap_handles_empty_elements(self) -> None:
        doc = JustHTML("<div><span></span>ok</div>", transforms=[Unwrap("span")])
        assert doc.to_html(pretty=False, safe=False) == "<html><head></head><body><div>ok</div></body></html>"

    def test_empty_removes_children_but_keeps_element(self) -> None:
        doc = JustHTML("<div><b>x</b>y</div>", transforms=[Empty("div")])
        assert doc.to_html(pretty=False, safe=False) == "<html><head></head><body><div></div></body></html>"

    def test_empty_also_clears_template_content(self) -> None:
        doc = JustHTML("<template><b>x</b></template>", transforms=[Empty("template")])
        assert doc.to_html(pretty=False, safe=False) == "<html><head><template></template></head><body></body></html>"

    def test_edit_can_mutate_attrs(self) -> None:
        def cb(node):
            node.attrs["data-x"] = "1"

        doc = JustHTML('<a href="https://e.com">x</a>', transforms=[Edit("a", cb)])
        assert 'data-x="1"' in doc.to_html(pretty=False, safe=False)

    def test_editdocument_runs_once_on_root(self) -> None:
        seen: list[str] = []

        def cb(root: SimpleDomNode) -> None:
            seen.append(str(root.name))
            root.append_child(SimpleDomNode("p"))

        doc = JustHTML("<p>x</p>", fragment=True, transforms=[EditDocument(cb)])
        assert seen == ["#document-fragment"]
        assert doc.to_html(pretty=False, safe=False) == "<p>x</p><p></p>"

    def test_walk_transforms_traverse_root_template_content(self) -> None:
        root = TemplateNode("template", attrs={}, namespace="html")
        assert root.template_content is not None
        root.template_content.append_child(ElementNode("p", {}, "html"))

        apply_compiled_transforms(root, compile_transforms([SetAttrs("p", id="x")]))
        assert root.to_html(pretty=False, safe=False) == '<template><p id="x"></p></template>'

    def test_transform_callbacks_can_emit_errors_without_parse_error_collection(self) -> None:
        def cb(node: SimpleDomNode) -> None:
            emit_error("transform-warning", node=node, message="bad <p>")

        doc = JustHTML(
            "<!--x--><p>Hello</p>",
            track_node_locations=True,
            transforms=[Edit("p", cb), SetAttrs("p", id="x")],
        )
        assert len(doc.errors) == 1
        err = doc.errors[0]
        assert err.category == "transform"
        assert err.code == "transform-warning"
        assert err.message == "bad <p>"
        assert err.line is not None
        assert err.column is not None
        assert 'id="x"' in doc.to_html(pretty=False, safe=False)

    def test_transform_callback_errors_merge_with_parse_errors_when_collect_errors_true(self) -> None:
        doc = JustHTML(
            "<p>\x00</p>",
            collect_errors=True,
            track_node_locations=True,
            transforms=[Edit("p", lambda n: emit_error("transform-warning", node=n, message="bad <p>"))],
        )
        codes = {e.code for e in doc.errors}
        assert "transform-warning" in codes
        assert "unexpected-null-character" in codes

    def test_emit_error_noops_without_active_sink(self) -> None:
        root = JustHTML("<p>x</p>", fragment=True, track_node_locations=True).root
        compiled = compile_transforms([Edit("p", lambda n: emit_error("x", node=n, message="msg"))])
        apply_compiled_transforms(root, compiled)

        errs = []
        compiled2 = compile_transforms([Edit("p", lambda n: emit_error("x", line=1, column=2, message="msg"))])
        apply_compiled_transforms(root, compiled2, errors=errs)
        assert len(errs) == 1
        assert errs[0].code == "x"
        assert errs[0].line == 1
        assert errs[0].column == 2

    def test_transforms_run_in_order_and_drop_short_circuits(self) -> None:
        doc = JustHTML(
            "<p>Hello</p>",
            transforms=[SetAttrs("p", id="x"), Drop("p"), SetAttrs("p", class_="y")],
        )
        assert doc.to_html(pretty=False, safe=False) == "<html><head></head><body></body></html>"

    def test_disabled_transforms_are_omitted_at_compile_time(self) -> None:
        doc = JustHTML(
            "<p>ok</p><script>alert(1)</script><div><b>x</b></div>",
            transforms=[
                Drop("script", enabled=False),
                Unwrap("b", enabled=False),
                Empty("div", enabled=False),
            ],
        )
        assert (
            doc.to_html(pretty=False, safe=False)
            == "<html><head></head><body><p>ok</p><script>alert(1)</script><div><b>x</b></div></body></html>"
        )

    def test_drop_with_callback_uses_general_selector_path_when_not_simple_tag_list(self) -> None:
        dropped: list[str] = []

        def on_drop(node: SimpleDomNode) -> None:
            dropped.append(str(node.name))

        doc = JustHTML(
            '<div class="x"></div><div class="y"></div>',
            fragment=True,
            transforms=[Drop("div.x", on_drop=on_drop)],
        )
        assert doc.to_html(pretty=False, safe=False) == '<div class="y"></div>'
        assert dropped == ["div"]

    def test_drop_with_callback_tag_list_fast_path_rejection_still_validates_selector(self) -> None:
        dropped: list[str] = []

        def on_drop(node: SimpleDomNode) -> None:
            dropped.append(str(node.name))

        doc = JustHTML(
            "<script>x</script><p>ok</p>",
            fragment=True,
            transforms=[Drop("script, ", on_drop=on_drop)],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>ok</p>"
        assert dropped == ["script"]

    def test_drop_foreign_namespaces_can_report_to_policy(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["p"],
            allowed_attributes={"*": []},
            unsafe_handling="collect",
        )
        policy.reset_collected_security_errors()

        root = SimpleDomNode("#document-fragment")
        root.append_child(ElementNode("svg", {}, "svg"))

        apply_compiled_transforms(root, compile_transforms([DropForeignNamespaces(on_report=policy.handle_unsafe)]))
        assert root.children == []
        assert policy.collected_security_errors()

    def test_drop_foreign_namespaces_drops_even_without_policy(self) -> None:
        root = SimpleDomNode("#document-fragment")
        root.append_child(ElementNode("svg", {}, "svg"))

        apply_compiled_transforms(root, compile_transforms([DropForeignNamespaces(on_report=None)]))
        assert root.children == []

    def test_dropattrs_patterns_cover_event_namespaced_and_exact(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": []},
            unsafe_handling="collect",
        )
        policy.reset_collected_security_errors()

        root = SimpleDomNode("#document-fragment")
        node = ElementNode(
            "div",
            {
                "onClick": "1",
                "xml:lang": "sv",
                "srcdoc": "<p>x</p>",
                "href": "https://example.com/",
                " ": "ignored",
            },
            "html",
        )
        root.append_child(node)

        apply_compiled_transforms(
            root,
            compile_transforms(
                [
                    DropAttrs(
                        "*",
                        patterns=("on*", "*:*", "srcdoc", "href"),
                        on_report=policy.handle_unsafe,
                    )
                ]
            ),
        )
        assert node.attrs == {}
        assert len(policy.collected_security_errors()) == 4

    def test_dropattrs_can_be_disabled(self) -> None:
        root = SimpleDomNode("#document-fragment")
        node = ElementNode("div", {"onclick": "1"}, "html")
        root.append_child(node)

        apply_compiled_transforms(root, compile_transforms([DropAttrs("*", patterns=("on*",), enabled=False)]))
        assert node.attrs == {"onclick": "1"}

    def test_dropattrs_with_no_policy_still_drops(self) -> None:
        root = SimpleDomNode("#document-fragment")
        node = ElementNode("div", {"onClick": "1", "xml:lang": "sv", "srcdoc": "x"}, "html")
        root.append_child(node)

        apply_compiled_transforms(
            root,
            compile_transforms([DropAttrs("*", patterns=("on*", "*:*", "srcdoc"), on_report=None)]),
        )
        assert node.attrs == {}

    def test_allowlistattrs_lowercases_keys_skips_blank_and_reports_disallowed(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["a"],
            allowed_attributes={"*": [], "a": ["href"]},
            force_link_rel={"noopener"},
            unsafe_handling="collect",
        )
        policy.reset_collected_security_errors()

        root = SimpleDomNode("#document-fragment")
        a = ElementNode(
            "a",
            {
                "HREF": "https://example.com",
                "Rel": "noreferrer",
                "BAD": "x",
                " ": "ignored",
            },
            "html",
        )
        root.append_child(a)

        apply_compiled_transforms(
            root,
            compile_transforms(
                [
                    AllowlistAttrs(
                        "*",
                        allowed_attributes={"*": [], "a": ["href", "rel"]},
                        on_report=policy.handle_unsafe,
                    )
                ]
            ),
        )
        assert a.attrs.get("href") == "https://example.com"
        assert a.attrs.get("rel") == "noreferrer"
        assert "bad" not in a.attrs
        assert policy.collected_security_errors()

    def test_allowlistattrs_can_be_disabled(self) -> None:
        root = SimpleDomNode("#document-fragment")
        a = ElementNode("a", {"href": "https://example.com", "bad": "x"}, "html")
        root.append_child(a)

        apply_compiled_transforms(
            root,
            compile_transforms([AllowlistAttrs("*", allowed_attributes={"*": [], "a": ["href"]}, enabled=False)]),
        )
        assert a.attrs == {"href": "https://example.com", "bad": "x"}

    def test_allowlistattrs_without_policy_drops_without_reporting(self) -> None:
        root = SimpleDomNode("#document-fragment")
        a = ElementNode("a", {"href": "https://example.com", "bad": "x"}, "html")
        root.append_child(a)

        apply_compiled_transforms(
            root,
            compile_transforms(
                [
                    AllowlistAttrs(
                        "*",
                        allowed_attributes={"*": [], "a": ["href"]},
                        on_report=None,
                    )
                ],
            ),
        )
        assert a.attrs == {"href": "https://example.com"}

    def test_dropurlattrs_branches_raw_none_no_rule_and_invalid_url(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["a", "img"],
            allowed_attributes={"*": [], "a": ["href"], "img": ["src"]},
            url_policy=UrlPolicy(
                default_handling="allow",
                allow_rules={
                    ("a", "href"): UrlRule(allowed_schemes={"http", "https"}),
                },
            ),
            unsafe_handling="collect",
        )
        policy.reset_collected_security_errors()

        root = SimpleDomNode("#document-fragment")
        a_none = ElementNode("a", {"href": None}, "html")
        img_no_rule = ElementNode("img", {"src": "https://example.com/x.png"}, "html")
        a_bad = ElementNode("a", {"href": "javascript:alert(1)"}, "html")
        root.append_child(a_none)
        root.append_child(img_no_rule)
        root.append_child(a_bad)

        apply_compiled_transforms(
            root,
            compile_transforms([DropUrlAttrs("*", url_policy=policy.url_policy, on_report=policy.handle_unsafe)]),
        )
        assert "href" not in a_none.attrs
        assert "src" not in img_no_rule.attrs
        assert "href" not in a_bad.attrs
        assert len(policy.collected_security_errors()) == 3

    def test_dropurlattrs_works_without_on_unsafe_callback(self) -> None:
        url_policy = UrlPolicy(
            default_handling="allow",
            allow_rules={
                ("a", "href"): UrlRule(allowed_schemes={"http", "https"}),
            },
        )

        root = SimpleDomNode("#document-fragment")
        a_none = ElementNode("a", {"href": None}, "html")
        img_no_rule = ElementNode("img", {"src": "https://example.com/x.png"}, "html")
        a_bad = ElementNode("a", {"href": "javascript:alert(1)"}, "html")
        root.append_child(a_none)
        root.append_child(img_no_rule)
        root.append_child(a_bad)

        apply_compiled_transforms(root, compile_transforms([DropUrlAttrs("*", url_policy=url_policy)]))
        assert "href" not in a_none.attrs
        assert "src" not in img_no_rule.attrs
        assert "href" not in a_bad.attrs

    def test_dropurlattrs_allows_valid_srcset(self) -> None:
        url_policy = UrlPolicy(
            default_handling="allow",
            allow_rules={
                ("img", "srcset"): UrlRule(allowed_schemes={"https"}),
            },
        )

        root = SimpleDomNode("#document-fragment")
        img = ElementNode("img", {"srcset": "https://example.com/a 1x"}, "html")
        root.append_child(img)

        apply_compiled_transforms(root, compile_transforms([DropUrlAttrs("*", url_policy=url_policy)]))
        assert img.attrs.get("srcset") == "https://example.com/a 1x"

    def test_dropurlattrs_can_be_disabled(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["a"],
            allowed_attributes={"*": [], "a": ["href"]},
            url_policy=UrlPolicy(allow_rules={("a", "href"): UrlRule(allowed_schemes={"http", "https"})}),
            unsafe_handling="collect",
        )
        policy.reset_collected_security_errors()

        doc = JustHTML(
            '<a href="javascript:alert(1)">x</a>',
            fragment=True,
            transforms=[
                DropUrlAttrs("*", url_policy=policy.url_policy, enabled=False, on_report=policy.handle_unsafe)
            ],
        )
        assert doc.to_html(pretty=False, safe=False) == '<a href="javascript:alert(1)">x</a>'
        assert policy.collected_security_errors() == []

    def test_allowstyleattrs_branches_raw_none_and_sanitized_none(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["span"],
            allowed_attributes={"*": ["style"]},
            allowed_css_properties={"color"},
            unsafe_handling="collect",
        )
        policy.reset_collected_security_errors()

        root = SimpleDomNode("#document-fragment")
        s_none = ElementNode("span", {"style": None}, "html")
        s_bad = ElementNode("span", {"style": "position: fixed"}, "html")
        s_ok = ElementNode("span", {"style": "color: red; position: fixed"}, "html")
        s_no_style = ElementNode("span", {}, "html")
        root.append_child(s_none)
        root.append_child(s_bad)
        root.append_child(s_ok)
        root.append_child(s_no_style)

        apply_compiled_transforms(
            root,
            compile_transforms(
                [
                    AllowStyleAttrs(
                        "span",
                        allowed_css_properties=policy.allowed_css_properties,
                        on_report=policy.handle_unsafe,
                    )
                ]
            ),
        )
        assert "style" not in s_none.attrs
        assert "style" not in s_bad.attrs
        assert s_ok.attrs.get("style") == "color: red"
        assert s_no_style.attrs == {}
        assert len(policy.collected_security_errors()) == 2

    def test_allowstyleattrs_works_without_on_unsafe_callback(self) -> None:
        root = SimpleDomNode("#document-fragment")
        s_none = ElementNode("span", {"style": None}, "html")
        s_bad = ElementNode("span", {"style": "position: fixed"}, "html")
        s_ok = ElementNode("span", {"style": "color: red"}, "html")
        root.append_child(s_none)
        root.append_child(s_bad)
        root.append_child(s_ok)

        apply_compiled_transforms(
            root,
            compile_transforms([AllowStyleAttrs("span", allowed_css_properties={"color"})]),
        )
        assert "style" not in s_none.attrs
        assert "style" not in s_bad.attrs
        assert s_ok.attrs.get("style") == "color: red"

    def test_allowstyleattrs_can_be_disabled(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["span"],
            allowed_attributes={"*": ["style"]},
            allowed_css_properties={"color"},
            unsafe_handling="collect",
        )
        policy.reset_collected_security_errors()

        doc = JustHTML(
            '<span style="position: fixed">x</span>',
            fragment=True,
            transforms=[
                AllowStyleAttrs(
                    "[style]",
                    allowed_css_properties=policy.allowed_css_properties,
                    enabled=False,
                    on_report=policy.handle_unsafe,
                )
            ],
        )
        assert doc.to_html(pretty=False, safe=False) == '<span style="position: fixed">x</span>'
        assert policy.collected_security_errors() == []

    def test_mergeattrs_rewrites_on_add_missing_and_normalization(self) -> None:
        doc = JustHTML(
            '<a></a><a rel="NoOpEnEr noopener"></a><a rel="noreferrer"></a><a rel="noopener"></a>',
            fragment=True,
            transforms=[MergeAttrs("a", attr="rel", tokens={"noopener"})],
        )
        assert (
            doc.to_html(pretty=False, safe=False)
            == '<a rel="noopener"></a><a rel="noopener"></a><a rel="noreferrer noopener"></a><a rel="noopener"></a>'
        )

    def test_mergeattrs_skips_non_matching_elements(self) -> None:
        doc = JustHTML(
            "<div></div><a></a>",
            fragment=True,
            transforms=[MergeAttrs("a", attr="rel", tokens={"noopener"})],
        )
        assert doc.to_html(pretty=False, safe=False) == '<div></div><a rel="noopener"></a>'

    def test_mergeattrs_is_skipped_if_no_tokens(self) -> None:
        compiled = compile_transforms([MergeAttrs("a", attr="rel", tokens=set())])
        assert compiled == []

    def test_dropattrs_noops_when_patterns_empty(self) -> None:
        root = SimpleDomNode("#document-fragment")
        node = ElementNode("div", {"id": "x"}, "html")
        root.append_child(node)

        apply_compiled_transforms(root, compile_transforms([DropAttrs("*", patterns=())]))
        assert node.attrs == {"id": "x"}

    def test_disabled_top_level_stage_is_skipped(self) -> None:
        # Ensure disabled stages are skipped both when flattening and when
        # splitting into top-level stages.
        doc = JustHTML(
            "<p>Hello</p>",
            fragment=True,
            transforms=[
                Stage([SetAttrs("p", id="x")], enabled=False),
                Stage([SetAttrs("p", **{"class": "y"})]),
            ],
        )
        html = doc.to_html(pretty=False, safe=False)
        assert 'id="x"' not in html
        assert 'class="y"' in html

    def test_apply_compiled_transforms_empty_list_noops(self) -> None:
        root = SimpleDomNode("#document-fragment")
        root.append_child(ElementNode("p", {}, "html"))
        apply_compiled_transforms(root, [])

    def test_selector_transforms_skip_comment_nodes(self) -> None:
        doc = JustHTML("<!--x--><p>y</p>", transforms=[SetAttrs("p", id="x")])
        assert '<p id="x">y</p>' in doc.to_html(pretty=False, safe=False)

    def test_decide_star_can_drop_comment_nodes(self) -> None:
        def decide(node: object) -> DecideAction:
            name = getattr(node, "name", "")
            if name == "#comment":
                return Decide.DROP
            return Decide.KEEP

        doc = JustHTML("<!--x--><p>y</p>", fragment=True, transforms=[Decide("*", decide)])
        assert doc.to_html(pretty=False, safe=False) == "<p>y</p>"

    def test_decide_selector_only_runs_on_elements(self) -> None:
        seen: list[str] = []

        def decide(node: object) -> DecideAction:
            name = getattr(node, "name", "")
            # Decide("p", ...) should never be called for non-elements.
            assert not str(name).startswith("#")
            seen.append(str(name))
            return Decide.DROP

        doc = JustHTML("<!--x--><p>y</p>", fragment=True, transforms=[Decide("p", decide)])
        assert doc.to_html(pretty=False, safe=False) == "<!--x-->"
        assert seen == ["p"]

    def test_decide_empty_clears_template_content(self) -> None:
        def decide(node: object) -> DecideAction:
            if getattr(node, "name", "") == "template":
                return Decide.EMPTY
            return Decide.KEEP

        doc = JustHTML("<template><b>x</b></template>", fragment=True, transforms=[Decide("*", decide)])
        assert doc.to_html(pretty=False, safe=False) == "<template></template>"

    def test_decide_empty_clears_element_children(self) -> None:
        doc = JustHTML(
            "<div><span>x</span>y</div>",
            fragment=True,
            transforms=[Decide("div", lambda n: Decide.EMPTY)],
        )
        assert doc.to_html(pretty=False, safe=False) == "<div></div>"

    def test_decide_unwrap_hoists_template_content(self) -> None:
        doc = JustHTML(
            "<div><template><b>x</b></template>y</div>",
            fragment=True,
            transforms=[Decide("template", lambda n: Decide.UNWRAP)],
        )
        assert doc.to_html(pretty=False, safe=False) == "<div><b>x</b>y</div>"

    def test_decide_unwrap_hoists_element_children(self) -> None:
        doc = JustHTML(
            "<div><span><b>x</b></span>y</div>",
            fragment=True,
            transforms=[Decide("span", lambda n: Decide.UNWRAP)],
        )
        assert doc.to_html(pretty=False, safe=False) == "<div><b>x</b>y</div>"

    def test_decide_unwrap_with_no_children_still_removes_node(self) -> None:
        doc = JustHTML(
            "<div><span></span>ok</div><div><template></template>y</div>",
            fragment=True,
            transforms=[Decide("span, template", lambda n: Decide.UNWRAP)],
        )
        assert doc.to_html(pretty=False, safe=False) == "<div>ok</div><div>y</div>"

    def test_rewriteattrs_can_replace_attribute_dict(self) -> None:
        def rewrite(node: SimpleDomNode) -> dict[str, str | None] | None:
            assert node.name == "a"
            return {"href": node.attrs.get("href"), "data-ok": "1"}

        doc = JustHTML('<a href="x" onclick="y">t</a>', fragment=True, transforms=[EditAttrs("a", rewrite)])
        assert doc.to_html(pretty=False, safe=False) == '<a href="x" data-ok="1">t</a>'

    def test_rewriteattrs_returning_none_noops(self) -> None:
        doc = JustHTML('<a href="x">t</a>', fragment=True, transforms=[EditAttrs("a", lambda n: None)])
        assert doc.to_html(pretty=False, safe=False) == '<a href="x">t</a>'

    def test_rewriteattrs_skips_non_matching_elements(self) -> None:
        doc = JustHTML("<p>t</p>", fragment=True, transforms=[EditAttrs("a", lambda n: {"x": "1"})])
        assert doc.to_html(pretty=False, safe=False) == "<p>t</p>"

    def test_walk_transforms_traverse_nested_document_containers(self) -> None:
        root = SimpleDomNode("#document-fragment")
        nested = SimpleDomNode("#document-fragment")
        nested.append_child(SimpleDomNode("p"))
        root.append_child(nested)

        apply_compiled_transforms(root, compile_transforms([SetAttrs("p", id="x")]))
        assert root.to_html(pretty=False, safe=False) == '<p id="x"></p>'

    def test_apply_compiled_transforms_handles_empty_root(self) -> None:
        root = SimpleDomNode("div")
        apply_compiled_transforms(root, compile_transforms([SetAttrs("div", id="x")]))
        assert root.to_html(pretty=False, safe=False) == "<div></div>"

    def test_apply_compiled_transforms_noops_with_no_transforms(self) -> None:
        root = SimpleDomNode("div")
        apply_compiled_transforms(root, [])
        assert root.to_html(pretty=False, safe=False) == "<div></div>"

    def test_apply_compiled_transforms_supports_text_root(self) -> None:
        root = TextNode("example.com")
        apply_compiled_transforms(root, compile_transforms([Linkify()]))  # type: ignore[arg-type]
        assert root.data == "example.com"

    def test_apply_compiled_transforms_rejects_unknown_compiled_transform(self) -> None:
        root = SimpleDomNode("div")
        with self.assertRaises(TypeError):
            apply_compiled_transforms(root, [object()])  # type: ignore[list-item]

    def test_transforms_can_run_after_sanitize(self) -> None:
        doc = JustHTML(
            "<p>x</p>",
            fragment=True,
            transforms=[Sanitize(), SetAttrs("p", **{"class": "y"})],
        )
        assert doc.to_html(pretty=False, safe=False) == '<p class="y">x</p>'

    def test_sanitize_root_comment_and_doctype_keep(self) -> None:
        policy_keep = SanitizationPolicy(
            allowed_tags=[],
            allowed_attributes={"*": []},
            url_policy=UrlPolicy(allow_rules={}),
            drop_comments=False,
            drop_doctype=False,
        )

        compiled = compile_transforms([Sanitize(policy_keep)])

        c = SimpleDomNode("#comment", data="x")
        apply_compiled_transforms(c, compiled)
        assert c.to_html(pretty=False, safe=False) == "<!--x-->"

        d = SimpleDomNode("!doctype", data="html")
        apply_compiled_transforms(d, compiled)
        assert d.to_html(pretty=False, safe=False) == "<!DOCTYPE html>"

    def test_collapsewhitespace_collapses_text_nodes(self) -> None:
        doc = JustHTML(
            "<p>Hello \n\t world</p><p>a  b</p>",
            fragment=True,
            transforms=[CollapseWhitespace()],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>Hello world</p><p>a b</p>"

    def test_collapsewhitespace_skips_pre_by_default(self) -> None:
        doc = JustHTML(
            "<pre>a  b</pre><p>a  b</p>",
            fragment=True,
            transforms=[CollapseWhitespace()],
        )
        assert doc.to_html(pretty=False, safe=False) == "<pre>a  b</pre><p>a b</p>"

    def test_collapsewhitespace_noops_when_no_collapse_needed(self) -> None:
        doc = JustHTML(
            "<p>Hello world</p>",
            fragment=True,
            transforms=[CollapseWhitespace()],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>Hello world</p>"

    def test_collapsewhitespace_can_skip_custom_tags(self) -> None:
        doc = JustHTML(
            "<p>a  b</p>",
            fragment=True,
            transforms=[CollapseWhitespace(skip_tags=("p",))],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>a  b</p>"

    def test_collapsewhitespace_ignores_empty_text_nodes(self) -> None:
        root = SimpleDomNode("div")
        root.append_child(TextNode(""))
        apply_compiled_transforms(root, compile_transforms([CollapseWhitespace()]))
        assert root.to_html(pretty=False, safe=False) == "<div></div>"

    def test_to_html_still_sanitizes_by_default_after_transforms_and_mutation(self) -> None:
        doc = JustHTML("<p>ok</p>")
        # Mutate the tree after parse.
        doc.root.append_child(SimpleDomNode("script"))
        # Safe-by-default output should strip it.
        assert doc.to_html(pretty=False) == "<html><head></head><body><p>ok</p></body></html>"

    def test_pruneempty_drops_empty_elements(self) -> None:
        doc = JustHTML(
            "<p></p><p><img></p><p>   </p>",
            fragment=True,
            transforms=[PruneEmpty("p")],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p><img></p>"

    def test_pruneempty_is_recursive_post_order(self) -> None:
        doc = JustHTML(
            "<div><p></p></div>",
            fragment=True,
            transforms=[PruneEmpty("p, div")],
        )
        assert doc.to_html(pretty=False, safe=False) == ""

    def test_pruneempty_drops_nested_empty_elements(self) -> None:
        doc = JustHTML(
            "<span><span></span></span>",
            fragment=True,
            transforms=[PruneEmpty("span")],
        )
        assert doc.to_html(pretty=False, safe=False) == ""

    def test_pruneempty_supports_consecutive_prune_transforms(self) -> None:
        doc = JustHTML(
            "<div><p></p></div>",
            fragment=True,
            transforms=[PruneEmpty("p"), PruneEmpty("div")],
        )
        assert doc.to_html(pretty=False, safe=False) == ""

    def test_pruneempty_can_run_before_other_transforms(self) -> None:
        # If pruning runs before later transforms, it only prunes emptiness at
        # that point in the pipeline.
        doc = JustHTML(
            "<p></p><p><img></p>",
            fragment=True,
            transforms=[PruneEmpty("p"), Drop("img")],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p></p>"

    def test_pruneempty_ignores_comments_when_determining_emptiness(self) -> None:
        doc = JustHTML(
            "<p><!--x--></p>",
            fragment=True,
            transforms=[PruneEmpty("p")],
        )
        assert doc.to_html(pretty=False, safe=False) == ""

    def test_pruneempty_can_preserve_whitespace_only_text(self) -> None:
        doc = JustHTML(
            "<p>   </p>",
            fragment=True,
            transforms=[PruneEmpty("p", strip_whitespace=False)],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>   </p>"

    def test_pruneempty_does_not_prune_void_elements(self) -> None:
        doc = JustHTML(
            '<img src="/static/images/icons/wikipedia.png" alt height="50" width="50">',
            fragment=True,
            transforms=[PruneEmpty("*")],
        )
        assert doc.to_html(pretty=False, safe=False) == (
            '<img src="/static/images/icons/wikipedia.png" alt height="50" width="50">'
        )

    def test_pruneempty_strip_whitespace_false_still_drops_empty_text_nodes(self) -> None:
        root = SimpleDomNode("div")
        p = SimpleDomNode("p")
        p.append_child(TextNode(""))
        root.append_child(p)

        apply_compiled_transforms(root, compile_transforms([PruneEmpty("p", strip_whitespace=False)]))
        assert root.to_html(pretty=False, safe=False) == "<div></div>"

    def test_pruneempty_considers_template_content(self) -> None:
        doc = JustHTML(
            "<template>ok</template><template><p></p></template>",
            fragment=True,
            transforms=[PruneEmpty("p, template")],
        )
        assert doc.to_html(pretty=False, safe=False) == "<template>ok</template>"

    def test_transform_order_is_respected_for_linkify_and_drop(self) -> None:
        # Drop runs before Linkify: it should not remove links created later.
        doc_keep = JustHTML(
            "<p>example.com</p>",
            fragment=True,
            transforms=[Drop("a"), Linkify()],
        )
        assert doc_keep.to_html(pretty=False, safe=False) == '<p><a href="http://example.com">example.com</a></p>'

        # Drop runs after Linkify: it should remove the linkified <a>.
        doc_drop = JustHTML(
            "<p>example.com</p>",
            fragment=True,
            transforms=[Linkify(), Drop("a")],
        )
        assert doc_drop.to_html(pretty=False, safe=False) == "<p></p>"

    def test_stage_auto_grouping_does_not_change_ordering(self) -> None:
        # Stage boundaries split passes, but ordering semantics are preserved.
        doc_stage = JustHTML(
            "<p>example.com</p>",
            fragment=True,
            transforms=[Drop("a"), Stage([Linkify()])],
        )
        assert doc_stage.to_html(pretty=False, safe=False) == '<p><a href="http://example.com">example.com</a></p>'

    def test_stage_can_be_nested_and_is_flattened(self) -> None:
        doc = JustHTML(
            "<p>example.com</p>",
            fragment=True,
            transforms=[Stage([Stage([Linkify()])])],
        )
        assert doc.to_html(pretty=False, safe=False) == '<p><a href="http://example.com">example.com</a></p>'

    def test_stage_auto_grouping_includes_trailing_transforms(self) -> None:
        # When a Stage exists at the top level, transforms outside stages are
        # implicitly grouped into stages too (including a trailing segment).
        doc = JustHTML(
            "<p>Hello</p>",
            fragment=True,
            transforms=[Stage([SetAttrs("p", id="x")]), SetAttrs("p", **{"class": "y"})],
        )
        html = doc.to_html(pretty=False, safe=False)
        assert "<p" in html
        assert 'id="x"' in html
        assert 'class="y"' in html

    def test_linkify_noops_when_no_links_found(self) -> None:
        # Covers the linkify path where we scan text but find no matches.
        doc = JustHTML(
            "<p>Hello world</p>",
            fragment=True,
            transforms=[Linkify()],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>Hello world</p>"
