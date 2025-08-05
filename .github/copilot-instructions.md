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
3. **Iterate**: Continue improving tests until a natural stopping point, then validate overall progress with the test summary diff

This workflow ensures continuous progress while maintaining quality and preventing regressions.
