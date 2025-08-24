"""Analyze regressions in test-summary.txt.

This script shells out to `git diff --unified=0 -- test-summary.txt` and parses
changes to individual per-file summary lines of the form:

    tests1.dat: 93/112 (83%) [..x.x.s..]

It detects newly introduced failures (a '.' that became an 'x' at the same
pattern position, or an appended 'x' at the end) and prints, for each file
with regressions, a test-spec compatible string of the form:

    tests1.dat:5,23,40

Indices are zero-based test indices matching the enumeration used when running
`run_tests.py` (pattern position corresponds to test index). Skipped tests ('s')
and previously failing tests ('x' staying 'x') are ignored. Only NEW failures
are reported.

Finally, if any regressions are found, it prints a convenience command line
you can paste directly to re-run just those tests:

    python run_tests.py --test-specs tests1.dat:5,23 tests2.dat:10

If no regressions are detected, it prints a friendly message and exits 0.

You can also pipe in a diff (e.g. from CI) via stdin; if stdin is not a TTY
and contains data, that content is parsed instead of invoking git.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

LINE_RE = re.compile(
    r"^[+-]"  # diff line marker
    r"(?P<file>[\w./-]+\.dat):\s*"  # filename ending in .dat (may contain path segments)
    r"(?P<passed>\d+)/(?:\d+)"  # passed / runnable (we don't need the runnable number separately)
    r"[^\[]*"  # any chars up to the pattern
    r"\[(?P<pattern>[.xs]+)\]"  # the compact pattern
)


@dataclass
class FileChange:
    old_pattern: Optional[str] = None
    new_pattern: Optional[str] = None

    def regressions(self) -> List[int]:
        """Return list of indices that regressed ('.' -> 'x' or newly appended 'x')."""
        if self.old_pattern is None or self.new_pattern is None:
            return []  # Can't assess without both sides (added/removed file lines not treated here)

        old = self.old_pattern
        new = self.new_pattern
        max_len = max(len(old), len(new))
        reg: List[int] = []
        for i in range(max_len):
            o = old[i] if i < len(old) else None
            n = new[i] if i < len(new) else None
            if n == 'x' and o == '.':
                reg.append(i)
            elif n == 'x' and o is None:
                # Newly extended pattern containing a failure at new tail
                reg.append(i)
            # We do NOT treat '.' -> 's' or 's' -> 'x' (latter is legitimate regression) separately:
            elif n == 'x' and o == 's':  # previously skipped now failing
                reg.append(i)
        return reg


def read_diff_text() -> str:
    """Return diff text either from stdin (if piped) or by invoking git diff."""
    if not sys.stdin.isatty():  # Data may be piped in
        data = sys.stdin.read()
        if data.strip():
            return data
    # Fallback: invoke git
    try:
        result = subprocess.run(
            ["git", "diff", "--unified=0", "--", "test-summary.txt"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        print("Error: git not found; supply diff via stdin.", file=sys.stderr)
        sys.exit(2)
    if result.returncode not in (0, 1):  # git diff exits 1 when differences present
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout


def parse_diff(diff_text: str) -> Dict[str, FileChange]:
    """Parse diff text, returning mapping of filename -> FileChange."""
    changes: Dict[str, FileChange] = {}
    for line in diff_text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        file = m.group('file')
        pattern = m.group('pattern')
        change = changes.setdefault(file, FileChange())
        if line.startswith('-'):
            change.old_pattern = pattern
        elif line.startswith('+'):
            change.new_pattern = pattern
    return changes


def main() -> int:
    diff_text = read_diff_text()
    if not diff_text.strip():
        print("=== test-summary regression analysis ===")
        print("No diff for test-summary.txt (file unchanged).")
        return 0

    changes = parse_diff(diff_text)
    regressions: Dict[str, List[int]] = {}
    for file, change in changes.items():
        reg = change.regressions()
        if reg:
            regressions[file] = reg

    if not regressions:
        print("=== test-summary regression analysis ===")
        print("No new test regressions detected.")
        return 0

    print("=== test-summary regression analysis ===")
    print("Listing new failing test indices (0-based) per file: file -> file:i,j,k")
    print("")

    specs: List[str] = []
    for file in sorted(regressions):
        indices = regressions[file]
        indices_str = ",".join(str(i) for i in indices)
        spec = f"{file}:{indices_str}"
        specs.append(spec)
        print(f"{file} -> {spec}")

    print("\nRe-run just the regressed tests with:")
    joined = " ".join(specs)
    print(f"python run_tests.py --test-specs {joined}")
    return 1  # Non-zero so CI can flag regressions (adjust if undesired)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
