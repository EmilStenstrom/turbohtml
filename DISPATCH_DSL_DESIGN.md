# Dict-Based Dispatch DSL Design

## Goal
Replace runtime `should_handle_*` predicates with static dispatch tables for maximum performance.

## Current State (Step 1 ✅)
```python
# Parser iterates handlers and calls should_handle_*
for handler in self._active_start_handlers:
    if handler.should_handle_start(tag_name, context):
        handler.handle_start(token, context)
```

## Target State (Step 5)
```python
# Direct dict lookup, no predicates
handler_method = DISPATCH_TABLE.get((context.document_state, tag_name))
if handler_method:
    handler_method(token, context)
```

## Intermediate Steps

### Step 2: Add HANDLED_TAGS to handlers
```python
class HeadTagHandler(TagHandler):
    HANDLED_TAGS = HEAD_ELEMENTS  # Static declaration
    APPLICABLE_STATES = {DocumentState.IN_HEAD, Document State.INITIAL}

    def handle_start(self, token, context):
        # Logic here
```

### Step 3: Build dispatch tables from HANDLED_TAGS
```python
def _build_dispatch_tables(self):
    # For each handler with HANDLED_TAGS
    for handler in self.tag_handlers:
        if hasattr(handler, 'HANDLED_TAGS'):
            for tag in handler.HANDLED_TAGS:
                for state in handler.APPLICABLE_STATES:
                    self._dispatch[(state, tag)] = handler.handle_start
```

### Step 4: Fast-path dispatch with fallback
```python
def handle_start_tag(self, token, context):
    # Try fast path first
    handler_method = self._dispatch.get((context.document_state, tag_name))
    if handler_method:
        handler_method(token, context)
        return

    # Fall back to should_handle_* for complex cases
    for handler in self._active_start_handlers:
        if handler.should_handle_start(tag_name, context):
            handler.handle_start(token, context)
            return
```

### Step 5: Pure dispatch (no fallback)
All logic moved into handlers or pre-computed in dispatch tables.

## Migration Strategy

### Phase 1: Identify Simple Handlers
Handlers with simple tag checks that can be statically declared:
- HeadTagHandler → HEAD_ELEMENTS
- FormattingTagHandler → FORMATTING_ELEMENTS  
- HeadingTagHandler → HEADING_ELEMENTS
- VoidTagHandler → VOID_ELEMENTS
- RawtextTagHandler → RAWTEXT_ELEMENTS
- ListTagHandler → {"li", "dt", "dd"}
- etc.

### Phase 2: Add HANDLED_TAGS Incrementally
Add one handler at a time, test remains 100% passing.

### Phase 3: Complex Handlers
For handlers with complex logic (AutoClosingTagHandler, TableTagHandler):
- Option A: Keep should_handle_* as fallback
- Option B: Break into multiple specialized handlers
- Option C: Move complexity into handle_* method

### Phase 4: State-Aware Dispatch
Once HANDLED_TAGS exist, add APPLICABLE_STATES:
```python
class HeadTagHandler:
    HANDLED_TAGS = HEAD_ELEMENTS
    APPLICABLE_STATES = {DocumentState.IN_HEAD}  # Only active in head
```

## Performance Wins

### Current Bottlenecks
1. Iterating all handlers for every tag (even with base class filtering)
2. Calling should_handle_* methods (function call overhead)
3. Complex predicates in should_handle_* (state checks, ancestor walks)

### After Dict Dispatch
1. O(1) lookup instead of O(n) iteration
2. No function call overhead for dispatch
3. All complexity pre-computed or moved to handle_*

## Compatibility

### Backward Compatibility
Keep should_handle_* as fallback for:
- Complex handlers during migration
- Edge cases not in dispatch table
- Plugin/extension handlers

### Forward Compatibility  
New handlers can use either:
- Static HANDLED_TAGS (fast path)
- Dynamic should_handle_* (complex logic)
- Hybrid (static for common tags, dynamic fallback)

## Testing Strategy

Each step must maintain 1740/1740 tests passing:
1. Add HANDLED_TAGS to one handler
2. Run tests
3. If passing, commit
4. Repeat for next handler

Never commit breaking changes - each step is additive only.
