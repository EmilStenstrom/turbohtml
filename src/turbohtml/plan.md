# Remaining HTML5 Tree-Construction Gaps (6 tests)

## tests1.dat – lists and table contexts
- **Case 108** (`<table><colgroup><tbody><colgroup>…`): we continue to accept `<colgroup>` inside a tbody/tr. The parser should jump back to the “in table” insertion mode and reprocess structural tokens so they land before the row group.

## tests19.dat – nested tables and inline adoption
- **Case 93** (`<!doctype html><table><i>a<div>b<tr>c<b>d</i>e`): complex-case adoption around `<i>/<b>` chains inside a table moves inline nodes across the foster-parent boundary. Align Step 14 placement with the appropriate-place helper and keep the furthest block as the insertion anchor.
- **Case 94** (`<!doctype html><table><td><table><i>a<div>b<b>c</i>d`): nested tables combined with adoption duplicate `<b>` wrappers inside the inner table. Need a consistent hand-off between adoption and foster parenting when the furthest block lives inside a table cell.

## tricky01.dat – legacy formatting with foster parenting
- **Case 3** (`<dl>` with `<b>` across `<dt>/<dd>`): the adoption algorithm re-closes `<b>` at the wrong depth. Respect `%dl` boundaries so the formatting element stays associated with both list items.
- **Case 5** (`<table><center> <font>a</center> …`): table foster parenting and adoption still conflict, leaving stray `<font>` wrappers around whitespace. Normalize adoption output before the foster-parent step.
- **Case 7** (`<center><center><td>…` / nested tables + `<font>`): stacked centers + fonts break when adoption fires inside table insertion modes. We need a unified path that reprocesses structural tokens in “in table” mode and then rebuilds the formatting chain without duplicates.

# Targeted Workstreams

1. **Table insertion-mode recovery**  \
	When structural tags like `<colgroup>` appear from tbody/tr contexts, switch back to “in table”, reprocess the token, and ensure adoption doesn’t leave the insertion point inside the row group (tests1 108, tricky01 7).
2. **Adoption × foster parenting integration**  \
	Share a single “appropriate place” helper for Step 14 and foster-parent relocation so inline nodes stay attached to the correct table ancestor (tests19 93/94, tricky01 5/7).
3. **Inline chain stabilization in nested tables**  \
	Audit the cloned formatting stacks created during complex-case adoption to guarantee we neither duplicate nor drop `<b>/<i>` wrappers when the furthest block sits in a cell or foster-parent slot (tests19 93/94, tricky01 5).

Each item should ship with focused runs (`python run_tests.py --filter-files …`) followed by a full regression sweep.