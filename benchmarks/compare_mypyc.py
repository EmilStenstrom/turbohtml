#!/usr/bin/env python3
"""
Benchmark comparison between pure Python and mypyc-compiled versions of JustHTML.

This script measures performance differences for:
- HTML parsing
- HTML serialization
- Entity decoding (compiled in mypyc version)
"""

import time
from pathlib import Path

# Sample HTML for testing
SIMPLE_HTML = "<html><body><p>Hello World</p></body></html>"

COMPLEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
    <meta charset="utf-8">
</head>
<body>
    <div class="container">
        <h1>Main Heading</h1>
        <p>This is a test paragraph with <strong>bold</strong> and <em>italic</em> text.</p>
        <ul>
            <li>Item 1</li>
            <li>Item 2</li>
            <li>Item 3</li>
        </ul>
        <table>
            <tr><td>Cell 1</td><td>Cell 2</td></tr>
            <tr><td>Cell 3</td><td>Cell 4</td></tr>
        </table>
    </div>
</body>
</html>
""" * 10  # Repeat to make it larger

HTML_WITH_ENTITIES = """
<html><body>
<p>&lt;&gt;&amp;&quot;&apos;</p>
<p>&nbsp;&copy;&reg;&trade;</p>
<p>&mdash;&ndash;&hellip;</p>
</body></html>
""" * 100


def check_compiled_modules():
    """Check which modules are compiled with mypyc."""
    try:
        from justhtml import serialize, entities, tokenizer

        compiled = []
        # Check if module file ends with .so (compiled) instead of .py
        if hasattr(tokenizer, '__file__') and tokenizer.__file__.endswith('.so'):
            compiled.append('tokenizer')
        if hasattr(serialize, '__file__') and serialize.__file__.endswith('.so'):
            compiled.append('serialize')
        if hasattr(entities, '__file__') and entities.__file__.endswith('.so'):
            compiled.append('entities')

        return compiled
    except ImportError:
        return []


def benchmark_parsing(html, iterations=1000):
    """Benchmark HTML parsing."""
    from justhtml import JustHTML

    start = time.perf_counter()
    for _ in range(iterations):
        _ = JustHTML(html)
    end = time.perf_counter()

    return end - start


def benchmark_serialization(html, iterations=1000):
    """Benchmark HTML serialization."""
    from justhtml import JustHTML

    doc = JustHTML(html)

    start = time.perf_counter()
    for _ in range(iterations):
        _ = doc.to_html()
    end = time.perf_counter()

    return end - start


def benchmark_entity_decoding(html, iterations=1000):
    """Benchmark HTML parsing with entity decoding."""
    from justhtml import JustHTML

    start = time.perf_counter()
    for _ in range(iterations):
        doc = JustHTML(html)
        _ = doc.to_html()
    end = time.perf_counter()

    return end - start


def run_benchmarks():
    """Run all benchmarks."""
    print("=" * 70)
    print("JustHTML mypyc Benchmark Comparison")
    print("=" * 70)

    def print_module_files():
        import importlib

        module_names = [
            "justhtml.tokenizer",
            "justhtml.treebuilder",
            "justhtml.serialize",
            "justhtml.entities",
        ]
        for name in module_names:
            try:
                mod = importlib.import_module(name)
                print(f"  {name}: {getattr(mod, '__file__', '<?>')}")
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  {name}: <import failed: {exc}>")

    compiled_modules = check_compiled_modules()
    if compiled_modules:
        print(f"\n✓ Compiled modules detected: {', '.join(compiled_modules)}")
    else:
        print("\n✗ No compiled modules detected (running pure Python)")
    print("\nModule locations:")
    print_module_files()

    print("\n" + "-" * 70)
    print("Benchmark 1: Simple HTML Parsing")
    print("-" * 70)
    time_simple = benchmark_parsing(SIMPLE_HTML, iterations=10000)
    print(f"Time: {time_simple:.4f}s for 10,000 iterations")
    print(f"Rate: {10000 / time_simple:.2f} parses/second")

    print("\n" + "-" * 70)
    print("Benchmark 2: Complex HTML Parsing")
    print("-" * 70)
    time_complex = benchmark_parsing(COMPLEX_HTML, iterations=1000)
    print(f"Time: {time_complex:.4f}s for 1,000 iterations")
    print(f"Rate: {1000 / time_complex:.2f} parses/second")

    print("\n" + "-" * 70)
    print("Benchmark 3: HTML Serialization")
    print("-" * 70)
    time_serialize = benchmark_serialization(COMPLEX_HTML, iterations=1000)
    print(f"Time: {time_serialize:.4f}s for 1,000 iterations")
    print(f"Rate: {1000 / time_serialize:.2f} serializations/second")

    print("\n" + "-" * 70)
    print("Benchmark 4: Entity Decoding")
    print("-" * 70)
    time_entities = benchmark_entity_decoding(HTML_WITH_ENTITIES, iterations=1000)
    print(f"Time: {time_entities:.4f}s for 1,000 iterations")
    print(f"Rate: {1000 / time_entities:.2f} operations/second")

    print("\n" + "=" * 70)

    return {
        'simple_parse': time_simple,
        'complex_parse': time_complex,
        'serialize': time_serialize,
        'entities': time_entities,
    }


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare performance of pure Python vs mypyc-compiled JustHTML"
    )
    parser.add_argument(
        '--mode',
        choices=['pure', 'compiled'],
        default='compiled',
        help="Which version to benchmark (default: compiled)",
    )

    args = parser.parse_args()

    if args.mode == 'pure':
        print("\n" + "=" * 70)
        print("RUNNING PURE PYTHON BENCHMARKS")
        print("=" * 70)

        # Ensure we're running pure Python version
        # Remove .so files temporarily if they exist
        import justhtml
        justhtml_path = Path(justhtml.__file__).parent
        so_files = list(justhtml_path.glob("*.so"))

        if so_files:
            print(f"\nWarning: Found {len(so_files)} compiled modules.")
            print("To run pure Python benchmarks, first build without mypyc:")
            print("  1. Remove .so files: find src -name '*.so' -delete")
            print("  2. Reinstall: uv pip install -e .")
            print("\nAborting pure benchmarks to avoid mixed results.\n")
            sys.exit(1)

        run_benchmarks()

    elif args.mode == 'compiled':
        print("\n" + "=" * 70)
        print("RUNNING MYPYC-COMPILED BENCHMARKS")
        print("=" * 70)
        print("\nTo build with mypyc:")
        print("  JUSTHTML_USE_MYPYC=1 uv pip install -e[mypyc] . --no-build-isolation")
        print()

        run_benchmarks()


if __name__ == "__main__":
    main()
