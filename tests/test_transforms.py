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
    Stage,
    Unwrap,
    apply_compiled_transforms,
    compile_transforms,
    emit_error,
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

    def test_transforms_can_run_after_sanitize(self) -> None:
        doc = JustHTML(
            "<p>x</p>",
            fragment=True,
            transforms=[Sanitize(), SetAttrs("p", **{"class": "y"})],
        )
        assert doc.to_html(pretty=False, safe=False) == '<p class="y">x</p>'

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
