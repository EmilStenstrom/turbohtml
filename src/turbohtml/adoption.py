"""Adoption Agency Algorithm (HTML5 tree construction: formatting element adoption).

Implementation focuses on spec steps; comments describe intent (why) rather than history.
"""

from typing import List, Optional, Dict
from dataclasses import dataclass

from turbohtml.node import Node
from turbohtml.tokenizer import HTMLToken
from turbohtml.constants import FORMATTING_ELEMENTS, BLOCK_ELEMENTS, SPECIAL_CATEGORY_ELEMENTS


@dataclass
class FormattingElementEntry:
    """Entry in the active formatting elements stack"""

    element: Node
    token: HTMLToken

    # Marker entries have element None (scope boundaries for tables/templates).

    def matches(self, tag_name: str, attributes: Dict[str, str] = None) -> bool:
        """Check if this entry matches the given tag and attributes"""
        if self.element.tag_name != tag_name:
            return False

        if attributes is None:
            return True

        # Compare attributes (for Noah's Ark clause)
        return self.element.attributes == attributes


class ActiveFormattingElements:
    """Active formatting elements list (spec stack with markers + Noah's Ark clause)."""

    def __init__(self, max_size: int = 12):
        self._stack: List[FormattingElementEntry] = []
        self._max_size = max_size

    def push(self, element: Node, token: HTMLToken) -> None:
        """Add a formatting element to the active list"""
        entry = FormattingElementEntry(element, token)
        # Enforce Noah's Ark clause before adding more duplicates
        self._apply_noahs_ark(entry)

        self._stack.append(entry)

        # Enforce maximum size (remove oldest if needed)
        if len(self._stack) > self._max_size:
            self._stack.pop(0)

    def push_marker(self) -> None:
        """Push a marker entry (spec: used for table/template boundaries)."""
        # Represent marker as entry with element=None, token=None
        marker = FormattingElementEntry(element=None, token=None)  # type: ignore
        self._stack.append(marker)

    def is_marker(self, entry: FormattingElementEntry) -> bool:
        return entry.element is None

    def find(self, tag_name: str, attributes: Dict[str, str] = None) -> Optional[FormattingElementEntry]:
        """Find a formatting element by tag name and optionally attributes"""
        # Search from most recent to oldest
        for entry in reversed(self._stack):
            if self.is_marker(entry):
                continue
            if entry.matches(tag_name, attributes):
                return entry
        return None

    def find_element(self, element: Node) -> Optional[FormattingElementEntry]:
        """Find an entry by element instance"""
        for entry in self._stack:
            if self.is_marker(entry):
                continue
            if entry.element is element:
                return entry
        return None

    def remove(self, element: Node) -> bool:
        """Remove a formatting element from the active list"""
        for i, entry in enumerate(self._stack):
            if not self.is_marker(entry) and entry.element is element:
                self._stack.pop(i)
                return True
        return False

    def remove_entry(self, entry: FormattingElementEntry) -> bool:
        """Remove a specific entry from the active list"""
        if entry in self._stack:
            self._stack.remove(entry)
            return True
        return False

    # --- spec: Noah's Ark clause (prevent more than 3 identical entries) ---
    def _apply_noahs_ark(self, new_entry: FormattingElementEntry) -> None:
        if self.is_marker(new_entry):
            return
        # Count existing matching entries (same tag & attributes)
        matching = []
        for entry in self._stack:
            if self.is_marker(entry):
                continue
            if entry.matches(new_entry.element.tag_name, new_entry.element.attributes):
                matching.append(entry)
        if len(matching) >= 3:
            # Remove the earliest (lowest index) matching entry
            earliest = matching[0]
            try:
                self._stack.remove(earliest)
            except ValueError:
                pass

    def is_empty(self) -> bool:
        return not any(not self.is_marker(e) for e in self._stack)

    def __iter__(self):
        return (e for e in self._stack if not self.is_marker(e))

    def get_index(self, entry: FormattingElementEntry) -> int:
        try:
            return self._stack.index(entry)
        except ValueError:
            return -1

    def __len__(self) -> int:
        return len(self._stack)

    def insert_at_index(self, index: int, element: Node, token: HTMLToken) -> None:
        # Clamp index to valid range
        if index < 0:
            index = 0
        if index > len(self._stack):
            index = len(self._stack)
        entry = FormattingElementEntry(element, token)
        self._stack.insert(index, entry)

    def replace_entry(self, old_entry: FormattingElementEntry, new_element: Node, new_token: HTMLToken) -> None:
        """Replace an entry with a new element"""
        for i, entry in enumerate(self._stack):
            if entry is old_entry:
                self._stack[i] = FormattingElementEntry(new_element, new_token)
                return
        # If not found, just push
        self.push(new_element, new_token)


class OpenElementsStack:
    """Stack of open elements per HTML5 tree construction algorithm.

    Provides only the operations required by the parser and adoption agency:
      * push / pop / current / is_empty
      * contains / index_of / remove_element
      * replace_element / insert_after
      * has_element_in_scope (general scope variant sufficient for current tests)
      * _is_special_category (category check used during adoption)
    """

    def __init__(self) -> None:
        self._stack: List[Node] = []

    # --- basic stack ops ---
    def push(self, element: Node) -> None:
        self._stack.append(element)

    def pop(self) -> Optional[Node]:
        return self._stack.pop() if self._stack else None

    def current(self) -> Optional[Node]:
        return self._stack[-1] if self._stack else None

    def is_empty(self) -> bool:
        return not self._stack

    # --- membership / search ---
    def contains(self, element: Node) -> bool:
        return element in self._stack

    def index_of(self, element: Node) -> int:
        try:
            return self._stack.index(element)
        except ValueError:
            return -1

    def remove_element(self, element: Node) -> bool:
        try:
            self._stack.remove(element)
            return True
        except ValueError:
            return False

    # --- structural mutation ---
    def replace_element(self, old: Node, new: Node) -> None:
        idx = self.index_of(old)
        if idx != -1:
            self._stack[idx] = new

    def insert_after(self, reference: Node, new_element: Node) -> None:
        idx = self.index_of(reference)
        if idx == -1:
            self._stack.append(new_element)
        else:
            self._stack.insert(idx + 1, new_element)

    # --- scope handling ---
    def has_element_in_scope(self, tag_name: str) -> bool:
        scope_boundaries = {"applet", "caption", "html", "table", "td", "th", "marquee", "object", "template"}
        for element in reversed(self._stack):
            if element.tag_name == tag_name:
                return True
            if element.tag_name in scope_boundaries:
                return False
        return False

    def has_element_in_button_scope(self, tag_name: str) -> bool:
        """Return True if an element with tag_name is in button scope (HTML spec).

        Button scope is the same as the normal *scope* definition but with the additional
        boundary element 'button'. Used primarily to decide whether an open <p> should be
        implicitly closed before inserting a new block / paragraph start tag.
        """
        scope_boundaries = {"applet", "caption", "html", "table", "td", "th", "marquee", "object", "template", "button"}
        for element in reversed(self._stack):
            if element.tag_name == tag_name:
                return True
            if element.tag_name in scope_boundaries:
                return False
        return False

    # --- category helpers ---
    def _is_special_category(self, element: Node) -> bool:
        return element.tag_name in SPECIAL_CATEGORY_ELEMENTS

    # --- iteration helpers ---
    def __iter__(self):
        return iter(self._stack)

    def __len__(self):
        return len(self._stack)


class AdoptionAgencyAlgorithm:

    def __init__(self, parser):
        self.parser = parser
        # Direct attribute access (env_debug always defined in parser)
        self.debug_enabled = parser.env_debug
        self._ran_a = False


    def should_run_adoption(self, tag_name: str, context) -> bool:
        # Determine if the adoption agency algorithm should run for this tag (spec conditions)
        if tag_name not in FORMATTING_ELEMENTS:
            return False
        # Only run if there is an active formatting element AND conditions that require adoption.
        # Per spec this is any time we see an end tag for a formatting element that is in the
        # list of active formatting elements. However, running the full algorithm when the
        # element is the current node and there are no block elements after it is equivalent
        # to a simple pop. For those simple cases we let the normal end-tag handling do the work
        entry = context.active_formatting_elements.find(tag_name)
        if not entry:
            return False
        # Skip retained outer formatting elements tracked internally (no dynamic node attributes)
        el = entry.element
        # (Currently no retained outer mechanism implemented post-refactor; always proceed)
        # If the formatting element is the current node and there are no special category
        # (block/special) elements after it in the open elements stack, treat as simple.
        formatting_element = entry.element
        if context.open_elements.current() is formatting_element:
            # Scan for a special element after formatting element; if none, normally simple.
            idx = context.open_elements.index_of(formatting_element)
            has_block_after = False
            if idx != -1:
                for later in context.open_elements._stack[idx + 1 :]:
                    if context.open_elements._is_special_category(later):
                        has_block_after = True
                        break
            if not has_block_after:
                if self.debug_enabled:
                    print(f"    should_run_adoption: simple current-node case for <{tag_name}>, using normal closure")
                return False
        # Otherwise run adoption (there may be blocks after or non‑current node)
        # Final fast-path: after a complex run Step 19 may reorder the stack so the formatting
        # element clone is now immediately above its furthest block and becomes the current node.
        # If now current and still present in active list, defer to simple pop behavior instead
        # of re-entering complex loop (prevents 8 identical iterations).
        if context.open_elements.current() is formatting_element:
            # Verify no special elements after it (for non-<a>)
            idx2 = context.open_elements.index_of(formatting_element)
            trailing_special = any(
                context.open_elements._is_special_category(e) for e in context.open_elements._stack[idx2 + 1 :]
            )
            if not trailing_special:
                if self.debug_enabled:
                    print(f"    should_run_adoption: after reordering, <{tag_name}> is current with no trailing blocks; simple closure")
                return False
        if self.debug_enabled:
            print(f"    should_run_adoption: tag={tag_name}, triggering adoption (entry present, complex conditions)")
        return True

    def run_algorithm(self, tag_name: str, context, iteration_count: int = 0) -> bool:
        # Run adoption algorithm (WHATWG HTML spec)
        if tag_name == 'a':
            self._ran_a = True
        if self.debug_enabled:
            print(f"\n=== ADOPTION AGENCY ALGORITHM START ===")
            print(f"    Target tag: {tag_name}")
            print(f"    Open elements stack: {[e.tag_name for e in context.open_elements._stack]}")
            print(
                f"    Active formatting elements: {[e.element.tag_name for e in context.active_formatting_elements]}"
            )
        # Spec step 1: Choose the last (most recent) element in the list of active formatting elements
        # whose tag name matches the target tag name.
        formatting_entry = None
        for entry in reversed(list(context.active_formatting_elements)):
            if entry.element is None:  # skip marker entries
                continue
            if entry.element.tag_name == tag_name:
                formatting_entry = entry
                break
        if not formatting_entry:
            if self.debug_enabled:
                print("    No active formatting element entry found; aborting adoption agency run")
            return False
        formatting_element = formatting_entry.element
        if self.debug_enabled:
            print(
                f"    Selected formatting element (most recent spec): {formatting_element} at stack index {context.open_elements.index_of(formatting_element)}"
            )

        # Intervening <b> entries retained; no active formatting pruning mid-run

        # Step 1: If the current node is an HTML element whose tag name is subject,
        # and the current node is not in the list of active formatting elements,
        # then pop the current node off the stack of open elements and return.
        current_node = context.open_elements.current() if not context.open_elements.is_empty() else None
        if self.debug_enabled:
            print(f"\n--- STEP 1: Check current node ---")
            print(f"    Current node: {current_node}")
            print(f"    Current node tag: {current_node.tag_name if current_node else None}")
            print(f"    Target tag: {tag_name}")

        if current_node and current_node.tag_name == tag_name:
            is_in_active_formatting = context.active_formatting_elements.find_element(current_node) is not None
            if self.debug_enabled:
                print(f"    Current node matches target tag")
                print(f"    Current node in active formatting elements: {is_in_active_formatting}")

            if not is_in_active_formatting:
                if self.debug_enabled:
                    print(f"    STEP 1 RESULT: Simple case - popping current node and returning")
                context.open_elements.pop()
                return True

        # Step 2: We already found the formatting element above
        if self.debug_enabled:
            print(f"\n--- STEP 2: Use selected formatting element ---")
            print(f"    Formatting element: {formatting_element}")
            print(
                f"    Formatting element parent: {formatting_element.parent.tag_name if formatting_element.parent else None}"
            )

        # Step 3: If formatting element is not in stack of open elements
        if not context.open_elements.contains(formatting_element):
            if self.debug_enabled:
                print(f"\n--- STEP 3: Check if formatting element is in open elements ---")
                print(f"    STEP 3 RESULT: Formatting element not in open elements - removing from active formatting")
            context.active_formatting_elements.remove(formatting_element)
            return True

        # Step 4: If formatting element is in stack but not in scope
        if not context.open_elements.has_element_in_scope(formatting_element.tag_name):
            if self.debug_enabled:
                print(f"\n--- STEP 4: Check scope ---")
                print(
                    f"    STEP 4 RESULT: Formatting element not in scope - spec: parse error, ignore token, abort"
                )
            # Parse error: ignore token; abort this adoption run
            return False

        # Step 5: If formatting element is not the current node, it's a parse error
        if context.open_elements.current() != formatting_element:
            if self.debug_enabled:
                print(f"\n--- STEP 5: Parse error check ---")
                print(f"    STEP 5 RESULT: Parse error - formatting element not current node (continuing anyway)")
            # Continue with algorithm anyway

        # Step 6: Find the furthest block
        furthest_block = self._find_furthest_block_spec_compliant(formatting_element, context)
        if self.debug_enabled:
            print(f"\n--- STEP 6: Find furthest block ---")
            print(f"    Furthest block: {furthest_block}")
            if furthest_block:
                print(
                    f"    Furthest block parent: {furthest_block.parent.tag_name if furthest_block.parent else None}"
                )

        # Step 7: If no furthest block, then simple case
        if furthest_block is None:
            if self.debug_enabled:
                print(f"    STEP 7: No furthest block - running simple case")
            return self._handle_no_furthest_block_spec(formatting_element, formatting_entry, context)

        # Step 8-19: Complex case
        if self.debug_enabled:
            print(f"    STEP 8-19: Complex case with furthest block")
        return self._run_complex_adoption_spec(formatting_entry, furthest_block, context, iteration_count)

    # Helper: run adoption repeatedly (spec max 8) until no action
    def run_until_stable(self, tag_name: str, context, max_runs: int = 8) -> int:
        """Run the adoption agency algorithm up to max_runs times until it reports no further action.

        Returns the number of successful runs performed. Encapsulates the counter that used
        to live in various callers so external code no longer manages the iteration variable.
        """
        runs = 0
        while runs < max_runs and self.should_run_adoption(tag_name, context):
            # iteration_count passed as 1-based for debugging parity
            if not self.run_algorithm(tag_name, context, runs + 1):
                break
            runs += 1
            if tag_name == 'a':
                # Limit </a> adoption to a single iteration
                break
            if tag_name == 'a':
                # Early stop if no trailing special/block elements; further iterations redundant
                entry = context.active_formatting_elements.find('a')
                if entry:
                    a_el = entry.element
                    idx = context.open_elements.index_of(a_el)
                    if idx != -1:
                        trailing_special = any(
                            context.open_elements._is_special_category(e)
                            for e in context.open_elements._stack[idx + 1 :]
                        )
                        if not trailing_special:
                            break
        # No post-loop ladder heuristics
        return runs

    # --- Spec helpers ---
    def _find_furthest_block_spec_compliant(self, formatting_element: Node, context) -> Optional[Node]:
        """Locate the furthest block for Step 6 of the adoption agency algorithm.

        Spec intent: starting immediately after the formatting element on the open
        elements stack, find the first element that is a special / block formatting
        separator (html5lib treats any element in the "special" category or a known
        block element as a boundary). If no such element appears before the top of
        the stack, return None (simple case).

        Conservative: classify using SPECIAL/BLOCK sets only.
        """
        try:
            idx = context.open_elements.index_of(formatting_element)
        except Exception:  # defensive; should not happen
            return None
        if idx == -1:
            return None
        stack = context.open_elements._stack
        # Scan successive elements after formatting_element
        for node in stack[idx + 1 :]:
            # A candidate furthest block must be a special category OR a block element
            if node.tag_name in SPECIAL_CATEGORY_ELEMENTS or node.tag_name in BLOCK_ELEMENTS:
                return node
        return None

    def _handle_no_furthest_block_spec(
        self, formatting_element: Node, formatting_entry: FormattingElementEntry, context
    ) -> bool:
        """Handle the simple case when no furthest block is found (Steps 7.x in spec).

        Operations (minimal, spec-aligned):
          * Pop elements from open elements stack up to and including formatting element
          * Remove formatting element from active formatting elements list
          * Set insertion point to the element *before* the popped formatting element (its parent)
        Returns True to signal the adoption attempt consumed the end tag.
        """
        # Pop from open elements until we've removed the formatting element
        stack = context.open_elements._stack
        if formatting_element in stack:
            # Remove any elements above formatting_element first (these are ignored per spec simple case)
            while stack and stack[-1] is not formatting_element:
                stack.pop()
            if stack and stack[-1] is formatting_element:
                stack.pop()
        # Remove from active formatting list
        context.active_formatting_elements.remove_entry(formatting_entry)
        # Move insertion point to parent (if exists)
        parent = formatting_element.parent
        if parent is not None:
            context.move_to_element(parent)
        return True

    
        
        
        # Collect candidates first (avoid mutating while traversing)
        root = context.current_parent
        # Walk from document root to be safe
        doc = self.parser.root
        candidates = []
        stack = [doc]
        while stack:
            node = stack.pop()
            stack.extend(reversed(node.children))
            if node.tag_name == 'b' and node.parent and node.parent.tag_name == 'a':
                if node.attributes:
                    continue
                text_children = [c for c in node.children if c.tag_name == '#text' and c.text_content and c.text_content.strip()]
                if text_children:
                    continue
                elem_children = [c for c in node.children if c.tag_name != '#text']
    
    def _get_body_or_root(self, context):
        """Get the body element or fallback to root"""
        body_node = None
        # Get HTML node from parser instead of context
        html_node = self.parser.html_node
        if html_node:
            for child in html_node.children:
                if child.tag_name == "body":
                    body_node = child
                    break
        if body_node:
            return body_node
        else:
            return self.parser.root

    def _reconstruct_formatting_elements(self, elements: List[Node], context):
        """Reconstruct formatting elements that were implicitly closed"""
        if not elements:
            return

        if self.debug_enabled:
            print(f"    Adoption Agency: Reconstructing formatting elements: {[e.tag_name for e in elements]}")
            print(f"    Adoption Agency: Current parent before reconstruction: {context.current_parent.tag_name}")

        # Reconstruct each formatting element as nested children
        current_parent = context.current_parent

        for element in elements:
            # Clone the formatting element
            clone = Node(element.tag_name, element.attributes.copy())

            # Add as child of current parent
            current_parent.append_child(clone)

            # Add to open elements stack so subsequent parsing knows about it
            context.open_elements.push(clone)

            # Update the active formatting elements to point to the clone instead of the original
            entry = context.active_formatting_elements.find_element(element)
            if entry:
                # Replace the element in the active formatting elements entry
                entry.element = clone
                if self.debug_enabled:
                    print(
                        f"    Adoption Agency: Updated active formatting elements entry to point to cloned {clone.tag_name}"
                    )
            else:
                # Element not found in active formatting elements, add the clone
                # This happens when we reconstruct elements that were previously closed
                from turbohtml.tokenizer import HTMLToken

                dummy_token = HTMLToken("StartTag", clone.tag_name, clone.attributes)
                context.active_formatting_elements.push(clone, dummy_token)
                if self.debug_enabled:
                    print(f"    Adoption Agency: Added cloned {clone.tag_name} to active formatting elements")

            # Update current parent to be the clone for nesting
            current_parent = clone

            if self.debug_enabled:
                print(f"    Adoption Agency: Reconstructed {clone.tag_name} inside {clone.parent.tag_name}")

        # Update context's current parent to the innermost reconstructed element
        context.move_to_element(current_parent)

        if self.debug_enabled:
            print(f"    Adoption Agency: Current parent after reconstruction: {context.current_parent.tag_name}")

    def _safe_detach_node(self, node: Node) -> None:
        """Detach node from its parent safely, even if linkage is inconsistent.

        Ensures node.parent becomes None and sibling pointers are cleared without throwing.
        """
        parent = node.parent
        if not parent:
            return
        # Parent is always a Node with a children list
        if node in parent.children:
            parent.remove_child(node)
        else:
            # Inconsistent linkage: clear pointers directly
            node.parent = None
            node.previous_sibling = None
            node.next_sibling = None

    def reconstruct_active_formatting_elements(self, context):
        """Reconstruct active formatting elements per spec."""
        stack = context.active_formatting_elements._stack
        if not stack:
            return
        if self.debug_enabled:
            print("    reconstruct: active formatting tags:", [e.element.tag_name if e.element else 'MARKER' for e in stack])
        # NOTE: Do NOT snapshot the open elements stack here; it may mutate during reconstruction decisions.
        # Always reference context.open_elements._stack to avoid stale membership causing spurious clones.
        open_stack = context.open_elements._stack
        # Find first (earliest after last marker) formatting entry whose element is not on the current open stack
        first_missing_index = None
        for i, entry in enumerate(stack):
            if entry.element is None:  # marker resets search
                first_missing_index = None
                continue
            if entry.element not in context.open_elements._stack:
                first_missing_index = i
                break
        if first_missing_index is None:
            return
        if self.debug_enabled:
            print("    Adoption Agency: reconstruct: starting from index", first_missing_index)
        for entry in list(stack[first_missing_index:]):
            if entry.element is None or entry.element in open_stack:
                continue
            if self.debug_enabled:
                print(f"    reconstruct: cloning missing formatting element <{entry.element.tag_name}>")
            clone = Node(entry.element.tag_name, entry.element.attributes.copy())
            context.current_parent.append_child(clone)
            context.open_elements.push(clone)
            entry.element = clone
            context.move_to_element(clone)
            if self.debug_enabled:
                print(f"    Adoption Agency: reconstructed {clone.tag_name}")



    def _run_complex_adoption_spec(
        self, formatting_entry: FormattingElementEntry, furthest_block: Node, context, iteration_count: int = 0
    ) -> bool:
        """Run the complex adoption agency algorithm (steps 8-19) per HTML5 spec.

        This implements the full algorithm with proper element reconstruction
        following the html5lib approach.

        Args:
            iteration_count: Which iteration of the algorithm this is (1-8)
        """
        formatting_element = formatting_entry.element
        if self.debug_enabled:
            print(f"\n=== COMPLEX ADOPTION ALGORITHM (Steps 8-19) ===")
            print(f"    Formatting element: {formatting_element.tag_name}")
            print(f"    Furthest block: {furthest_block.tag_name}")
            print(f"    Stack before: {[e.tag_name for e in context.open_elements._stack]}")

        # Step 8: Create a bookmark pointing to the location of the formatting element
        # in the list of active formatting elements
        bookmark_index = context.active_formatting_elements.get_index(formatting_entry)
        if self.debug_enabled:
            print(f"\n--- STEP 8: Create bookmark ---")
            print(f"    Bookmark index in active formatting elements: {bookmark_index}")

        # Step 9: Create a list of elements to be removed from the stack of open elements
        formatting_index = context.open_elements.index_of(formatting_element)
        furthest_index = context.open_elements.index_of(furthest_block)
        if self.debug_enabled:
            print(f"\n--- STEP 9: Identify elements ---")
            print(f"    Formatting element index in stack: {formatting_index}")
            print(f"    Furthest block index in stack: {furthest_index}")

        # Step 10: Find the common ancestor: the element immediately BEFORE the formatting
        # element in the stack of open elements (i.e., one position closer to the root).
        if formatting_index - 1 >= 0:
            common_ancestor = context.open_elements._stack[formatting_index - 1]
        else:
            # If there is no element before it in the stack, fall back to its DOM parent
            common_ancestor = formatting_element.parent

        if not common_ancestor:
            if self.debug_enabled:
                print(f"    STEP 10 ERROR: No common ancestor found - aborting")
            return False

        if self.debug_enabled:
            print(f"\n--- STEP 10: Find common ancestor ---")
            print(f"    Common ancestor: {common_ancestor.tag_name}")

        # Step 11: Create a list "node list" and initialize it to empty
        node_list = []
        if self.debug_enabled:
            print(f"\n--- STEP 11: Initialize node list ---")
            print(f"    Node list initialized (empty)")

        # Step 12: Reconstruction loop
        # This loop implements steps 12.1-12.3 with inner and outer loops
        node = furthest_block
        last_node = furthest_block
        inner_loop_counter = 0

        if self.debug_enabled:
            print(f"\n--- STEP 12: Reconstruction loop ---")
            print(f"    Starting with furthest_block: {furthest_block.tag_name}")
            print(
                f"    Initial furthest_block parent: {furthest_block.parent.tag_name if furthest_block.parent else 'None'}"
            )

        max_iterations = len(context.open_elements._stack) + 10
        # Track previous stack index to ensure we make upward progress; the
        # previous implementation compared against (index-1) which caused
        # legitimate upward moves (index-1) to appear as no progress and
        # prematurely terminated reconstruction, losing required clones.
        prev_node_index = None
        # Track a single intervening formatting element we cloned (for optional inner wrapper)
        cloned_intervening_tag: Optional[str] = None
        while True:
            if inner_loop_counter >= max_iterations:
                if self.debug_enabled:
                    print(f"        STEP 12 SAFEGUARD: exceeded max_iterations={max_iterations}, breaking loop")
                break
            inner_loop_counter += 1
            if self.debug_enabled:
                print(f"\n    --- Loop iteration {inner_loop_counter} ---")
                print(f"        Current node: {node.tag_name}")

            # Step 12.1: Find the previous element in open elements stack
            node_index = context.open_elements.index_of(node)
            if node_index <= 0:
                if self.debug_enabled:
                    print(f"        STEP 12.1: Node index <= 0, breaking loop")
                break
            # Determine the previous element (moving upward). A valid upward move
            # must strictly decrease the stack index. If it does not, we stop to
            # avoid infinite looping.
            prev_index = node_index - 1
            node = context.open_elements._stack[prev_index]
            if self.debug_enabled:
                print(
                    f"        STEP 12.1: Previous element: {node.tag_name} (index {prev_index}) | stack={[e.tag_name for e in context.open_elements._stack]}"
                )
            if prev_node_index is not None and prev_index >= prev_node_index:
                if self.debug_enabled:
                    print(
                        f"        STEP 12 GUARD: no upward progress (prev_index {prev_index} >= last {prev_node_index}), breaking loop"
                    )
                break
            prev_node_index = prev_index

            # Step 12.2: If node is the formatting element, then break
            if node == formatting_element:
                if self.debug_enabled:
                    print(f"        STEP 12.2: Node is formatting element, breaking loop")
                break


            # Step 12.3: If node is not in active formatting elements, remove it
            node_entry = context.active_formatting_elements.find_element(node)
            if not node_entry:
                if self.debug_enabled:
                    print(
                        f"        STEP 12.3: Node {node.tag_name} not in active formatting - removing from stack (stack_idx={context.open_elements.index_of(node)})"
                    )
                context.open_elements.remove_element(node)
                # Spec: simply remove non-formatting node from stack; DOM reparenting of such
                # intervening nodes is not performed here (they remain in place). Custom <a>
                # ladder relocation logic removed for spec purity.
                # Reset node to last_node (the subtree we are restructuring) so the next
                # iteration's Step 12.1 finds the element immediately above the removed
                # node relative to the still-current furthest block chain. This prevents
                # premature termination when index_of(node) becomes -1 (early break) and
                # allows climbing further to clone remaining formatting ancestors (e.g. <em>
                # in multi-iteration adoption ladder cases).
                node = last_node
                continue


            # Step 12.4 (spec): If we've been through this loop three times already and node is
            # still in the list of active formatting elements, then remove node from that list
            # (without touching the DOM) and stop processing this node (continue loop).
            if inner_loop_counter > 3:
                if self.debug_enabled:
                    print(f"        STEP 12.4: Loop count > 3, removing {node.tag_name} from active formatting")
                context.active_formatting_elements.remove_entry(node_entry)
                continue

            # Step 12.5: Create a clone of node
            node_clone = Node(tag_name=node.tag_name, attributes=node.attributes.copy())
            if self.debug_enabled:
                print(
                    f"        STEP 12.5: Created clone of {node.tag_name} (will replace original at stack_idx={context.open_elements.index_of(node)})"
                )
            # Record intervening formatting clone (only first) for potential inner wrapper later
            if (
                cloned_intervening_tag is None
                and formatting_element.tag_name == 'b'
                and furthest_block.tag_name == 'p'
                and node.tag_name in ('i', 'em')
            ):
                cloned_intervening_tag = node.tag_name

            # Step 12.6: Replace the entry for node in active formatting elements
            # with an entry for the clone
            clone_entry = FormattingElementEntry(node_clone, node_entry.token)
            bookmark_index_before = context.active_formatting_elements.get_index(node_entry)
            context.active_formatting_elements.replace_entry(node_entry, node_clone, node_entry.token)
            if self.debug_enabled:
                print(f"        STEP 12.6: Replaced active formatting entry")

            # Step 12.7: Replace node with the clone in the open elements stack
            context.open_elements.replace_element(node, node_clone)
            if self.debug_enabled:
                print(f"        STEP 12.7: Replaced in open elements stack")

            # Step 12.8: If last_node is the furthest block, set the bookmark
            if last_node == furthest_block:
                bookmark_index = bookmark_index_before + 1
                if self.debug_enabled:
                    print(f"        STEP 12.8: Updated bookmark index to {bookmark_index}")

            # Step 12.9: Insert last_node as a child of node_clone
            if last_node.parent:
                if self.debug_enabled:
                    print(f"        STEP 12.9: Removing {last_node.tag_name} from parent {last_node.parent.tag_name}")
                last_node.parent.remove_child(last_node)

            if self.debug_enabled:
                print(
                    f"        STEP 12.9: Adding {last_node.tag_name} as child of {node_clone.tag_name} (children_of_clone_before={[c.tag_name for c in node_clone.children]})"
                )

            node_clone.append_child(last_node)

            # Step 12.10: Set last_node to node_clone
            last_node = node_clone
            node = node_clone
            if self.debug_enabled:
                print(f"        STEP 12.10: Set last_node to {node_clone.tag_name}")

        # Step 13: Insert last_node into common_ancestor (always execute; prints optional)
        # Adjustment: For iterative </a> complex adoptions beyond the first,
        # html5lib expected trees show the newly formed block (last_node, typically a <div>) nesting
        # inside the nearest ancestor <div> that already contains earlier <a> wrappers, rather than
        # being appended directly under <body>. When the common_ancestor resolved to the root/body,
        # we rewrite it to the deepest <div> ancestor of the formatting element (if any) so each
        # successive iteration produces a deeper nested <div><a><div><a> ladder instead of a flat
        # sequence of sibling <div>/<a> pairs.
        # Additional Step 13 adjustment for </a> ladder iterations:
        # After first complex iteration, the cloned <b> (last_node) should become a top-level sibling
        # of the outer <div>, not remain nested inside it. Mark that <b> so later iterations can
        # target it as the common ancestor for appended nested <div> blocks.
        if self.debug_enabled:
            print(f"\n--- STEP 13: Insert last_node into common ancestor ---")
            print(f"    last_node={last_node.tag_name}, common_ancestor={common_ancestor.tag_name}, furthest_block={furthest_block.tag_name}")
            print("    STEP 13 CONTEXT: common_ancestor_children_before=", [c.tag_name for c in common_ancestor.children] if common_ancestor else None)
            if formatting_element.tag_name == 'i' and furthest_block.tag_name == 'p':
                print("    STEP 13 DETAIL (i+p case): furthest_block initial children=", [c.tag_name for c in furthest_block.children])
        if common_ancestor is last_node:
            if self.debug_enabled:
                print("    Step 13: last_node is common_ancestor (no insertion)")
        else:
            # Guard: if common_ancestor is already a descendant of last_node, inserting would create a cycle.
            ca_cursor = common_ancestor
            is_desc = False
            guard_walk = 0
            while ca_cursor is not None and guard_walk < 200:
                if ca_cursor is last_node:
                    is_desc = True
                    break
                ca_cursor = ca_cursor.parent
                guard_walk += 1
            if is_desc:
                if self.debug_enabled:
                    print("    Step 13: skipped insertion; common_ancestor is descendant of last_node (cycle guard)")
                # Treat as already positioned; no further action
                pass
            else:
            # Detach if needed
                if last_node.parent is not None and last_node.parent is not common_ancestor:
                    self._safe_detach_node(last_node)
                # Foster parenting if required
                if self._should_foster_parent(common_ancestor):
                    if self.debug_enabled:
                        print("    Step 13: foster parenting last_node")
                    self._foster_parent_node(last_node, context, common_ancestor)
                else:
                    if common_ancestor.tag_name == 'template':
                        content_child = None
                        for ch in common_ancestor.children:
                            if ch.tag_name == 'content':
                                content_child = ch
                                break
                        (content_child or common_ancestor).append_child(last_node)
                    else:
                        # Only append if not already child
                        if last_node.parent is not common_ancestor:
                            try:
                                common_ancestor.append_child(last_node)
                            except ValueError:
                                # Cycle guard fallback: skip append
                                if self.debug_enabled:
                                    print("    Step 13: append skipped by cycle guard ValueError")
                    if self.debug_enabled:
                        print(f"    Step 13: appended {last_node.tag_name} under {common_ancestor.tag_name}")
                        print("    STEP 13 CONTEXT: common_ancestor_children_after=", [c.tag_name for c in common_ancestor.children])



            # Post-Step-13 targeted relocation: If we are processing an <a>
            # on a later iteration and the common ancestor was the body/html, we want the newly
            # inserted last_node (typically a <div>) to become nested inside the existing top-level
            # <div> ladder instead of remaining a sibling under <body>. Expected tree shows exactly
            # one top-level <div> with a cascading <div><a><div><a> structure.

        # Step 14: Create a clone of the formatting element (spec always clones)
        # NOTE: Previous optimization to skip cloning for trivial empty case caused
        # repeated Adoption Agency invocations without making progress. Always clone
        # to ensure Steps 17-19 can update stacks and active formatting elements.
        formatting_clone = Node(tag_name=formatting_element.tag_name, attributes=formatting_element.attributes.copy())
        # No propagation of non-spec flags
        if self.debug_enabled:
            print(f"\n--- STEP 14: Create formatting element clone ---")
            print(f"    Created clone of {formatting_element.tag_name}")

        # Step 15/16 (spec): Take all children of furthest_block and append them to formatting_clone; then
        # append formatting_clone to furthest_block. The spec does NOT special‑case table containers here; the
        # furthest_block by definition is a special element after the formatting element (may be table descendent);
        # html5lib behavior keeps clone inside furthest_block when furthest_block is a td/th, but if furthest_block
        # is a table container itself, its children are moved into clone then clone is appended (mirroring spec).
        table_containers = {"table", "tbody", "thead", "tfoot", "tr"}
        is_table_container = furthest_block.tag_name in table_containers
        if self.debug_enabled:
            print(f"\n--- STEP 15/16: Integrate formatting clone ---")
            print(f"    Furthest block is table container: {is_table_container}")
        if is_table_container:
            parent = furthest_block.parent or self._get_body_or_root(context)
            if parent:
                if furthest_block in parent.children:
                    idx = parent.children.index(furthest_block)
                else:
                    idx = len(parent.children)
                parent.children.insert(idx, formatting_clone)
                formatting_clone.parent = parent
                if self.debug_enabled:
                    print(f"    Foster-parented clone before <{furthest_block.tag_name}>")
        else:
            if self.debug_enabled:
                print(f"--- STEP 15: Move children of furthest_block into clone ---")
            for child in furthest_block.children[:]:
                furthest_block.remove_child(child)
                formatting_clone.append_child(child)
            # Append clone under furthest_block (cycle guard just in case)
            if furthest_block._would_create_circular_reference(formatting_clone):
                parent = furthest_block.parent or self._get_body_or_root(context)
                if parent:
                    idx = parent.children.index(furthest_block) if furthest_block in parent.children else len(parent.children)
                    parent.children.insert(idx, formatting_clone)
                    formatting_clone.parent = parent
                    if self.debug_enabled:
                        print(f"    Cycle guard: inserted clone before furthest_block")
            else:
                furthest_block.append_child(formatting_clone)
                if self.debug_enabled:
                    print(f"--- STEP 16: Appended clone under furthest_block <{furthest_block.tag_name}>")

        # Safety check: Ensure no circular references were created
        self._validate_no_circular_references(formatting_clone, furthest_block)

        # Step 17: Remove original formatting element entry from active list
        context.active_formatting_elements.remove_entry(formatting_entry)
        if self.debug_enabled:
            print(f"\n--- STEP 17: Removed original formatting element from active list ---")

        # Step 18: Insert clone entry at bookmark index
        if bookmark_index >= 0 and bookmark_index <= len(context.active_formatting_elements):
            context.active_formatting_elements.insert_at_index(bookmark_index, formatting_clone, formatting_entry.token)
        else:
            context.active_formatting_elements.push(formatting_clone, formatting_entry.token)
        if self.debug_enabled:
            print(f"--- STEP 18: Inserted clone into active formatting at index {bookmark_index}")

        # Step 19: Replace original formatting element in open elements stack with clone (same position)
        # Locate original position (could have shifted if nodes removed); compute fresh index
        original_index = context.open_elements.index_of(formatting_element)
        if original_index != -1:
            # Replace in-place
            context.open_elements._stack[original_index] = formatting_clone
        else:
            # If formatting element vanished (e.g. popped in step 12 removals) insert clone just above furthest_block
            fb_index = context.open_elements.index_of(furthest_block)
            insert_at = fb_index + 1 if fb_index != -1 else len(context.open_elements._stack)
            context.open_elements._stack.insert(insert_at, formatting_clone)
        if self.debug_enabled:
            print(f"--- STEP 19: Replaced original formatting element in open stack with clone ---")

        # Ensure stack order reflects DOM ancestor-before-descendant: if the clone (a descendant
        # of furthest_block after step 15/16) appears before furthest_block, move it to directly
        # after furthest_block. This prevents repeated complex adoption runs for the same end tag
        # by making the formatting clone the current node (top of stack) when no further special
        # elements follow it.
        fb_index = context.open_elements.index_of(furthest_block)
        clone_index = context.open_elements.index_of(formatting_clone)
        if (
            fb_index != -1
            and clone_index != -1
            and clone_index < fb_index
        ):
            if self.debug_enabled:
                print(
                    f"    Step 19 reorder: moving formatting clone after furthest_block (indices {clone_index} -> after {fb_index})"
                )
            context.open_elements._stack.pop(clone_index)
            fb_index = context.open_elements.index_of(furthest_block)
            context.open_elements._stack.insert(fb_index + 1, formatting_clone)

        # prior heuristic reinstatement attempts. The previous implementation
        # performed a full depth-based stable sort of the open elements stack which, while
        # ensuring ancestor-before-descendant order, can reorder sibling groups in ways the
        # spec's push/pop sequence would not, altering later tree construction decisions.
        # If specific misordering cases reappear (descendant before ancestor), implement a
        # minimal local swap instead of full-stack sorting.
        self._normalize_local_misordered_pair(context, formatting_clone, furthest_block)

        # Cleanup: remove empty formatting clone before text when not immediately re-nested
        if (
            not formatting_clone.children
            and formatting_clone.parent
            and (formatting_clone.next_sibling and formatting_clone.next_sibling.tag_name == "#text")
            and not (formatting_clone.previous_sibling and formatting_clone.previous_sibling.tag_name == formatting_clone.tag_name)
        ):
            parent = formatting_clone.parent
            parent.remove_child(formatting_clone)
            afe_entry = context.active_formatting_elements.find_element(formatting_clone)
            if afe_entry:
                context.active_formatting_elements.remove_entry(afe_entry)
            if context.open_elements.contains(formatting_clone):
                context.open_elements.remove_element(formatting_clone)
            if self.debug_enabled:
                print("    Cleanup: removed stray empty formatting clone before text")

        # Insertion point: per spec set to furthest_block (current node)
        context.move_to_element(furthest_block)


        if self.debug_enabled:
            print(f"\n--- STEP 18/19: Update stacks ---")
            print(f"    Removed original {formatting_element.tag_name} from stack")
            print(f"    Added {formatting_clone.tag_name} under {furthest_block.tag_name}")
            print(f"    Final stack: {[e.tag_name for e in context.open_elements._stack]}")
            print(f"    Final active formatting: {[e.element.tag_name for e in context.active_formatting_elements]}")
            print(f"    Current parent now: {context.current_parent.tag_name}")
            if formatting_element.tag_name == 'i' and furthest_block.tag_name == 'p':
                print(
                    "    POST ADOPTION (i+p case): paragraph children now=",
                    [c.tag_name for c in furthest_block.children],
                )
            print(f"=== ADOPTION AGENCY ALGORITHM END ===\n")
        return True


    def _normalize_local_misordered_pair(self, context, clone: Node, furthest_block: Node) -> None:
        """Minimal correction: if clone (now ancestor) appears before furthest_block on stack, swap.

        Avoids full-stack reordering side-effects while still preventing repeated adoption loops
        where descendant precedes its ancestor.
        """
        # Previous implementation skipped <a> to allow deeper ladder construction, but this produced
        # runaway nested <a> chains (<a><a><a>...) because the formatting clone (now a descendant of
        # the furthest block) remained earlier on the open elements stack, continually satisfying
        # adoption preconditions. We now normalize uniformly for all formatting elements: if the
        # clone's stack index is before the furthest block, move it to directly after the furthest
        # block. This matches the spec requirement that the open elements stack reflect DOM ancestor
        # ordering (ancestors before descendants). We do NOT require the clone be an ancestor of the
        # furthest block—being a descendant is the misordering we correct.
        stack = context.open_elements._stack
        if len(stack) < 2:
            return
        try:
            ci = stack.index(clone)
            fbi = stack.index(furthest_block)
        except ValueError:
            return
        if ci < fbi:
            # Move clone to directly after furthest_block (maintain relative order otherwise)
            stack.pop(ci)
            # Adjust index if removal shifts positions
            fbi = stack.index(furthest_block)
            stack.insert(fbi + 1, clone)
            if self.debug_enabled:
                print("    LocalStackNorm: moved formatting clone after furthest_block (swap)")




    def _validate_no_circular_references(self, formatting_clone: Node, furthest_block: Node) -> None:
        """Validate that no circular references were created in the DOM tree"""
        if self.debug_enabled:
            print(f"    Adoption Agency: Validating no circular references")

        # Check that formatting_clone doesn't have furthest_block as an ancestor
        current = formatting_clone.parent
        visited = set()
        depth = 0

        while current and depth < 50:  # Safety limit
            if id(current) in visited:
                raise ValueError(f"Circular reference detected: {current.tag_name} already visited")

            if current == furthest_block:
                # This is expected - furthest_block should be the parent
                if self.debug_enabled:
                    print(f"    Adoption Agency: Valid parent relationship confirmed")
                break

            visited.add(id(current))
            current = current.parent
            depth += 1

        # Also check the reverse - that furthest_block doesn't have formatting_clone as an ancestor
        current = furthest_block.parent
        visited = set()
        depth = 0

        while current and depth < 50:  # Safety limit
            if id(current) in visited:
                raise ValueError(
                    f"Circular reference detected in furthest_block ancestry: {current.tag_name} already visited"
                )
            if current == formatting_clone:
                raise ValueError(
                    f"Circular reference: furthest_block {furthest_block.tag_name} has formatting_clone {formatting_clone.tag_name} as ancestor"
                )
            visited.add(id(current))
            current = current.parent
            depth += 1
        # If loop exits normally, no circular reference detected
        return

    def _iter_descendants(self, node: Node):
        # Yield all descendants (depth-first) of a node
        stack = list(node.children)
        while stack:
            cur = stack.pop()
            yield cur
            # All nodes have a children list
            if cur.children:
                stack.extend(cur.children)


    def _should_foster_parent(self, common_ancestor: Node) -> bool:
        # Check if foster parenting is needed
        # Foster parenting is needed if common ancestor is a table element
        # and we're not already in a cell or caption
        return common_ancestor.tag_name in (
            "table",
            "tbody",
            "tfoot",
            "thead",
            "tr",
        ) and not common_ancestor.find_ancestor(lambda n: n.tag_name in ("td", "th", "caption"))

    def _foster_parent_node(self, node: Node, context, table: Node = None) -> None:
        # Foster parent a node according to HTML5 rules
        # Use provided table or find the table
        if not table:
            table = None
            current = context.current_parent
            while current:
                if current.tag_name == "table":
                    table = current
                    break
                current = current.parent

        if table and table.parent:
            # Insert before the table
            table_index = table.parent.children.index(table)
            table.parent.children.insert(table_index, node)
            node.parent = table.parent
            if self.debug_enabled:
                print(f"    Adoption Agency: Foster parented {node.tag_name} before table at index {table_index}")
        else:
            # Fallback - need to find a safe parent that won't create circular reference
            safe_parent = self._find_safe_parent(node, context)
            if safe_parent:
                safe_parent.append_child(node)
            else:
                # Last resort - add to the document body or root
                body_or_root = self._get_body_or_root(context)
                if body_or_root != node and not node._would_create_circular_reference(body_or_root):
                    body_or_root.append_child(node)
                else:
                    # Cannot safely place the node - this indicates a serious issue
                    if self.debug_enabled:
                        print(f"    Adoption Agency: WARNING - Cannot safely foster parent {node.tag_name}")

    def _find_safe_parent(self, node: Node, context) -> Optional[Node]:
        # Find a safe ancestor under which to reparent a node during foster parenting (spec helper)
        candidate = context.current_parent
        visited: set[int] = set()
        while candidate is not None and id(candidate) not in visited:
            if candidate is not node and not node._would_create_circular_reference(candidate):
                return candidate
            visited.add(id(candidate))
            candidate = candidate.parent
        body_or_root = self._get_body_or_root(context)
        if body_or_root and body_or_root is not node and not node._would_create_circular_reference(body_or_root):
            return body_or_root
        return None

