from __future__ import annotations

import unittest

from justhtml.sanitize import DEFAULT_POLICY, SanitizationPolicy, UrlRule, sanitize
from justhtml.serialize import to_html
from justhtml.treebuilder import SimpleDomNode as Node


class TestSanitize(unittest.TestCase):
    def test_sanitize_is_noop(self) -> None:
        root = object()
        assert sanitize(root) is root

    def test_urlrule_normalizes_to_sets(self) -> None:
        rule = UrlRule(allowed_schemes=["https", "mailto"], allowed_hosts=["example.com"])
        assert isinstance(rule.allowed_schemes, set)
        assert rule.allowed_schemes == {"https", "mailto"}
        assert isinstance(rule.allowed_hosts, set)
        assert rule.allowed_hosts == {"example.com"}

        rule2 = UrlRule(allowed_schemes={"https"}, allowed_hosts=None)
        assert isinstance(rule2.allowed_schemes, set)
        assert rule2.allowed_schemes == {"https"}
        assert rule2.allowed_hosts is None

    def test_policy_normalizes_collections(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=["p", "a"],
            allowed_attributes={"*": [], "a": ["href", "title"]},
            url_rules={("a", "href"): UrlRule(allowed_schemes=["https"])},
            drop_content_tags=["script", "style"],
            force_link_rel=["noopener"],
        )

        assert isinstance(policy.allowed_tags, set)
        assert policy.allowed_tags == {"p", "a"}

        assert isinstance(policy.allowed_attributes, dict)
        assert policy.allowed_attributes["*"] == set()
        assert policy.allowed_attributes["a"] == {"href", "title"}

        assert isinstance(policy.drop_content_tags, set)
        assert policy.drop_content_tags == {"script", "style"}

        assert isinstance(policy.force_link_rel, set)
        assert policy.force_link_rel == {"noopener"}

    def test_policy_accepts_pre_normalized_sets(self) -> None:
        # Cover the branches where inputs are already normalized.
        policy = SanitizationPolicy(
            allowed_tags={"div"},
            allowed_attributes={"*": set(), "div": {"title"}},
            url_rules={},
            drop_content_tags={"script"},
            force_link_rel={"noopener", "noreferrer"},
        )

        assert policy.allowed_tags == {"div"}
        assert policy.allowed_attributes["*"] == set()
        assert policy.allowed_attributes["div"] == {"title"}
        assert policy.drop_content_tags == {"script"}
        assert policy.force_link_rel == {"noopener", "noreferrer"}

    def test_default_policy_is_constructed(self) -> None:
        # Smoke test plus coverage for DEFAULT_POLICY path.
        assert "a" in DEFAULT_POLICY.allowed_tags
        assert "img" in DEFAULT_POLICY.allowed_tags
        assert "href" in DEFAULT_POLICY.allowed_attributes["a"]
        assert ("a", "href") in DEFAULT_POLICY.url_rules

    def test_serialize_safe_and_policy_branches(self) -> None:
        frag = Node("#document-fragment")
        div = Node("div")
        frag.append_child(div)
        div.append_child(Node("#text", data="ok"))

        # Cover safe=False branch.
        assert to_html(frag, pretty=False, safe=False) == "<div>ok</div>"

        # Cover safe=True with an explicit policy (exercise `policy or DEFAULT_POLICY`).
        policy = SanitizationPolicy(
            allowed_tags=["div"],
            allowed_attributes={"*": []},
            url_rules={},
        )
        assert to_html(frag, pretty=False, safe=True, policy=policy) == "<div>ok</div>"

    def test_urlrule_allowed_hosts_set_branch(self) -> None:
        rule = UrlRule(allowed_schemes=["https"], allowed_hosts={"example.com"})
        assert isinstance(rule.allowed_hosts, set)
        assert rule.allowed_hosts == {"example.com"}
