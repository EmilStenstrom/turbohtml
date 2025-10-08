BOUNDARY_ELEMENTS = {
    "applet",
    "caption",
    "html",
    "table",
    "td",
    "th",
    "marquee",
    "object",
    "template",
}


class Node:
    """Represents a DOM-like node.
    - tag_name: e.g., 'div', 'p', etc. Use '#text' for text nodes.
    - attributes: dict of tag attributes
    - children: list of child Nodes
    - parent: reference to parent Node (or None for root)
    - next_sibling/previous_sibling: references to adjacent nodes in the tree.
    """

    __slots__ = (
        "attributes",
        "children",
        "namespace",
        "next_sibling",
        "parent",
        "previous_sibling",
        # Flag for stack-only synthetic nodes (not part of DOM tree). These nodes may be
        # pushed onto the open elements stack during fragment parsing to emulate required
        # ancestor context (e.g. table/tbody/tr for td/th fragments) without mutating the
        # actual fragment DOM. They are pruned after parsing. Keeping this in __slots__
        # prevents AttributeError when fragment bootstrap logic marks nodes.
        "synthetic_stack_only",
        "tag_name",
        "text_content",
    )

    def __init__(self, tag_name, attributes=None, preserve_attr_case=False, text_content=None, namespace=None):
        # Instrumentation / safety: empty tag names should never be constructed.
        # If this triggers we want a loud failure with context so we can trace upstream logic.
        if tag_name is None or tag_name == "":
            msg = "Empty tag_name passed to Node constructor (bug: tokenization or handler produced blank tag)"
            raise ValueError(
                msg,
            )

        self.tag_name = tag_name
        self.namespace = namespace  # None for HTML, "svg" or "math" for foreign elements
        if attributes:
            if preserve_attr_case:
                # Keep first occurrence preserving original key casing
                kept = {}
                for k, v in attributes.items():
                    if k not in kept:
                        kept[k] = v
                self.attributes = kept
            else:
                # Lowercase attribute names deterministically; keep first occurrence
                lowered = {}
                for k, v in attributes.items():
                    lk = k.lower()
                    if lk not in lowered:
                        lowered[lk] = v
                self.attributes = lowered
        else:
            self.attributes = {}
        self.children = []
        self.parent = None
        # For text and comment nodes store inline text; for element nodes this may be unused
        self.text_content = text_content if text_content is not None else ""
        self.next_sibling = None
        self.previous_sibling = None
        # Default: real DOM node (False). Fragment bootstrap may set True on ephemeral
        # ancestors that exist only on the open elements stack.
        self.synthetic_stack_only = False

    @property
    def is_svg(self):
        """Check if this is an SVG element."""
        return self.namespace == "svg"

    @property
    def is_mathml(self):
        """Check if this is a MathML element."""
        return self.namespace == "math"

    @property
    def is_foreign(self):
        """Check if this is a foreign element (SVG or MathML)."""
        return self.namespace in ("svg", "math")

    @property
    def local_name(self):
        """Get the local tag name (same as tag_name now that namespace is separate)."""
        return self.tag_name

    def matches_tag(self, tag_spec):
        """Check if this node matches a tag specification.

        tag_spec can be:
        - A simple tag name: "div" matches tag_name="div", namespace=None
        - A namespaced tag: "svg circle" matches tag_name="circle", namespace="svg"
        """
        if " " in tag_spec:
            ns, local = tag_spec.split(" ", 1)
            return self.namespace == ns and self.tag_name == local
        return self.namespace is None and self.tag_name == tag_spec

    def append_child(self, child):
        # Check for circular reference before adding
        if self._would_create_circular_reference(child):
            msg = f"Adding {child.tag_name} as child of {self.tag_name} would create circular reference"
            raise ValueError(
                msg,
            )

        if child.parent:
            # Update sibling links in old location
            if child.previous_sibling:
                child.previous_sibling.next_sibling = child.next_sibling
            if child.next_sibling:
                child.next_sibling.previous_sibling = child.previous_sibling
            child.parent.children.remove(child)

        # Update sibling links in new location
        if self.children:
            self.children[-1].next_sibling = child
            child.previous_sibling = self.children[-1]
        else:
            child.previous_sibling = None

        child.parent = self
        child.next_sibling = None
        self.children.append(child)

    def _would_create_circular_reference(self, child):
        """Check if adding child would create a circular reference."""
        # Fast path: if child has no parent, it can't be our ancestor
        if not child.parent:
            return False

        # Check if self is a descendant of child
        current = self
        visited = set()
        depth = 0

        while current and depth < 100:  # Safety limit
            if current == child:
                return True  # Self is a descendant of child

            # Only track visited if we have a parent (to detect cycles in existing tree)
            if current.parent:
                node_id = id(current)
                if node_id in visited:
                    return True  # Already found circular reference in current tree
                visited.add(node_id)

            current = current.parent
            depth += 1

        return False

    def insert_child_at(self, index, child):
        """Insert a child at the specified index."""
        if child.parent:
            # Remove from old location
            if child.previous_sibling:
                child.previous_sibling.next_sibling = child.next_sibling
            if child.next_sibling:
                child.next_sibling.previous_sibling = child.previous_sibling
            child.parent.children.remove(child)

        # Insert at the specified position
        if index < 0 or index >= len(self.children):
            # Append at end if index is out of bounds
            self.append_child(child)
            return

        # Update child's parent
        child.parent = self

        # Insert into children list
        self.children.insert(index, child)

        # Update sibling links
        if index == 0:
            # Inserting at beginning
            child.previous_sibling = None
            if len(self.children) > 1:
                child.next_sibling = self.children[1]
                self.children[1].previous_sibling = child
            else:
                child.next_sibling = None
        else:
            # Inserting in middle or end
            child.previous_sibling = self.children[index - 1]
            if index < len(self.children) - 1:
                child.next_sibling = self.children[index + 1]
                self.children[index + 1].previous_sibling = child
            else:
                child.next_sibling = None

            # Update previous sibling's next link
            self.children[index - 1].next_sibling = child

    def insert_before(self, new_node, reference_node):
        if reference_node not in self.children:
            return

        if new_node.parent:
            # Update sibling links in old location
            if new_node.previous_sibling:
                new_node.previous_sibling.next_sibling = new_node.next_sibling
            if new_node.next_sibling:
                new_node.next_sibling.previous_sibling = new_node.previous_sibling
            new_node.parent.children.remove(new_node)

        idx = self.children.index(reference_node)
        new_node.parent = self
        self.children.insert(idx, new_node)

        # Update sibling pointers
        new_node.next_sibling = reference_node
        new_node.previous_sibling = reference_node.previous_sibling
        reference_node.previous_sibling = new_node
        if new_node.previous_sibling:
            new_node.previous_sibling.next_sibling = new_node

    def __repr__(self):
        if self.tag_name == "#text":
            return f"Node(#text='{self.text_content[:30]}')"
        if self.tag_name == "#comment":
            return f"Node(#comment='{self.text_content[:30]}')"
        return f"Node(<{self.tag_name}>, children={len(self.children)})"

    def to_test_format(self, indent=0):
        if self.tag_name in {"document", "document-fragment"}:
            return "\n".join(child.to_test_format(0) for child in self.children)
        if self.tag_name == "content":
            # Template content should be displayed without angle brackets
            parts = [f"| {' ' * indent}content"]
            parts.extend(child.to_test_format(indent + 2) for child in self.children)
            return "\n".join(parts)
        if self.tag_name == "#text":
            return f'| {" " * indent}"{self.text_content}"'
        if self.tag_name == "#comment":
            return f"| {' ' * indent}<!-- {self.text_content} -->"
        if self.tag_name == "!doctype":
            # Format DOCTYPE with the actual content, adding space if content is empty
            content = self.text_content if self.text_content is not None else ""
            if content.strip():
                return f"| <!DOCTYPE {content}>"
            return "| <!DOCTYPE >"

        # Start with the tag name (with namespace prefix for foreign elements)
        if self.namespace:
            display_tag = f"{self.namespace} {self.tag_name}"
        else:
            display_tag = self.tag_name
        result = f"| {' ' * indent}<{display_tag}>"

        # Add attributes on their own line if present (sorted alphabetically)
        if self.attributes:
            # Preserve original insertion order for foreign (svg/math) elements where tests rely on
            # specific grouping; otherwise sort alphabetically for deterministic HTML output.
            if self.is_foreign:
                attr_items = self.attributes.items()
            else:
                attr_items = sorted(self.attributes.items())
            for key, value in attr_items:
                # Namespaced attribute presentation rules:
                #  * Inside foreign (svg/math) elements, tests expect prefixes separated
                #    by a space: xlink:href -> xlink href, xml:lang -> xml lang, xmlns:xlink -> xmlns xlink.
                #  * On pure HTML elements, retain the original colon form (body xlink:href remains xlink:href).
                if ":" in key and self.is_foreign:
                    prefix, local = key.split(":", 1)
                    if (prefix == "xml" and local in ("lang", "space")) or (prefix in ("xlink", "xmlns") and local):
                        display_key = f"{prefix} {local}"
                    else:
                        display_key = key
                else:
                    display_key = key
                result += f'\n| {" " * (indent + 2)}{display_key}="{value}"'

        # Add children
        if self.children:
            parts = [result]
            parts.extend(child.to_test_format(indent + 2) for child in self.children)
            return "\n".join(parts)
        return result

    def find_ancestor(self, tag_name_or_predicate, stop_at_boundary=False):
        """Find the nearest ancestor matching the given tag name or predicate.
        Includes the current node in the search.

        Args:
            tag_name_or_predicate: Tag name or callable that takes a Node and returns bool
            stop_at_boundary: If True, stop searching at boundary elements (HTML5 scoping rules)

        Returns:
            The matching ancestor Node or None if not found

        """
        # Optimize: check callable once, not in loop
        is_callable = callable(tag_name_or_predicate)
        current = self

        if is_callable:
            # Callable predicate path
            while current:
                if tag_name_or_predicate(current):
                    return current
                if stop_at_boundary and current.tag_name in BOUNDARY_ELEMENTS:
                    return None
                current = current.parent
        else:
            # String tag name path (most common)
            while current:
                if current.tag_name == tag_name_or_predicate:
                    return current
                if stop_at_boundary and current.tag_name in BOUNDARY_ELEMENTS:
                    return None
                current = current.parent
        return None

    def remove_child(self, child):
        """Remove a child node, updating all sibling links.

        Args:
            child: The Node to remove

        """
        if child not in self.children:
            return

        # Update sibling links
        if child.previous_sibling:
            child.previous_sibling.next_sibling = child.next_sibling
        if child.next_sibling:
            child.next_sibling.previous_sibling = child.previous_sibling

        # Remove from children list and clear parent
        self.children.remove(child)
        child.parent = None
        child.next_sibling = None
        child.previous_sibling = None

    def find_ancestor_until(self, tag_name_or_predicate, stop_at):
        """Find ancestor matching criteria, stopping at a specific node.

        Args:
            tag_name_or_predicate: Tag name or callable that takes a Node and returns bool
            stop_at: Node to stop searching at (exclusive - won't check this node)

        Returns:
            The matching ancestor Node or None if not found before stop_at

        """
        current = self
        while current and current != stop_at:
            if callable(tag_name_or_predicate):
                if tag_name_or_predicate(current):
                    return current
            elif current.tag_name == tag_name_or_predicate:
                return current
            current = current.parent
        return None

    def find_first_ancestor_in_tags(self, tag_names, stop_at=None):
        """Find the first ancestor whose tag matches any in the given list.

        Args:
            tag_names: Single tag name or list of tag names to match
            stop_at: Optional node to stop searching at (exclusive)

        Returns:
            The first matching ancestor Node or None if not found

        """
        if isinstance(tag_names, str):
            tag_names = [tag_names]

        current = self
        while current and current != stop_at:
            if current.tag_name in tag_names:
                return current
            current = current.parent
        return None

    def last_child_is_text(self):
        """Check if the last child is a text node."""
        return self.children and self.children[-1].tag_name == "#text"

    def is_inside_tag(self, tag_name):
        """Check if this node is inside an element with the given tag name.

        Args:
            tag_name: Tag name to check for
        Returns:
            True if inside the tag, False otherwise

        """
        return self.find_ancestor(tag_name) is not None

    def find_child_by_tag(self, tag_name):
        """Find first child with the given tag name.

        Args:
            tag_name: Tag name to search for
        Returns:
            First matching child or None if not found

        """
        for child in self.children:
            if child.tag_name == tag_name:
                return child
        return None

    def get_last_child_with_tag(self, tag_name):
        """Get the last child with the given tag name.

        Args:
            tag_name: Tag name to search for
        Returns:
            Last matching child or None if not found

        """
        for child in reversed(self.children):
            if child.tag_name == tag_name:
                return child
        return None

    def collect_ancestors_until(self, stop_at, predicate=None):
        """Collect ancestors from this node up to (but not including) stop_at.

        Args:
            stop_at: Node to stop at (exclusive)
            predicate: Optional filter function - only nodes matching this are included
        Returns:
            List of matching ancestors ordered outermost->innermost (rootward first, nearest last)

        """
        ancestors = []
        current = self
        while current and current != stop_at:
            if predicate is None or predicate(current):
                ancestors.insert(0, current)  # Insert at beginning for reverse order
            current = current.parent
        return ancestors

    def move_up_while_in_tags(self, tags):
        """Move up the tree while current node has tag in the given list."""
        if isinstance(tags, str):
            tags = [tags]
        current = self
        while current and current.tag_name in tags:
            if current.parent:
                current = current.parent
            else:
                break
        return current

    def has_ancestor_matching(self, predicate):
        """Check if any ancestor matches the given predicate."""
        current = self.parent
        while current:
            if predicate(current):
                return True
            current = current.parent
        return False

    def contains_text_nodes(self):
        """Recursively check if this node or any descendant is a text node."""
        if self.tag_name == "#text":
            return True
        return any(child.contains_text_nodes() for child in self.children)

    def has_text_children(self):
        """Check if any immediate child is a text node with content."""
        return any(child.tag_name == "#text" and child.text_content for child in self.children)

    def find_last_child_index(self, tag_name):
        """Find the index of the last child with the given tag name."""
        for i in range(len(self.children) - 1, -1, -1):
            if self.children[i].tag_name == tag_name:
                return i
        return -1

    def find_child_after_index(self, tag_name, start_index):
        """Find first child with tag_name after the given index."""
        for i in range(start_index + 1, len(self.children)):
            if self.children[i].tag_name == tag_name:
                return self.children[i]
        return None
