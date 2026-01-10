from __future__ import annotations

import unittest

from justhtml import JustHTML, SelectorError
from justhtml.node import SimpleDomNode
from justhtml.transforms import (
    Drop,
    Edit,
    Empty,
    SetAttrs,
    Unwrap,
    apply_compiled_transforms,
    compile_transforms,
)


class TestTransforms(unittest.TestCase):
    def test_compile_transforms_rejects_unknown_transform_type(self) -> None:
        with self.assertRaises(TypeError):
            compile_transforms([object()])

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

    def test_transforms_run_in_order_and_drop_short_circuits(self) -> None:
        doc = JustHTML(
            "<p>Hello</p>",
            transforms=[SetAttrs("p", id="x"), Drop("p"), SetAttrs("p", class_="y")],
        )
        assert doc.to_html(pretty=False, safe=False) == "<html><head></head><body></body></html>"

    def test_selector_transforms_skip_comment_nodes(self) -> None:
        doc = JustHTML("<!--x--><p>y</p>", transforms=[SetAttrs("p", id="x")])
        assert '<p id="x">y</p>' in doc.to_html(pretty=False, safe=False)

    def test_apply_compiled_transforms_handles_empty_root(self) -> None:
        root = SimpleDomNode("div")
        apply_compiled_transforms(root, compile_transforms([SetAttrs("div", id="x")]))
        assert root.to_html(pretty=False, safe=False) == "<div></div>"

    def test_apply_compiled_transforms_noops_with_no_transforms(self) -> None:
        root = SimpleDomNode("div")
        apply_compiled_transforms(root, [])
        assert root.to_html(pretty=False, safe=False) == "<div></div>"

    def test_to_html_still_sanitizes_by_default_after_transforms_and_mutation(self) -> None:
        doc = JustHTML("<p>ok</p>")
        # Mutate the tree after parse.
        doc.root.append_child(SimpleDomNode("script"))
        # Safe-by-default output should strip it.
        assert doc.to_html(pretty=False) == "<html><head></head><body><p>ok</p></body></html>"
