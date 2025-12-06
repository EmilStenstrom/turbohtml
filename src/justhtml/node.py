from .selector import query
from .serialize import to_html


class SimpleDomNode:
    __slots__ = ("attrs", "children", "data", "name", "namespace", "parent")

    def __init__(self, name, attrs=None, data=None, namespace=None):
        self.name = name
        self.parent = None
        self.data = data

        if name.startswith("#") or name == "!doctype":
            self.namespace = namespace
            if name == "#comment" or name == "!doctype":
                self.children = None
                self.attrs = None
            else:
                self.children = []
                self.attrs = attrs if attrs is not None else {}
        else:
            self.namespace = namespace or "html"
            self.children = []
            self.attrs = attrs if attrs is not None else {}

    def append_child(self, node):
        self.children.append(node)
        node.parent = self

    def remove_child(self, node):
        self.children.remove(node)
        node.parent = None

    def to_html(self, indent=0, indent_size=2, pretty=True):
        """Convert node to HTML string."""
        return to_html(self, indent, indent_size, pretty=pretty)

    def query(self, selector):
        """
        Query this subtree using a CSS selector.

        Args:
            selector: A CSS selector string

        Returns:
            A list of matching nodes

        Raises:
            ValueError: If the selector is invalid
        """
        return query(self, selector)


class ElementNode(SimpleDomNode):
    __slots__ = ()

    def __init__(self, name, attrs, namespace):
        self.name = name
        self.parent = None
        self.data = None
        self.namespace = namespace
        self.children = []
        self.attrs = attrs


class TemplateNode(ElementNode):
    __slots__ = ("template_content",)

    def __init__(self, name, attrs=None, data=None, namespace=None):
        super().__init__(name, attrs, namespace)
        if self.namespace == "html":
            self.template_content = SimpleDomNode("#document-fragment")
        else:
            self.template_content = None


class TextNode:
    __slots__ = ("data", "name", "namespace", "parent")

    def __init__(self, data):
        self.data = data
        self.parent = None
        self.name = "#text"
        self.namespace = None
