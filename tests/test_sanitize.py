from __future__ import annotations

import unittest

from justhtml.node import SimpleDomNode, TemplateNode, TextNode
from justhtml.sanitize import DEFAULT_POLICY, SanitizationPolicy, UrlRule, sanitize
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
        )
        assert isinstance(policy.allowed_tags, set)
        assert isinstance(policy.allowed_attributes, dict)
        assert isinstance(policy.drop_content_tags, set)
        assert isinstance(policy.force_link_rel, set)

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


if __name__ == "__main__":
    unittest.main()
