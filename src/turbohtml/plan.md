🔍 Key gaps preventing spec parity

# Adoption agency simple-case drift

Step 7 currently pops every element above the formatting element and prunes descendant AFE entries. The spec only removes the formatting element itself.
Side effects: lost wrappers, duplicated <em>, stale AFE entries (see tests1.dat:30,102) and the adoption misfires in tests19.dat.

# Complex-case misplacement around tables

Step 14/15 deviates from the standard “appropriate place for inserting a node” sequencing, and the post-step foster move only handles a narrow block set.
Result: anchors stay glued inside tables instead of resuming outside (tests1.dat:30,101) and inline elements migrate into table descendants (tests19.dat).

# Anchor/text resume heuristics

TextHandler forcibly re-enters the last open <a> (via resume_anchor_after_structure / active-<a> scan) and merges text into it, even after spec-driven adoption should have closed it.
That’s why tests1.dat:77 and :79 weld “aoe” or “braoe” onto the wrong anchor.

# Formatting start-tag order of operations

Reconstruction happens before the duplicate-anchor adoption run; if the adoption closes the current anchor, we immediately rebuild it in the old location.
Combined with the anchor-specific suppression flag in simple-case, this keeps stale wrappers alive.

# Active formatting bookkeeping tweaks

The ad-hoc pruning of popped descendants and reconstruction suppression for <a> breaks the contract that AFE mirrors the stack; later reconstructions either never happen or happen in the wrong place.

# Table insertion state machine gaps

TableTagHandler accepts <colgroup> while in tbody, tr, or td, instead of switching back to “in table” mode and topping out per spec.
That’s the root of tests1.dat:108 and contributes to the malformed table trees in tests19.dat.

# tricky01 foster/adoption mix

Similar stack-sync problems show up with %center%, <font>, and <dl>: without spec-faithful adoption and correct block-scope closures, formatting elements accumulate or end up under table rows.
🛠️ Roadmap to 100%

# Re-implement Step 7 exactly

Pop only the formatting element; don’t touch siblings or descendant AFE entries.
Immediately run the standard “stale formatting” reconstruction check (no anchor-specific suppression) so the tree/AFE stay in sync.

# Align Steps 11–15 with the spec text

Track nodeAbove via the stack without custom pruning, recreate clones, and always insert lastNode using the tree-construction “appropriate place” helper.
Remove one-off post-step heuristics; if special cases are truly needed, document them with the corresponding spec clause.
After Step 19, the insertion point should follow the spec: stay at furthestBlock unless it had pre-existing text, in which case move to its parent—no extra anchor hacks.

# Clean up formatting start-tag flow

Run the duplicate-<a> adoption before any reconstruction, then let reconstruction operate on the new insertion point.
Drop resume_anchor_after_structure and similar one-off flags; rely on the adoption algorithm + reconstruction to reopen anchors when required.

# Fix text insertion around tables

Let the standard insertion location determine where text goes after adoption; no manual anchor re-entry.
Ensure table foster parenting defers to the spec (characters in table contexts handled via the foster-parent algorithm without custom anchor continuation code).

# Modernize table insertion modes

When colgroup, tbody, tr, etc., appear out of place, switch the insertion mode and reprocess the token (mirroring the HTML5 “in table” algorithm).

# Tighten the per-mode handlers so colgroup cannot become a child of tbody, tr, or td.

Once the adoption pipeline and table modes are spec-faithful, sweep remaining heuristics (e.g., skip_stale_reconstruct_once, anchor-specific flags) to ensure we rely purely on the standard algorithm. This should close the last handful of skipped/failed cases.