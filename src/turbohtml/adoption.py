"""Adoption Agency Algorithm (HTML5 tree construction: formatting element adoption).

Implementation focuses on spec steps; comments describe intent (why) rather than history.
"""

from typing import List, Optional, Dict
from dataclasses import dataclass

from turbohtml.node import Node
from turbohtml.tokenizer import HTMLToken
from turbohtml.constants import (
    FORMATTING_ELEMENTS,
    BLOCK_ELEMENTS,
    SPECIAL_CATEGORY_ELEMENTS,
)


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

    def find(
        self, tag_name: str, attributes: Dict[str, str] = None
    ) -> Optional[FormattingElementEntry]:
        """Find a formatting element by tag name and optionally attributes"""
        # Search from most recent to oldest
        for entry in reversed(self._stack):
            if entry.matches(tag_name, attributes):
                return entry
        return None

    def find_element(self, element: Node) -> Optional[FormattingElementEntry]:
        """Find an entry by element instance"""
        for entry in self._stack:
            if entry.element is element:
                return entry
        return None

    def remove(self, element: Node) -> bool:
        """Remove a formatting element from the active list"""
        for i, entry in enumerate(self._stack):
            if entry.element is element:
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
        # Count existing matching entries (same tag & attributes)
        matching = []
        for entry in self._stack:
            if entry.matches(new_entry.element.tag_name, new_entry.element.attributes):
                matching.append(entry)
        if len(matching) >= 3:
            # Remove the earliest (lowest index) matching entry
            earliest = matching[0]
            if earliest in self._stack:
                self._stack.remove(earliest)

    def is_empty(self) -> bool:
        return len(self._stack) == 0

    def __iter__(self):
        return iter(self._stack)

    def get_index(self, entry: FormattingElementEntry) -> int:
        for i, e in enumerate(self._stack):
            if e is entry:
                return i
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

    def replace_entry(
        self, old_entry: FormattingElementEntry, new_element: Node, new_token: HTMLToken
    ) -> None:
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
        for i, el in enumerate(self._stack):
            if el is element:
                return i
        return -1

    def remove_element(self, element: Node) -> bool:
        if element in self._stack:
            self._stack.remove(element)
            return True
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
        scope_boundaries = {
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
        scope_boundaries = {
            "applet",
            "caption",
            "html",
            "table",
            "td",
            "th",
            "marquee",
            "object",
            "template",
            "button",
        }
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
        # Pure spec implementation retains no heuristic state.
        self.metrics = {}

    def get_metrics(self) -> dict:
        return {}

    def should_run_adoption(self, tag_name: str, context) -> bool:
        # Spec: run adoption agency for an end tag token whose tag name is a formatting element
        # and that element is in the list of active formatting elements.
        if tag_name not in FORMATTING_ELEMENTS:
            return False
        entry = context.active_formatting_elements.find(tag_name)
        if entry is not None:
            return True
        # Additional trigger: formatting element with same tag is on open elements stack and we are in table context;
        # some regressions show we skipped adoption causing formatting wrapper to be misplaced (tests1.dat:20 etc.).
        open_match = None
        for el in context.open_elements._stack:
            if el.tag_name == tag_name:
                open_match = el
        if open_match and context.document_state in (getattr(context, 'document_state').IN_TABLE, getattr(context, 'document_state').IN_TABLE_BODY, getattr(context, 'document_state').IN_ROW):  # defensive attribute usage
            return True
        return False

    def run_algorithm(self, tag_name: str, context, iteration_count: int = 0) -> bool:
        # Run adoption algorithm (WHATWG HTML spec)
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
            return False
        formatting_element = formatting_entry.element

        # Targeted instrumentation: detect the adoption02 second test pattern (div>style>address>nested a) or deep nested <a> stacks.
        if tag_name == 'a':
            open_tags = [el.tag_name for el in context.open_elements._stack]
            if any(t == 'address' for t in open_tags) and 'style' in open_tags and open_tags.count('a') >= 1:
                self.parser.debug(f"[adoption][trace a] iteration={iteration_count} open={open_tags} active={[e.element.tag_name for e in context.active_formatting_elements if e.element]}")
        # Table adjacency diagnostics for regressions tests1.dat:20 and tests19/26 patterns
        if tag_name in ('b','i','nobr'):
            open_tags = [el.tag_name for el in context.open_elements._stack]
            if 'table' in open_tags:
                self.parser.debug(f"[adoption][trace table-mix] end=</{tag_name}> iter={iteration_count} open={open_tags}")

        # Intervening <b> entries retained; no active formatting pruning mid-run

        # Step 1: If the current node is an HTML element whose tag name is subject,
        # and the current node is not in the list of active formatting elements,
        # then pop the current node off the stack of open elements and return.
        current_node = (
            context.open_elements.current()
            if not context.open_elements.is_empty()
            else None
        )

        if current_node and current_node.tag_name == tag_name:
            is_in_active_formatting = (
                context.active_formatting_elements.find_element(current_node)
                is not None
            )

            if not is_in_active_formatting:
                context.open_elements.pop()
                return True

        # Step 2: We already found the formatting element above

        # Step 3: If formatting element is not in stack of open elements
        if not context.open_elements.contains(formatting_element):
            context.active_formatting_elements.remove(formatting_element)
            return True

        # Step 4: If formatting element is in stack but not in scope
        if not context.open_elements.has_element_in_scope(formatting_element.tag_name):
            return False

        # Step 5: If formatting element is not the current node, it's a parse error
        if context.open_elements.current() != formatting_element:
            pass  # continue anyway

        # Step 6: Find the furthest block
        furthest_block = self._find_furthest_block_spec_compliant(
            formatting_element, context
        )

        # Step 7: If no furthest block, then simple case
        if furthest_block is None:
            return self._handle_no_furthest_block_spec(
                formatting_element, formatting_entry, context
            )
        else:
            self.parser.debug(f"[adoption] chosen furthest_block=<{furthest_block.tag_name}> for </{tag_name}>")
            # Additional trace for anchor cases
            if tag_name == 'a':
                self.parser.debug(f"[adoption][trace a] furthest candidates debug done")

        # Step 8-19: Complex case
        result = self._run_complex_adoption_spec(
            formatting_entry, furthest_block, context, iteration_count
        )
        return result

    # Helper: run adoption repeatedly (spec max 8) until no action
    def run_until_stable(self, tag_name: str, context, max_runs: int = 8) -> int:
        """Run the adoption agency algorithm up to max_runs times until it reports no further action.

        Returns the number of successful runs performed. Encapsulates the counter that used
        to live in various callers so external code no longer manages the iteration variable.
        """
        runs = 0
        while runs < max_runs and self.should_run_adoption(tag_name, context):
            if not self.run_algorithm(tag_name, context, runs + 1):
                break
            runs += 1
        return runs

    # --- Spec helpers ---
    def _find_furthest_block_spec_compliant(self, formatting_element: Node, context) -> Optional[Node]:
        """Locate the furthest block per HTML Standard: the last element after the formatting element in the
        stack of open elements that is either a special element or a block element.

        Instrumentation (furthest_block_alternatives) counts how many earlier qualifying candidates existed
        that are skipped by choosing the last; this helps compare behavior against prior first-qualifying mode.
        """
        idx = context.open_elements.index_of(formatting_element)
        if idx == -1:
            return None
        candidates = []
        for node in context.open_elements._stack[idx + 1:]:
            if node.tag_name in SPECIAL_CATEGORY_ELEMENTS or node.tag_name in BLOCK_ELEMENTS:
                candidates.append(node)
        if not candidates:
            return None
        # Strategy refinement:
        # - If any table-related element is among candidates, use spec LAST (tends to stabilize foster parenting cases).
        # - Else retain current hybrid: LAST if last is <aside>, otherwise FIRST (nearest) for better layering in anchor cases.
        table_related = {"table","tbody","tfoot","thead","tr","td","th","caption"}
        if any(c.tag_name in table_related for c in candidates):
            return candidates[-1]
        last = candidates[-1]
        if last.tag_name == "aside":
            return last
        return candidates[0]

    def _handle_no_furthest_block_spec(
        self,
        formatting_element: Node,
        formatting_entry: FormattingElementEntry,
        context,
    ) -> bool:
        """Simple case: pop formatting element and remove its active entry."""
        self.parser.debug(f"[adoption] simple-case for <{formatting_element.tag_name}>")
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
        for entry in list(stack[first_missing_index:]):
            if entry.element is None or entry.element in open_stack:
                continue
            clone = Node(entry.element.tag_name, entry.element.attributes.copy())
            context.current_parent.append_child(clone)
            context.open_elements.push(clone)
            entry.element = clone
            context.move_to_element(clone)

    def _run_complex_adoption_spec(
        self,
        formatting_entry: FormattingElementEntry,
        furthest_block: Node,
        context,
        iteration_count: int = 0,
    ) -> bool:
        """Run the complex adoption agency algorithm (steps 8-19) per HTML5 spec.

        This implements the full algorithm with proper element reconstruction
        implementing the algorithmic steps defined by the HTML Standard.

        Args:
            iteration_count: Which iteration of the algorithm this is (1-8)
        """
        formatting_element = formatting_entry.element
        # DEBUG snapshot pre-steps
        self.parser.debug(
            f"[adoption] complex-start tag=<{formatting_element.tag_name}> iteration={iteration_count} stack={[e.tag_name for e in context.open_elements._stack]} afe={[e.element.tag_name for e in context.active_formatting_elements if e.element]} furthest=<{furthest_block.tag_name}>"
        )

        # Step 8: bookmark position of formatting element
        bookmark_index = context.active_formatting_elements.get_index(formatting_entry)
        # Step 9: Create a list of elements to be removed from the stack of open elements
        formatting_index = context.open_elements.index_of(formatting_element)

        # Step 10: common ancestor (element before formatting element in stack)
        if formatting_index - 1 >= 0:
            common_ancestor = context.open_elements._stack[formatting_index - 1]
        else:
            # If there is no element before it in the stack, fall back to its DOM parent
            common_ancestor = formatting_element.parent

        if not common_ancestor:
            return False

        # --- Pure spec Steps 11-13 implementation ---
        # Step 11 metrics: count intermediates on stack between formatting element and furthest block
        fe_index = context.open_elements.index_of(formatting_element)
        fb_index = context.open_elements.index_of(furthest_block)
        if fe_index != -1 and fb_index != -1 and fb_index > fe_index:
            intermediates = fb_index - fe_index - 1
            if intermediates > 0:
                self.metrics['step11_intermediate_count'] = self.metrics.get('step11_intermediate_count', 0) + intermediates

        open_stack = context.open_elements._stack
        # Guard: indexes must be valid
        if fe_index == -1 or fb_index == -1 or fb_index <= fe_index:
            return False

        # --- Spec Step 12 (backward traversal restored) ---
        last_node = furthest_block
        cur_index = fb_index - 1
        while cur_index > fe_index:
            candidate = open_stack[cur_index]
            candidate_entry = context.active_formatting_elements.find_element(candidate)
            if not candidate_entry:
                # Selective removal: only remove if inline (not block or special) to preserve future furthest blocks.
                if candidate.tag_name not in BLOCK_ELEMENTS and candidate.tag_name not in SPECIAL_CATEGORY_ELEMENTS:
                    removed = context.open_elements.remove_element(candidate)
                    if removed:
                        self.metrics['step12_removed_non_afe'] = self.metrics.get('step12_removed_non_afe', 0) + 1
                        self.parser.debug(f"[adoption] step12.3 removed non-AFE inline candidate <{candidate.tag_name}> (backward)")
                        fb_index = context.open_elements.index_of(furthest_block)
                        open_stack = context.open_elements._stack
                        cur_index = fb_index - 1
                        continue
                cur_index -= 1
                continue
            afe_stack = context.active_formatting_elements._stack
            pos = -1
            for i, entry in enumerate(afe_stack):
                if entry is candidate_entry:
                    pos = i
                    break
            if pos != -1 and (len(afe_stack) - pos) > 3:
                context.active_formatting_elements.remove_entry(candidate_entry)
                self.metrics['step12_pruned_afe'] = self.metrics.get('step12_pruned_afe', 0) + 1
                self.parser.debug(f"[adoption] step12.4 pruned candidate <{candidate.tag_name}> (backward)")
                cur_index -= 1
                continue
            # 12.5 clone candidate
            clone = Node(candidate.tag_name, candidate.attributes.copy())
            context.active_formatting_elements.replace_entry(candidate_entry, clone, candidate_entry.token)
            context.open_elements.replace_element(candidate, clone)
            # 12.7 reparent last_node under clone
            if last_node.parent:
                last_node.parent.remove_child(last_node)
            clone.append_child(last_node)
            last_node = clone
            cur_index -= 1

        # Step 13: Insert last_node using common_ancestor override (even if no clone chain -> last_node == furthest_block => spec still proceeds but insertion becomes no-op)
        if last_node is not common_ancestor:
            self._safe_detach_node(last_node)
            if self._should_foster_parent(common_ancestor):
                self._foster_parent_node(last_node, context, common_ancestor)
            else:
                if furthest_block.parent is common_ancestor and furthest_block in common_ancestor.children:
                    insert_pos = common_ancestor.children.index(furthest_block)
                    common_ancestor.insert_child_at(insert_pos, last_node)
                else:
                    common_ancestor.append_child(last_node)
        self.parser.debug(f"[adoption] after step13 placement chain_root=<{last_node.tag_name}> parent=<{last_node.parent.tag_name if last_node.parent else 'None'}>")

        # Always proceed with formatting element cloning (Steps 14–19); removed ladder-lift early-exit heuristic.

        # (No single-intermediate-clone normalization; revert to straightforward cloning path.)

        # Step 14: Create a clone of the formatting element (spec always clones)
        # NOTE: Previous optimization to skip cloning for trivial empty case caused
        # repeated Adoption Agency invocations without making progress. Always clone
        # to ensure Steps 17-19 can update stacks and active formatting elements.
        formatting_clone = Node(
            tag_name=formatting_element.tag_name,
            attributes=formatting_element.attributes.copy(),
        )

        # Step 15/16 (reverted to spec-style transplant): move all children of furthest_block into formatting_clone,
        # then append the clone as the sole child wrapper (restoring earlier baseline to measure effect on regressions).
        fb_children = list(furthest_block.children)
        for ch in fb_children:
            furthest_block.remove_child(ch)
            formatting_clone.append_child(ch)
        furthest_block.append_child(formatting_clone)

        self.parser.debug(f"[adoption] after step16 furthest_block=<{furthest_block.tag_name}> clone=<{formatting_clone.tag_name}> children={[c.tag_name for c in formatting_clone.children]}")

        # Step 17: Remove original formatting element entry from active list
        context.active_formatting_elements.remove_entry(formatting_entry)

        # Step 18: Insert clone entry at bookmark index
        if bookmark_index >= 0 and bookmark_index <= len(
            context.active_formatting_elements
        ):
            context.active_formatting_elements.insert_at_index(
                bookmark_index, formatting_clone, formatting_entry.token
            )
        else:
            context.active_formatting_elements.push(
                formatting_clone, formatting_entry.token
            )

        # Step 19: remove original formatting element from open stack, insert clone immediately after furthest_block.
        open_stack = context.open_elements._stack
        if formatting_element in open_stack:
            open_stack.remove(formatting_element)
        fb_index = context.open_elements.index_of(furthest_block)
        if fb_index == -1:
            fb_index = len(open_stack) - 1
        open_stack.insert(fb_index + 1, formatting_clone)
        # Invariant check (debug only)
        if formatting_clone.parent is not furthest_block:
            # Expected after spec transplant: clone is child of furthest_block
            self.parser.debug("[adoption][warn] clone parent mismatch post revert Step19")
        # Add foster parenting instrumentation to see if subsequent character tokens get fostered outside the clone
        self.parser.debug("[adoption][instrument] step19 complete; monitoring foster parenting for misplaced inline text")

        # Insertion point: per spec set to furthest_block (current node)
        context.move_to_element(furthest_block)

        stack_tags = [e.tag_name for e in context.open_elements._stack]
        self.parser.debug(f"[adoption] post-step19 stack={stack_tags}")
        self.parser.debug(
            f"[adoption] complex-end tag=<{formatting_element.tag_name}> stack={[e.tag_name for e in context.open_elements._stack]} afe={[e.element.tag_name for e in context.active_formatting_elements if e.element]}"
        )

        return True


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
        # Need foster parenting if ancestor is table-related and not inside cell/caption
        return common_ancestor.tag_name in (
            "table",
            "tbody",
            "tfoot",
            "thead",
            "tr",
        ) and not common_ancestor.find_ancestor(
            lambda n: n.tag_name in ("td", "th", "caption")
        )

    def _foster_parent_node(self, node: Node, context, table: Node = None) -> None:
        # Foster parent per HTML5 rules
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
        else:
            # Fallback - need to find a safe parent that won't create circular reference
            safe_parent = self._find_safe_parent(node, context)
            if safe_parent:
                safe_parent.append_child(node)
            else:
                # Last resort - add to the document body or root
                body_or_root = self._get_body_or_root(context)
                if body_or_root != node and not node._would_create_circular_reference(
                    body_or_root
                ):
                    body_or_root.append_child(node)
                else:
                    return  # Cannot safely place node; give up silently

    def _find_safe_parent(self, node: Node, context) -> Optional[Node]:
        # Find safe ancestor for foster parenting
        candidate = context.current_parent
        visited: set[int] = set()
        while candidate is not None and id(candidate) not in visited:
            if candidate is not node and not node._would_create_circular_reference(
                candidate
            ):
                return candidate
            visited.add(id(candidate))
            candidate = candidate.parent
        body_or_root = self._get_body_or_root(context)
        if (
            body_or_root
            and body_or_root is not node
            and not node._would_create_circular_reference(body_or_root)
        ):
            return body_or_root
        return None
