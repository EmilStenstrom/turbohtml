
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
    """
    Represents a DOM-like node.
    - tag_name: e.g., 'div', 'p', etc. Use '#text' for text nodes.
    - attributes: dict of tag attributes
    - children: list of child Nodes
    - parent: reference to parent Node (or None for root)
    - next_sibling/previous_sibling: references to adjacent nodes in the tree
    """

    __slots__ = (
        "tag_name",
        "attributes",
        "children",
        "parent",
        "text_content",
        "next_sibling",
        "previous_sibling",
        # Flag for stack-only synthetic nodes (not part of DOM tree). These nodes may be
        # pushed onto the open elements stack during fragment parsing to emulate required
        # ancestor context (e.g. table/tbody/tr for td/th fragments) without mutating the
        # actual fragment DOM. They are pruned after parsing. Keeping this in __slots__
        # prevents AttributeError when fragment bootstrap logic marks nodes.
        "synthetic_stack_only",
    )

    def __init__(self, tag_name, attributes=None, preserve_attr_case=False):
        # Instrumentation / safety: empty tag names should never be constructed.
        # If this triggers we want a loud failure with context so we can trace upstream logic.
        if tag_name is None or tag_name == "":
            raise ValueError(
                "Empty tag_name passed to Node constructor (bug: tokenization or handler produced blank tag)"
            )
        self.tag_name = tag_name
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
        self.text_content = ""  # For text nodes or concatenated text in element nodes
        self.next_sibling = None
        self.previous_sibling = None
        # Default: real DOM node (False). Fragment bootstrap may set True on ephemeral
        # ancestors that exist only on the open elements stack.
        self.synthetic_stack_only = False

    def append_child(self, child):
        # Check for circular reference before adding
        if self._would_create_circular_reference(child):
            raise ValueError(
                f"Adding {child.tag_name} as child of {self.tag_name} would create circular reference"
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
        """Check if adding child would create a circular reference"""
        # Check if self is a descendant of child
        current = self
        visited = set()
        depth = 0

        while current and depth < 100:  # Safety limit
            if id(current) in visited:
                return True  # Already found circular reference in current tree

            if current == child:
                return True  # Self is a descendant of child

            visited.add(id(current))
            current = current.parent
            depth += 1

        return False

    def insert_child_at(self, index, child):
        """Insert a child at the specified index"""
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
        if self.tag_name in ("document", "document-fragment"):
            result = []
            for child in self.children:
                result.append(child.to_test_format(0))
            return "\n".join(result)
        if self.tag_name == "content":
            # Template content should be displayed without angle brackets
            result = f"| {' ' * indent}content"
            for child in self.children:
                result += "\n" + child.to_test_format(indent + 2)
            return result
        if self.tag_name == "#text":
            return f'| {" " * indent}"{self.text_content}"'
        if self.tag_name == "#comment":
            return f"| {' ' * indent}<!-- {self.text_content} -->"
        if self.tag_name == "!doctype":
            # Format DOCTYPE with the actual content, adding space if content is empty
            content = self.text_content if self.text_content is not None else ""
            if content.strip():
                return f"| <!DOCTYPE {content}>"
            else:
                return "| <!DOCTYPE >"

        # Start with the tag name
        result = f"| {' ' * indent}<{self.tag_name}>"

        # Add attributes on their own line if present (sorted alphabetically)
        if self.attributes:
            # Preserve original insertion order for foreign (svg/math) elements where tests rely on
            # specific grouping; otherwise sort alphabetically for deterministic HTML output.
            if self.tag_name.startswith("svg ") or self.tag_name.startswith("math "):
                attr_items = self.attributes.items()
            else:
                attr_items = sorted(self.attributes.items())
            for key, value in attr_items:
                # Namespaced attribute presentation rules:
                #  * Inside foreign (svg/math prefixed tag_name) elements, tests expect prefixes separated
                #    by a space: xlink:href -> xlink href, xml:lang -> xml lang, xmlns:xlink -> xmlns xlink.
                #  * On pure HTML elements, retain the original colon form (body xlink:href remains xlink:href).
                if ":" in key and (
                    self.tag_name.startswith("svg ")
                    or self.tag_name.startswith("math ")
                ):
                    prefix, local = key.split(":", 1)
                    if prefix == "xml" and local in ("lang", "space"):
                        display_key = f"{prefix} {local}"
                    elif prefix in ("xlink", "xmlns") and local:
                        display_key = f"{prefix} {local}"
                    else:
                        display_key = key
                else:
                    display_key = key
                result += f'\n| {" " * (indent + 2)}{display_key}="{value}"'

        # Add children
        for child in self.children:
            result += "\n" + child.to_test_format(indent + 2)
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
        current = self
        while current:
            if callable(tag_name_or_predicate):
                if tag_name_or_predicate(current):
                    return current
            elif current.tag_name == tag_name_or_predicate:
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
        """Check if the last child is a text node"""
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
        """Move up the tree while current node has tag in the given list"""
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
        """Check if any ancestor matches the given predicate"""
        current = self.parent
        while current:
            if predicate(current):
                return True
            current = current.parent
        return False
