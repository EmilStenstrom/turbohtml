# Remaining HTML5 Tree-Construction Gaps (9 tests)

## tests1.dat – anchors, lists, and table contexts
- **Case 91** (`<a><table><a>…`): anchor adoption still traps the outer `<a>` inside the table. Need Step 14 placement to reinsert the formatting element outside the table after adoption.
- **Case 102** (`<a><table><td><a>…`): table cell foster parenting combined with nested anchors reopens `<a>` in the wrong scope. Requires consistent adoption + foster-parent integration during Step 19 cleanup.
- **Case 103** (`<ul><li></li><div><li>…`): list item/adoption interaction overwrites the list structure; formatting element removal should stop at the list boundary while reparenting inline stacks.
- **Case 109** (`<table><colgroup><tbody><colgroup>…`): table mode fallback still allows `<colgroup>` inside tbody/tr. Need to re-run the “in table” insertion-mode switch before processing structural tokens.

## tests19.dat – nested tables and head-only elements
- **Case 95** (`<table><td><table><i>a<div>b<b>c</i>d`): mixed foster parenting and adoption around nested `<i>/<b>` chains leaks inline nodes across tables. Align complex-case clone attachment with the spec’s “appropriate place” logic while keeping the insertion point at the furthest block.
- **Case 96** (`<body><bgsound>`): proprietary head-only tag lands in the body. Should route through the head-element handler (create `<head>` if missing) and keep the body insertion point unchanged.

## tricky01.dat – legacy formatting with foster parenting
- **Case 4** (`<dl>` with `<b>` straddling `<dt>/<dd>`): adoption needs to stop re-closing `<b>` at the wrong depth when definition list items end; respect scope boundaries for `%dl` structures.
- **Case 6** (`<table><center><font>…`): foster-parented formatting elements before tables still duplicate wrappers and leave stray text nodes. Reconcile adoption with the center/font stack handling before invoking table foster parenting.
- **Case 8** (`<center><center><td>…` / nested tables + `<font>`): combination of table foster parenting and adoption breaks `<font>` hierarchy. Need a unified path that (a) pushes tokens back to “in table” mode for structural tags and (b) lets adoption rebuild formatting chains without manual heuristics.

# Targeted Workstreams
1. **Finalize adoption Step 14–19 alignment for table contexts**  \
	Handle placement of `last_node` via the standard “appropriate place” helper and ensure the post-adoption insertion point resumes outside `<table>` when required (covers tests1 91/102 and tricky01 6/8).
2. **List/adoption boundary enforcement**  \
	During simple-case cleanup, stop popping past list containers and trigger reconstruction only after restoring the `<li>` scope (tests1 103, tricky01 4).
3. **Table insertion-mode recovery**  \
	When processing `<colgroup>` (and other table-structure tags) from tbody/tr contexts, switch the parser back to the “in table” mode and reprocess the token so undesired nesting cannot occur (tests1 109, tricky01 8 side-effects).
4. **Nested-table foster parenting audit**  \
	Combine adoption and foster parenting so inline nodes migrate to the foster parent without duplicating `<i>/<b>` chains (tests19 95, tricky01 6/8 overlap).
5. **Head-only element routing**  \
	Extend the head handler to catch `bgsound` (and similar tags) even when the current insertion point is `<body>`; synthesize `<head>` as needed (tests19 96).

Each item should land with focused unit runs (`python run_tests.py --filter-files …`) followed by a full suite confirmation.