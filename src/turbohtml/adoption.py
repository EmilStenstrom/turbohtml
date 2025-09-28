"""Adoption Agency Algorithm (HTML5 tree construction: formatting element adoption).

Implementation focuses on spec steps; comments describe intent (why) rather than history.
All static type annotations removed (runtime only)."""

from .node import Node
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

    def insert_at_index(self, index, element, token):
        if index < 0:
            index = 0
        if index > len(self._stack):
            index = len(self._stack)
        entry = FormattingElementEntry(element, token)
        self._stack.insert(index, entry)
        if len(self._stack) > self._max_size:
            self._stack.pop(0)

    def replace_entry(self, old_entry, new_element, new_token):
        for i, entry in enumerate(self._stack):
            if entry is old_entry:
                self._stack[i] = FormattingElementEntry(new_element, new_token)
                return
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

    def __init__(self):
        self._stack = []

    # --- basic stack ops ---
    def push(self, element):
        self._stack.append(element)
    def pop(self):
        return self._stack.pop() if self._stack else None
    def current(self):
        return self._stack[-1] if self._stack else None
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

    def insert_after(self, reference, new_element):
        idx = self.index_of(reference)
        if idx == -1:
            self._stack.append(new_element)
        else:
            self._stack.insert(idx + 1, new_element)

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
    def _is_special_category(self, element):
        return element.tag_name in SPECIAL_CATEGORY_ELEMENTS

    # --- iteration helpers ---
    def __iter__(self):
        return iter(self._stack)

    def __len__(self):
        return len(self._stack)

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

    def _find_active_entry(self, tag_name, context):
        stack = context.active_formatting_elements._stack
        for entry in reversed(stack):
            if entry.element is None:
                break
            if entry.element.tag_name == tag_name:
                return entry
        return None

    def should_run_adoption(self, tag_name, context):
        if tag_name not in FORMATTING_ELEMENTS:
            return False
        return self._find_active_entry(tag_name, context) is not None

    def run_algorithm(self, tag_name, context, outer_invocation=1):
        made_progress = False
        outer_loop_counter = 0

        while outer_loop_counter < 8:
            outer_loop_counter += 1

            formatting_entry = self._find_active_entry(tag_name, context)
            if not formatting_entry:
                return made_progress

            formatting_element = formatting_entry.element

            if tag_name == "a" and not context.processing_end_tag:
                break

            if not context.open_elements.contains(formatting_element):
                context.active_formatting_elements.remove_entry(formatting_entry)
                context.post_adoption_reconstruct_pending = True
                return True

            if not context.open_elements.has_element_in_scope(formatting_element.tag_name):
                context.active_formatting_elements.remove_entry(formatting_entry)
                return made_progress

            furthest_block = self._find_furthest_block(formatting_element, context)
            if furthest_block is None:
                self.parser.debug(
                    f"[adoption] simple-case for </{tag_name}> stack={[el.tag_name for el in context.open_elements._stack]}"
                )
                self._run_simple_case(formatting_entry, formatting_element, context)
                return True

            self._run_complex_case(formatting_entry, formatting_element, furthest_block, context)
            made_progress = True
            context.post_adoption_reconstruct_pending = True

        return made_progress

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
    def _find_furthest_block(self, formatting_element, context):
        idx = context.open_elements.index_of(formatting_element)
        if idx == -1:
            return None
        for candidate in context.open_elements._stack[idx + 1 :]:
            if candidate.tag_name in SPECIAL_CATEGORY_ELEMENTS:
                return candidate
        return None

    def _run_simple_case(self, formatting_entry, formatting_element, context):
        stack = context.open_elements._stack

        had_table_descendant = any(
            child.tag_name == "table" for child in formatting_element.children
        )

        # Remove the formatting element entry from the active list (spec step 7a)
        context.active_formatting_elements.remove_entry(formatting_entry)

        # If the element is missing from the open stack we're done (step 7b)
        if not context.open_elements.contains(formatting_element):
            return

        # Pop elements until the formatting element has been removed (step 7c)
        if formatting_element in stack:
            while stack:
                removed = stack.pop()
                if removed is formatting_element:
                    break

        # Anchor specific clean-up: remove stray open anchors no longer in AFE
        if formatting_element.tag_name == "a":
            active_anchor_elements = {
                entry.element
                for entry in context.active_formatting_elements
                if entry.element is not None
            }
            if context.open_elements._stack:
                cleaned_stack = []
                removed_anchor = False
                for element in context.open_elements._stack:
                    if element.tag_name == "a" and element not in active_anchor_elements:
                        removed_anchor = True
                        continue
                    cleaned_stack.append(element)
                if removed_anchor:
                    context.open_elements._stack = cleaned_stack
                    if cleaned_stack:
                        context.move_to_element(cleaned_stack[-1])
                    else:
                        context.move_to_element(self._get_body_or_root(context))

        # If the formatting element still has a parent that is a viable insertion point,
        # realign the insertion location to that ancestor so foreign content stays nested.
        fmt_parent = formatting_element.parent
        target = None
        if fmt_parent is not None:
            if fmt_parent.tag_name in ("td", "th", "caption"):
                target = fmt_parent
            else:
                candidate = fmt_parent
                while candidate is not None:
                    if candidate is context.current_parent:
                        target = candidate
                        break
                    if context.open_elements.contains(candidate):
                        target = candidate
                        break
                    tag = candidate.tag_name
                    if tag.startswith("svg ") or tag.startswith("math ") or tag in {"svg", "math", "math annotation-xml"}:
                        break
                    candidate = candidate.parent
                if target is None:
                    target = fmt_parent
        if target is None:
            if context.open_elements._stack:
                target = context.open_elements._stack[-1]
            else:
                target = self._get_body_or_root(context)
        context.move_to_element(target)
        if formatting_element.tag_name == "font":
            wrapper_parent = fmt_parent if fmt_parent is not None else target
            new_wrapper = self._wrap_trailing_font_content(wrapper_parent, context)
            if new_wrapper is not None:
                context.pending_font_wrapper_parent = None
                context.pending_font_wrapper = None
            elif had_table_descendant and wrapper_parent and wrapper_parent.tag_name != "document-fragment":
                context.pending_font_wrapper_parent = wrapper_parent
                context.pending_font_wrapper = None
            else:
                context.pending_font_wrapper_parent = None
                context.pending_font_wrapper = None
        context.post_adoption_reconstruct_pending = True

        # Trigger reconstruction if any active formatting entries are now stale
        for entry in context.active_formatting_elements:
            element = entry.element
            if element and not context.open_elements.contains(element):
                context.post_adoption_reconstruct_pending = True
                break

    def _wrap_trailing_font_content(self, parent, context):
        if parent is None or not parent.children:
            return None
        last_table_index = None
        for idx, child in enumerate(parent.children):
            if child.tag_name == "table":
                last_table_index = idx
        if last_table_index is None:
            return None
        start_index = last_table_index + 1
        if start_index >= len(parent.children):
            return None
        movable = []
        idx = start_index
        while idx < len(parent.children):
            node = parent.children[idx]
            if node.tag_name == "a" and node.children:
                break
            if node.tag_name == "font" and node.children:
                break
            movable.append(node)
            idx += 1
        if not movable:
            return None
        new_wrapper = Node("font")
        parent.insert_child_at(start_index, new_wrapper)
        for node in movable:
            parent.remove_child(node)
            new_wrapper.append_child(node)
        return new_wrapper

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

    def _run_complex_case(self, formatting_entry, formatting_element, furthest_block, context):
        bookmark_index = context.active_formatting_elements.get_index(formatting_entry)
        if bookmark_index == -1:
            bookmark_index = len(context.active_formatting_elements)

        formatting_index = context.open_elements.index_of(formatting_element)
        if formatting_index == -1:
            return

        if formatting_index - 1 >= 0:
            common_ancestor = context.open_elements._stack[formatting_index - 1]
        else:
            common_ancestor = formatting_element.parent

        if not common_ancestor:
            return

        node = furthest_block
        last_node = furthest_block
        inner_loop_counter = 0
        removed_above = {}

        while True:
            if node is formatting_element:
                break

            inner_loop_counter += 1

            if context.open_elements.contains(node):
                idx_current = context.open_elements.index_of(node)
                above_index = idx_current - 1
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
                    idx_candidate = context.open_elements.index_of(candidate)
                    above_candidate = (
                        context.open_elements._stack[idx_candidate - 1]
                        if idx_candidate - 1 >= 0
                        else None
                    )
                    removed_above[id(candidate)] = above_candidate
                    context.open_elements.remove_element(candidate)
                node = candidate
                continue

            if inner_loop_counter > 3:
                candidate_index = context.active_formatting_elements.get_index(candidate_entry)
                if candidate_index != -1:
                    context.active_formatting_elements.remove_entry(candidate_entry)
                if context.open_elements.contains(candidate):
                    idx_candidate = context.open_elements.index_of(candidate)
                    above_candidate = (
                        context.open_elements._stack[idx_candidate - 1]
                        if idx_candidate - 1 >= 0
                        else None
                    )
                    removed_above[id(candidate)] = above_candidate
                    context.open_elements.remove_element(candidate)
                node = candidate
                continue

            if candidate is formatting_element:
                node = candidate
                break

            candidate_index = context.active_formatting_elements.get_index(candidate_entry)
            if last_node is furthest_block and candidate_index != -1:
                bookmark_index = candidate_index + 1

            clone = Node(candidate.tag_name, candidate.attributes.copy())
            context.active_formatting_elements.replace_entry(candidate_entry, clone, candidate_entry.token)
            if context.open_elements.contains(candidate):
                context.open_elements.replace_element(candidate, clone)

            clone.append_child(last_node)
            last_node = clone
            node = clone

        if (
            common_ancestor.tag_name == "template"
            and common_ancestor.children
        ):
            content_child = None
            for child in common_ancestor.children:
                if child.tag_name == "content":
                    content_child = child
                    break

            if content_child is not None:
                def _under(candidate_node, ancestor_node):
                    cur = candidate_node
                    while cur is not None:
                        if cur is ancestor_node:
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

        occurrences = [
            idx
            for idx, element in enumerate(context.open_elements._stack)
            if element is last_node
        ]
        if len(occurrences) > 1:
            for idx in reversed(occurrences[1:]):
                context.open_elements._stack.pop(idx)

        fe_clone = Node(formatting_element.tag_name, formatting_element.attributes.copy())
        for child in list(furthest_block.children):
            furthest_block.remove_child(child)
            fe_clone.append_child(child)
        furthest_block.append_child(fe_clone)

        formatting_token = formatting_entry.token
        context.active_formatting_elements.remove_entry(formatting_entry)
        if bookmark_index < 0:
            bookmark_index = 0
        if bookmark_index > len(context.active_formatting_elements):
            bookmark_index = len(context.active_formatting_elements)
        context.active_formatting_elements.insert_at_index(bookmark_index, fe_clone, formatting_token)

        if context.open_elements.contains(formatting_element):
            context.open_elements.remove_element(formatting_element)
        if context.open_elements.contains(furthest_block):
            fb_index = context.open_elements.index_of(furthest_block)
            context.open_elements._stack.insert(fb_index + 1, fe_clone)

        if context.open_elements._stack:
            context.move_to_element(context.open_elements._stack[-1])

    def _step14_place_last_node(
        self,
        formatting_element,
        last_node,
        furthest_block,
        common_ancestor,
        context,
    ):
        if common_ancestor is None:
            return

        target = common_ancestor

        if target.tag_name == "template":
            content_child = None
            for child in target.children:
                if child.tag_name == "content":
                    content_child = child
                    break
            if content_child is not None:
                target = content_child

        if (
            last_node.parent is target
            and target.children
            and target.children[-1] is last_node
        ):
            return

        if (
            last_node is furthest_block
            and last_node.tag_name in {"td", "th"}
            and last_node.parent
            and last_node.parent.tag_name == "tr"
        ):
            return

        table_child_allow = {
            "table": {"caption", "colgroup", "thead", "tbody", "tfoot", "tr"},
            "tbody": {"tr"},
            "thead": {"tr"},
            "tfoot": {"tr"},
            "tr": {"td", "th"},
        }

        if target.tag_name == "table" and last_node.tag_name == "tr":
            section = None
            for child in reversed(target.children):
                if child.tag_name in {"tbody", "thead", "tfoot"}:
                    section = child
                    break
            if section is not None:
                if last_node.parent is section:
                    return
                if last_node.parent is not None:
                    last_node.parent.remove_child(last_node)
                section.append_child(last_node)
                return

        allowed_children = table_child_allow.get(target.tag_name)
        if (
            allowed_children
            and last_node.tag_name in allowed_children
            and last_node.tag_name not in {"td", "th"}
        ):
            if last_node.parent is target:
                target.remove_child(last_node)
            target.append_child(last_node)
            return

        if needs_foster_parenting(target):
            parent, before = foster_parent(target, context.open_elements, self.parser.root)
            if parent is None:
                parent = target
            if before is not None and before.parent is parent:
                parent.insert_before(last_node, before)
            else:
                parent.append_child(last_node)
            return

        target.append_child(last_node)
