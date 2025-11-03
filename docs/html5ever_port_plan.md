# html5ever → TurboHTML Python Port Plan

## Goals
- Deliver a pure-Python HTML5 parser that mirrors html5ever semantics and stays 100% spec compliant.
- Achieve performance ahead of existing Python parsers (BeautifulSoup, html5lib, selectolax-python binding excluded) by prioritizing tight loops and low-allocation data structures.
- Preserve TurboHTML's modular structure so tokenizer, tree builder, and sink handlers can evolve without cross-module rewrites.

## Key References
- html5ever repo: https://github.com/servo/html5ever
- Tokenizer state machine: `html5ever/src/tokenizer/mod.rs`
- Tree builder logic: `html5ever/src/tree_builder/mod.rs`
- Tendril (rope-like UTF-8 buffer) abstraction: `html5ever/src/tendril`

## Architectural Overview (html5ever)
- **Tokenizer**: Stateful machine driven by `states::State` enum. Maintains internal buffers, attribute accumulators, and character reference sub-tokenizer. Emits `Token` variants to a `TokenSink`.
- **Tree Builder**: Consumes tokens, maintains insertion mode stack, active formatting list, adoption-agency algorithm, foreign content handling, and fosters parenting logic. Relies on `TreeSink` trait for DOM construction.
- **Utilities**: Tendril for chunked UTF-8 buffers, macros for spec DSL (`go!`, `shorthand!`), SIMD fast-path for `Data` state, and declarative tag/attribute normalization tables.

## Porting Strategy
1. **Tokenizer Translation**
   - Mirror `states::State` as Python `Enum` or integer constants for speed.
   - Replace macros (`go!`, `shorthand!`) with inline helper functions; ensure early returns map to Python control flow without exceptions.
   - Implement `BufferQueue` equivalent using deque of `memoryview` over `bytes` to avoid copies; expose `pop_except_from` semantics.
   - Character reference tokenizer: translate to a dedicated class maintaining minimal Python objects; reuse buffers via `bytearray`.
   - Keep per-token temporary buffers as `bytearray` or `array('u')` depending on code point usage; convert to `str` lazily.
2. **Tree Builder Translation**
   - Map `TreeSink` trait to Python protocol class; keep DOM agnostic but provide default DOM implementation.
   - Represent open element stack and active formatting lists with lists; ensure `same_node` semantics via object identity.
   - Translate adoption-agency, foster parenting, and foreign content adjustments directly, preserving spec order.
   - Replace tag/attribute rewrite macros with generated lookup tables (Python dict or tuple-indexed arrays) built at module import.
3. **Shared Utilities**
   - Implement `tendril` analog: `ByteBuffer` class wrapping `bytearray` with slicing without copies (use start/end indices).
   - Reproduce `small_char_set!` as bitset objects (e.g., 128-bit mask) to minimize membership checks.
   - Provide lowercasing helpers matching html5ever semantics without allocating intermediate strings (operate on bytes, use `ord`).
4. **Performance Considerations**
   - Tight loops in Python: prefer `while` loops with local variable binding; hoist attribute lookups to locals.
   - Use `__slots__` on frequently-instantiated classes (`Token`, DOM nodes) to shrink footprint.
   - Avoid Python exceptions in hot paths; use sentinel returns.
   - Expose optional C accelerator hooks later (drop-in) but keep core pure Python.
5. **Testing & Compliance**
   - Continue using `html5lib-tests`; port harness to feed tokenizer/tree builder combos with pythonic buffer objects.
   - Create microbenchmarks comparing html5lib, BeautifulSoup, current TurboHTML, and the port.
   - Add regression guard using `python run_tests.py --regressions` before merging states.

## Implementation Phases
1. **Scaffolding**
   - Create `turbohtml/html5ever/` namespace with modules mirroring upstream layout.
   - Stub interfaces (`tokenizer.py`, `tree_builder.py`, `buffer_queue.py`, `tokens.py`, `tendril.py`).
2. **Tokenizer Core**
   - Implement data structures and main loop for `Data` state; add incremental support for other states following spec order.
   - Integrate character reference tokenizer; ensure BOM handling and newline normalization match spec.
3. **Tree Builder Core**
   - Translate insertion mode system, `TreeSink` protocol, and base DOM sink.
   - Implement adoption agency and foreign content adjustments.
4. **Completeness & Optimizations**
   - Port remaining states, error reporting, script/rawtext handling.
   - Introduce fast-paths (vectorized ASCII scans using `memoryview` + `find` when possible).
   - Normalize attribute/tag lookup tables.
5. **Testing & Benchmarking**
   - Hook up html5lib fixtures; ensure parity with existing parser before enabling new code path.
   - Benchmark using `benchmark.py`, add dedicated script for tokenizer throughput.
6. **Migration Plan**
   - Keep existing TurboHTML parser intact while new port matures behind feature flag.
   - Document API parity and migration steps in `README.md`.

## Current Status
- Legacy handler/handler-stack implementation removed from the branch.
- Minimal scaffolding in place: `buffer.py`, `smallset.py`, `tokenizer.py`, `tokens.py`, `treebuilder.py`, and a thin `TurboHTML` façade.
- Tokenizer currently emits a single text run placeholder; tree builder records tokens into a simple DOM skeleton pending spec-accurate logic.

## Open Questions / Research Tasks
- Determine best pure-Python substitute for Tendril chunking (candidate: `array('b')` + slices, or custom gap buffer).
- Evaluate whether `memoryview`-based SIMD-like scanning (via `find` on bytes) is competitive enough to offset lack of explicit SIMD.
- Investigate python-level caching for lowercase conversions without violating Golden Rule #11 (reuse logic rather than caches where structure implies it).
- Plan for parser reentrancy (tokenizer pause/resume) to support `document.write` semantics in the future.

## Immediate Next Steps
1. Port html5ever's tokenizer states (start with Data/TagOpen/TagName) to begin emitting structured tokens.
2. Replace the stub tree builder with an insertion-mode engine mirroring html5ever's `TreeBuilder`.
3. Wire html5lib tests to the new pipeline to keep regressions visible while functionality grows.
