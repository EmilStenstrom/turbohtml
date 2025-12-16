"""
Build script for JustHTML with optional mypyc compilation.

Usage:
    # Pure Python build (default)
    python -m build

    # Compiled with mypyc
    JUSTHTML_USE_MYPYC=1 pip install .
"""

import os
import sys
from pathlib import Path

from setuptools import setup

# Determine if we should use mypyc
USE_MYPYC = os.environ.get("JUSTHTML_USE_MYPYC", "0") == "1"

# Core modules to compile with mypyc (performance-critical parsing code)
# Note: treebuilder_modes.py is excluded due to mixin type compatibility issues
# Note: node.py is excluded due to type incompatibility issues with class hierarchies
# Note: selector.py is excluded due to class attribute access issues
# These patterns don't work well with mypyc's type system
#
# Compiling modules for performance:
MYPYC_MODULES = [
    "src/justhtml/treebuilder.py",   # ⚡ Hot path - tests refactored to use composition
    "src/justhtml/tokenizer.py",    # ⚡ Newly mypyc-compatible thanks to Enum state machine
    "src/justhtml/serialize.py",
    "src/justhtml/entities.py",
]


def build_with_mypyc() -> list:
    """Build extension modules using mypyc."""
    try:
        from mypyc.build import mypycify
    except ImportError:
        print(
            "ERROR: mypyc is not installed. Install with: pip install mypy",
            file=sys.stderr,
        )
        print("Or install with mypyc support: pip install justhtml[mypyc]", file=sys.stderr)
        sys.exit(1)

    # Verify all modules exist
    for module_path in MYPYC_MODULES:
        if not Path(module_path).exists():
            print(f"ERROR: Module not found: {module_path}", file=sys.stderr)
            sys.exit(1)

    print("=" * 70)
    print("Building JustHTML with mypyc compilation")
    print("=" * 70)
    print(f"Compiling {len(MYPYC_MODULES)} modules:")
    for module in MYPYC_MODULES:
        print(f"  - {module}")
    print("=" * 70)

    # Configure mypyc options
    opt_level = os.environ.get("MYPYC_OPT_LEVEL", "3")
    debug_level = os.environ.get("MYPYC_DEBUG_LEVEL", "0")

    mypyc_options = {
        "opt_level": opt_level,
        "debug_level": debug_level,
        "verbose": True,
        "separate": False,  # Don't use separate extensions
        "multi_file": False,  # Single group compilation
    }

    return mypycify(MYPYC_MODULES, **mypyc_options)


if __name__ == "__main__":
    ext_modules = []

    if USE_MYPYC:
        ext_modules = build_with_mypyc()
    else:
        print("Building JustHTML in pure Python mode (no mypyc compilation)")
        print("To enable mypyc: JUSTHTML_USE_MYPYC=1 pip install .")

    setup(
        ext_modules=ext_modules,
    )
