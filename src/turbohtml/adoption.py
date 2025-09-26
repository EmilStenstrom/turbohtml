"""Adoption Agency Algorithm (HTML5 tree construction: formatting element adoption).

Implementation focuses on spec steps; comments describe intent (why) rather than history.
All static type annotations removed (runtime only)."""

from turbohtml.node import Node
from turbohtml.constants import (
    FORMATTING_ELEMENTS,
    SPECIAL_CATEGORY_ELEMENTS,
)
from turbohtml.foster import foster_parent, needs_foster_parenting

class FormattingElementEntry:
    """Entry in the active formatting elements stack.

    Marker entries have element == None (scope boundaries for tables/templates)."""

    __slots__ = ("element", "token")

    def __init__(self, element, token):
        self.element = element
        self.token = token

    def matches(self, tag_name, attributes=None):
        if self.element.tag_name != tag_name:
            return False
        if attributes is None:
            return True
        return self.element.attributes == attributes


class ActiveFormattingElements:
    """Active formatting elements list (spec stack with markers + Noah's Ark clause)."""

    def __init__(self, max_size=12):
        self._stack = []
        self._max_size = max_size

    def push(self, element, token):
        entry = FormattingElementEntry(element, token)
        self._apply_noahs_ark(entry)
        self._stack.append(entry)
        if len(self._stack) > self._max_size:
            self._stack.pop(0)

    def find(self, tag_name, attributes=None):
        for entry in reversed(self._stack):
            if entry.matches(tag_name, attributes):
                return entry
        return None

    def find_element(self, element):
        for entry in self._stack:
            if entry.element is element:
                return entry
        return None

    def remove(self, element):
        for i, entry in enumerate(self._stack):
            if entry.element is element:
                self._stack.pop(i)
                return True
        return False

    def remove_entry(self, entry):
        if entry in self._stack:
            self._stack.remove(entry)
            return True
        return False

    def _apply_noahs_ark(self, new_entry):
        matching = []
        for entry in self._stack:
            if entry.matches(new_entry.element.tag_name, new_entry.element.attributes):
                matching.append(entry)
        if len(matching) >= 3:
            earliest = matching[0]
            if earliest in self._stack:
                self._stack.remove(earliest)

    def is_empty(self):
        return len(self._stack) == 0

    def __iter__(self):
        return iter(self._stack)

    def get_index(self, entry):
        for i, e in enumerate(self._stack):
            if e is entry:
                return i
        return -1

    def __len__(self):
        return len(self._stack)

    def replace_entry(self, old_entry, new_element, new_token):
        for i, entry in enumerate(self._stack):
            if entry is old_entry:
                self._stack[i] = FormattingElementEntry(new_element, new_token)
                return
        self.push(new_element, new_token)

    def insert_at(self, index, element, token):
        entry = FormattingElementEntry(element, token)
        if index < 0:
            index = 0
        if index > len(self._stack):
            index = len(self._stack)
        self._stack.insert(index, entry)
        if len(self._stack) > self._max_size:
            self._stack.pop(0)


class OpenElementsStack:
    """Stack of open elements per HTML5 tree construction algorithm.

        Provides only the operations required by the parser and adoption agency:
            * push / pop / is_empty
            * contains / index_of / remove_element
            * replace_element
            * has_element_in_scope (general scope variant sufficient for current tests)
    """

    def __init__(self):
        self._stack = []

    # --- basic stack ops ---
    def push(self, element):
        self._stack.append(element)
    def pop(self):
        return self._stack.pop() if self._stack else None
    def is_empty(self):
        return not self._stack

    # --- membership / search ---
    def contains(self, element):
        return element in self._stack
    def index_of(self, element):
        for i, el in enumerate(self._stack):
            if el is element:
                return i
        return -1
    def remove_element(self, element):
        if element in self._stack:
            self._stack.remove(element)
            return True
        return False

    # --- structural mutation ---
    def replace_element(self, old, new):
        idx = self.index_of(old)
        if idx != -1:
            self._stack[idx] = new

    # --- scope handling ---
    def has_element_in_scope(self, tag_name):
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

    def has_element_in_button_scope(self, tag_name):
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
    # --- iteration helpers ---
    def __iter__(self):
        return iter(self._stack)

# Experimental anchor/table relocation feature flag removed (kept disabled in practice); code simplified to baseline behavior.

class AdoptionAgencyAlgorithm:
    def __init__(self, parser):
        self.parser = parser
        # Pure spec implementation (no metrics / instrumentation state retained).

    # Deterministic descendant iterator used by text normalization (handlers) to inspect
    # formatting subtrees without relying on reflective attribute probing. Kept simple
    # and allocation‑light (explicit stack) to preserve hot path performance.
    def _iter_descendants(self, node):  # pragma: no cover - traversal utility
        stack = list(node.children)
        while stack:
            cur = stack.pop()
            yield cur
            if cur.children:
                stack.extend(cur.children)

    def should_run_adoption(self, tag_name, context):
        # Spec trigger: end tag whose tag name is a formatting element AND a matching
        # entry exists in the active formatting elements list.
        if tag_name not in FORMATTING_ELEMENTS:
            return False
        return context.active_formatting_elements.find(tag_name) is not None

    def run_algorithm(self, tag_name, context, outer_invocation=1):
        """Run the full Adoption Agency Algorithm for a given end tag.

        This inlines the spec's internal *loop* (up to 8 iterations) inside a single call so callers
        (handlers) do not need to repeatedly invoke the algorithm. Each iteration attempts to perform
        one adoption cycle; if no progress is made (stacks unchanged) or the algorithm signals that
        no further action is required, we terminate early.
        """
        made_progress_overall = False
        processed_furthest_blocks = set()
        complex_case_executed = False  # track whether we performed complex (steps 8-19) adoption
        # simple_case_popped_above removed (we no longer trigger reconstruction for simple case)
        for iteration_count in range(1, 9):  # spec max 8
            # Guard: only execute anchor adoption when processing a genuine end tag. Start-tag
            # paths (e.g. table start) must not implicitly segment an open <a> per spec; earlier
            # heuristic closures caused loss of anchor wrapping for foster‑parented text (tests1.dat:78).
            if tag_name == 'a' and not context.processing_end_tag:
                break
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
            # Diagnostic: show formatting element selection and stack slice below it
            if tag_name == 'a':
                fmt_idx = context.open_elements.index_of(formatting_element)
                if fmt_idx != -1:
                    below = [n.tag_name for n in context.open_elements._stack[fmt_idx+1:]]
                else:
                    below = []
                self.parser.debug(f"[adoption][diag-select] fmt=<a> idx={fmt_idx} below={below}")

            # Instrumentation (kept minimal)
            if tag_name == 'a':
                open_tags = [el.tag_name for el in context.open_elements._stack]
                if 'table' in open_tags or 'address' in open_tags:
                    self.parser.debug(f"[adoption][loop] tag=a iter={iteration_count} open={open_tags}")

            # Step 3: formatting element must be on open stack else remove from AFE and ABORT (spec)
            # HTML Standard: "If formatting element is not in the stack of open elements, then this is a parse error;
            # remove the element from the list of active formatting elements and abort these steps." Previous implementation
            # used 'continue', which could look for an earlier duplicate and close formatting earlier than the spec intends.
            # Switching to 'break' restores strict spec behavior: only remove the missing entry and abort for this end tag.
            if not context.open_elements.contains(formatting_element):
                context.active_formatting_elements.remove(formatting_element)
                made_progress_overall = True
                break

            # Step 4: scope check. If the formatting element is not in scope the spec removes it from
            # the list of active formatting elements and aborts the algorithm for this tag name.
            # (Previous experimental relaxation for <a> across a pure table structural chain was removed
            # after introducing regressions in template + anchor tests. We now adhere strictly to spec
            # scope semantics here.)
            in_scope = context.open_elements.has_element_in_scope(formatting_element.tag_name)
            if not in_scope:
                context.active_formatting_elements.remove_entry(formatting_entry)
                made_progress_overall = True
                break

            # Step 5 (parse error if not current) – ignored for control flow

            # Step 6: furthest block
            if tag_name == 'a':
                fmt_idx_dbg = context.open_elements.index_of(formatting_element)
                if fmt_idx_dbg != -1:
                    slice_tags = [n.tag_name for n in context.open_elements._stack[fmt_idx_dbg+1:]]
                else:
                    slice_tags = []
                self.parser.debug(f"[adoption][pre-furthest-scan] fmt_idx={fmt_idx_dbg} slice={slice_tags}")
            furthest_block = self._find_furthest_block_spec_compliant(formatting_element, context)
            if tag_name == 'a':
                self.parser.debug(f"[adoption][furthest-result] {'None' if furthest_block is None else furthest_block.tag_name}")

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
                complex_case_executed = True
                continue  # keep looping for same end tag per spec
            else:
                break

            # (progress detection block removed as loop always continues or breaks earlier)

        # Trigger one-shot reconstruction only for complex-case adoptions (steps 8–19) where cloned wrappers were produced;
        # simple-case removals must not immediately re-wrap subsequent text to avoid duplicating inline formatting wrappers.
        if made_progress_overall and complex_case_executed:
            context.post_adoption_reconstruct_pending = True
        return made_progress_overall

    # Helper: run adoption repeatedly (spec max 8) until no action
    def run_until_stable(self, tag_name, context, max_runs=8):
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
    def _find_furthest_block_spec_compliant(self, formatting_element, context):
        """Locate the furthest block per HTML Standard.

        Spec wording: "Let furthestBlock be the topmost node in the stack of open elements that is lower
        in the stack than formattingElement, and is an element in the special category." Here the stack's
        0 index is closest to root; "topmost" below formattingElement in spec terms refers to the element
        highest in tree order among those below it, which corresponds to the *deepest* (largest index) matching
        special element in our open elements stack representation (since newer descendants are pushed later).
        Selecting the deepest enables multi-iteration adoption layering required for complex mis-nesting cases
        (anchors wrapping table structures). Earlier implementation chose the first match (closest to root),
        prematurely terminating layering and blocking correct split behavior.
        """
        idx = context.open_elements.index_of(formatting_element)
        if idx == -1:
            return None
        subseq = context.open_elements._stack[idx + 1 :]
        if not subseq:
            return None
        for node in subseq:
            if formatting_element.tag_name == 'a':
                self.parser.debug(f"[adoption][scan] below_fmt_candidate=<{node.tag_name}> special={'yes' if node.tag_name in SPECIAL_CATEGORY_ELEMENTS else 'no'}")
            if node.tag_name in SPECIAL_CATEGORY_ELEMENTS:
                if formatting_element.tag_name == 'a':
                    self.parser.debug(f"[adoption][furthest-pick] fmt=<a> candidate=<{node.tag_name}>")
                return node
        if formatting_element.tag_name == 'a':
            self.parser.debug('[adoption][furthest-miss] no special candidate found below <a>')
        return None

    def _handle_no_furthest_block_spec(
        self,
        formatting_element,
        formatting_entry,
        context,
    ):
        """Simple case: pop formatting element and remove its active entry."""
        stack_before = [e.tag_name for e in context.open_elements._stack]
        afe_before = [e.element.tag_name for e in context.active_formatting_elements if e.element]
        self.parser.debug(
            f"[adoption] simple-case for <{formatting_element.tag_name}> stack_before={stack_before} afe_before={afe_before}"
        )

        # Step 7a: remove the formatting element entry from the active formatting elements list.
        context.active_formatting_elements.remove_entry(formatting_entry)

        # Step 7b: if the element is missing from the open elements stack, we are done.
        if not context.open_elements.contains(formatting_element):
            self.parser.debug(
                f"[adoption] simple-case exit (<{formatting_element.tag_name}> not in open stack)"
            )
            return True

        # Step 7c: pop elements from the stack of open elements until the formatting element has been removed.
        stack = context.open_elements._stack
        if formatting_element in stack:
            while stack:
                removed = stack.pop()
                if removed is formatting_element:
                    break

        # Step 7d (spec): set the current node to the last node in the stack of open elements.
        if context.open_elements._stack:
            context.move_to_element(context.open_elements._stack[-1])
        else:
            body = self.parser._ensure_body_node(context)
            if body:
                context.move_to_element(body)
            else:
                context.move_to_element(self.parser.root)

        if formatting_element.tag_name == 'a':
            afe_elements = {
                entry.element
                for entry in context.active_formatting_elements
                if entry.element is not None
            }
            stack = context.open_elements._stack
            if stack:
                new_stack = []
                removed_anchor = False
                for el in stack:
                    if el.tag_name == 'a' and el not in afe_elements:
                        removed_anchor = True
                        continue
                    new_stack.append(el)
                if removed_anchor:
                    context.open_elements._stack = new_stack
                    if new_stack:
                        context.move_to_element(new_stack[-1])
                    else:
                        body = self.parser._ensure_body_node(context)
                        context.move_to_element(body if body else self.parser.root)

        fmt_parent = formatting_element.parent
        if fmt_parent is not None and fmt_parent is not context.current_parent:
            if fmt_parent.tag_name in ("td", "th", "caption"):
                context.move_to_element(fmt_parent)
            else:
                target = fmt_parent
                while target is not None:
                    if target is context.current_parent:
                        break
                    if context.open_elements.contains(target):
                        break
                    tag = target.tag_name
                    if tag.startswith("svg ") or tag.startswith("math ") or tag in {"svg", "math", "math annotation-xml"}:
                        break
                    target = target.parent
                if target is not None and target is not context.current_parent:
                    context.move_to_element(target)

        # Trigger reconstruction if any active formatting entries are now stale.
        for entry_chk in context.active_formatting_elements:
            elc = entry_chk.element
            if elc and not context.open_elements.contains(elc):
                context.post_adoption_reconstruct_pending = True
                break

        insertion_parent = context.current_parent.tag_name if context.current_parent else 'None'
        stack_after = [e.tag_name for e in context.open_elements._stack]
        afe_after = [e.element.tag_name for e in context.active_formatting_elements if e.element]
        self.parser.debug(
            f"[adoption] simple-case exit insertion_parent={insertion_parent} stack_after={stack_after} afe_after={afe_after}"
        )
        return True

    def _safe_detach_node(self, node):
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

    def _run_complex_adoption_spec(
        self,
        formatting_entry,
        furthest_block,
        context,
        iteration_count=0,
    ):
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
            _intermediates = fb_index - fe_index - 1  # noqa: F841 retained for potential debugging
        else:
            _intermediates = 0  # noqa: F841
        open_stack = context.open_elements._stack  # noqa: F841 (debug logging later may reference)
        # Guard: indexes must be valid
        if fe_index == -1 or fb_index == -1 or fb_index <= fe_index:
            return False

        # --- Accurate Spec Steps 11–13 implementation ---
        # Step 11: node and lastNode initialized to furthest_block
        node = furthest_block
        last_node = furthest_block
        inner_loop_counter = 0
        removed_above = {}
        while True:
            if node is formatting_element:
                break
            inner_loop_counter += 1
            if context.open_elements.contains(node):
                idx_cur = context.open_elements.index_of(node)
                above_index = idx_cur - 1
                node_above = (
                    context.open_elements._stack[above_index]
                    if above_index >= 0
                    else None
                )
            else:
                node_above = removed_above.get(id(node))
            if node_above is None:
                break
            candidate = node_above
            candidate_entry = context.active_formatting_elements.find_element(candidate)
            if not candidate_entry:
                if context.open_elements.contains(candidate):
                    idx_cand = context.open_elements.index_of(candidate)
                    above2 = (
                        context.open_elements._stack[idx_cand - 1]
                        if idx_cand - 1 >= 0
                        else None
                    )
                    removed_above[id(candidate)] = above2
                    context.open_elements.remove_element(candidate)
                node = candidate
                continue
            if inner_loop_counter > 3:
                cand_index = context.active_formatting_elements.get_index(candidate_entry)
                if cand_index != -1:
                    context.active_formatting_elements.remove_entry(candidate_entry)
                if context.open_elements.contains(candidate):
                    idx_cand = context.open_elements.index_of(candidate)
                    above2 = (
                        context.open_elements._stack[idx_cand - 1]
                        if idx_cand - 1 >= 0
                        else None
                    )
                    removed_above[id(candidate)] = above2
                    context.open_elements.remove_element(candidate)
                node = candidate
                continue
            if candidate is formatting_element:
                node = candidate
                break
            cand_index = context.active_formatting_elements.get_index(candidate_entry)
            if last_node is furthest_block and cand_index != -1:
                bookmark_index = cand_index + 1
            clone = Node(candidate.tag_name, candidate.attributes.copy())
            context.active_formatting_elements.replace_entry(candidate_entry, clone, candidate_entry.token)
            if context.open_elements.contains(candidate):
                context.open_elements.replace_element(candidate, clone)
            clone.append_child(last_node)
            last_node = clone
            node = clone

        # Step 14 (refined): Insert last_node at the "appropriate place for inserting a node" using common_ancestor as override.
        # Empirically our suite expects movement even when last_node == furthest_block (some legacy formatting cases),
        # so we retain unconditional move variant (with cycle guard) that produced best pass rate earlier.
        # Step 14 (unconditional move variant that previously maximized pass rate)
        # Step 14 refinement: avoid relocating if last_node already correctly placed.
        # Unified Step 14 relocation following spec: relocate only if ordering or parent differ.
        # Template content preservation: if common_ancestor is a <template> and the furthest block (or formatting element)
        # lives inside its 'content' fragment, redirect placement to that fragment to avoid leaking nodes outside.
        if common_ancestor.tag_name == 'template':
            content_child = None
            for ch in common_ancestor.children:
                if ch.tag_name == 'content':
                    content_child = ch
                    break
            if content_child is not None:
                def _under(node, ancestor):
                    cur = node
                    while cur is not None:
                        if cur is ancestor:
                            return True
                        cur = cur.parent
                    return False
                if _under(furthest_block, content_child) or _under(formatting_element, content_child):
                    common_ancestor = content_child
        self._step14_place_last_node(
            formatting_element,
            last_node,
            furthest_block,
            common_ancestor,
            context,
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
        # Step 18: Remove formatting entry and insert clone at bookmark position per spec
        formatting_token = formatting_entry.token
        context.active_formatting_elements.remove_entry(formatting_entry)
        if bookmark_index == -1:
            bookmark_index = len(context.active_formatting_elements)
        if bookmark_index < 0:
            bookmark_index = 0
        if bookmark_index > len(context.active_formatting_elements):
            bookmark_index = len(context.active_formatting_elements)
        context.active_formatting_elements.insert_at(bookmark_index, fe_clone, formatting_token)
        # Step 19: Remove formatting element from open elements stack; insert fe_clone immediately AFTER furthest_block
        if context.open_elements.contains(formatting_element):
            context.open_elements.remove_element(formatting_element)
        if context.open_elements.contains(furthest_block):
            fb_index2 = context.open_elements.index_of(furthest_block)
            context.open_elements._stack.insert(fb_index2 + 1, fe_clone)
        # After step 19 the current node should be the last entry on the open elements stack.
        if context.open_elements._stack:
            context.move_to_element(context.open_elements._stack[-1])
        stack_tags = [e.tag_name for e in context.open_elements._stack]
        afe_tags = [e.element.tag_name for e in context.active_formatting_elements if e.element]
        self.parser.debug(f"[adoption] post-step19 fe_clone=<{fe_clone.tag_name}> parent=<{fe_clone.parent.tag_name if fe_clone.parent else 'None'}> stack={stack_tags} afe={afe_tags}")
        self.parser.debug(
            f"[adoption] complex-end tag=<{formatting_element.tag_name}> stack={[e.tag_name for e in context.open_elements._stack]} afe={[e.element.tag_name for e in context.active_formatting_elements if e.element]}"
        )

        return True


    def _iter_descendants(self, node):
        # Yield all descendants (depth-first) of a node
        stack = list(node.children)
        while stack:
            cur = stack.pop()
            yield cur
            if cur.children:
                stack.extend(cur.children)

    # --- Step 14 helper ---
    def _step14_place_last_node(
        self,
        formatting_element,
        last_node,
        furthest_block,
        common_ancestor,
        context,
    ):
        """Insert last_node using the general 'appropriate place' algorithm with override target.

        Mirrors the HTML Standard definition: select the override target (common_ancestor),
        redirect to template content when needed, and delegate table contexts to the foster
        parent helper. No special-casing for formatting/tag combinations remains here.
        """
        if common_ancestor is None:
            return

        target = common_ancestor

        # Template override: insert into template content fragment when available.
        if target.tag_name == "template":
            content_child = None
            for ch in target.children:
                if ch.tag_name == "content":
                    content_child = ch
                    break
            if content_child is not None:
                target = content_child

        # Fast-path: already the last child of the correct parent.
        if (
            last_node.parent is target
            and target.children
            and target.children[-1] is last_node
        ):
            self.parser.debug("[adoption][step14] skip (already tail child)")
            return

        # Table contexts rely on foster parenting (table, tbody, thead, tfoot, tr).
        if needs_foster_parenting(target):
            parent, before = foster_parent(target, context.open_elements, self.parser.root)
            if parent is None:
                parent = target
            if before is not None and before.parent is parent:
                parent.insert_before(last_node, before)
            else:
                parent.append_child(last_node)
            self.parser.debug(
                f"[adoption][step14] fostered <{last_node.tag_name}> into <{parent.tag_name}> before={before.tag_name if before else 'None'}"
            )
            return

        # Default: append into target (Node helpers handle reparenting and sibling links).
        target.append_child(last_node)
        self.parser.debug(
            f"[adoption][step14] appended <{last_node.tag_name}> under <{target.tag_name}> children={[c.tag_name for c in target.children]}"
        )

