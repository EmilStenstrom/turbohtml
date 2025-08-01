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
2. **State Management**: Use `context.document_state` and `context.content_state` enums, not booleans
3. **Tree Building**: Always use `append_child()`, `insert_before()` methods to maintain sibling links
4. **Test Format**: Node output must match html5lib format via `to_test_format()` method
5. **Debug Tracing**: Use `self.debug()` in handlers and `parser.debug()` with consistent indentation

## Code Style

Python 3.8+, Black formatting (119 chars), type hints, descriptive variable names, comprehensive docstrings.

## Performance Goals

- **Parsing Speed**: ~2-5x faster than `lxml` for large documents
- **Memory Usage**: ~30-50% lower than `BeautifulSoup`

## When Contributing

Focus on failing test cases, ensure HTML5 spec compliance, maintain handler modularity, and preserve the existing state machine patterns.

## Testing

Run tests with `python run_tests.py`. Use `--debug` for detailed output, `--filter-files` to target specific test files, and `--print-fails` to see failing test details.

Use `--debug` to understand why something fails, do not create new test files.

The `tests/` directory contains html5lib test data files (`.dat` format) with test cases for HTML parsing conformance. Each test includes input HTML, expected errors, and expected DOM tree output in a specific format that must be matched exactly.
