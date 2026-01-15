from __future__ import annotations

import unittest

from justhtml import JustHTML
from justhtml.node import ElementNode, SimpleDomNode, TemplateNode, TextNode
from justhtml.sanitize import SanitizationPolicy
from justhtml.transforms import (
    CollapseWhitespace,
    Drop,
    Linkify,
    PruneEmpty,
    Sanitize,
    SetAttrs,
    apply_compiled_transforms,
    compile_transforms,
)


class TestSanitizeTransform(unittest.TestCase):
    def test_compile_transforms_empty_is_ok(self) -> None:
        assert compile_transforms(()) == []

    def test_compile_transforms_rejects_multiple_sanitize(self) -> None:
        with self.assertRaises(ValueError):
            compile_transforms((Sanitize(), Sanitize()))

    def test_sanitize_transform_makes_dom_safe_in_place(self) -> None:
        doc = JustHTML(
            '<p><a href="javascript:alert(1)" onclick="x()">x</a><script>alert(1)</script></p>',
            fragment=True,
            transforms=[Sanitize()],
        )

        # Tree is already sanitized, so raw and safe output match.
        assert doc.to_html(pretty=False, safe=False) == "<p><a>x</a></p>"
        assert doc.to_html(pretty=False, safe=True) == "<p><a>x</a></p>"

    def test_compile_transforms_allows_transforms_after_sanitize(self) -> None:
        compile_transforms((Sanitize(), Linkify()))
        compile_transforms((Sanitize(), SetAttrs("p", **{"class": "x"})))

    def test_transforms_can_run_after_sanitize(self) -> None:
        doc = JustHTML(
            '<p><a href="javascript:alert(1)" onclick="x()">x</a> https://example.com</p>',
            fragment=True,
            transforms=[Sanitize(), Linkify()],
        )

        # Existing unsafe content is removed by Sanitize, then Linkify runs.
        assert doc.to_html(pretty=False, safe=False) == (
            '<p><a>x</a> <a href="https://example.com">https://example.com</a></p>'
        )

    def test_pruneempty_can_run_after_sanitize(self) -> None:
        doc = JustHTML(
            "<p><script>alert(1)</script></p>",
            fragment=True,
            transforms=[Sanitize(), PruneEmpty("p")],
        )
        assert doc.to_html(pretty=False, safe=False) == ""

    def test_drop_then_pruneempty_can_run_after_sanitize_in_order(self) -> None:
        doc = JustHTML(
            "<p><a>x</a></p>",
            fragment=True,
            transforms=[Sanitize(), Drop("a"), PruneEmpty("p")],
        )
        assert doc.to_html(pretty=False, safe=False) == ""

    def test_collapsewhitespace_can_run_after_sanitize(self) -> None:
        doc = JustHTML(
            "<p>a  b</p>",
            fragment=True,
            transforms=[Sanitize(), CollapseWhitespace()],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>a b</p>"

    def test_post_sanitize_collapsewhitespace_then_pruneempty_runs_in_order(self) -> None:
        doc = JustHTML(
            "<p>   </p><p>x</p>",
            fragment=True,
            transforms=[Sanitize(), CollapseWhitespace(), PruneEmpty("p")],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>x</p>"

    def test_post_sanitize_pruneempty_then_collapsewhitespace_runs_in_order(self) -> None:
        doc = JustHTML(
            "<p>a  b</p><span> </span>",
            fragment=True,
            transforms=[Sanitize(), PruneEmpty("span"), CollapseWhitespace()],
        )
        assert doc.to_html(pretty=False, safe=False) == "<p>a b</p>"

    def test_post_sanitize_consecutive_pruneempty_transforms_are_batched(self) -> None:
        doc = JustHTML(
            "<div><p></p></div>",
            fragment=True,
            transforms=[Sanitize(), PruneEmpty("p"), PruneEmpty("div")],
        )
        assert doc.to_html(pretty=False, safe=False) == ""

    def test_sanitize_transform_supports_element_root(self) -> None:
        root = ElementNode("a", {"href": "javascript:alert(1)", "onclick": "x()"}, "html")
        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.attrs == {}

    def test_sanitize_transform_supports_template_root(self) -> None:
        root = TemplateNode("div", attrs={"onclick": "x()", "class": "ok"}, namespace="html")
        root.append_child(ElementNode("span", {}, "html"))

        assert root.template_content is not None
        script = ElementNode("script", {}, "html")
        script.append_child(TextNode("alert(1)"))
        root.template_content.append_child(script)

        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert "onclick" not in root.attrs
        assert root.attrs.get("class") == "ok"
        assert all(child.parent is root for child in root.children)
        assert root.template_content is not None
        assert root.template_content.children == []

    def test_sanitize_transform_supports_text_root(self) -> None:
        root = TextNode("hello")
        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)  # type: ignore[arg-type]
        assert root.data == "hello"

    def test_sanitize_transform_supports_simpledomnode_element_root(self) -> None:
        root = SimpleDomNode("a", {"href": "javascript:alert(1)", "onclick": "x()"}, namespace="html")
        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)
        assert root.attrs == {}

    def test_sanitize_transform_policy_override_is_used(self) -> None:
        # Covers the Sanitize(policy=...) override path.
        policy = SanitizationPolicy(allowed_tags={"p"}, allowed_attributes={"*": set()})
        root = SimpleDomNode("#document-fragment")
        compiled = compile_transforms((Sanitize(policy),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"

    def test_sanitize_transform_converts_comment_root_to_fragment_when_dropped(self) -> None:
        root = SimpleDomNode("#comment", data="x")
        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"
        assert root.data is None

    def test_sanitize_transform_converts_doctype_root_to_fragment_when_dropped(self) -> None:
        root = SimpleDomNode("!doctype")
        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"
        assert root.data is None

    def test_sanitize_transform_drops_foreign_namespace_element_root(self) -> None:
        root = SimpleDomNode("p", namespace="svg")
        root.append_child(SimpleDomNode("span"))

        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"
        assert root.children == []

    def test_sanitize_transform_drops_foreign_namespace_element_root_without_children(self) -> None:
        root = SimpleDomNode("p", namespace="svg")

        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"
        assert root.children == []

    def test_sanitize_transform_drops_content_for_drop_content_tag_root(self) -> None:
        root = SimpleDomNode("script")
        root.append_child(TextNode("alert(1)"))

        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"
        assert root.children == []

    def test_sanitize_transform_drops_content_for_drop_content_tag_root_without_children(self) -> None:
        root = SimpleDomNode("script")

        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"
        assert root.children == []

    def test_sanitize_transform_disallowed_root_hoists_children(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=set(),
            allowed_attributes={"*": set()},
            drop_foreign_namespaces=False,
            drop_content_tags=set(),
        )
        root = SimpleDomNode("p")
        root.append_child(TextNode("x"))

        compiled = compile_transforms((Sanitize(policy),))
        apply_compiled_transforms(root, compiled)
        assert root.name == "#document-fragment"
        assert root.to_html(pretty=False, safe=False) == "x"

    def test_sanitize_transform_disallowed_root_without_children_is_empty(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags=set(),
            allowed_attributes={"*": set()},
            drop_foreign_namespaces=False,
            drop_content_tags=set(),
        )
        root = SimpleDomNode("p")

        compiled = compile_transforms((Sanitize(policy),))
        apply_compiled_transforms(root, compiled)
        assert root.name == "#document-fragment"
        assert root.to_html(pretty=False, safe=False) == ""

    def test_sanitize_transform_disallowed_template_root_hoists_template_content(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags={"b"},
            allowed_attributes={"*": set()},
            drop_foreign_namespaces=False,
            drop_content_tags=set(),
        )
        root = TemplateNode("template", attrs={}, namespace="html")
        assert root.template_content is not None
        root.template_content.append_child(SimpleDomNode("b"))

        compiled = compile_transforms((Sanitize(policy),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"
        assert root.children is not None
        assert [c.name for c in root.children] == ["b"]

    def test_sanitize_transform_disallowed_template_root_with_empty_template_content_hoists_children(self) -> None:
        policy = SanitizationPolicy(
            allowed_tags={"b"},
            allowed_attributes={"*": set()},
            drop_foreign_namespaces=False,
            drop_content_tags=set(),
        )
        root = TemplateNode("template", attrs={}, namespace="html")
        root.append_child(SimpleDomNode("b"))

        compiled = compile_transforms((Sanitize(policy),))
        apply_compiled_transforms(root, compiled)

        assert root.name == "#document-fragment"
        assert [c.name for c in root.children] == ["b"]

    def test_sanitize_transform_decide_handles_comments_doctype_and_containers(self) -> None:
        root = SimpleDomNode("#document-fragment")
        root.append_child(SimpleDomNode("#comment", data="x"))
        root.append_child(SimpleDomNode("!doctype"))
        nested = SimpleDomNode("#document-fragment")
        nested.append_child(SimpleDomNode("p"))
        root.append_child(nested)

        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.to_html(pretty=False, safe=False) == "<p></p>"

    def test_sanitize_transform_decide_drops_foreign_namespace_elements(self) -> None:
        root = SimpleDomNode("#document-fragment")
        root.append_child(SimpleDomNode("p", namespace="svg"))

        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.to_html(pretty=False, safe=False) == ""

    def test_sanitize_transform_decide_unwraps_disallowed_elements(self) -> None:
        root = SimpleDomNode("#document-fragment")
        blink = SimpleDomNode("blink")
        blink.append_child(TextNode("x"))
        root.append_child(blink)

        compiled = compile_transforms((Sanitize(),))
        apply_compiled_transforms(root, compiled)

        assert root.to_html(pretty=False, safe=False) == "x"
