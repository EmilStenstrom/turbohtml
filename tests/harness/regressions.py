from __future__ import annotations

import re
import subprocess
import sys


def run_regression_check(runner, reporter):
    """Compare current in-memory results against committed baseline test-summary.txt.

    Baseline is read via `git show HEAD:test-summary.txt`.
    If missing, we skip silently.
    Regression definition (per test index):
      - '.' -> 'x'
      - 's' -> 'x'
      - pattern extension where new char is 'x'
    Exit code: 1 if regressions found, else 0.
    """
    baseline_file = "test-summary.txt"

    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "show", f"HEAD:{baseline_file}"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return
    if proc.returncode != 0 or not proc.stdout.strip():
        return

    baseline_text = proc.stdout

    # Build current patterns mapping file -> pattern
    current_patterns = {}
    for filename, result in runner.file_results.items():
        pattern = reporter.generate_test_pattern(result["test_indices"])
        current_patterns[filename] = pattern

    # Parse baseline lines: look for lines like 'tests1.dat: 93/112 (83%) [..x..]'
    line_re = re.compile(r"^(?P<file>[\w./-]+\.dat):.*?\[(?P<pattern>[.xs]+)\]")
    baseline_patterns = {}
    for line in baseline_text.splitlines():
        m = line_re.match(line.strip())
        if m:
            baseline_patterns[m.group("file")] = m.group("pattern")

    regressions = {}
    for file, new_pattern in current_patterns.items():
        old_pattern = baseline_patterns.get(file)
        if not old_pattern:
            # Treat new file entirely as potential regressions only where failures exist
            newly_failed = [i for i, ch in enumerate(new_pattern) if ch == "x"]
            if newly_failed:
                regressions[file] = newly_failed
            continue
        max_len = max(len(old_pattern), len(new_pattern))
        reg_indices = []
        for i in range(max_len):
            old_ch = old_pattern[i] if i < len(old_pattern) else None
            new_ch = new_pattern[i] if i < len(new_pattern) else None
            if new_ch == "x" and (old_ch in (".", "s") or old_ch is None):
                reg_indices.append(i)
        if reg_indices:
            regressions[file] = reg_indices

    print("\n=== regression analysis (HEAD vs current) ===")
    if not regressions:
        print("No new regressions detected.")
        return
    print("New failing test indices (0-based):")
    specs = []  # collected spec patterns for rerun message
    for file in sorted(regressions):
        indices = regressions[file]
        joined = ",".join(str(i) for i in indices)
        specs.append(f"{file}:{joined}")
        print(f"{file} -> {file}:{joined}")
    print("\nRe-run just the regressed tests with:")
    print("python run_tests.py --test-specs " + " ".join(specs))
    # Exit with non-zero to surface in CI
    sys.exit(1)
