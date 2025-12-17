# Mypyc Integration for JustHTML

This document describes the mypyc integration added to JustHTML to provide C-accelerated performance while maintaining the pure Python implementation.

## Overview

Mypyc is a compiler that compiles Python modules to C extensions. This integration allows JustHTML to be built with optional C-compiled modules for improved performance, while maintaining full backward compatibility with the pure Python version.

## What's Compiled

Due to mypyc's limitations with certain Python patterns, only specific modules can be compiled:

### Currently Compiled Modules

- **`tokenizer.py`** - Tokenizer state machine (now mypyc-compatible thanks to Enum-based states)
- **`treebuilder.py`** - DOM construction logic (tests refactored to use composition)
- **`serialize.py`** - HTML serialization to string
- **`entities.py`** - HTML entity encoding/decoding

### Modules That Cannot Be Compiled

- **`treebuilder_modes.py`** - Uses mixin pattern with type annotation issues
- **`node.py`** - Type incompatibility issues with class hierarchies
- **`selector.py`** - Class attribute access pattern incompatible with mypyc

## Building

### Pure Python Build (Default)

```bash
# Standard installation - no compilation
uv pip install -e .
# or
pip install -e .
```

### Mypyc Compiled Build

```bash
# Install mypyc dependencies first
uv pip install -e ".[mypyc]"

# Build with mypyc compilation
JUSTHTML_USE_MYPYC=1 uv pip install -e . --no-build-isolation
```

Or use the helper script:

```bash
./build_mypyc.sh
```

## Testing

### Test Compiled Version

```bash
# Build with mypyc
JUSTHTML_USE_MYPYC=1 uv pip install -e . --no-build-isolation

# Run full test suite
python run_tests.py

# Should see: PASSED: 9375/9375 passed (100.0%), 13 skipped
```

### Verify Compilation

```bash
# Check for .so files
ls -lh src/justhtml/*.so

# Should show:
#   tokenizer.cpython-311-x86_64-linux-gnu.so
#   treebuilder.cpython-311-x86_64-linux-gnu.so
#   serialize.cpython-311-x86_64-linux-gnu.so
#   entities.cpython-311-x86_64-linux-gnu.so
```

## Benchmarking

### Quick Benchmark

```bash
# Build with mypyc first
JUSTHTML_USE_MYPYC=1 uv pip install -e . --no-build-isolation

# Run benchmarks
python benchmarks/compare_mypyc.py --mode compiled
```

### Full Comparison (Pure Python vs Compiled)

```bash
# Automated comparison script
./compare_pure_vs_compiled.sh

# This will:
# 1. Build and benchmark pure Python version
# 2. Build and benchmark mypyc-compiled version
# 3. Calculate and display speedup ratios
# 4. Save results to a timestamped file
```

> **Tip:** The compiled extensions are CPython-version specific. Run the script from the same interpreter that built them (e.g. `source .venv/bin/activate` to use the project's Python 3.11) or the benchmarks will silently fall back to the pure Python modules.

### Latest Benchmark (2025‑12‑17 · CPython 3.13.7)

`./compare_pure_vs_compiled.sh` (see `benchmark_results_20251217_155343.txt`) produced:

| Benchmark                | Pure Python Time | mypyc Time | Speedup |
| ------------------------ | ---------------- | ---------- | ------- |
| Simple HTML Parsing¹     | 0.3875s / 10,000 | 0.2538s    | 1.53×   |
| Complex HTML Parsing     | 2.5933s / 1,000  | 1.5411s    | 1.68×   |
| HTML Serialization       | 0.2529s / 1,000  | 0.1600s    | 1.58×   |
| Entity Decoding          | 6.3085s / 1,000  | 3.1904s    | 1.98×   |

¹Simple parsing runs 10,000 iterations; the others run 1,000 iterations.

### Expected Performance Improvements

With tokenizer, treebuilder, serialize, and entities compiled, the hot path is fully native. Typical speedups (from the latest run) are now:

- **Simple HTML Parsing**: ~1.5×
- **Complex HTML Parsing**: ~1.7×
- **HTML Serialization**: ~1.6×
- **Entity Decoding**: ~2.0×

Further gains now depend on making the remaining Python-heavy helpers (e.g., `treebuilder_modes.py`, `node.py`) mypyc-friendly.

## Continuous Integration

The CI workflow (`.github/workflows/ci.yml`) includes a `test-mypyc` job that:

1. Builds JustHTML with mypyc compilation
2. Runs the full test suite to ensure compatibility
3. Runs benchmarks to track performance
4. Tests on Python 3.11 and 3.12

## Files Added/Modified

### New Files

- `setup.py` - Build script with mypyc integration
- `build_mypyc.sh` - Helper script for building with mypyc
- `benchmarks/compare_mypyc.py` - Benchmark script for performance testing
- `compare_pure_vs_compiled.sh` - Automated comparison script
- `MYPYC_INTEGRATION.md` - This documentation

### Modified Files

- `pyproject.toml` - Added:
  - `[project.optional-dependencies.mypyc]` section
  - Changed `build-backend` to `setuptools.build_meta`
  - Added setuptools configuration
- `.github/workflows/ci.yml` - Added `test-mypyc` job

## Future Improvements

To push performance further we now need to:

1. **Make `treebuilder_modes.py` mypyc-friendly** by untangling the mixin/type-mismatch issues.
2. **Refactor `node.py`** to remove inheritance patterns that confuse mypyc.
3. **Modernize `selector.py`** so its dynamic class attribute lookups can be compiled.

Compiling these remaining modules would reduce interpreter overhead in DOM manipulation and selector matching.

## Limitations

1. **mypyc compatibility**: Not all Python patterns are supported by mypyc
2. **Platform-specific**: Compiled .so files are platform and Python version specific
3. **Build time**: Compilation adds significant time to the build process
4. **Debugging**: Compiled code is harder to debug than pure Python

## Distribution Strategy

Currently, JustHTML maintains a single package name with both pure Python and compiled versions available:

- **Pure Python wheel**: `justhtml-0.12.0-py3-none-any.whl` (universal, works everywhere)
- **Compiled wheels** (if built): Platform-specific wheels for Linux/macOS/Windows

Users can choose:
- Install pure Python: `pip install justhtml`
- Build with mypyc: `JUSTHTML_USE_MYPYC=1 pip install justhtml` (from source)

## Resources

- [Mypyc Documentation](https://mypyc.readthedocs.io/)
- [Mypyc GitHub](https://github.com/mypyc/mypyc)
- [Python Performance Tips](https://wiki.python.org/moin/PythonSpeed/PerformanceTips)
