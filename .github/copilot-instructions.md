## TurboHTML – Agent instructions

# Decision & Clarification Policy (Overrides)

- Default to acting. When details are missing, make up to two reasonable assumptions based on repo conventions and proceed.
- Ask at most one concise clarifying question **only** if a single decision truly blocks execution; otherwise continue.
- Do not ask for approval before running safe, local actions (reads, searches, diffs, non-destructive edits/tests).
- If edit tools are unavailable, output a minimal unified diff/patch instead of asking for permission.
- When uncertain about file paths, first search the workspace and use conventional locations; create new files as needed with a brief note.
- Replace “propose a follow-up” with “propose **and execute** the best alternative by default; ask only for destructive/irreversible choices.”
- Keep preambles to a single declarative sentence (“I’m scanning the repo and then drafting a minimal fix.”) — no approval requests.

### Core Purpose
TurboHTML is a HTML5 parser targeting 100% html5 spec compliance with handler modularity, speed (2–5× lxml), and lean memory (30–50% below BeautifulSoup).

### Architecture Snapshot
- Tokenizer (`tokenizer.py`): Spec state machines (incl. RAWTEXT). No exception-driven flow.
- Parser + Handlers (`parser.py`, `handlers.py`): Ordered, specific→general dispatch. Pure `should_handle_*` predicates.
- Node tree (`node.py`): DOM-like; always use `append_child()` / `insert_before()` (sibling links + cycle guard).
- Context (`context.py`): `document_state` changed only via `parser.transition_to_state()`. Read `content_state` directly.
- Adoption agency (`adoption.py`): Spec steps; table foster parenting safeguards.
- Constants (`constants.py`): Ordered element category lists (ordering matters—don’t reshuffle).

### Golden Rules
1. Deterministic control flow: no try/except for normal branching or membership.
2. Exceptions: none in hot paths unless truly unrecoverable.
3. No reflective probing (`hasattr`, dynamic `getattr`) in performance paths.
4. Persist only non-derivable state; infer the rest from stacks / tree.
5. Handlers: early return for inapplicable modes (foreign content, template, frameset).
6. Tree ops: never manual pointer hacks outside audited spots; no circular structures.
7. Debug logging: structural/spec phrasing only; no test file name references.
8. Minimal allocations: reuse locals; avoid per-token tiny objects.
9. Formatting/adoption: follow spec steps; no heuristic “shortcuts”.
10. Output determinism: attribute order only where tests require it (don’t gratuitously sort).
11. Less code > more code: prefer removing/simplifying logic over adding layers; consolidate duplicate paths.
12. Avoid one-off properties on `parser.py` / `context.py`: only add persistent fields after exhausting structural derivation (stacks, existing state) options.

### Heuristics Policy
No heuristics allowed, and if found remove and replace with spec-compliant code instead.

### Prohibited
- No test filename references in comments (`tests\d+`, `tricky`, `webkit`, etc.).
- No hidden fallback branches, we don't care about backwards compatibility
- No overfitting patches referencing specific test cases.
- Caching “one-shot” flags that the structure (via parse tree or open elements) already implies.
- No typing
- No exceptions
- No hasattr/getattr/delattr, we have full control of the code

### Testing Workflow
1. Target failing areas first (use `--filter-files` or `--test-specs`).
2. Use `-vv` to trace execution path through the parser.
2. Iterate: fix → focused run → full run.
3. Always check for regressions: run `python run_tests.py --regressions` or inspect `git diff test-summary.txt`.
4. Never merge with net fewer passing tests unless justified.
5. Quick snippet runner (full test suite never takes longer than 5s):
   ```
   python -c "from turbohtml import TurboHTML; print(TurboHTML('<html>', debug=True).root.to_test_format())"
   ```

### Logging & Comments
- Comments: current behavior + spec rationale (cite concept/step).
- No historical notes ("Previously", "Removed"), prefer replacing old code with nothing.
- Debug: use `self.debug()` / `parser.debug()`, no gating needed.
- Be dilligent when determining consistent indentation.

### Performance Mindset
- Keep tokenizer tight (no slicing churn, no exception rewinds).
- Infer instead of storing (e.g., adoption state from stacks).
