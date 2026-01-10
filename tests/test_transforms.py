from __future__ import annotations

import unittest

from justhtml import JustHTML, SelectorError
from justhtml.node import SimpleDomNode, TextNode
from justhtml.transforms import (
    CollapseWhitespace,
    Drop,
    Edit,
    Empty,
    Linkify,
    PruneEmpty,
    Sanitize,
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

    def test_apply_compiled_transforms_supports_text_root(self) -> None:
        root = TextNode("example.com")
        apply_compiled_transforms(root, compile_transforms([Linkify()]))  # type: ignore[arg-type]
        assert root.data == "example.com"

    def test_apply_compiled_transforms_rejects_unknown_compiled_transform(self) -> None:
        root = SimpleDomNode("div")
        with self.assertRaises(TypeError):
            apply_compiled_transforms(root, [object()])  # type: ignore[list-item]

    def test_apply_compiled_transforms_rejects_non_prune_after_sanitize(self) -> None:
        root = SimpleDomNode("div")
        compiled = compile_transforms([SetAttrs("div", id="x"), Sanitize()])
        compiled.append(compile_transforms([SetAttrs("div", class_="y")])[0])
        with self.assertRaises(TypeError):
            apply_compiled_transforms(root, compiled)

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
