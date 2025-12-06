import unittest

from justhtml.node import ElementNode, SimpleDomNode, TemplateNode, TextNode


class TestNode(unittest.TestCase):
    def test_text_property_simple(self):
        node = SimpleDomNode("div")
        text = TextNode("Hello")
        node.append_child(text)
        assert node.text == "Hello"

    def test_text_property_nested(self):
        root = SimpleDomNode("div")
        span = SimpleDomNode("span")
        text1 = TextNode("Hello ")
        text2 = TextNode("World")

        root.append_child(text1)
        root.append_child(span)
        span.append_child(text2)

        assert root.text == "Hello World"
        assert span.text == "World"

    def test_text_property_empty(self):
        node = SimpleDomNode("div")
        assert node.text == ""

    def test_text_property_comment(self):
        node = SimpleDomNode("#comment", data="comment")
        assert node.text == ""

    def test_insert_before(self):
        parent = SimpleDomNode("div")
        child1 = SimpleDomNode("span", attrs={"id": "1"})
        child2 = SimpleDomNode("span", attrs={"id": "2"})

        parent.append_child(child1)
        parent.insert_before(child2, child1)

        assert parent.children == [child2, child1]
        assert child2.parent == parent

    def test_insert_before_none(self):
        parent = SimpleDomNode("div")
        child1 = SimpleDomNode("span", attrs={"id": "1"})
        child2 = SimpleDomNode("span", attrs={"id": "2"})

        parent.append_child(child1)
        parent.insert_before(child2, None)

        assert parent.children == [child1, child2]
        assert child2.parent == parent

    def test_insert_before_invalid_reference(self):
        parent = SimpleDomNode("div")
        child1 = SimpleDomNode("span", attrs={"id": "1"})
        child2 = SimpleDomNode("span", attrs={"id": "2"})
        other = SimpleDomNode("div")

        parent.append_child(child1)

        with self.assertRaises(ValueError):
            parent.insert_before(child2, other)

    def test_insert_before_no_children_allowed(self):
        comment = SimpleDomNode("#comment", data="foo")
        node = SimpleDomNode("div")

        with self.assertRaises(ValueError):
            comment.insert_before(node, None)

    def test_text_node_none(self):
        text = TextNode(None)
        assert text.text == ""

    def test_simple_dom_node_text_none(self):
        node = SimpleDomNode("#text", data=None)
        assert node.text == ""

    def test_replace_child(self):
        parent = SimpleDomNode("div")
        child1 = SimpleDomNode("span", attrs={"id": "1"})
        child2 = SimpleDomNode("span", attrs={"id": "2"})
        new_child = SimpleDomNode("p")

        parent.append_child(child1)
        parent.append_child(child2)

        replaced = parent.replace_child(new_child, child1)

        assert replaced == child1
        assert parent.children == [new_child, child2]
        assert new_child.parent == parent
        assert child1.parent is None

    def test_replace_child_invalid(self):
        parent = SimpleDomNode("div")
        child1 = SimpleDomNode("span")
        other = SimpleDomNode("p")

        parent.append_child(child1)

        with self.assertRaises(ValueError):
            parent.replace_child(other, other)

    def test_replace_child_no_children_allowed(self):
        comment = SimpleDomNode("#comment", data="foo")
        node = SimpleDomNode("div")

        with self.assertRaises(ValueError):
            comment.replace_child(node, node)

    def test_has_child_nodes(self):
        parent = SimpleDomNode("div")
        assert not parent.has_child_nodes()

        parent.append_child(SimpleDomNode("span"))
        assert parent.has_child_nodes()

    def test_clone_node_shallow(self):
        node = SimpleDomNode("div", attrs={"class": "foo"}, namespace="html")
        child = SimpleDomNode("span")
        node.append_child(child)

        clone = node.clone_node(deep=False)

        assert clone.name == "div"
        assert clone.attrs == {"class": "foo"}
        assert clone.namespace == "html"
        assert clone.children == []
        assert clone is not node
        assert clone.attrs is not node.attrs

    def test_clone_node_simple(self):
        node = SimpleDomNode("div", attrs={"id": "1"})
        clone = node.clone_node()
        assert clone.name == "div"
        assert clone.attrs == {"id": "1"}
        assert clone is not node
        assert clone.children == []

    def test_clone_node_deep(self):
        parent = SimpleDomNode("div")
        child = SimpleDomNode("span")
        parent.append_child(child)

        clone = parent.clone_node(deep=True)
        assert len(clone.children) == 1
        assert clone.children[0].name == "span"
        assert clone.children[0] is not child
        assert clone.children[0].parent == clone

    def test_clone_text_node(self):
        text = TextNode("hello")
        clone = text.clone_node()
        assert clone.data == "hello"
        assert clone is not text

    def test_clone_template_node(self):
        template = TemplateNode("template", namespace="html")
        content_child = SimpleDomNode("div")
        template.template_content.append_child(content_child)

        clone = template.clone_node(deep=True)
        assert clone is not template
        assert clone.template_content is not template.template_content
        assert len(clone.template_content.children) == 1
        assert clone.template_content.children[0].name == "div"

    def test_clone_template_node_with_children(self):
        template = TemplateNode("template", namespace="html")
        child = SimpleDomNode("span")
        template.append_child(child)

        clone = template.clone_node(deep=True)
        assert len(clone.children) == 1
        assert clone.children[0].name == "span"
        assert clone.children[0] is not child
        assert clone.children[0].parent == clone

    def test_clone_element_node(self):
        element = ElementNode("div", attrs={"class": "foo"}, namespace="html")
        child = SimpleDomNode("span")
        element.append_child(child)

        # Shallow clone
        clone_shallow = element.clone_node(deep=False)
        assert isinstance(clone_shallow, ElementNode)
        assert clone_shallow.children == []

        # Deep clone
        clone_deep = element.clone_node(deep=True)
        assert len(clone_deep.children) == 1
        assert clone_deep.children[0].name == "span"
        assert clone_deep.children[0] is not child
        assert clone_deep.children[0].parent == clone_deep

    def test_clone_node_empty_attrs(self):
        node = SimpleDomNode("div")
        clone = node.clone_node()
        assert clone.attrs == {}

    def test_clone_comment_node(self):
        node = SimpleDomNode("#comment", data="foo")
        clone = node.clone_node()
        assert clone.attrs is None
        assert clone.data == "foo"

    def test_clone_template_node_non_html(self):
        template = TemplateNode("template", namespace="svg")
        assert template.template_content is None
        # Add a child to exercise the for loop even when template_content is None
        child = SimpleDomNode("g")
        template.append_child(child)

        clone = template.clone_node(deep=True)
        assert clone.template_content is None
        assert clone.namespace == "svg"
        assert len(clone.children) == 1
        assert clone.children[0].name == "g"

    def test_clone_template_node_shallow(self):
        template = TemplateNode("template", namespace="html")
        child = SimpleDomNode("div")
        template.append_child(child)

        clone = template.clone_node(deep=False)
        assert clone.name == "template"
        assert clone.namespace == "html"
        # Shallow clone should not copy children
        assert len(clone.children) == 0

    def test_clone_doctype(self):
        node = SimpleDomNode("!doctype", data="html")
        clone = node.clone_node()
        assert clone.name == "!doctype"
        assert clone.attrs is None

    def test_clone_document(self):
        node = SimpleDomNode("#document")
        clone = node.clone_node()
        assert clone.name == "#document"
        assert clone.children == []
        assert clone.attrs == {}

    def test_remove_child(self):
        parent = SimpleDomNode("div")
        child = SimpleDomNode("span")
        parent.append_child(child)

        parent.remove_child(child)
        assert parent.children == []
        assert child.parent is None

    def test_remove_child_not_found(self):
        parent = SimpleDomNode("div")
        child = SimpleDomNode("span")
        with self.assertRaises(ValueError):
            parent.remove_child(child)

    def test_to_html_method(self):
        node = SimpleDomNode("div")
        output = node.to_html()
        assert "<div>" in output

    def test_query_method(self):
        parent = SimpleDomNode("div")
        child = SimpleDomNode("span")
        parent.append_child(child)
        results = parent.query("span")
        assert len(results) == 1
        assert results[0].name == "span"

    def test_template_node_clone_with_content(self):
        template = TemplateNode("template", namespace="html")
        inner = SimpleDomNode("div")
        template.template_content.append_child(inner)
        # Also add a direct child to cover line 180-181
        direct_child = SimpleDomNode("span")
        template.append_child(direct_child)

        clone = template.clone_node(deep=True)
        assert len(clone.template_content.children) == 1
        assert clone.template_content.children[0].name == "div"
        assert len(clone.children) == 1
        assert clone.children[0].name == "span"

    def test_text_node_children_and_has_child_nodes(self):
        text = TextNode("hello")
        assert text.children == []
        assert not text.has_child_nodes()
