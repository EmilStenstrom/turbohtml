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

    @property
    def text(self):
        """Return the text content of this node and its descendants."""
        if self.name == "#text":
            return self.data or ""
        if not self.children:
            return ""
        return "".join(child.text for child in self.children)

    def insert_before(self, node, reference_node):
        """
        Insert a node before a reference node.

        Args:
            node: The node to insert
            reference_node: The node to insert before. If None, append to end.

        Raises:
            ValueError: If reference_node is not a child of this node
        """
        if self.children is None:
            raise ValueError(f"Node {self.name} cannot have children")

        if reference_node is None:
            self.append_child(node)
            return

        try:
            index = self.children.index(reference_node)
            self.children.insert(index, node)
            node.parent = self
        except ValueError:
            raise ValueError("Reference node is not a child of this node") from None

    def replace_child(self, new_node, old_node):
        """
        Replace a child node with a new node.

        Args:
            new_node: The new node to insert
            old_node: The child node to replace

        Returns:
            The replaced node (old_node)

        Raises:
            ValueError: If old_node is not a child of this node
        """
        if self.children is None:
            raise ValueError(f"Node {self.name} cannot have children")

        try:
            index = self.children.index(old_node)
        except ValueError:
            raise ValueError("The node to be replaced is not a child of this node") from None

        self.children[index] = new_node
        new_node.parent = self
        old_node.parent = None
        return old_node

    def has_child_nodes(self):
        """Return True if this node has children."""
        return bool(self.children)

    def clone_node(self, deep=False):
        """
        Clone this node.

        Args:
            deep: If True, recursively clone children.

        Returns:
            A new node that is a copy of this node.
        """
        clone = SimpleDomNode(
            self.name,
            self.attrs.copy() if self.attrs else None,
            self.data,
            self.namespace,
        )
        if deep and self.children:
            for child in self.children:
                clone.append_child(child.clone_node(deep=True))
        return clone


class ElementNode(SimpleDomNode):
    __slots__ = ("template_content",)

    def __init__(self, name, attrs, namespace):
        self.name = name
        self.parent = None
        self.data = None
        self.namespace = namespace
        self.children = []
        self.attrs = attrs
        self.template_content = None

    def clone_node(self, deep=False):
        clone = ElementNode(self.name, self.attrs.copy() if self.attrs else {}, self.namespace)
        if deep:
            for child in self.children:
                clone.append_child(child.clone_node(deep=True))
        return clone


class TemplateNode(ElementNode):
    __slots__ = ()

    def __init__(self, name, attrs=None, data=None, namespace=None):
        super().__init__(name, attrs, namespace)
        if self.namespace == "html":
            self.template_content = SimpleDomNode("#document-fragment")
        else:
            self.template_content = None

    def clone_node(self, deep=False):
        clone = TemplateNode(
            self.name,
            self.attrs.copy() if self.attrs else {},
            self.data,
            self.namespace,
        )
        if deep:
            if self.template_content:
                clone.template_content = self.template_content.clone_node(deep=True)
            for child in self.children:
                clone.append_child(child.clone_node(deep=True))
        return clone


class TextNode:
    __slots__ = ("data", "name", "namespace", "parent")

    def __init__(self, data):
        self.data = data
        self.parent = None
        self.name = "#text"
        self.namespace = None

    @property
    def text(self):
        """Return the text content of this node."""
        return self.data or ""

    @property
    def children(self):
        """Return empty list for TextNode (leaf node)."""
        return []

    def has_child_nodes(self):
        """Return False for TextNode."""
        return False

    def clone_node(self, deep=False):
        return TextNode(self.data)
