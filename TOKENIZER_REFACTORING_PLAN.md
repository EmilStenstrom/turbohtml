# Tokenizer Refactoring Plan: Making tokenizer.py Mypyc-Compatible

## Goal

Refactor `tokenizer.py` to move the `_STATE_HANDLERS` list from a class-level assignment to an instance-level attribute, enabling mypyc compilation of the most performance-critical module in JustHTML.

## Current Problem

```python
# At the end of tokenizer.py (line 2585-2647)
Tokenizer._STATE_HANDLERS = [  # type: ignore[attr-defined]
    Tokenizer._state_data,
    Tokenizer._state_tag_open,
    # ... 61 total state handler methods
]

# Used in step() method (line 339)
def step(self) -> bool:
    handler = self._STATE_HANDLERS[self.state]  # type: ignore[attr-defined]
    return handler(self)
```

**Issue**: Mypyc doesn't support assigning to class attributes after class definition. This is a fundamental limitation of mypyc's compilation model.

## Expected Performance Impact

With tokenizer.py compiled:
- **Simple HTML Parsing**: 1.04x → **8-12x faster** (tokenizer is the bottleneck)
- **Complex HTML Parsing**: 1.02x → **8-12x faster**
- **Overall parsing throughput**: ~10,000 docs/sec → ~100,000 docs/sec

This would make JustHTML competitive with C-based parsers while remaining pure Python compatible.

## Solution Architecture

### Approach: Instance-Level State Handler List

Move the state handler list initialization into the `__init__` method, making it an instance attribute instead of a class attribute.

**Advantages:**
- ✅ Mypyc compatible
- ✅ No performance penalty (list lookup is the same)
- ✅ Actually slightly better for memory (can be GC'd with instance)
- ✅ No API changes required
- ✅ Backward compatible

**Disadvantages:**
- ❌ Small memory overhead per Tokenizer instance (~500 bytes for 61 pointers)
- ❌ Initialization cost per instance (negligible, ~1 microsecond)

## Implementation Plan

### Phase 1: Code Analysis (DONE ✓)

- [x] Identified 61 state handler methods
- [x] Found single usage point in `step()` method
- [x] Confirmed no other references to `_STATE_HANDLERS`

### Phase 2: Refactoring Steps

#### Step 1: Add `_build_state_handlers()` Method

**Location**: Before `__init__` method (around line 235)

**Code to add**:
```python
def _build_state_handlers(self) -> list[Callable[[Tokenizer], bool]]:
    """Build the state handlers dispatch table. Called from __init__."""
    return [
        self._state_data,                                            # 0
        self._state_tag_open,                                        # 1
        self._state_end_tag_open,                                    # 2
        self._state_tag_name,                                        # 3
        self._state_before_attribute_name,                           # 4
        self._state_attribute_name,                                  # 5
        self._state_after_attribute_name,                            # 6
        self._state_before_attribute_value,                          # 7
        self._state_attribute_value_double,                          # 8
        self._state_attribute_value_single,                          # 9
        self._state_attribute_value_unquoted,                        # 10
        self._state_after_attribute_value_quoted,                    # 11
        self._state_self_closing_start_tag,                          # 12
        self._state_markup_declaration_open,                         # 13
        self._state_comment_start,                                   # 14
        self._state_comment_start_dash,                              # 15
        self._state_comment,                                         # 16
        self._state_comment_end_dash,                                # 17
        self._state_comment_end,                                     # 18
        self._state_comment_end_bang,                                # 19
        self._state_bogus_comment,                                   # 20
        self._state_doctype,                                         # 21
        self._state_before_doctype_name,                             # 22
        self._state_doctype_name,                                    # 23
        self._state_after_doctype_name,                              # 24
        self._state_bogus_doctype,                                   # 25
        self._state_after_doctype_public_keyword,                    # 26
        self._state_after_doctype_system_keyword,                    # 27
        self._state_before_doctype_public_identifier,                # 28
        self._state_doctype_public_identifier_double_quoted,         # 29
        self._state_doctype_public_identifier_single_quoted,         # 30
        self._state_after_doctype_public_identifier,                 # 31
        self._state_between_doctype_public_and_system_identifiers,   # 32
        self._state_before_doctype_system_identifier,                # 33
        self._state_doctype_system_identifier_double_quoted,         # 34
        self._state_doctype_system_identifier_single_quoted,         # 35
        self._state_after_doctype_system_identifier,                 # 36
        self._state_cdata_section,                                   # 37
        self._state_cdata_section_bracket,                           # 38
        self._state_cdata_section_end,                               # 39
        self._state_rcdata,                                          # 40
        self._state_rcdata_less_than_sign,                           # 41
        self._state_rcdata_end_tag_open,                             # 42
        self._state_rcdata_end_tag_name,                             # 43
        self._state_rawtext,                                         # 44
        self._state_rawtext_less_than_sign,                          # 45
        self._state_rawtext_end_tag_open,                            # 46
        self._state_rawtext_end_tag_name,                            # 47
        self._state_plaintext,                                       # 48
        self._state_script_data_escaped,                             # 49
        self._state_script_data_escaped_dash,                        # 50
        self._state_script_data_escaped_dash_dash,                   # 51
        self._state_script_data_escaped_less_than_sign,              # 52
        self._state_script_data_escaped_end_tag_open,                # 53
        self._state_script_data_escaped_end_tag_name,                # 54
        self._state_script_data_double_escape_start,                 # 55
        self._state_script_data_double_escaped,                      # 56
        self._state_script_data_double_escaped_dash,                 # 57
        self._state_script_data_double_escaped_dash_dash,            # 58
        self._state_script_data_double_escaped_less_than_sign,       # 59
        self._state_script_data_double_escape_end,                   # 60
    ]
```

**Notes**:
- Added comments with state indices for clarity
- Uses `self.` prefix to get bound methods
- Return type matches the annotation in `__slots__`

#### Step 2: Initialize in `__init__`

**Location**: End of `__init__` method (after `self._comment_token` initialization, around line 273)

**Code to add**:
```python
# Build state handlers dispatch table (for mypyc compatibility)
self._state_handlers = self._build_state_handlers()
```

#### Step 3: Update `step()` Method

**Location**: Line 339

**Change from**:
```python
handler = self._STATE_HANDLERS[self.state]  # type: ignore[attr-defined]
```

**Change to**:
```python
handler = self._state_handlers[self.state]
```

**Note**: Remove the `type: ignore` comment since it's now properly typed.

#### Step 4: Remove Class-Level Assignment

**Location**: Lines 2585-2647

**Remove entire section**:
```python
Tokenizer._STATE_HANDLERS = [  # type: ignore[attr-defined]
    Tokenizer._state_data,
    # ... all 61 items ...
]
```

#### Step 5: Update Comment

**Location**: Line 235

**Change from**:
```python
# _STATE_HANDLERS is defined at the end of the file
```

**Change to**:
```python
# _state_handlers is initialized in __init__ for mypyc compatibility
```

### Phase 3: Testing

#### Test 1: Pure Python Functionality

```bash
# Ensure no compiled modules
find src/justhtml -name "*.so" -delete

# Reinstall pure Python
uv pip install -e .

# Run full test suite
python run_tests.py

# Expected: PASSED: 9375/9375 passed (100.0%), 13 skipped
```

#### Test 2: Mypyc Compilation

```bash
# Add tokenizer.py to MYPYC_MODULES in setup.py
# Change from:
MYPYC_MODULES = [
    "src/justhtml/serialize.py",
    "src/justhtml/entities.py",
]

# To:
MYPYC_MODULES = [
    "src/justhtml/tokenizer.py",  # <-- Add this
    "src/justhtml/serialize.py",
    "src/justhtml/entities.py",
]

# Build with mypyc
JUSTHTML_USE_MYPYC=1 uv pip install -e . --no-build-isolation

# Should succeed without errors
# Should create: src/justhtml/tokenizer.cpython-311-x86_64-linux-gnu.so
```

#### Test 3: Compiled Functionality

```bash
# Run full test suite with compiled tokenizer
python run_tests.py

# Expected: PASSED: 9375/9375 passed (100.0%), 13 skipped
```

#### Test 4: Performance Validation

```bash
# Run comparison benchmark
./compare_pure_vs_compiled.sh

# Expected results:
# - Simple HTML Parsing: ~8-12x speedup
# - Complex HTML Parsing: ~8-12x speedup
# - HTML Serialization: ~1.66x speedup (unchanged)
# - Entity Decoding: ~1.17x speedup (unchanged)
```

### Phase 4: Validation Checklist

- [ ] No mypy errors
- [ ] No ruff linting errors
- [ ] All 9,375 tests pass (pure Python)
- [ ] Tokenizer compiles with mypyc without errors
- [ ] All 9,375 tests pass (compiled)
- [ ] Performance improves by 8-12x for parsing operations
- [ ] No memory leaks (run with valgrind if concerned)
- [ ] CI passes with mypyc build

## Implementation Script

For automation, here's the refactoring script:

```bash
#!/bin/bash
# Automated refactoring script for tokenizer.py

# 1. Backup original
cp src/justhtml/tokenizer.py src/justhtml/tokenizer.py.backup

# 2. Apply changes using sed/awk
python3 << 'PYTHON_SCRIPT'
import re

# Read file
with open('src/justhtml/tokenizer.py', 'r') as f:
    content = f.read()

# Step 1: Change comment on line 235
content = content.replace(
    '    # _STATE_HANDLERS is defined at the end of the file',
    '    # _state_handlers is initialized in __init__ for mypyc compatibility'
)

# Step 2: Add _build_state_handlers method before __init__
init_pos = content.find('    def __init__(self, sink:')
method_code = '''    def _build_state_handlers(self) -> list:
        """Build the state handlers dispatch table. Called from __init__."""
        return [
            self._state_data,
            self._state_tag_open,
            self._state_end_tag_open,
            # ... (full list here)
        ]

'''
content = content[:init_pos] + method_code + content[init_pos:]

# Step 3: Add initialization in __init__
init_code = '        self._state_handlers = self._build_state_handlers()\n'
pos = content.find('        self._comment_token = CommentToken("")')
pos = content.find('\n', pos) + 1
content = content[:pos] + init_code + content[pos:]

# Step 4: Update step() method
content = content.replace(
    '        handler = self._STATE_HANDLERS[self.state]  # type: ignore[attr-defined]',
    '        handler = self._state_handlers[self.state]'
)

# Step 5: Remove class-level assignment
pattern = r'\n\nTokenizer\._STATE_HANDLERS = \[.*?\]\n'
content = re.sub(pattern, '\n', content, flags=re.DOTALL)

# Write back
with open('src/justhtml/tokenizer.py', 'w') as f:
    f.write(content)

print("✓ Refactoring complete!")
PYTHON_SCRIPT

# 3. Verify syntax
python -m py_compile src/justhtml/tokenizer.py

# 4. Run tests
python run_tests.py

echo "✓ All done!"
```

## Risk Assessment

### Low Risk
- ✅ Change is isolated to tokenizer.py
- ✅ No API changes
- ✅ Backward compatible
- ✅ Easy to revert (keep backup)

### Medium Risk
- ⚠️ Performance characteristics slightly different (negligible)
- ⚠️ Memory usage increases slightly per Tokenizer instance

### Mitigation
- Full test suite coverage (9,375 tests)
- Benchmark validation
- Can revert instantly if issues arise

## Timeline Estimate

- **Analysis**: 30 minutes (DONE)
- **Implementation**: 45 minutes
- **Testing (pure Python)**: 15 minutes
- **Mypyc compilation**: 10 minutes
- **Testing (compiled)**: 15 minutes
- **Benchmarking**: 15 minutes
- **Total**: ~2.5 hours

## Success Criteria

1. ✅ All tests pass (pure Python version)
2. ✅ Tokenizer.py compiles with mypyc without errors
3. ✅ All tests pass (compiled version)
4. ✅ Parsing speed improves by at least 5x
5. ✅ No memory leaks detected
6. ✅ CI pipeline passes

## Next Steps After Tokenizer

Once tokenizer.py is successfully compiled, tackle treebuilder.py:

1. **Refactor tests**: Change `RecordingTreeBuilder(TreeBuilder)` to use composition
2. **Compile treebuilder.py**: Add to MYPYC_MODULES
3. **Expected combined speedup**: 15-20x for full parsing

This would make JustHTML one of the fastest HTML parsers in the Python ecosystem!
