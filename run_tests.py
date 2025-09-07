from turbohtml import TurboHTML
import argparse
from io import StringIO
from contextlib import redirect_stdout
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path
import signal

# Minimal Unix-friendly fix: if stdout is a pipe and the reader (e.g. `head`) closes early,
# writes would raise BrokenPipeError at interpreter shutdown. Reset SIGPIPE so the process
# exits quietly instead of emitting a traceback. Guard for non-POSIX platforms.
try:  # pragma: no cover - platform dependent
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (
    AttributeError,
    OSError,
    RuntimeError,
):  # AttributeError on non-Unix, others just in case
    pass


@dataclass
class TestCase:
    data: str
    errors: List[str]
    document: str
    fragment_context: Optional[str] = None  # Context element for fragment parsing
    script_directive: Optional[str] = None  # Either "script-on", "script-off", or None


@dataclass
class TestResult:
    passed: bool
    input_html: str
    expected_errors: List[str]
    expected_output: str
    actual_output: str
    debug_output: str = ""


def compare_outputs(expected: str, actual: str) -> bool:
    """Compare expected and actual outputs, normalizing whitespace"""

    def normalize(text: str) -> str:
        return "\n".join(line.rstrip() for line in text.strip().splitlines())

    return normalize(expected) == normalize(actual)


class TestRunner:
    def __init__(self, test_dir: Path, config: dict):
        self.test_dir = test_dir
        self.config = config
        self.results = []
        self.file_results = {}  # Track results per file

    def _natural_sort_key(self, path: Path):
        """Convert string to list of string and number chunks for natural sorting
        "z23a" -> ["z", 23, "a"]
        """

        def convert(text):
            return int(text) if text.isdigit() else text.lower()

        import re

        return [convert(c) for c in re.split("([0-9]+)", str(path))]

    def _parse_dat_file(self, path: Path) -> List[TestCase]:
        """Parse a .dat file into a list of TestCase objects"""
        content = path.read_text(encoding="utf-8")
        tests = []

        # Split content into lines for proper parsing
        lines = content.split("\n")

        current_test_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]

            # Add line to current test
            current_test_lines.append(line)

            # Check if we've reached the end of a test (next line starts a new test or is EOF)
            if i + 1 >= len(lines) or (i + 1 < len(lines) and lines[i + 1] == "#data"):
                # Process the current test if it's not empty
                if current_test_lines and any(
                    line.strip() for line in current_test_lines
                ):
                    test = self._parse_single_test(current_test_lines)
                    if test:
                        tests.append(test)

                current_test_lines = []

            i += 1

        return tests

    def _parse_single_test(self, lines: List[str]) -> Optional[TestCase]:
        """Parse a single test from a list of lines"""
        data = []
        errors = []
        document = []
        fragment_context = None
        script_directive = None
        mode = None

        for line in lines:
            if line.startswith("#"):
                directive = line[1:]
                if directive in ("script-on", "script-off"):
                    script_directive = directive
                else:
                    mode = directive
            else:
                if mode == "data":
                    data.append(line)
                elif mode == "errors":
                    errors.append(line)
                elif mode == "document":
                    document.append(line)
                elif mode == "document-fragment":
                    fragment_context = line.strip()

        if data or document:
            return TestCase(
                data="\n".join(data),
                errors=errors,
                document="\n".join(document),
                fragment_context=fragment_context,
                script_directive=script_directive,
            )

        return None

    def _should_run_test(self, filename: str, index: int, test: TestCase) -> bool:
        """Determine if a test should be run based on configuration"""
        # Skip script-dependent tests since HTML parsers don't execute JavaScript
        if test.script_directive in ("script-on", "script-off"):
            return False

        if self.config["test_specs"]:
            spec_match = False
            for spec in self.config["test_specs"]:
                if ":" not in spec:
                    continue
                spec_file, indices = spec.split(":")
                if filename == spec_file and str(index) in indices.split(","):
                    spec_match = True
                    break
            if not spec_match:
                return False

        if self.config["exclude_html"]:
            if any(exclude in test.data for exclude in self.config["exclude_html"]):
                return False

        if self.config["filter_html"]:
            if not any(include in test.data for include in self.config["filter_html"]):
                return False

        if self.config["exclude_errors"]:
            if any(
                exclude in error
                for exclude in self.config["exclude_errors"]
                for error in test.errors
            ):
                return False

        if self.config["filter_errors"]:
            if not any(
                include in error
                for include in self.config["filter_errors"]
                for error in test.errors
            ):
                return False

        return True

    def load_tests(self) -> List[tuple[Path, List[TestCase]]]:
        """Load and filter test files based on configuration"""
        test_files = self._collect_test_files()
        return [(path, self._parse_dat_file(path)) for path in test_files]

    def _collect_test_files(self) -> List[Path]:
        """Collect and filter .dat files based on configuration"""
        files = list(self.test_dir.rglob("*.dat"))

        if self.config["exclude_files"]:
            files = [
                f
                for f in files
                if not any(
                    exclude in f.name for exclude in self.config["exclude_files"]
                )
            ]

        if self.config["filter_files"]:
            files = [
                f
                for f in files
                if any(
                    filter_str in f.name for filter_str in self.config["filter_files"]
                )
            ]

        return sorted(files, key=self._natural_sort_key)

    def run(self) -> tuple[int, int, int]:
        """Run all tests and return (passed, failed, skipped) counts"""
        passed = failed = skipped = 0

        for file_path, tests in self.load_tests():
            file_passed = file_failed = file_skipped = 0
            file_test_indices = []

            for i, test in enumerate(tests):
                if not self._should_run_test(file_path.name, i, test):
                    if test.script_directive in ("script-on", "script-off"):
                        skipped += 1
                        file_skipped += 1
                        file_test_indices.append(("skip", i))
                    continue

                try:
                    result = self._run_single_test(test)
                    self.results.append(result)

                    if result.passed:
                        passed += 1
                        file_passed += 1
                        file_test_indices.append(("pass", i))
                    else:
                        failed += 1
                        file_failed += 1
                        file_test_indices.append(("fail", i))
                        self._handle_failure(file_path, i, result)
                except Exception:
                    print(f"\nError in test {file_path.name}:{i}")
                    print(f"Input HTML:\n{test.data}\n")
                    raise  # Re-raise the exception to show the full traceback

                if failed and self.config["fail_fast"]:
                    return passed, failed, skipped

            # Store file results if any tests were relevant for this file.
            # When running with explicit --test-specs we suppress files that only
            # contributed auto-skipped (script-on/off) tests to reduce noise. This
            # implements the requested behavior of not listing a "bunch of files"
            # unrelated to the targeted specs.
            if file_test_indices:
                if self.config.get("test_specs") and file_passed == 0 and file_failed == 0:
                    # All collected indices are skips; omit this file in spec-focused run.
                    pass
                else:
                    # Use relative path to handle duplicate filenames in different directories
                    relative_path = file_path.relative_to(self.test_dir)
                    self.file_results[str(relative_path)] = {
                        "passed": file_passed,
                        "failed": file_failed,
                        "skipped": file_skipped,
                        "total": file_passed + file_failed + file_skipped,
                        "test_indices": file_test_indices,
                    }

        return passed, failed, skipped

    def _run_single_test(self, test: TestCase) -> TestResult:
        """Run a single test and return the result.

        Verbosity levels:
          0: no per-test output (only summaries)
          1: print failing test diffs
          2: include parser debug for failing tests (debug captured for all tests for simplicity)
          3: capture parser debug for all tests (currently printed only for failures like level 2)
        """
        verbosity = self.config["verbosity"]
        capture_debug = verbosity >= 2  # capture once (fast enough) when user wants debug
        debug_output = ""
        if capture_debug:
            f = StringIO()
            with redirect_stdout(f):
                parser = TurboHTML(
                    test.data, debug=True, fragment_context=test.fragment_context
                )
                actual_tree = parser.root.to_test_format()
            debug_output = f.getvalue()
        else:
            parser = TurboHTML(test.data, fragment_context=test.fragment_context)
            actual_tree = parser.root.to_test_format()

        passed = compare_outputs(test.document, actual_tree)

        return TestResult(
            passed=passed,
            input_html=test.data,
            expected_errors=test.errors,
            expected_output=test.document,
            actual_output=actual_tree,
            debug_output=debug_output,
        )

    def _handle_failure(self, file_path: Path, test_index: int, result: TestResult):
        """Handle test failure - print report based on verbosity (>=1)."""
        if self.config["verbosity"] >= 1 and not self.config["quiet"]:
            print(f"\nTest failed in {file_path.name}:{test_index}")
            TestReporter(self.config).print_test_result(result)


class TestReporter:
    def __init__(self, config: dict):
        self.config = config
    # A "full" run means no narrowing flags were supplied. Only then do we write test-summary.txt.
    def _is_full_run(self) -> bool:
        return not (
            self.config.get("test_specs")
            or self.config.get("filter_files")
            or self.config.get("exclude_files")
            or self.config.get("exclude_errors")
            or self.config.get("filter_errors")
            or self.config.get("exclude_html")
            or self.config.get("filter_html")
        )

    def print_test_result(self, result: TestResult):
        """Print detailed test result according to verbosity.

        Verbosity >=1: print failing test diffs.
        Verbosity >=2: include debug block for failing tests (if captured).
        Verbosity >=3: reserved for potential future pass printing (currently same as 2).
        """
        verbosity = self.config["verbosity"]
        if result.passed:
            # At present we do not print passing tests even at highest verbosity to avoid log noise.
            return
        if verbosity >= 1:
            lines = [
                "FAILED:",
                f"=== INCOMING HTML ===\n{result.input_html}\n",
                f"Errors to handle when parsing: {result.expected_errors}\n",
                f"=== WHATWG HTML5 SPEC COMPLIANT TREE ===\n{result.expected_output}\n",
                f"=== CURRENT PARSER OUTPUT TREE ===\n{result.actual_output}",
            ]
            if verbosity >= 2 and result.debug_output:
                # Insert debug block before trees maybe? Keep after errors for readability.
                lines.insert(3, f"=== DEBUG PRINTS WHEN PARSING ===\n{result.debug_output.rstrip()}\n")
            print("\n".join(lines))

    def print_summary(
        self, passed: int, failed: int, skipped: int = 0, file_results: dict = None
    ):
        """Print summary and conditionally write test-summary.txt.

        We only persist the summary file when running the full unfiltered suite.
        Focused/filtered runs should not overwrite the canonical summary file.
        Quiet mode still limits stdout to the header line.
        """
        total = passed + failed
        percentage = round(passed * 100 / total) if total else 0
        header = f"Tests passed: {passed}/{total} ({percentage}%) ({skipped} skipped)"
        full_run = self._is_full_run()
        # If no file breakdown collected, just output header (and write header)
        if not file_results:
            if full_run:
                Path("test-summary.txt").write_text(header)
            # No leading newline needed; progress indicators are disabled.
            print(header)
            return
        detailed = self._generate_detailed_summary(header, file_results)
        # Persist only for full runs
        if full_run:
            Path("test-summary.txt").write_text(detailed)
        if self.config.get("quiet"):
            # Quiet: only header to stdout (no leading blank line)
            print(header)
        else:
            # Full detailed summary (no leading blank line)
            print(detailed)

    def _generate_detailed_summary(
        self, overall_summary: str, file_results: dict
    ) -> str:
        """Generate a detailed summary with per-file breakdown"""
        lines = [overall_summary, ""]

    # Sort files naturally (tests1.dat, tests2.dat, etc.)
        import re

        def natural_sort_key(filename):
            return [
                int(text) if text.isdigit() else text.lower()
                for text in re.split("([0-9]+)", filename)
            ]

        sorted_files = sorted(file_results.keys(), key=natural_sort_key)

        for filename in sorted_files:
            result = file_results[filename]

            # Calculate percentage based on runnable tests (excluding skipped)
            runnable_tests = result["passed"] + result["failed"]
            skipped_tests = result.get("skipped", 0)

            # Format: "filename: 15/16 (94%) [.....x] (2 skipped)"
            if runnable_tests > 0:
                percentage = round(result["passed"] * 100 / runnable_tests)
                status_line = (
                    f"{filename}: {result['passed']}/{runnable_tests} ({percentage}%)"
                )
            else:
                status_line = f"{filename}: 0/0 (N/A)"

            # Generate compact test pattern
            pattern = self._generate_test_pattern(result["test_indices"])
            if pattern:
                status_line += f" [{pattern}]"

            # Add skipped count if any
            if skipped_tests > 0:
                status_line += f" ({skipped_tests} skipped)"

            lines.append(status_line)

        return "\n".join(lines)

    def _generate_test_pattern(self, test_indices: list) -> str:
        """Generate a compact pattern showing pass/fail/skip for each test"""
        if not test_indices:
            return ""

        # Sort by test index to maintain order
        sorted_tests = sorted(test_indices, key=lambda x: x[1])

        # Always show the actual pattern with ., x, and s
        pattern = ""
        for status, idx in sorted_tests:
            if status == "pass":
                pattern += "."
            elif status == "fail":
                pattern += "x"
            elif status == "skip":
                pattern += "s"

        return pattern


def parse_args() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-x", "--fail-fast", action="store_true", help="Break on first test failure"
    )
    parser.add_argument(
        "--test-specs",
        type=str,
        nargs="+",
        default=None,
        help="Space-separated list of test specs in format: file:indices (e.g., test1.dat:0,1,2 test2.dat:5,6)",
    )
    parser.add_argument(
        "--filter-files",
        type=str,
        nargs="+",
        help="Only run tests from files containing any of these strings (space-separated)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity: -v show failing test diffs; -vv add parser debug for failures; -vvv capture debug for all tests (currently printed only on failures)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode: only print the header line (no per-file breakdown). For a full unfiltered run the detailed summary is still written to test-summary.txt",
    )
    parser.add_argument(
        "--exclude-errors",
        type=str,
        help="Skip tests containing any of these strings in their errors (comma-separated)",
    )
    parser.add_argument(
        "--exclude-files",
        type=str,
        help="Skip files containing any of these strings in their names (comma-separated)",
    )
    parser.add_argument(
        "--exclude-html",
        type=str,
        help="Skip tests containing any of these strings in their HTML input (comma-separated)",
    )
    parser.add_argument(
        "--filter-html",
        type=str,
        help="Only run tests containing any of these strings in their HTML input (comma-separated)",
    )
    parser.add_argument(
        "--filter-errors",
        type=str,
        help="Only run tests containing any of these strings in their errors (comma-separated)",
    )
    parser.add_argument(
        "--regressions",
        action="store_true",
        help="After a full (unfiltered) run, compare results to committed HEAD test-summary.txt and report new failures (exits 1 if regressions).",
    )
    args = parser.parse_args()

    test_specs = []
    if args.test_specs:
        for spec in args.test_specs:
            test_specs.extend(spec.split(","))

    exclude_errors = args.exclude_errors.split(",") if args.exclude_errors else None
    exclude_files = args.exclude_files.split(",") if args.exclude_files else None
    exclude_html = args.exclude_html.split(",") if args.exclude_html else None
    filter_html = args.filter_html.split(",") if args.filter_html else None
    filter_errors = args.filter_errors.split(",") if args.filter_errors else None

    return {
        "fail_fast": args.fail_fast,
        "test_specs": test_specs,
        "filter_files": args.filter_files,
        "quiet": args.quiet,
        "exclude_errors": exclude_errors,
        "exclude_files": exclude_files,
        "exclude_html": exclude_html,
        "filter_html": filter_html,
        "filter_errors": filter_errors,
        "verbosity": args.verbose,
        "regressions": args.regressions,
    }


def main():
    config = parse_args()
    test_dir = Path("../html5lib-tests/tree-construction")

    runner = TestRunner(test_dir, config)
    reporter = TestReporter(config)

    passed, failed, skipped = runner.run()
    reporter.print_summary(passed, failed, skipped, runner.file_results)

    # Integrated regression detection
    if config.get("regressions"):
        # Only meaningful for full unfiltered run
        if not reporter._is_full_run():  # reuse logic
            print("\n[regressions] Skipping: run was filtered (need full suite).")
            return
        _run_regression_check(runner, reporter)


def _run_regression_check(runner: TestRunner, reporter: TestReporter):
    """Compare current in-memory results against committed baseline test-summary.txt.

    Baseline is read via `git show HEAD:test-summary.txt`. If missing, we skip silently.
    Regression definition (per test index):
      - '.' -> 'x'
      - 's' -> 'x'
      - pattern extension where new char is 'x'
    Exit code: 1 if regressions found, else 0.
    """
    import subprocess, sys, re

    try:
        proc = subprocess.run(
            ["git", "show", "HEAD:test-summary.txt"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("\n[regressions] git not found; skipping regression analysis.")
        return
    if proc.returncode != 0 or not proc.stdout.strip():
        print("\n[regressions] No baseline test-summary.txt in HEAD; skipping.")
        return

    baseline_text = proc.stdout

    # Build current patterns mapping file -> pattern
    current_patterns = {}
    for filename, result in runner.file_results.items():
        pattern = reporter._generate_test_pattern(result["test_indices"])  # reuse
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
    specs = []
    for file in sorted(regressions):
        indices = regressions[file]
        joined = ",".join(str(i) for i in indices)
        spec = f"\n{file}:{joined}"
        specs.append(f"{file}:{joined}")
        print(f"{file} -> {file}:{joined}")
    print("\nRe-run just the regressed tests with:")
    print("python run_tests.py --test-specs " + " ".join(specs))
    # Exit with non-zero to surface in CI
    sys.exit(1)


if __name__ == "__main__":
    main()
