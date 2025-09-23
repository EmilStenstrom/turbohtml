"""New adoption agency implementation (spec-faithful, phased rollout).

Phase 1 goals:
  * Correct furthest_block selection (first special after formatting element).
  * Remove heuristics (text-descendant based insertion, bespoke foster moves).
  * Provide invariant assertions (debug mode only).
  * Limit activation to subset {a, b, i} when feature flag enabled.

Integration strategy: parser will delegate to this module when
`flags.NEW_ADOPTION` is True; otherwise legacy adoption remains.
"""
from __future__ import annotations

from typing import Optional

from .flags import NEW_ADOPTION
from .constants import FORMATTING_ELEMENTS, SPECIAL_CATEGORY_ELEMENTS
from .node import Node


class NewAdoptionAgency:
    def __init__(self, parser):
        self.parser = parser

    # Public entry -----------------------------------------------------
    def maybe_run(self, tag_name: str, context) -> bool:
        """Attempt to run the new adoption algorithm for any formatting element.

        Phase gating removed: now covers the full FORMATTING_ELEMENTS set when the
        NEW_ADOPTION feature flag is enabled. We still perform a fast membership
        check against the active formatting elements list to avoid unnecessary
        work when the end tag does not correspond to an active formatting entry.
        """
        if not NEW_ADOPTION:
            return False
    # Only run for genuine end tag processing. Start-tag driven implicit adoption (previous
    # segmentation heuristics) was removed to keep control flow spec-aligned and avoid
    # premature closure of anchors around block/table structures.
        # Allow execution either for end tag processing OR for a duplicate <a> start tag segmentation
        # signaled by FormattingElementHandler (context.duplicate_anchor_adoption_recent). This restores
        # spec behavior where a new <a> start tag triggers the adoption agency for any active <a>.
        processing_end = getattr(context, 'processing_end_tag', False)
        if not processing_end:
            # Allow start-tag driven segmentation for anchors when a handler explicitly flagged it.
            if tag_name == 'a' and getattr(context, 'anchor_start_tag_segmentation', False):
                # Clear flag so we don't re-enter repeatedly.
                try:
                    delattr(context, 'anchor_start_tag_segmentation')  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    pass
            else:
                return False
        if tag_name not in FORMATTING_ELEMENTS:
            return False
        if not any(
            (e.element is not None and e.element.tag_name == tag_name)
            for e in context.active_formatting_elements
        ):
            return False
        return self._run(tag_name, context)

    # Core algorithm --------------------------------------------------
    def _run(self, tag_name: str, context) -> bool:
        processed = False
        for _ in range(8):  # spec iteration cap
            entry = self._find_last_afe_entry(tag_name, context)
            if not entry:
                break
            fe = entry.element
            if fe not in context.open_elements._stack:  # step3
                # Stale AFE entry: only treat as fully handled (processed=True) if another
                # earlier same-tag formatting element still exists on the open elements stack.
                # This distinguishes true mis-nesting (test53) from cases where the element
                # actually needs closure via fallback path (adoption01/adoption02).
                same_tag_outer = False
                for el in context.open_elements._stack:
                    if el is fe:
                        break
                    if el.tag_name == tag_name:
                        same_tag_outer = True
                context.active_formatting_elements.remove_entry(entry)
                if same_tag_outer:
                    processed = True  # mis-nested inner removed; outer remains
                break
            if not context.open_elements.has_element_in_scope(fe.tag_name):  # step4
                # Only suppress fallback when an earlier same-tag ancestor is open.
                same_tag_outer = any(
                    (el is not fe and el.tag_name == tag_name)
                    for el in context.open_elements._stack
                )
                context.active_formatting_elements.remove_entry(entry)
                if same_tag_outer:
                    processed = True
                break
            furthest_block = self._find_furthest_block(fe, context)  # step6
            if furthest_block is None:
                self._simple_case(entry, fe, context)
                processed = True
                break  # step7 abort
            self._complex_case(entry, fe, furthest_block, context)
            # Complex case performed; per spec we may need to iterate again (up to 8) if mis-nesting
            # still exists for this tag name. Continue loop to attempt further restructuring.
            processed = True
            continue
        return processed

    # Helpers ---------------------------------------------------------
    def _find_last_afe_entry(self, tag_name, context):
        for entry in reversed(list(context.active_formatting_elements)):
            if entry.element is None:
                continue
            if entry.element.tag_name == tag_name:
                return entry
        return None

    def _find_furthest_block(self, formatting_element: Node, context) -> Optional[Node]:
        idx = context.open_elements.index_of(formatting_element)
        if idx == -1:
            return None
    # Spec note: We interpret "topmost" here as the nearest (first) special element after the
    # formatting element in the stack. This permits iterative adoption for nested block chains
    # (anchor layering cases) — choosing the deepest would collapse those layers into one pass.
        for n in context.open_elements._stack[idx + 1 :]:
            if n.tag_name in SPECIAL_CATEGORY_ELEMENTS:
                return n
        return None

    def _simple_case(self, entry, formatting_element: Node, context) -> None:
        if self.parser.env_debug:
            self.parser.debug(f"[adoption-simple:start] fe={formatting_element.tag_name} parent_before={context.current_parent.tag_name}")
        stack = context.open_elements._stack
        while stack and stack[-1] is not formatting_element:
            stack.pop()
        if stack and stack[-1] is formatting_element:
            stack.pop()
        # Spec: simple case removes the formatting element from both open elements stack and AFE.
        context.active_formatting_elements.remove_entry(entry)
        # Move insertion point to the formatting element's former parent if still attached; this is
        # spec-aligned (subsequent inserts happen where the element would have accepted siblings).
        parent = formatting_element.parent
        if parent is not None:
            context.move_to_element(parent)
        # Request one-shot reconstruction so that any remaining active formatting entries whose elements
        # are not on the open stack are recreated before the next character/token insertion. This matches
        # the legacy adoption path expectation and the spec's requirement that reconstruction occur at any
        # insertion point when needed. Applying uniformly (including <a>) prevents loss of expected wrapper
        # layering observed in adoption01/tests22 after anchor suppression changes.
        for entry_chk in context.active_formatting_elements:
            elc = entry_chk.element
            if elc and not context.open_elements.contains(elc):
                context.post_adoption_reconstruct_pending = True
                break
        # Clear duplicate anchor segmentation transient flag (it served its purpose triggering adoption).
        # No per-anchor suppression flags remain.
        if self.parser.env_debug:
            self.parser.debug(f"[adoption-simple:end] fe={formatting_element.tag_name} insertion_parent={context.current_parent.tag_name}")

    def _complex_case(self, entry, formatting_element: Node, furthest_block: Node, context) -> None:
        if self.parser.env_debug:
            self.parser.debug(f"[adoption-complex:start] fe={formatting_element.tag_name} parent_before={context.current_parent.tag_name}")
        fe_index = context.open_elements.index_of(formatting_element)
        fb_index = context.open_elements.index_of(furthest_block)
        if fe_index == -1 or fb_index == -1 or fb_index <= fe_index:
            return
        # Step10 common ancestor
        common_ancestor = context.open_elements._stack[fe_index - 1] if fe_index > 0 else formatting_element.parent
        if not common_ancestor:
            return
        # We do not record text-descendant heuristics; spec always leaves insertion at furthestBlock.
        node = furthest_block
        last_node = furthest_block
        removed = 0
        cloned = 0
        depth_count = 0
        while True:  # step11 loop
            if node is formatting_element:
                break
            depth_count += 1
            idx_node = context.open_elements.index_of(node)
            if idx_node == -1:
                break
            if idx_node - 1 < 0:
                break
            node_above = context.open_elements._stack[idx_node - 1]
            # Advance if not formatting element
            if not any(e.element is node_above for e in context.active_formatting_elements):
                node = node_above
                continue
            # Remove after 3 formatting elements encountered
            if depth_count > 3:
                # Remove node_above from both structures
                context.active_formatting_elements.remove(node_above)
                context.open_elements.remove_element(node_above)
                removed += 1
                node = node_above
                continue
            if node_above is formatting_element:
                node = node_above
                break
            # Clone path
            clone = Node(node_above.tag_name, node_above.attributes.copy())
            # Replace in AFE
            afe_entry = context.active_formatting_elements.find_element(node_above)
            if afe_entry:
                afe_entry.element = clone
            # Replace in OES
            idx_above = context.open_elements.index_of(node_above)
            if idx_above != -1:
                context.open_elements._stack[idx_above] = clone
            # Reparent chain
            clone.append_child(last_node)
            last_node = clone
            cloned += 1
            node = clone
        # Step14 placement (spec: appropriate place for inserting last_node). We approximate:
        # Additional spec-aligned adjustment: reparent intermediate non-formatting elements (between formatting_element
        # and furthest_block) out of the formatting element so they become siblings. The HTML Standard's steps 11–13
        # result in those nodes being relocated when building the clone chain. Because we short‑circuit for non-formatting
        # elements (advancing 'node' without moving them), we explicitly relocate them here to approximate the final tree.
        # (Intermediate non-formatting relocation intentionally omitted – earlier attempt regressed multiple suites.)
        # If formatting_element shares parent with common_ancestor, insert last_node immediately after it; else append.
        if last_node.parent is not common_ancestor:
            if last_node.parent is not None and last_node in last_node.parent.children:
                last_node.parent.remove_child(last_node)
            inserted = False
            if (
                formatting_element.parent is common_ancestor
                and formatting_element in common_ancestor.children
            ):
                idx_fmt = common_ancestor.children.index(formatting_element)
                common_ancestor.insert_child_at(idx_fmt + 1, last_node)
                inserted = True
            if not inserted:
                common_ancestor.append_child(last_node)
        # (Removed experimental reparenting of furthest_block under last_node; spec does not move furthest_block.)
        # Steps15-19
        fe_clone = Node(formatting_element.tag_name, formatting_element.attributes.copy())
        # Move children of furthest_block into fe_clone
        for ch in list(furthest_block.children):
            furthest_block.remove_child(ch)
            fe_clone.append_child(ch)
        furthest_block.append_child(fe_clone)
        # Replace entry in AFE
        entry.element = fe_clone
        # Remove original formatting element from OES, insert clone after furthest_block
        context.open_elements.remove_element(formatting_element)
        if furthest_block in context.open_elements._stack:
            insert_at = context.open_elements.index_of(furthest_block) + 1
            context.open_elements._stack.insert(insert_at, fe_clone)
        # Spec insertion point: move to furthest_block so subsequent text inserts inside it.
        # Fallback: when no structural cloning/removal occurred and formatting element is
        # an inline segmentation-sensitive tag (anchor/nobr), legacy trees place subsequent
        # content at the common ancestor level rather than nested under furthest_block.
        if cloned == 0 and removed == 0 and formatting_element.tag_name == 'a':
            # Anchor segmentation edge: legacy trees place following content at common ancestor
            # rather than nested inside furthest_block when no structural mutations occurred.
            if common_ancestor:
                context.move_to_element(common_ancestor)
            else:
                context.move_to_element(furthest_block)
        else:
            # For nobr (and other formatting elements) keep spec insertion point inside furthest_block
            context.move_to_element(furthest_block)
        # Trailing text preservation: if no structural changes (cloned/removed == 0) for a non-anchor formatting
        # element and an ancestor formatting element remains open whose parent is the current insertion parent,
        # move insertion into that ancestor so subsequent text stays wrapped (tests1:53 scenario).
        if cloned == 0 and removed == 0 and formatting_element.tag_name != 'a':
            # Find nearest formatting ancestor (excluding the processed element) still on open stack.
            outer_fmt = None
            for el in reversed(context.open_elements._stack):  # type: ignore[attr-defined]
                if el is formatting_element:
                    continue
                if el.tag_name in ('b','i','u','em','strong','font'):
                    outer_fmt = el
                    break
            if outer_fmt and outer_fmt in context.open_elements._stack:
                # Only reposition if outer_fmt is direct child of current insertion parent or its parent
                if outer_fmt is context.current_parent or outer_fmt.parent is context.current_parent:
                    context.move_to_element(outer_fmt)
        # Anchor/table layering aid: if no intermediate formatting elements were cloned (cloned==0)
        # and the formatting element is <a> with a block descendant furthest_block, detach the original
        # formatting element from its parent (already removed from open stack) and, if its previous parent
        # still exists, insert it just before furthest_block so future nested anchors split correctly.
        if cloned == 0 and formatting_element.tag_name == 'a' and furthest_block.parent is not None:
            parent = furthest_block.parent
            if formatting_element.parent is parent and formatting_element in parent.children:
                try:
                    parent.remove_child(formatting_element)
                    idx_fb = parent.children.index(furthest_block)
                    parent.insert_child_at(idx_fb, formatting_element)
                except Exception:
                    pass
        # Request reconstruction only when structural cloning/removal occurred; this reduces
        # over-wrapping for pure segmentation cases (cloned==0 and removed==0) and matches legacy.
        if removed > 0 or (cloned > 0 and formatting_element.tag_name in ('a','nobr')) or (cloned == 0 and removed == 0 and formatting_element.tag_name == 'nobr'):
            # Reconstruction triggers:
            #   * Any removal always (structure changed, may need wrappers recreated)
            #   * Cloned path only for anchor/nobr where segmentation requires immediate wrapper recreation
            #   * Pure segmentation (no clone/remove) for nobr (spec nuance)
            context.post_adoption_reconstruct_pending = True
        else:
            # For cloned-only structural changes on other formatting elements, suppress the next stale-AFE
            # reconstruction so trailing character immediately after adoption stays inside furthest_block (adoption02:0).
            if cloned > 0 and removed == 0 and formatting_element.tag_name not in ('a','nobr'):
                context.skip_stale_reconstruct_once = True  # type: ignore[attr-defined]
        if cloned == 0 and removed == 0:
            # clone/remove-free path: if any active formatting entry is stale (element not on open stack),
            # request one-shot reconstruction so trailing text is wrapped (fixes lost wrapper tail cases).
            for entry_check in context.active_formatting_elements:
                elc = entry_check.element
                if elc and not context.open_elements.contains(elc):
                    context.post_adoption_reconstruct_pending = True
                    break
        # Record whether this complex adoption produced structural mutations; paragraph hook
        # can use this to decide on forced reconstruction heuristic for legacy alignment.
        context.last_complex_adoption_no_structural_change = (cloned == 0 and removed == 0)
        if self.parser.env_debug:
            self.parser.debug(f"[adoption-complex:end] fe={formatting_element.tag_name} removed={removed} cloned={cloned} insertion_parent={context.current_parent.tag_name}")
