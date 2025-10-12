# TurboHTML Performance Optimization Journey

## Summary

A series of incremental optimizations reduced function call overhead by 17% and improved parsing speed by 9%, while maintaining 100% test compatibility (1740/1740 tests passing).

## Optimization Results

### Before (Baseline - commit 45fad41)
- **Function calls**: ~2,200,000
- **Time**: ~0.750s
- **Tests**: 1740/1740 (100%)

### After (Current - commit 0b36fc6)
- **Function calls**: 1,825,771 ⬇️ **17% reduction**
- **Time**: 0.684s ⬇️ **9% faster**
- **Tests**: 1740/1740 (100%) ✅

## Optimization Steps

### 1. Base Class Method Filtering (commit ae70fe3)

**Technique**: Pre-filter handlers at initialization time using `__func__` identity checks.

```python
# Before: Called should_handle_* on all handlers (including base class no-ops)
for handler in self.tag_handlers:
    if handler.should_handle_start(tag, context):
        ...

# After: Only call handlers that override base class methods
self._active_start_handlers = [
    h for h in self.tag_handlers
    if h.should_handle_start.__func__ is not base_should_handle_start
]
```

**Impact**: Eliminated ~277,000 base class should_handle calls per test run.

### 2. HANDLED_TAGS Declarations (commits d4df71c, d859023)

**Technique**: Add static tag declarations to handlers with clear tag sets.

```python
class FormattingTagHandler(TagHandler):
    HANDLED_TAGS = FORMATTING_ELEMENTS  # frozenset of b, i, strong, em, etc.
    HANDLED_END_TAGS = FORMATTING_ELEMENTS
```

**Handlers annotated** (13 total):
- HeadingTagHandler (h1-h6)
- FormattingTagHandler (b, i, strong, em, etc.)
- VoidTagHandler (img, br, hr, input, etc.)
- RawtextTagHandler (script, style, title, etc.)
- ListTagHandler (li, dt, dd)
- RubyTagHandler (ruby, rb, rt, rp, rtc)
- FormTagHandler (form, input, button, textarea, select, label)
- ImageTagHandler (img, image)
- ButtonTagHandler (button)
- MenuitemTagHandler (menuitem)
- MarqueeTagHandler (marquee)
- HeadTagHandler (HEAD_ELEMENTS)
- TemplateElementHandler (template)
- ParagraphTagHandler (end tags only - start logic too complex)

**Impact**: Enables fast-path tag filtering (next step).

### 3. Fast-Path Tag Filtering (commit f7690bf)

**Technique**: Skip handlers with HANDLED_TAGS that don't match current tag.

```python
for handler in self._active_start_handlers:
    if hasattr(handler, 'HANDLED_TAGS') and handler.HANDLED_TAGS is not None:
        if tag_name not in handler.HANDLED_TAGS:
            continue  # Skip - doesn't handle this tag
    if handler.should_handle_start(tag_name, context):
        ...
```

**Critical**: Preserves handler order (DocumentStructureHandler must run before HeadingTagHandler).

**Impact**: O(1) frozenset membership checks eliminate unnecessary should_handle calls.

### 4. Hasattr Overhead Elimination (commit 0b36fc6)

**Technique**: Pre-compute handler metadata at build time instead of checking hasattr in hot path.

```python
# Build time (once):
self._start_handler_metadata = [
    (h, getattr(h, 'HANDLED_TAGS', None))
    for h in self._active_start_handlers
]

# Dispatch (hot path):
for handler, handled_tags in self._start_handler_metadata:
    if handled_tags is not None and tag_name not in handled_tags:
        continue
    if handler.should_handle_start(tag_name, context):
        ...
```

**Impact**: Eliminated 237,000 hasattr calls per test run.

## Remaining Hotspots

### should_handle_start (31k calls)
- **TableTagHandler**: 11k calls - Complex table mode + foreign content logic
- **SelectTagHandler**: 11k calls - Malformed tag handling + select subtree logic  
- **Others**: 9k calls - Various context-dependent handlers

### should_handle_text (36k calls)
- **TableTagHandler**: 21k calls - Table text handling with foster parenting
- **FramesetTagHandler**: 15k calls - Frameset text validation

### should_handle_end (20k calls)
- **ForeignTagHandler**: 9k calls - SVG/MathML end tag dispatch
- **Others**: 11k calls - Various handlers

## Analysis

### What Works
These handlers have **complex context-dependent logic** that requires runtime predicates:
- **TableTagHandler**: Checks document_state (IN_TABLE, IN_ROW, IN_CELL, etc.) and foreign content
- **SelectTagHandler**: Detects malformed tags, checks select subtree nesting
- **ForeignTagHandler**: SVG/MathML namespace and integration point detection

These are **legitimate should_handle calls** - they represent real spec-compliant decision logic.

### Future Optimization Opportunities

1. **State-Aware Dispatch**
   - Add `APPLICABLE_STATES` to handlers that only apply in specific DocumentStates
   - Build per-state handler lists: `dispatch_tables[state]` contains only applicable handlers
   - Example: TableTagHandler only needed in table states (IN_TABLE, IN_ROW, IN_CELL, IN_CAPTION)
   - Example: HeadTagHandler only in IN_HEAD, AFTER_HEAD states
   - Risk: State transitions could break handler ordering assumptions

2. **Dict-Based DSL** (Long-term)
   - For simple handlers: `DISPATCH_TABLE[(state, tag)] = handler_method`
   - Keep should_handle_* for complex handlers (TableTagHandler, SelectTagHandler, AutoClosingTagHandler)
   - 95%+ common tags use O(1) dict lookup, 5% use predicate logic
   - Risk: Requires careful analysis to identify truly "simple" handlers

3. **Micro-Optimizations**
   - Inline common context checks (avoid function call overhead)
   - Cache frequently-checked DOM relationships
   - Profile-guided optimization of specific hot paths in TableTagHandler

## Lessons Learned

1. **Incremental is safer**: Each optimization tested in isolation, committed separately
2. **Preserve handler order**: Critical for spec compliance (discovered when tests broke)
3. **Measure everything**: Profile before and after each change
4. **No heuristics**: Every optimization based on structural properties, not test-specific patterns
5. **100% tests always**: Never commit with regressions (reverted bad attempts)

## Performance Mindset

Per project guidelines:
- Keep tokenizer tight (no slicing churn, no exception rewinds) ✅
- Infer instead of storing (e.g., adoption state from stacks) ✅
- No hasattr/getattr in hot paths ✅ **Achieved**
- No exceptions in hot paths ✅
- Minimal allocations: reuse locals ✅

## Conclusion

Achieved **17% function call reduction** and **9% speedup** through systematic optimization:
1. Eliminated base class overhead
2. Declared static tag sets where possible
3. Built fast-path dispatch preserving handler order
4. Pre-computed metadata to eliminate runtime reflection

Remaining should_handle calls are **legitimate context-dependent logic**. Further gains would require state-aware dispatch or architectural changes, with diminishing returns vs. risk.

**The current implementation is clean, maintainable, and spec-compliant.**
