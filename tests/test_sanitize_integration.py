from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from justhtml import DEFAULT_POLICY, JustHTML
from justhtml.context import FragmentContext
from justhtml.sanitize import SanitizationPolicy, UrlRule

_CASES_DIR = Path(__file__).with_name("justhtml-sanitize-tests")


def _url_filter_by_name(name: str):
    if name == "drop_or_rewrite":

        def url_filter(tag: str, attr: str, value: str) -> str | None:
            if tag == "a" and attr == "href" and value == "https://drop.me":
                return None
            if tag == "a" and attr == "href" and value == "https://rewrite.me":
                return "https://example.com"
            return value

        return url_filter

    raise ValueError(f"Unknown url_filter name: {name}")


def _build_policy(spec: Any) -> SanitizationPolicy:
    if spec == "DEFAULT":
        return DEFAULT_POLICY

    if not isinstance(spec, dict):
        raise TypeError("policy must be 'DEFAULT' or an object")

    allowed_tags = spec["allowed_tags"]
    allowed_attributes = spec["allowed_attributes"]

    url_rules_list = spec.get("url_rules", [])
    url_rules: dict[tuple[str, str], UrlRule] = {}
    for rule_spec in url_rules_list:
        if not isinstance(rule_spec, dict):
            raise TypeError("url_rules entries must be objects")
        tag = rule_spec["tag"]
        attr = rule_spec["attr"]
        url_rules[(tag, attr)] = UrlRule(
            allow_relative=rule_spec.get("allow_relative", True),
            allow_fragment=rule_spec.get("allow_fragment", True),
            allow_protocol_relative=rule_spec.get("allow_protocol_relative", False),
            allowed_schemes=rule_spec.get("allowed_schemes", []),
            allowed_hosts=rule_spec.get("allowed_hosts", None),
        )

    url_filter_name = spec.get("url_filter")
    url_filter = _url_filter_by_name(url_filter_name) if isinstance(url_filter_name, str) else None

    return SanitizationPolicy(
        allowed_tags=allowed_tags,
        allowed_attributes=allowed_attributes,
        url_rules=url_rules,
        url_filter=url_filter,
        drop_comments=spec.get("drop_comments", True),
        drop_doctype=spec.get("drop_doctype", True),
        drop_foreign_namespaces=spec.get("drop_foreign_namespaces", True),
        strip_disallowed_tags=spec.get("strip_disallowed_tags", True),
        drop_content_tags=spec.get("drop_content_tags", ["script", "style"]),
        force_link_rel=spec.get("force_link_rel", []),
    )


class TestSanitizeIntegration(unittest.TestCase):
    def test_sanitize_cases(self) -> None:
        cases_path = _CASES_DIR / "cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise TypeError("cases.json must contain a list")

        for case in cases:
            name = case["name"]
            policy = _build_policy(case["policy"])
            input_html = case["input_html"]
            expected_html = case["expected_html"]

            parse_mode = case.get("parse", "fragment")
            if parse_mode == "fragment":
                ctx = case.get("fragment_context", "div")
                doc = JustHTML(input_html, fragment_context=FragmentContext(ctx))
            elif parse_mode == "document":
                doc = JustHTML(input_html)
            else:
                raise ValueError(f"Unknown parse mode in {name}: {parse_mode}")

            actual = doc.to_html(pretty=False, safe=True, policy=policy)
            if actual != expected_html:
                self.fail(
                    "\n".join(
                        [
                            f"Case: {name}",
                            f"Input: {input_html}",
                            f"Expected: {expected_html}",
                            f"Actual:   {actual}",
                        ]
                    )
                )


if __name__ == "__main__":
    unittest.main()
