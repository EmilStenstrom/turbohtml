# Programming Copilot Instructions for TurboHTML

**TurboHTML** is an HTML5 parser being built with AI assistance, currently passing html5lib test suite tests. It follows a modular handler-based architecture strictly adhering to the WHATWG HTML5 specification.

## Key Architecture

- **Tokenizer** (`tokenizer.py`): HTML5-compliant token generation with state machines for RAWTEXT handling
- **Handler System** (`handlers.py`): Modular tag handlers (VoidElement, Formatting, Table, etc.) that process tokens
- **Node Tree** (`node.py`): DOM-like tree with parent/child/sibling relationships and `to_test_format()` output
- **Context State** (`context.py`): Tracks DocumentState (IN_HEAD, IN_BODY, etc.) and ContentState (RAWTEXT, PLAINTEXT)
- **Constants** (`constants.py`): HTML5 element categorization lists (maintain order for deterministic behavior)

## Critical Patterns

1. **Handler Priority**: Handlers process in specific order - more specific handlers (DoctypeHandler, PlaintextHandler) before general ones
2. **State Management**: `context.document_state` is read-only; use `parser.transition_to_state()` to change state. Read `context.content_state` directly, not booleans
3. **Tree Building**: Always use `append_child()`, `insert_before()` methods to maintain sibling links
4. **Test Format**: Node output must match html5lib format via `to_test_format()` method
5. **Debug Tracing**: Use `self.debug()` in handlers and `parser.debug()` with consistent indentation
6. **Circular References**: Node.append_child() has built-in circular reference detection - trust it to prevent DOM cycles
7. **Adoption Agency**: Clean html5lib-style implementation in adoption.py with foster parenting safeguards

## Code Style

Python 3.8+, Black formatting (119 chars), type hints, descriptive variable names, comprehensive docstrings.

## Performance Goals

- **Parsing Speed**: ~2-5x faster than `lxml` for large documents
- **Memory Usage**: ~30-50% lower than `BeautifulSoup`

## When Contributing

Focus on failing test cases, ensure HTML5 spec compliance, maintain handler modularity, and preserve the existing state machine patterns.

## Testing

The current focus is to get to 100% test coverage.

Run tests with `python run_tests.py`. Use `--debug` for detailed output, `--filter-files` to target specific test files (supports multiple: `--filter-files adoption table`), and `--print-fails` to see failing test details. Do no create random test files, use `run_tests.py` or `python -c "command"` to troubleshoot.

**Efficiency Notes:**
- Use `timeout 30s` for any test runs to prevent infinite loops
- When debugging, start with `--filter-files` on specific test files rather than running all tests
- Use `--quiet` flag to reduce output when checking overall progress
- Don't read large files in small chunks - read meaningful sections at once
- Test config structure: all boolean flags default to False, lists default to None

### Quick Single Test Template

For fast debugging of specific HTML snippets without wasting tokens:

```python
timeout 5s python3 -c "
from turbohtml import TurboHTML
result = TurboHTML('<your test html here>', debug=True)
print(result.root.to_test_format())
"
```

Note: Use `TurboHTML(html, debug=True)` constructor directly (no separate `.parse()` call needed).

The `tests/` directory contains html5lib test data files (`.dat` format) with test cases for HTML parsing conformance. Each test includes input HTML, expected errors, and expected DOM tree output in a specific format that must be matched exactly.

Each time run_tests.py is run without filters, it writes an automated summary of which tests passed and failed to a file called test-summary.txt. You can use `git diff test-summary.txt` to see which tests were affected since last checkin.

## Development Workflow

The typical development workflow is:
1. **Improve tests**: Focus on fixing failing test cases, implementing missing handlers, or improving existing logic
2. **Check for regressions**: After making changes, run `git diff test-summary.txt` to ensure no previously passing tests have regressed
3. **Iterate**: Continue improving tests, then validate overall progress with `git diff test-summary.txt`
4. IMPORTANT: **Act with autonomy**: Don't stop and ask for permission to continue, continue iterating until you have improvements to test coverage to show.

This workflow ensures continuous progress while maintaining quality and preventing regressions.

## Coding Standards & Quality Rules

These standards must be followed for all new or modified code.

### 1. Deterministic Control Flow
- Do not use exceptions for normal control (no try/except around membership tests, stack pops, or flow decisions).
- Prevalidate conditions with explicit checks (e.g. `if entry in stack` before remove) instead of catching `ValueError`.
- Avoid hidden fallbacks; all branches should be intentional and spec-aligned.

### 2. Exception Policy
- Core parsing (tokenizer, handlers, adoption, parser) should be effectively exception-free during normal operation.
- If an exception is truly unrecoverable, let it surface (no broad `except:` or silent pass).
- Catch only the narrowest specific exception types when absolutely required for defensive safety.

### 3. Reflection & Introspection
- Do not use `hasattr`, `getattr` with dynamic names, or duck-typed probing in hot paths.
- Rely on explicit, guaranteed attributes and interfaces; unexpected absence is a bug, not a branch.

### 4. State Management
- Do not cache derivable or transient state (e.g. prior document state for `<template>`, adoption counters, last breakout nodes).
- Infer current conditions from the DOM structure and open element / active formatting stacks.
- Eliminate write-once flags once their behavior is representable structurally.
- Keep `ParseContext` lean: only persist state that cannot be recomputed cheaply each step.

### 5. Formatting & Adoption Agency
- Follow HTML5 spec steps; helper methods may bundle step groups but must preserve semantics.
- No heuristic flags to shortcut adoption loops; use structural checks and `run_until_stable` style iteration where needed.
- Reconstruct active formatting elements only when permitted (respect table / row / cell mode constraints).

### 6. Tree Operations
- Use `Node.append_child` / `insert_before` to preserve sibling linkage except in controlled, well-audited performance-sensitive spots; if bypassing, update sibling pointers correctly.
- Never create circular references (trust internal guard, do not reimplement it).
- When relocating nodes, detach safely (no partial pointer updates).

### 7. Comments & Documentation
- Source comments describe current behavior only (no historical change logs or “removed X” notes).
- Keep rationale concise; if a heuristic exists, state the invariant or spec clause it enforces—not how code “used to” behave.
- Debug messages may narrate spec step progression but should not reference past refactors.

### 8. Performance & Allocation
- Prefer structural inference over auxiliary bookkeeping objects or flags.
- Avoid per-token small object churn when a stack or existing node relationship suffices.
- Keep attribute iteration deterministic (sorted output where required by tests) but avoid unnecessary re-sorting elsewhere.

### 9. Testing & Regression Guardrails
- After any semantic change, run focused test subsets first, then full suite, and inspect `git diff test-summary.txt`.
- Never accept a net loss in passing tests without an accompanying explanation and an opened TODO to restore them.
- Add minimal targeted tests only via the existing `.dat` framework—no ad-hoc test harness files.

### 10. Handler Design
- A handler’s `should_handle_*` must be a pure predicate (no side effects) and cheap.
- Early-return aggressively for inapplicable contexts (foreign content, template content boundaries, frameset modes).
- Keep tag-specific logic contained; do not embed unrelated adoption or tokenizer details inside generic handlers.

### 11. Tokenizer Rules
- No exception-driven entity parsing; validate first, branch explicitly.
- Keep tight loops allocation-light (reuse local vars, avoid unnecessary slicing).
- Side effects (position advancement) must be obvious and linear—no rewinding via exceptions.

### 12. Consistency & Style
- Follow Black (line length 119) but do not reformat unrelated regions in functional PRs.
- Use descriptive variable names (avoid single letters outside tight loops or spec-correlated indices).
- Keep public-facing APIs typed; internal hot-path classes may omit annotations if profiling shows benefit.

### 13. Heuristics Policy
- Only introduce a heuristic if a spec ambiguity or malformed input edge case requires deterministic resolution for tests.
- Heuristics must be minimal, locally scoped, and reversible without breaking core spec conformance.

Adhering to these standards keeps the parser deterministic, maintainable, and performant while aligned with the HTML5 specification and test expectations.

### 14. Test-Agnostic Implementation Policy
To avoid re‑introducing brittle, test‑named heuristics or overfitting code to individual `.dat` cases:

- Prohibited in source: direct references to specific test file names (e.g. `tests22.dat`, `tricky01`, `adoption01.dat`, `webkit02`, `html5test-com`). Comments and debug strings must instead describe the structural or spec condition ("misnested formatting inside table cell before block", "stray end tag after partial table prelude", etc.).
- Prefer spec clause or structural invariant: When justifying a branch, cite the HTML Standard concept (e.g. "adoption agency Step 10: furthest block selection") rather than a test case.
- Debug / logging: Must not contain test file identifiers. Use neutral phrasing: `Adoption: suppressed duplicate cite wrapper (already ancestor)`.
- Heuristic introduction checklist:
	1. Identify the malformed input pattern in structural terms (sequence of tokens / DOM relationships).
	2. Confirm absence of a direct spec rule covering it.
	3. Implement the smallest transformation that restores spec-conformant tree building for subsequent steps (not one that "matches expected tree").
	4. Add a concise comment documenting the invariant enforced; omit any mention of the triggering test file.
	5. Ensure removal of the heuristic would only affect malformed input, not well‑formed cases.
- Removal policy: If a heuristic's behavior duplicates normal spec processing after adjacent refactors, delete it entirely instead of leaving a dormant branch.
- Review gate: Any PR introducing text matching regex `tests[0-9]|tricky|adoption0|webkit|html5test` in non-test files must revise wording before merge.

Rationale: Keeping implementation commentary test‑agnostic prevents brittle coupling, reduces temptation to accrete case-by-case patches, and keeps focus on spec semantics, improving maintainability and future optimization opportunities.
