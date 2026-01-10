from __future__ import annotations

import unittest

from justhtml import JustHTML
from justhtml.node import ElementNode, SimpleDomNode, TemplateNode, TextNode
from justhtml.transforms import Drop, PruneEmpty, Sanitize, apply_compiled_transforms, compile_transforms


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

    def test_sanitize_must_be_last_except_trailing_pruneempty(self) -> None:
        compile_transforms((Sanitize(),))
        compile_transforms((Sanitize(), PruneEmpty("p")))

        with self.assertRaises(TypeError):
            compile_transforms((Sanitize(), Drop("p")))

    def test_pruneempty_can_run_after_sanitize(self) -> None:
        doc = JustHTML(
            "<p><script>alert(1)</script></p>",
            fragment=True,
            transforms=[Sanitize(), PruneEmpty("p")],
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
