"""Trie data structure for efficient entity name prefix matching.

Optimized for HTML entity reference parsing: quickly reject invalid prefixes
and find longest matching entity names without reading unnecessary characters.

The trie maps entity names (with optional trailing `;`) to their decoded values,
enabling:
  - O(k) prefix matching where k = prefix length
  - Early termination on impossible prefixes
  - Longest prefix lookup for overlapping entities (e.g., "amp" vs "amp;")
"""


class TrieNode:
    """Single node in the trie tree."""
    __slots__ = ("children", "value", "is_terminal")

    def __init__(self):
        self.children = {}  # char -> TrieNode
        self.value = None  # Decoded entity value (or None if non-terminal)
        self.is_terminal = False  # True if this node represents a complete entity


class Trie:
    """Trie for efficient entity name lookup and prefix matching.

    Usage:
        entities = {"amp": "&", "amp;": "&", "lt": "<", "lt;": "<", ...}
        trie = Trie(entities)

        # Find longest matching entity name
        entity_name, value = trie.longest_prefix_item("ampersand;")
        # Returns ("amp;", "&") not ("amp", "&")
    """

    __slots__ = ("root",)

    def __init__(self, entities):
        """Build trie from entity name -> decoded value mapping.

        Args:
            entities: dict mapping entity names (with optional `;`) to decoded chars
        """
        self.root = TrieNode()
        for name, value in entities.items():
            self._insert(name, value)

    def _insert(self, name, value):
        """Insert entity name into trie."""
        node = self.root
        children = node.children
        for char in name:
            if char not in children:
                children[char] = TrieNode()
            node = children[char]
            children = node.children
        node.is_terminal = True
        node.value = value

    def longest_prefix_item(self, text):
        """Find longest entity name matching prefix of text.

        Scans text character by character, tracking the longest terminal node seen.
        Prefers longer matches (e.g., "amp;" over "amp").

        Args:
            text: string starting with entity name (without leading '&')

        Raises:
            KeyError: if no entity name matches any prefix of text

        Returns:
            tuple: (entity_name, decoded_value)
        """
        node = self.root
        longest_match_len = 0
        longest_value = None
        children = node.children

        for i, char in enumerate(text):
            if char not in children:
                break
            node = children[char]
            if node.is_terminal:
                longest_match_len = i + 1
                longest_value = node.value
            children = node.children

        if longest_match_len == 0:
            raise KeyError(f"No entity prefix match in '{text}'")

        return text[:longest_match_len], longest_value

    def __contains__(self, name):
        """Check if entity name exists in trie.

        Args:
            name: entity name (with optional trailing `;`)

        Returns:
            bool: True if exact match exists
        """
        node = self.root
        for char in name:
            node_children = node.children
            if char not in node_children:
                return False
            node = node_children[char]
        return node.is_terminal

    def __getitem__(self, name):
        """Get decoded value for entity name.

        Args:
            name: entity name (with optional trailing `;`)

        Raises:
            KeyError: if entity not found

        Returns:
            str: decoded character/value
        """
        node = self.root
        for char in name:
            node_children = node.children
            if char not in node_children:
                raise KeyError(name)
            node = node_children[char]
        if not node.is_terminal:
            raise KeyError(name)
        return node.value
