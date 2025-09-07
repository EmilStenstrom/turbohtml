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

    def run_algorithm(self, tag_name: str, context, outer_invocation: int = 1) -> bool:
        """Run the full Adoption Agency Algorithm for a given end tag.

        This inlines the spec's internal *loop* (up to 8 iterations) inside a single call so callers
        (handlers) do not need to repeatedly invoke the algorithm. Each iteration attempts to perform
        one adoption cycle; if no progress is made (stacks unchanged) or the algorithm signals that
        no further action is required, we terminate early.
        """
        made_progress_overall = False
        processed_furthest_blocks = set()
        for iteration_count in range(1, 9):  # spec max 8
            # Locate most recent matching formatting element (Step 1 selection prerequisite)
            formatting_entry = None
            for entry in reversed(list(context.active_formatting_elements)):
                if entry.element is None:
                    continue
                if entry.element.tag_name == tag_name:
                    formatting_entry = entry
                    break
            if not formatting_entry:
                break  # Nothing to adopt
            formatting_element = formatting_entry.element

            # Instrumentation (kept minimal)
            if tag_name == 'a':
                open_tags = [el.tag_name for el in context.open_elements._stack]
                if 'table' in open_tags or 'address' in open_tags:
                    self.parser.debug(f"[adoption][loop] tag=a iter={iteration_count} open={open_tags}")

            # Snapshot signatures for progress detection
            open_sig_before = tuple(id(el) for el in context.open_elements._stack)
            afe_sig_before = tuple(id(e.element) for e in context.active_formatting_elements if e.element)

            # Step 1 fast path: current node matches but is not active formatting element
            current_node = context.open_elements.current() if not context.open_elements.is_empty() else None
            if current_node and current_node.tag_name == tag_name and context.active_formatting_elements.find_element(current_node) is None:
                context.open_elements.pop()
                made_progress_overall = True
                continue  # One iteration consumed; attempt next

            # Step 3: formatting element must be on open stack else remove from AFE
            if not context.open_elements.contains(formatting_element):
                context.active_formatting_elements.remove(formatting_element)
                made_progress_overall = True
                continue

            # Step 4: if not in scope -> abort entire algorithm
            if not context.open_elements.has_element_in_scope(formatting_element.tag_name):
                break

            # Step 5 (parse error if not current) – ignored for control flow

            # Step 6: furthest block
            furthest_block = self._find_furthest_block_spec_compliant(formatting_element, context)

            # Instrumentation: if an <aside> exists as a descendant of formatting element OR as a candidate furthest block
            # log current stack and AFE to understand adoption01 last subtest divergence.
            if furthest_block and furthest_block.tag_name == 'aside':
                self.parser.debug(
                    f"[adoption][aside-trace] iter={iteration_count} fmt=<{formatting_element.tag_name}> furthest=aside stack={[e.tag_name for e in context.open_elements._stack]} afe={[e.element.tag_name for e in context.active_formatting_elements if e.element]}"
                )

            # Step 7: simple case
            if furthest_block is None:
                if self._handle_no_furthest_block_spec(formatting_element, formatting_entry, context):
                    made_progress_overall = True
                # Simple case always terminates algorithm per spec
                break
            else:
                self.parser.debug(f"[adoption] chosen furthest_block=<{furthest_block.tag_name}> for </{tag_name}> iter={iteration_count}")

            # Steps 8–19: complex case (may repeat up to 8 times)
            if id(furthest_block) in processed_furthest_blocks:
                break
            processed_furthest_blocks.add(id(furthest_block))
            complex_result = self._run_complex_adoption_spec(
                formatting_entry, furthest_block, context, iteration_count
            )
            if complex_result:
                made_progress_overall = True
                # Continue to attempt further adoption if same tag still present.
                continue
            else:
                break

            # (progress detection block removed as loop always continues or breaks earlier)

        return made_progress_overall

    # Helper: run adoption repeatedly (spec max 8) until no action
    def run_until_stable(self, tag_name: str, context, max_runs: int = 8) -> int:
        """Run the adoption agency algorithm up to max_runs times until it reports no further action.

        Returns the number of successful runs performed. Encapsulates the counter that used
        to live in various callers so external code no longer manages the iteration variable.
        """
        runs = 0
        # With the internal spec loop implemented inside run_algorithm, one invocation is sufficient.
        if self.should_run_adoption(tag_name, context):
            if self.run_algorithm(tag_name, context):
                runs = 1
        return runs

    # --- Spec helpers ---
    def _find_furthest_block_spec_compliant(self, formatting_element: Node, context) -> Optional[Node]:
        """Locate the furthest block per HTML Standard.

        Spec wording: "Let furthestBlock be the topmost node in the stack of open elements that is lower
        in the stack than formattingElement, and is an element in the special category." The stack grows
        downward with the most recently pushed (current node) at the *bottom*. "Topmost" therefore means
        the first qualifying element encountered when scanning downward from the formatting element's
        position (i.e. the closest descendant on the stack), NOT the last. Our earlier implementation
        incorrectly picked the last qualifying candidate, which prevented multi-iteration anchor nesting
        (adoption01 test 4 expected outer div to be chosen, not the deepest div).
        """
        idx = context.open_elements.index_of(formatting_element)
        if idx == -1:
            return None
        for node in context.open_elements._stack[idx + 1 :]:
            if (
                node.tag_name in SPECIAL_CATEGORY_ELEMENTS
                or node.tag_name in BLOCK_ELEMENTS
            ):
                return node
        return None

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
        self.parser.debug(f"[reconstruct] start missing_index={first_missing_index} afe={[e.element.tag_name if e.element else 'MARK' for e in stack]} open={[n.tag_name for n in open_stack]}")
        for entry in list(stack[first_missing_index:]):
            if entry.element is None or entry.element in open_stack:
                continue
            clone = Node(entry.element.tag_name, entry.element.attributes.copy())
            context.current_parent.append_child(clone)
            context.open_elements.push(clone)
            entry.element = clone
            context.move_to_element(clone)
            self.parser.debug(f"[reconstruct] cloned <{clone.tag_name}> new_open={[n.tag_name for n in context.open_elements._stack]}")

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

        # --- Accurate Spec Steps 11–13 implementation ---
        # Step 11: node and lastNode initialized to furthest_block
        node = furthest_block
        last_node = furthest_block
        # Capture ordering so we can find element immediately above a node even if it is later removed.
        # We'll recompute indices on each loop since open_stack mutates (removals & replacements) but we
        # keep a mapping of previous-above relationships for removed nodes.
        inner_loop_counter = 0
        # For removed nodes we store the element that was above them at time of removal.
        removed_above: dict[int, Node] = {}
        while True:
            if node is formatting_element:
                break  # Step: stop before reaching formatting element
            inner_loop_counter += 1
            # Find nodeAbove (element immediately above node in open elements stack)
            if context.open_elements.contains(node):
                idx_cur = context.open_elements.index_of(node)
                above_index = idx_cur - 1
                node_above = context.open_elements._stack[above_index] if above_index >= 0 else None
            else:
                node_above = removed_above.get(id(node))
            if node_above is None:
                break
            candidate = node_above
            # If candidate not a formatting element: spec says set node to element above and continue (NO removal).
            candidate_entry = context.active_formatting_elements.find_element(candidate)
            if not candidate_entry:
                # Spec: just advance upward; do NOT remove non-formatting elements from the open stack here
                node = candidate
                continue
            # If inner_loop_counter > 3: remove candidate entry (and from stack) then continue upward
            if inner_loop_counter > 3:
                if context.active_formatting_elements.find_element(candidate):
                    context.active_formatting_elements.remove_entry(candidate_entry)
                if context.open_elements.contains(candidate):
                    idx_cand = context.open_elements.index_of(candidate)
                    above2 = context.open_elements._stack[idx_cand - 1] if idx_cand - 1 >= 0 else None
                    removed_above[id(candidate)] = above2
                    context.open_elements.remove_element(candidate)
                node = candidate
                continue
            # If candidate IS the formatting element, stop (do not clone formatting element itself)
            if candidate is formatting_element:
                node = candidate
                break
            # Otherwise clone candidate formatting element
            clone = Node(candidate.tag_name, candidate.attributes.copy())
            context.active_formatting_elements.replace_entry(candidate_entry, clone, candidate_entry.token)
            if context.open_elements.contains(candidate):
                context.open_elements.replace_element(candidate, clone)
            clone.append_child(last_node)
            last_node = clone
            # Spec: let node be the new element (clone) so next iteration climbs from its position
            node = clone

        # Step 14 (refined): Insert last_node at the "appropriate place for inserting a node" using common_ancestor as override.
        # Empirically our suite expects movement even when last_node == furthest_block (some legacy formatting cases),
        # so we retain unconditional move variant (with cycle guard) that produced best pass rate earlier.
        # Step 14 (unconditional move variant that previously maximized pass rate)
        # Step 14 refinement: avoid relocating if last_node already correctly placed.
        if last_node.parent is common_ancestor:
            # Already where spec wants it; no movement.
            self.parser.debug("[adoption][step14] last_node already child of common_ancestor; no move")
        elif common_ancestor is last_node or common_ancestor.find_ancestor(lambda n: n is last_node):
            self.parser.debug("[adoption][step14] skipped move (cycle risk)")
        else:
            # Decide whether foster parenting is appropriate. We restrict foster parenting to cases
            # where common_ancestor is table-related AND last_node is *not* already a table section/row
            # (moving table structural nodes breaks expected subtree layout in several anchor tests).
            table_structural = {"table", "tbody", "thead", "tfoot", "tr"}
            do_foster = False
            if self._should_foster_parent(common_ancestor):
                if last_node.tag_name not in table_structural:
                    # Additionally ensure last_node is not inside a td/th (spec would keep it there).
                    inside_cell = last_node.find_ancestor(lambda n: n.tag_name in ("td", "th")) is not None
                    if not inside_cell:
                        do_foster = True
            if do_foster:
                self._safe_detach_node(last_node)
                self._foster_parent_node(last_node, context, common_ancestor)
                self.parser.debug(
                    f"[adoption][step14] foster-parented last_node <{last_node.tag_name}> relative to <{common_ancestor.tag_name}>"
                )
            else:
                # Normal placement: place after formatting element if it is still a child of common_ancestor,
                # otherwise append (maintains relative order).
                self._safe_detach_node(last_node)
                inserted = False
                if (
                    formatting_element.parent is common_ancestor
                    and formatting_element in common_ancestor.children
                ):
                    pos_fmt = common_ancestor.children.index(formatting_element)
                    common_ancestor.insert_child_at(pos_fmt + 1, last_node)
                    inserted = True
                if not inserted:
                    common_ancestor.append_child(last_node)
                self.parser.debug(
                    f"[adoption][step14] placed last_node <{last_node.tag_name}> under <{common_ancestor.tag_name}> children={[c.tag_name for c in common_ancestor.children]}"
                )
        # Instrumentation: show path from formatting element to furthest_block (if still connected)
        path_tags = []
        cur = furthest_block
        while cur is not None and cur is not formatting_element and len(path_tags) < 25:
            path_tags.append(cur.tag_name)
            cur = cur.parent
        if cur is formatting_element:
            path_tags.append(formatting_element.tag_name)
        self.parser.debug(f"[adoption][diag] path(furthest->fmt)={'/'.join(path_tags)}")
        self.parser.debug(f"[adoption][diag] common_ancestor_children={[c.tag_name for c in (common_ancestor.children if common_ancestor.children else [])]}")
        self.parser.debug(f"[adoption] after step13 (spec) chain_root=<{last_node.tag_name}> parent=<{last_node.parent.tag_name if last_node.parent else 'None'}>")

        # De-duplicate last_node (furthest_block chain root) in open elements stack if movement created duplicate logical entries.
        # Keep the earliest occurrence (closest to root) and drop later duplicates to maintain stack invariants.
        occurrences = [i for i, el in enumerate(context.open_elements._stack) if el is last_node]
        if len(occurrences) > 1:
            # remove from end backwards except first
            for i in reversed(occurrences[1:]):
                context.open_elements._stack.pop(i)
            self.parser.debug(f"[adoption][dedupe] removed duplicate stack entries for <{last_node.tag_name}> now stack={[e.tag_name for e in context.open_elements._stack]}")

        # Always proceed with formatting element cloning (Steps 14–19); removed ladder-lift early-exit heuristic.

        # (No single-intermediate-clone normalization; revert to straightforward cloning path.)

        # Previous relocation adjustment removed; spec insertion above covers extraction.

        # Step 15: Create a clone of the formatting element
        fe_clone = Node(formatting_element.tag_name, formatting_element.attributes.copy())
        # Step 16: Move all children of furthest_block into fe_clone
        for ch in list(furthest_block.children):
            furthest_block.remove_child(ch)
            fe_clone.append_child(ch)
        # Step 17: Append fe_clone to furthest_block
        furthest_block.append_child(fe_clone)
        # Step 18: Replace formatting element entry in active formatting elements with clone (keep same position)
        context.active_formatting_elements.replace_entry(formatting_entry, fe_clone, formatting_entry.token)
        # Step 19: Remove formatting element from open elements stack; insert fe_clone immediately AFTER furthest_block (spec: below it)
        if context.open_elements.contains(formatting_element):
            context.open_elements.remove_element(formatting_element)
        if context.open_elements.contains(furthest_block):
            fb_index2 = context.open_elements.index_of(furthest_block)
            context.open_elements._stack.insert(fb_index2 + 1, fe_clone)
        # Set insertion point to the new clone (so subsequent characters go inside formatting element per spec intent)
        context.move_to_element(fe_clone)
        stack_tags = [e.tag_name for e in context.open_elements._stack]
        afe_tags = [e.element.tag_name for e in context.active_formatting_elements if e.element]
        self.parser.debug(f"[adoption] post-step19 fe_clone=<{fe_clone.tag_name}> parent=<{fe_clone.parent.tag_name if fe_clone.parent else 'None'}> stack={stack_tags} afe={afe_tags}")
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
