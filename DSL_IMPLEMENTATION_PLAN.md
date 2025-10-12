# Dict-Based Dispatch DSL - Implementation Plan (Revised)

## Goal
Build state-aware dispatch tables to eliminate unnecessary should_handle calls:
`DISPATCH_TABLE[state][(tag)] -> [list of candidate handlers]`

This is an enhancement over current HANDLED_TAGS approach by adding state-level filtering.

## Current State (After Initial Optimizations)
- 1.83M function calls, 0.686s
- 13 handlers have HANDLED_TAGS declarations
- Still iterate through handlers calling should_handle_*
- 87k should_handle calls remain

## Target Architecture

### Dispatch Table Structure
```python
DISPATCH_TABLE = {
    # (DocumentState, tag_name): [(priority, handler, method_name), ...]
    (DocumentState.IN_BODY, "h1"): [
        (100, heading_handler, "handle_start"),
    ],
    (DocumentState.IN_BODY, "div"): [
        (50, auto_closing_handler, "handle_start"),
        (200, document_structure_handler, "handle_start"),  # fallback
    ],
    # Wildcard for tags that apply in any state
    (None, "script"): [(10, rawtext_handler, "handle_start")],
    # State wildcard for handlers that apply in any state for specific tags
    (DocumentState.IN_BODY, None): [(500, generic_handler, "handle_start")],
}
```

### Dispatch Algorithm
```python
def handle_start_tag(token, context):
    tag = token.tag_name
    state = context.document_state
    
    # Preprocessing (always runs)
    if self.frameset_handler:
        if self.frameset_handler.preprocess_start(token, context):
            return
    if self.formatting_handler:
        self.formatting_handler.preprocess_start(token, context)
    
    # O(1) dispatch table lookup
    handlers = self._start_dispatch_table.get((state, tag))
    if handlers:
        for priority, handler, method_name in handlers:
            method = getattr(handler, method_name)
            if method(token, context):
                return
    
    # Fallback for complex handlers
    for handler in self._fallback_handlers:
        if handler.should_handle_start(tag, context) and handler.handle_start(token, context):
            return
    
    # Default insertion
    self.insert_element(token, context, mode="normal", enter=not token.is_self_closing)
```

## Handler Classification

### Tier 1: Pure DSL (state + tag only, no context checks)
These handlers can be FULLY represented in the dispatch table:
- **VoidTagHandler**: VOID_ELEMENTS, any non-frameset/template state
- **RawtextTagHandler**: RAWTEXT_ELEMENTS, any non-frameset/template state
- **ImageTagHandler**: {img, image}, IN_BODY/IN_HEAD
- **ButtonTagHandler**: {button}, IN_BODY
- **MenuitemTagHandler**: {menuitem}, IN_BODY
- **MarqueeTagHandler**: {marquee}, IN_BODY
- **RubyTagHandler**: {ruby, rb, rt, rp, rtc}, IN_BODY

### Tier 2: Mostly DSL (minor context checks can be inlined)
- **HeadingTagHandler**: HEADING_ELEMENTS, IN_BODY (check if not in foreign)
- **FormTagHandler**: {form, input, ...}, IN_BODY (simple checks)
- **ListTagHandler**: {li, dt, dd}, IN_BODY (check parent list type)
- **TemplateElementHandler**: {template}, not IN_TEMPLATE_CONTENT
- **HeadTagHandler**: HEAD_ELEMENTS, IN_HEAD/AFTER_HEAD

### Tier 3: Hybrid (needs dispatch + should_handle fallback)
- **ParagraphTagHandler**: {p} + AUTO_CLOSING_TAGS["p"], but checks scope
- **FormattingTagHandler**: FORMATTING_ELEMENTS, but needs AFE reconstruction
- **DocumentStructureHandler**: {html, head, body}, complex initial setup

### Tier 4: Complex (keep should_handle entirely)
- **TableTagHandler**: Complex foreign content + table mode checks
- **SelectTagHandler**: Malformed tag detection + subtree validation  
- **ForeignTagHandler**: SVG/MathML namespace + integration points
- **AutoClosingTagHandler**: Checks current parent + incoming tag pairs
- **GenericEndTagHandler**: Catch-all for unhandled end tags

## Implementation Phases

### Phase 1: Add APPLICABLE_STATES to Tier 1 handlers ✅ Start here
```python
class VoidTagHandler(TagHandler):
    HANDLED_TAGS = VOID_ELEMENTS
    APPLICABLE_STATES = None  # All states except frameset/template (handled in DSL)
    DSL_COMPATIBLE = True  # Mark as pure DSL handler
```

### Phase 2: Build dispatch table at initialization
- Scan handlers for DSL_COMPATIBLE = True
- For each (state, tag) combination, add (priority, handler, method) to table
- Priority = handler index (preserves order)

### Phase 3: Implement dict dispatch with fallback
- Check dispatch table first (O(1) lookup)
- Fall back to should_handle iteration for Tier 3/4 handlers
- Measure performance gain

### Phase 4: Migrate Tier 2 handlers
- Inline simple context checks into handle_start
- Mark as DSL_COMPATIBLE
- Add to dispatch table

### Phase 5: Optimize Tier 3 handlers
- Extract state+tag fast-path to DSL
- Keep complex logic in should_handle
- Hybrid approach: DSL for 95% of cases, should_handle for 5%

## Expected Performance Gains

Current: 87k should_handle calls
Target: <20k should_handle calls (only Tier 4 complex handlers)

Estimated: **75% reduction** in should_handle overhead

## Success Criteria

1. ✅ 100% test compatibility maintained
2. ✅ Performance improves or stays same
3. ✅ Code is cleaner and more maintainable
4. ✅ Handler order preserved (critical for spec compliance)
5. ✅ No heuristics - only structural dispatch

## Risks & Mitigation

**Risk**: Breaking handler order dependencies
**Mitigation**: Priority system preserves original order

**Risk**: Missing edge cases in state transitions
**Mitigation**: Comprehensive testing at each phase, maintain fallback path

**Risk**: Over-complicating simple code
**Mitigation**: Keep hybrid approach - DSL for simple, should_handle for complex

## Next Steps

1. Add APPLICABLE_STATES + DSL_COMPATIBLE to VoidTagHandler
2. Test thoroughly
3. Add to RawtextTagHandler
4. Build dispatch table infrastructure
5. Implement dict dispatch with fallback
6. Measure and iterate
