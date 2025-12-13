# ruff: noqa: PERF401, S603

import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from justhtml import JustHTML, to_test_format
from justhtml.constants import VOID_ELEMENTS
from justhtml.context import FragmentContext
from justhtml.encoding import normalize_encoding_label, sniff_html_encoding
from justhtml.serialize import serialize_end_tag
from justhtml.tokenizer import Tokenizer, TokenizerOpts
from justhtml.tokens import CharacterTokens, CommentToken, Doctype, DoctypeToken, EOFToken, Tag
from justhtml.treebuilder import InsertionMode, TreeBuilder

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


class TestCase:
    """Container for a single tree-construction test case (typing removed)."""

    __slots__ = [
        "data",
        "document",
        "errors",
        "fragment_context",
        "iframe_srcdoc",
        "script_directive",
        "xml_coercion",
    ]

    def __init__(
        self,
        data,
        errors,
        document,
        fragment_context=None,
        script_directive=None,
        xml_coercion=False,
        iframe_srcdoc=False,
    ):
        self.data = data
        self.errors = errors
        self.document = document
        self.fragment_context = fragment_context
        self.script_directive = script_directive
        self.xml_coercion = xml_coercion
        self.iframe_srcdoc = iframe_srcdoc


class TestResult:
    """Result object for a single test (typing removed)."""

    __slots__ = [
        "actual_errors",
        "actual_output",
        "debug_output",
        "errors_matched",
        "expected_errors",
        "expected_output",
        "input_html",
        "passed",
    ]

    def __init__(
        self,
        passed,
        input_html,
        expected_errors,
        expected_output,
        actual_output,
        actual_errors=None,
        errors_matched=False,
        debug_output="",
    ):
        self.passed = passed
        self.input_html = input_html
        self.expected_errors = expected_errors
        self.expected_output = expected_output
        self.actual_output = actual_output
        self.actual_errors = actual_errors or []
        self.errors_matched = errors_matched
        self.debug_output = debug_output


def compare_outputs(expected, actual):
    """Compare expected and actual outputs, normalizing whitespace."""

    def normalize(text: str) -> str:
        return "\n".join(line.rstrip() for line in text.strip().splitlines())

    return normalize(expected) == normalize(actual)


class TestRunner:
    def __init__(self, test_dir, config):
        self.test_dir = test_dir
        self.config = config
        self.results = []
        self.file_results = {}  # Track results per file

    def _natural_sort_key(self, path):
        """Convert string to list of string and number chunks for natural sorting
        "z23a" -> ["z", 23, "a"].
        """

        def convert(text):
            return int(text) if text.isdigit() else text.lower()

        return [convert(c) for c in re.split("([0-9]+)", str(path))]

    def _parse_dat_file(self, path):
        """Parse a .dat file into a list of TestCase objects."""
        with path.open("r", encoding="utf-8", newline="") as f:
            content = f.read()
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
                if current_test_lines and any(line.strip() for line in current_test_lines):
                    test = self._parse_single_test(current_test_lines)
                    if test:
                        tests.append(test)

                current_test_lines = []

            i += 1

        return tests

    def _decode_escapes(self, text):
        """Decode escape sequences like \\x00, \\n, \\t in test data."""
        # Only process if there are escape sequences
        if "\\x" not in text and "\\u" not in text:
            return text
        # Use codecs to decode unicode_escape, but preserve valid UTF-8
        # Replace \\xNN with actual bytes
        result = []
        i = 0
        while i < len(text):
            if text[i : i + 2] == "\\x" and i + 3 < len(text):
                try:
                    byte_val = int(text[i + 2 : i + 4], 16)
                    result.append(chr(byte_val))
                    i += 4
                    continue
                except ValueError:
                    pass
            elif text[i : i + 2] == "\\u" and i + 5 < len(text):
                try:
                    code_point = int(text[i + 2 : i + 6], 16)
                    result.append(chr(code_point))
                    i += 6
                    continue
                except ValueError:
                    pass
            result.append(text[i])
            i += 1
        return "".join(result)

    def _parse_single_test(self, lines):
        """Parse a single test from a list of lines."""
        data = []
        errors = []
        document = []
        fragment_context = None
        script_directive = None
        xml_coercion = False
        iframe_srcdoc = False
        mode = None

        for line in lines:
            if line.startswith("#"):
                directive = line[1:]
                if directive in ("script-on", "script-off"):
                    script_directive = directive
                elif directive == "xml-coercion":
                    xml_coercion = True
                elif directive == "iframe-srcdoc":
                    iframe_srcdoc = True
                else:
                    mode = directive
            elif mode == "data":
                data.append(line)
            elif mode == "errors":
                errors.append(line)
            elif mode == "document":
                document.append(line)
            elif mode == "document-fragment":
                fragment_str = line.strip()
                # Parse "namespace tagname" format (e.g., "svg path", "math annotation-xml")
                # or plain tagname for HTML elements (e.g., "td", "table")
                if " " in fragment_str:
                    namespace, tag_name = fragment_str.split(" ", 1)
                    fragment_context = FragmentContext(tag_name, namespace)
                else:
                    fragment_context = FragmentContext(fragment_str)

        if data or document:
            raw_data = "\n".join(data)
            return TestCase(
                data=self._decode_escapes(raw_data),
                errors=errors,
                document="\n".join(document),
                fragment_context=fragment_context,
                script_directive=script_directive,
                xml_coercion=xml_coercion,
                iframe_srcdoc=iframe_srcdoc,
            )

        return None

    def _should_run_test(self, filename, index, test):
        """Determine if a test should be run based on configuration."""
        # Skip script-on tests since we don't execute JavaScript
        # We DO run script-off tests since scripting is disabled by default
        if test.script_directive == "script-on":
            return False

        if self.config["test_specs"]:
            spec_match = False
            for spec in self.config["test_specs"]:
                if ":" in spec:
                    # Format: file:indices (e.g., tests1.dat:0,1,2)
                    spec_file, indices = spec.split(":")
                    if filename == spec_file and str(index) in indices.split(","):
                        spec_match = True
                        break
                else:
                    # Just filename - match any test in that file
                    if spec in filename:
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

        if self.config["exclude_errors"] and any(
            exclude in error for exclude in self.config["exclude_errors"] for error in test.errors
        ):
            return False

        return not (
            self.config["filter_errors"]
            and not any(include in error for include in self.config["filter_errors"] for error in test.errors)
        )

    def load_tests(self):
        """Load and filter test files based on configuration."""
        test_files = self._collect_test_files()
        return [(path, self._parse_dat_file(path)) for path in test_files]

    def _collect_test_files(self):
        """Collect and filter .dat files based on configuration."""
        files = []
        for root, _, filenames in os.walk(self.test_dir, followlinks=True):
            for filename in filenames:
                if filename.endswith(".dat"):
                    files.append(Path(root) / filename)

        if self.config["exclude_files"]:
            files = [f for f in files if not any(exclude in f.name for exclude in self.config["exclude_files"])]

        return sorted(files, key=self._natural_sort_key)

    def run(self):
        """Run all tests and return (passed, failed, skipped) counts."""
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

                result = self._run_single_test(test, xml_coercion=test.xml_coercion)
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
                    key = str(relative_path)
                    # Keep suite prefixes stable in summaries. When running a focused
                    # directory (e.g. tests/html5lib-tests-tree), include that directory
                    # name as a prefix so output matches historical keys like
                    # html5lib-tests-tree/tests1.dat.
                    if self.test_dir.name != "tests":
                        key = f"{self.test_dir.name}/{key}"

                    self.file_results[key] = {
                        "passed": file_passed,
                        "failed": file_failed,
                        "skipped": file_skipped,
                        "total": file_passed + file_failed + file_skipped,
                        "test_indices": file_test_indices,
                    }

        return passed, failed, skipped

    def _run_single_test(self, test, xml_coercion=False):
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
        opts = TokenizerOpts(xml_coercion=xml_coercion)
        if capture_debug:
            f = StringIO()
            with redirect_stdout(f):
                parser = JustHTML(
                    test.data,
                    debug=True,
                    fragment_context=test.fragment_context,
                    tokenizer_opts=opts,
                    iframe_srcdoc=test.iframe_srcdoc,
                    collect_errors=True,
                )
                actual_tree = to_test_format(parser.root)
            debug_output = f.getvalue()
        else:
            parser = JustHTML(
                test.data,
                fragment_context=test.fragment_context,
                tokenizer_opts=opts,
                iframe_srcdoc=test.iframe_srcdoc,
                collect_errors=True,
            )
            actual_tree = to_test_format(parser.root)

        tree_passed = compare_outputs(test.document, actual_tree)

        # Extract just error codes for comparison (ignore positions)
        actual_codes = [e.code for e in parser.errors]
        expected_codes = self._extract_error_codes(test.errors)
        errors_matched = actual_codes == expected_codes

        # Format actual errors for display
        actual_error_strs = [f"({e.line},{e.column}): {e.code}" for e in parser.errors]

        # When --check-errors is set, test only passes if tree AND error codes match
        if self.config.get("check_errors"):
            passed = tree_passed and errors_matched
        else:
            passed = tree_passed

        return TestResult(
            passed=passed,
            input_html=test.data,
            expected_errors=test.errors,
            expected_output=test.document,
            actual_output=actual_tree,
            actual_errors=actual_error_strs,
            errors_matched=errors_matched,
            debug_output=debug_output,
        )

    def _extract_error_codes(self, error_lines):
        """Extract just error codes from test error lines like '(1,3): expected-doctype-but-got-start-tag'."""
        codes = []
        for raw_line in error_lines:
            line = raw_line.strip()
            if not line:
                continue
            # Skip malformed entries that start with # or |
            if line.startswith(("#", "|")):
                continue
            # Format: "(line,col): error-code" or "(line:col) error-code"
            if ": " in line:
                code = line.split(": ", 1)[1]
            elif ") " in line:
                code = line.split(") ", 1)[1]
            else:
                code = line
            codes.append(code)
        return codes

    def _handle_failure(self, file_path, test_index, result):
        """Handle test failure - print report based on verbosity (>=1)."""
        if self.config["verbosity"] >= 1 and not self.config["quiet"]:
            TestReporter(self.config).print_test_result(result)


class TestReporter:
    def __init__(self, config):
        self.config = config

    # A "full" run means no narrowing flags were supplied. Only then do we write test-summary.txt.
    def is_full_run(self):
        return not (
            self.config.get("test_specs")
            or self.config.get("exclude_files")
            or self.config.get("exclude_errors")
            or self.config.get("filter_errors")
            or self.config.get("exclude_html")
            or self.config.get("filter_html")
            or self.config.get("check_errors")
        )

    def print_test_result(self, result):
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
            ]
            # Show error diff if --check-errors and errors don't match
            if self.config.get("check_errors") and not result.errors_matched:
                expected_str = "\n".join(result.expected_errors) if result.expected_errors else "(none)"
                actual_str = "\n".join(result.actual_errors) if result.actual_errors else "(none)"
                lines.append(f"=== EXPECTED ERRORS ===\n{expected_str}\n")
                lines.append(f"=== ACTUAL ERRORS ===\n{actual_str}\n")
            else:
                lines.append(f"Errors to handle when parsing: {result.expected_errors}\n")
            lines.append(f"=== WHATWG HTML5 SPEC COMPLIANT TREE ===\n{result.expected_output}\n")
            lines.append(f"=== CURRENT PARSER OUTPUT TREE ===\n{result.actual_output}")
            if verbosity >= 2 and result.debug_output:
                # Insert debug block before trees maybe? Keep after errors for readability.
                lines.insert(3, f"=== DEBUG PRINTS WHEN PARSING ===\n{result.debug_output.rstrip()}\n")
            print("\n".join(lines))

    def print_summary(self, passed, failed, skipped=0, file_results=None):
        """Print summary and conditionally write test-summary.txt.

        We only persist the summary file when running the full unfiltered suite.
        Focused/filtered runs should not overwrite the canonical summary file.
        Quiet mode still limits stdout to the header line.
        """
        total = passed + failed
        percentage = math.floor(passed * 1000 / total) / 10 if total else 0
        result = "FAILED" if failed else "PASSED"
        header = f"{result}: {passed}/{total} passed ({percentage}%)"
        if skipped:
            header += f", {skipped} skipped"

        full_run = self.is_full_run()

        # Summary file
        summary_file = "test-summary.txt"

        # If no file breakdown collected, just output header (and write header)
        if not file_results:
            if full_run:
                Path(summary_file).write_text(header + "\n")
            # No leading newline needed; progress indicators are disabled.
            return
        detailed = self._generate_detailed_summary(header, file_results)
        # Persist only for full runs
        if full_run:
            Path(summary_file).write_text(detailed + "\n")
        if self.config.get("quiet"):
            # Quiet: only header to stdout (no leading blank line)
            print(header)
        else:
            # Full detailed summary (no leading blank line)
            print(detailed)

    def _generate_detailed_summary(self, overall_summary, file_results):
        """Generate a detailed summary with per-file breakdown."""
        lines = []

        # Sort files naturally (tests1.dat, tests2.dat, etc.)

        def natural_sort_key(filename):
            return [int(text) if text.isdigit() else text.lower() for text in re.split("([0-9]+)", filename)]

        sorted_files = sorted(file_results.keys(), key=natural_sort_key)

        for filename in sorted_files:
            result = file_results[filename]

            # Calculate percentage based on runnable tests (excluding skipped)
            runnable_tests = result["passed"] + result["failed"]
            skipped_tests = result.get("skipped", 0)

            # Format: "filename: 15/16 (94%) [.....x] (2 skipped)"
            if runnable_tests > 0:
                percentage = round(result["passed"] * 100 / runnable_tests)
                status_line = f"{filename}: {result['passed']}/{runnable_tests} ({percentage}%)"
            else:
                status_line = f"{filename}: 0/0 (N/A)"

            # Generate compact test pattern
            pattern = self.generate_test_pattern(result["test_indices"])
            if pattern:
                status_line += f" [{pattern}]"

            # Add skipped count if any
            if skipped_tests > 0:
                status_line += f" ({skipped_tests} skipped)"

            lines.append(status_line)

        # Overall summary comes at the end
        lines.extend(["", overall_summary])

        return "\n".join(lines)

    def generate_test_pattern(self, test_indices):
        """Generate a compact pattern showing pass/fail/skip for each test."""
        if not test_indices:
            return ""

        # Sort by test index to maintain order
        sorted_tests = sorted(test_indices, key=lambda x: x[1])

        # Always show the actual pattern with ., x, and s
        pattern = ""
        for status, _idx in sorted_tests:
            if status == "pass":
                pattern += "."
            elif status == "fail":
                pattern += "x"
            elif status == "skip":
                pattern += "s"

        return pattern


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-x",
        "--fail-fast",
        action="store_true",
        help="Break on first test failure",
    )
    parser.add_argument(
        "--test-specs",
        type=str,
        nargs="+",
        default=None,
        help="Space-separated list of test specs in format: file:indices (e.g., test1.dat:0,1,2 test2.dat:5,6)",
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
    parser.add_argument(
        "--check-errors",
        action="store_true",
        help="Fail tests if error codes and positions don't match expected values.",
    )
    args = parser.parse_args()

    # Preserve each provided spec exactly so patterns like 'tests1.dat:1,2,3' remain intact.
    # Keeping the raw spec strings allows _should_run_test to parse the comma-separated index
    # list correctly.
    test_specs = list(args.test_specs or [])

    exclude_errors = args.exclude_errors.split(",") if args.exclude_errors else None
    exclude_files = args.exclude_files.split(",") if args.exclude_files else None
    exclude_html = args.exclude_html.split(",") if args.exclude_html else None
    filter_html = args.filter_html.split(",") if args.filter_html else None
    filter_errors = args.filter_errors.split(",") if args.filter_errors else None

    return {
        "fail_fast": args.fail_fast,
        "test_specs": test_specs,
        "quiet": args.quiet,
        "exclude_errors": exclude_errors,
        "exclude_files": exclude_files,
        "exclude_html": exclude_html,
        "filter_html": filter_html,
        "filter_errors": filter_errors,
        "verbosity": args.verbose,
        "regressions": args.regressions,
        "check_errors": args.check_errors,
    }


# ---------------- Python unittest runner ----------------


def _run_unit_tests(config):
    """Discover and run Python unittest files in tests/ directory."""
    test_dir = Path("tests")
    test_specs = config.get("test_specs", [])
    quiet = config.get("quiet", False)
    verbosity = config.get("verbosity", 0)

    # Find all test_*.py files
    test_files = sorted(test_dir.glob("test_*.py"))

    if not test_files:
        return 0, 0, {}

    # Filter by test_specs if provided
    if test_specs:
        filtered_files = []
        for tf in test_files:
            for spec in test_specs:
                spec_file = spec.split(":")[0] if ":" in spec else spec
                if spec_file in tf.name or tf.name in spec_file:
                    filtered_files.append(tf)
                    break
        test_files = filtered_files

    if not test_files:
        return 0, 0, {}

    total_passed = 0
    total_failed = 0
    file_results = {}

    for test_file in test_files:
        # Load tests from file
        loader = unittest.TestLoader()
        suite = loader.discover(str(test_dir), pattern=test_file.name)

        # Run tests
        stream = StringIO() if quiet or verbosity < 1 else sys.stdout
        runner = unittest.TextTestRunner(stream=stream, verbosity=0 if quiet else verbosity)
        result = runner.run(suite)

        file_passed = result.testsRun - len(result.failures) - len(result.errors)
        file_failed = len(result.failures) + len(result.errors)

        total_passed += file_passed
        total_failed += file_failed

        # Build test indices for pattern display
        test_indices = []
        test_count = result.testsRun

        for i in range(test_count):
            # We can't easily map index to test name, so just use pass/fail counts
            if i < file_passed:
                test_indices.append(("pass", i))
            else:
                test_indices.append(("fail", i))

        file_results[test_file.name] = {
            "passed": file_passed,
            "failed": file_failed,
            "skipped": 0,
            "total": result.testsRun,
            "test_indices": test_indices,
        }

        # Print failures if verbose
        if verbosity >= 1 and not quiet and (result.failures or result.errors):
            for test, traceback in result.failures + result.errors:
                print(f"\nFAILED: {test}")
                print(traceback)

    return total_passed, total_failed, file_results


def main():
    config = parse_args()
    test_dir = Path("tests")

    # Check that html5lib-tests symlinks exist
    tree_tests = test_dir / "html5lib-tests-tree"
    tokenizer_tests = test_dir / "html5lib-tests-tokenizer"
    serializer_tests = test_dir / "html5lib-tests-serializer"
    encoding_tests = test_dir / "html5lib-tests-encoding"
    missing = []
    if not tree_tests.exists():
        missing.append(str(tree_tests))
    if not tokenizer_tests.exists():
        missing.append(str(tokenizer_tests))
    if not serializer_tests.exists():
        missing.append(str(serializer_tests))
    if not encoding_tests.exists():
        missing.append(str(encoding_tests))
    if len(missing) > 0:
        print("ERROR: html5lib-tests not found. Please create symlinks:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print("\nTo set up, clone html5lib-tests and create symlinks:", file=sys.stderr)
        print("  git clone https://github.com/html5lib/html5lib-tests.git ../html5lib-tests", file=sys.stderr)
        print("  ln -s ../../html5lib-tests/tree-construction tests/html5lib-tests-tree", file=sys.stderr)
        print("  ln -s ../../html5lib-tests/tokenizer tests/html5lib-tests-tokenizer", file=sys.stderr)
        print("  ln -s ../../html5lib-tests/serializer tests/html5lib-tests-serializer", file=sys.stderr)
        print("  ln -s ../../html5lib-tests/encoding tests/html5lib-tests-encoding", file=sys.stderr)
        sys.exit(1)

    runner = TestRunner(tree_tests, config)
    reporter = TestReporter(config)

    tree_passed, tree_failed, skipped = runner.run()

    # Run JustHTML-specific tree-construction tests (custom .dat fixtures).
    # These live outside the upstream html5lib-tests checkout.
    justhtml_tree_tests = test_dir / "justhtml-tests"
    justhtml_runner = TestRunner(justhtml_tree_tests, config)
    justhtml_tree_passed, justhtml_tree_failed, justhtml_tree_skipped = justhtml_runner.run()

    # Merge justhtml-tests results into the main runner for reporting and regression checks.
    for filename, result in justhtml_runner.file_results.items():
        runner.file_results[filename] = result

    tok_passed, tok_total, tok_file_results = _run_tokenizer_tests(config)

    ser_passed, ser_total, ser_skipped, ser_file_results = _run_serializer_tests(config)

    enc_passed, enc_total, enc_skipped, enc_file_results = _run_encoding_tests(config)

    unit_passed, unit_failed, unit_file_results = _run_unit_tests(config)

    total_passed = tree_passed + justhtml_tree_passed + tok_passed + ser_passed + enc_passed + unit_passed
    total_failed = (
        tree_failed
        + justhtml_tree_failed
        + (tok_total - tok_passed)
        + (ser_total - ser_passed - ser_skipped)
        + (enc_total - enc_passed - enc_skipped)
        + unit_failed
    )

    # Combine file results to show tokenizer files alongside tree tests
    combined_results = dict(runner.file_results)
    combined_results.update(tok_file_results)
    combined_results.update(ser_file_results)
    combined_results.update(enc_file_results)
    combined_results.update(unit_file_results)

    reporter.print_summary(
        total_passed,
        total_failed,
        skipped + justhtml_tree_skipped + ser_skipped + enc_skipped,
        combined_results,
    )

    if total_failed:
        sys.exit(1)

    # Integrated regression detection
    if config.get("regressions"):
        # Only meaningful for full unfiltered run
        if not reporter.is_full_run():
            return
        _run_regression_check(runner, reporter)


# ---------------- Tokenizer test runner (html5lib tokenizer JSON) ----------------


def _serializer_attr_list_to_dict(attrs):
    if isinstance(attrs, dict):
        return attrs
    if not attrs:
        return {}
    out = {}
    for a in attrs:
        # html5lib-tests serializer fixtures use entries like:
        # {"namespace": null, "name": "lang", "value": "en"}
        name = a.get("name")
        value = a.get("value")
        out[name] = value
    return out


def _escape_text_for_serializer_tests(text):
    # Keep this aligned with justhtml.serialize._escape_text, but avoid importing a private.
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr_value_for_serializer_tests(value, quote_char, escape_lt_in_attrs):
    if value is None:
        return ""
    value = str(value)
    value = value.replace("&", "&amp;")
    if escape_lt_in_attrs:
        value = value.replace("<", "&lt;")
    if quote_char == '"':
        return value.replace('"', "&quot;")
    return value.replace("'", "&#39;")


def _choose_attr_quote_for_serializer_tests(value, forced_quote_char=None):
    if forced_quote_char in {'"', "'"}:
        return forced_quote_char
    if value is None:
        return '"'
    value = str(value)
    if '"' in value and "'" not in value:
        return "'"
    return '"'


def _can_unquote_attr_value_for_serializer_tests(value):
    if value is None:
        return False
    value = str(value)
    for ch in value:
        if ch == ">":
            return False
        if ch in {'"', "'", "="}:
            return False
        if ch in {" ", "\t", "\n", "\f", "\r"}:
            return False
    return True


def _serializer_minimize_attr_value(name, value, minimize_boolean_attributes):
    if not minimize_boolean_attributes:
        return False
    if value is None or value == "":
        return True
    return str(value).lower() == str(name).lower()


def _serialize_start_tag_for_serializer_tests(name, attrs, options, is_void):
    options = options or {}
    attrs = attrs or {}

    quote_attr_values = bool(options.get("quote_attr_values"))
    minimize_boolean_attributes = options.get("minimize_boolean_attributes", True)
    use_trailing_solidus = bool(options.get("use_trailing_solidus"))
    escape_lt_in_attrs = bool(options.get("escape_lt_in_attrs"))
    forced_quote = options.get("quote_char")

    parts = ["<", name]

    if attrs:
        for key in sorted(attrs.keys()):
            value = attrs[key]

            if _serializer_minimize_attr_value(key, value, minimize_boolean_attributes):
                parts.extend([" ", key])
                continue

            if value is None:
                # Non-minimized None becomes an explicit empty value.
                parts.extend([" ", key, '=""'])
                continue

            value = str(value)
            if value == "":
                if minimize_boolean_attributes:
                    parts.extend([" ", key])
                else:
                    parts.extend([" ", key, '=""'])
                continue

            if not quote_attr_values and _can_unquote_attr_value_for_serializer_tests(value):
                escaped = value.replace("&", "&amp;")
                if escape_lt_in_attrs:
                    escaped = escaped.replace("<", "&lt;")
                parts.extend([" ", key, "=", escaped])
            else:
                quote = _choose_attr_quote_for_serializer_tests(value, forced_quote)
                escaped = _escape_attr_value_for_serializer_tests(value, quote, escape_lt_in_attrs)
                parts.extend([" ", key, "=", quote, escaped, quote])

    if use_trailing_solidus and is_void:
        parts.append(" />")
    else:
        parts.append(">")

    return "".join(parts)


def _strip_whitespace_for_serializer_tests(text):
    # Maps \t\r\n\f to spaces, then collapses runs of spaces to a single space.
    if not text:
        return ""
    out = []
    last_space = False
    for ch in text:
        mapped = " " if ch in {"\t", "\r", "\n", "\f"} else ch
        if mapped == " ":
            if last_space:
                continue
            last_space = True
            out.append(" ")
        else:
            last_space = False
            out.append(mapped)
    return "".join(out)


def _update_meta_content_type_charset(content, encoding):
    if content is None:
        return None
    if not encoding:
        return content
    s = str(content)
    lower = s.lower()
    idx = lower.find("charset=")
    if idx == -1:
        return s
    start = idx + len("charset=")
    end = start
    while end < len(s) and s[end] not in {";", " ", "\t", "\r", "\n", "\f"}:
        end += 1
    return s[:start] + str(encoding) + s[end:]


def _apply_inject_meta_charset(tokens, encoding):
    # Serializer fixtures treat this as serializing the contents of <head>, without the <head> wrapper.
    if not encoding:
        return []

    saw_head = False
    in_head = False
    content_tokens = []
    for t in tokens:
        kind = t[0]
        if not in_head:
            if kind == "StartTag" and t[2] == "head":
                saw_head = True
                in_head = True
            continue
        if kind == "EndTag" and t[2] == "head":
            break
        content_tokens.append(t)

    if not saw_head:
        content_tokens = list(tokens)

    processed = []
    found_charset = False
    for t in content_tokens:
        if t[0] == "EmptyTag" and t[1] == "meta":
            attrs = _serializer_attr_list_to_dict(t[2] if len(t) > 2 else {})
            if "charset" in attrs:
                attrs["charset"] = encoding
                found_charset = True
            elif str(attrs.get("http-equiv", "")).lower() == "content-type" and "content" in attrs:
                attrs["content"] = _update_meta_content_type_charset(attrs.get("content"), encoding)
                found_charset = True
            processed.append(["EmptyTag", "meta", attrs])
        else:
            processed.append(t)

    if not found_charset:
        processed.insert(0, ["EmptyTag", "meta", {"charset": encoding}])

    return processed


def _serializer_tok_name(tok):
    if tok is None:
        return None
    kind = tok[0]
    if kind == "StartTag":
        return tok[2]
    if kind == "EndTag":
        return tok[2]
    if kind == "EmptyTag":
        return tok[1]
    return None


def _serializer_tok_is_space_chars(tok):
    return tok is not None and tok[0] == "Characters" and tok[1].startswith(" ")


def _serializer_should_omit_start_tag(name, attrs, prev_tok, next_tok):
    if attrs:
        return False

    if name == "html":
        # Omit unless followed by a comment or leading space.
        if next_tok is None:
            return True
        if next_tok[0] == "Comment" or _serializer_tok_is_space_chars(next_tok):
            return False
        if next_tok[0] == "Characters" and next_tok[1] == "":
            return False
        return True

    if name == "head":
        if next_tok is None:
            return True
        # Keep when followed by comment or characters (including space).
        if next_tok[0] in {"Comment", "Characters"}:
            return False
        # Empty head: omit both <head> and </head>
        if next_tok[0] == "EndTag" and _serializer_tok_name(next_tok) == "head":
            return True
        # Otherwise omit when followed by tags/end tags.
        if next_tok[0] in {"StartTag", "EmptyTag", "EndTag"}:
            return True
        return False

    if name == "body":
        # Omit unless followed by a comment or leading space.
        if next_tok is None:
            return True
        if next_tok[0] == "Comment" or _serializer_tok_is_space_chars(next_tok):
            return False
        return True

    if name == "colgroup":
        # Omit the first colgroup start tag in a table when it has a col child.
        if prev_tok is not None and prev_tok[0] == "StartTag" and _serializer_tok_name(prev_tok) == "table":
            if (
                next_tok is not None
                and next_tok[0] in {"StartTag", "EmptyTag"}
                and _serializer_tok_name(next_tok) == "col"
            ):
                return True
        return False

    if name == "tbody":
        # Omit the first tbody start tag in a table when it has a tr child.
        if prev_tok is not None and prev_tok[0] == "StartTag" and _serializer_tok_name(prev_tok) == "table":
            if next_tok is not None and next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) == "tr":
                return True
        return False

    return False


def _serializer_should_omit_end_tag(name, next_tok):
    if name in {"html", "head", "body", "colgroup"}:
        if next_tok is None:
            return True
        if next_tok[0] == "Comment" or _serializer_tok_is_space_chars(next_tok):
            return False
        if next_tok[0] in {"StartTag", "EmptyTag", "EndTag"}:
            return True
        if next_tok[0] == "Characters":
            return not next_tok[1].startswith(" ")
        return True

    if name == "li":
        if next_tok is None:
            return True
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) == "li":
            return True
        if next_tok[0] == "EndTag":
            return True
        return False

    if name == "dt":
        if next_tok is None:
            return False
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) in {"dt", "dd"}:
            return True
        return False

    if name == "dd":
        if next_tok is None:
            return True
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) in {"dd", "dt"}:
            return True
        if next_tok[0] == "EndTag":
            return True
        return False

    if name == "p":
        if next_tok is None:
            return True
        if next_tok[0] == "EndTag":
            return True
        if next_tok[0] in {"StartTag", "EmptyTag"}:
            next_name = _serializer_tok_name(next_tok)
            if next_name in {
                "address",
                "article",
                "aside",
                "blockquote",
                "datagrid",
                "dialog",
                "dir",
                "div",
                "dl",
                "fieldset",
                "footer",
                "form",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "header",
                "hr",
                "menu",
                "nav",
                "ol",
                "p",
                "pre",
                "section",
                "table",
                "ul",
            }:
                return True
        return False

    if name == "optgroup":
        if next_tok is None:
            return True
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) == "optgroup":
            return True
        if next_tok[0] == "EndTag":
            return True
        return False

    if name == "option":
        if next_tok is None:
            return True
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) in {"option", "optgroup"}:
            return True
        if next_tok[0] == "EndTag":
            return True
        return False

    if name == "tbody":
        if next_tok is None:
            return True
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) in {"tbody", "tfoot"}:
            return True
        if next_tok[0] == "EndTag":
            return True
        return False

    if name == "tfoot":
        if next_tok is None:
            return True
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) == "tbody":
            return True
        if next_tok[0] == "EndTag":
            return True
        return False

    if name == "thead":
        if next_tok is not None and next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) in {"tbody", "tfoot"}:
            return True
        return False

    if name == "tr":
        if next_tok is None:
            return True
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) == "tr":
            return True
        if next_tok[0] == "EndTag":
            return True
        return False

    if name in {"td", "th"}:
        if next_tok is None:
            return True
        if next_tok[0] == "StartTag" and _serializer_tok_name(next_tok) in {"td", "th"}:
            return True
        if next_tok[0] == "EndTag":
            return True
        return False

    return False


def _serialize_serializer_token_stream(tokens, options=None):
    parts = []
    rawtext = None
    options = options or {}

    if options.get("inject_meta_charset"):
        encoding = options.get("encoding")
        if not encoding:
            return ""
        tokens = _apply_inject_meta_charset(tokens, encoding)

    open_elements = []
    strip_ws = bool(options.get("strip_whitespace"))
    escape_rcdata = bool(options.get("escape_rcdata"))
    ws_preserve = {"pre", "textarea", "script", "style"}

    for i, t in enumerate(tokens):
        prev_tok = tokens[i - 1] if i else None
        next_tok = tokens[i + 1] if i + 1 < len(tokens) else None

        kind = t[0]
        if kind == "StartTag":
            name = t[2]
            attrs = _serializer_attr_list_to_dict(t[3] if len(t) > 3 else {})

            open_elements.append(name)

            if _serializer_should_omit_start_tag(name, attrs, prev_tok, next_tok):
                continue

            parts.append(_serialize_start_tag_for_serializer_tests(name, attrs, options, name in VOID_ELEMENTS))
            if name in {"script", "style"} and not escape_rcdata:
                rawtext = name
        elif kind == "EndTag":
            name = t[2]

            if open_elements:
                if open_elements[-1] == name:
                    open_elements.pop()
                else:
                    # Best-effort sync when optional tags are omitted.
                    for j in range(len(open_elements) - 1, -1, -1):
                        if open_elements[j] == name:
                            del open_elements[j:]
                            break

            if _serializer_should_omit_end_tag(name, next_tok):
                continue

            parts.append(serialize_end_tag(name))
            if rawtext == name:
                rawtext = None
        elif kind == "EmptyTag":
            # html5lib serializer tests use EmptyTag to mean "emit start tag for a void element" in HTML mode.
            name = t[1]
            attrs = t[2] if len(t) > 2 else {}
            parts.append(_serialize_start_tag_for_serializer_tests(name, attrs, options, True))
        elif kind == "Characters":
            if rawtext is not None:
                parts.append(t[1])
            else:
                text = t[1]
                if strip_ws and not (set(open_elements) & ws_preserve):
                    text = _strip_whitespace_for_serializer_tests(text)
                parts.append(_escape_text_for_serializer_tests(text))
        elif kind == "Comment":
            parts.append(f"<!--{t[1]}-->")
        elif kind == "Doctype":
            # ["Doctype", name, publicId?, systemId?]
            name = t[1] if len(t) > 1 else ""
            public_id = t[2] if len(t) > 2 else None
            system_id = t[3] if len(t) > 3 else None

            if public_id is None and system_id is None:
                parts.append(f"<!DOCTYPE {name}>")
            else:
                has_public = public_id not in {None, ""}
                has_system = system_id not in {None, ""}
                if has_public:
                    if has_system:
                        parts.append(f'<!DOCTYPE {name} PUBLIC "{public_id}" "{system_id}">')
                    else:
                        parts.append(f'<!DOCTYPE {name} PUBLIC "{public_id}">')
                elif has_system:
                    parts.append(f'<!DOCTYPE {name} SYSTEM "{system_id}">')
                else:
                    parts.append(f"<!DOCTYPE {name}>")
        else:
            return None
    return "".join(parts)


def _run_serializer_tests(config):
    root = Path("tests")
    fixture_dir = root / "html5lib-tests-serializer"
    if not fixture_dir.exists():
        return 0, 0, 0, {}
    test_files = sorted(fixture_dir.glob("*.test"))
    if not test_files:
        print("No serializer tests found.")
        return 0, 0, 0, {}

    verbosity = config.get("verbosity", 0)
    quiet = config.get("quiet", False)
    test_specs = config.get("test_specs", [])

    total = 0
    passed = 0
    skipped = 0
    file_results = {}

    for path in test_files:
        filename = path.name
        rel_name = str(path.relative_to(Path("tests")))

        # Filter by test_specs if provided
        if test_specs:
            should_run_file = False
            specific_indices = None
            for spec in test_specs:
                if ":" in spec:
                    spec_file, indices_str = spec.split(":", 1)
                    if spec_file in rel_name or spec_file in filename:
                        should_run_file = True
                        specific_indices = set(int(i) for i in indices_str.split(","))
                        break
                else:
                    if spec in rel_name or spec in filename:
                        should_run_file = True
                        break
            if not should_run_file:
                continue
        else:
            specific_indices = None

        data = json.loads(path.read_text())
        tests = data.get("tests", [])
        file_passed = 0
        file_failed = 0
        file_skipped = 0
        test_indices = []

        supported_option_keys = {
            "encoding",
            "inject_meta_charset",
            "strip_whitespace",
            "quote_attr_values",
            "use_trailing_solidus",
            "minimize_boolean_attributes",
            "quote_char",
            "escape_lt_in_attrs",
            "escape_rcdata",
        }

        for idx, test in enumerate(tests):
            if specific_indices is not None and idx not in specific_indices:
                continue

            total += 1

            options = test.get("options") or {}
            if not isinstance(options, dict):
                skipped += 1
                file_skipped += 1
                test_indices.append(("skip", idx))
                continue

            if any(k not in supported_option_keys for k in options.keys()):
                skipped += 1
                file_skipped += 1
                test_indices.append(("skip", idx))
                continue

            actual = _serialize_serializer_token_stream(test.get("input", []), options)
            if actual is None:
                skipped += 1
                file_skipped += 1
                test_indices.append(("skip", idx))
                continue
            expected_list = test.get("expected", [])
            ok = actual in expected_list

            if ok:
                passed += 1
                file_passed += 1
                test_indices.append(("pass", idx))
            else:
                file_failed += 1
                test_indices.append(("fail", idx))
                if verbosity >= 1 and not quiet:
                    desc = test.get("description", "")
                    print(f"\nSERIALIZER FAIL: {filename}:{idx} {desc}")
                    print("EXPECTED one of:")
                    for e in expected_list:
                        print(repr(e))
                    print("ACTUAL:")
                    print(repr(actual))

        file_results[rel_name] = {
            "passed": file_passed,
            "failed": file_failed,
            "skipped": file_skipped,
            "total": file_passed + file_failed + file_skipped,
            "test_indices": test_indices,
        }

    return passed, total, skipped, file_results


def _parse_encoding_dat_file(path):
    data = path.read_bytes()
    tests = []
    mode = None
    current_data = []
    current_encoding = None

    def flush():
        nonlocal current_data, current_encoding
        if current_data is None or current_encoding is None:
            return
        tests.append((b"".join(current_data), current_encoding))
        current_data = []
        current_encoding = None

    for line in data.splitlines(keepends=True):
        stripped = line.rstrip(b"\r\n")
        if stripped == b"#data":
            flush()
            mode = "data"
            continue
        if stripped == b"#encoding":
            mode = "encoding"
            continue

        if mode == "data":
            current_data.append(line)
        elif mode == "encoding":
            # First non-empty line after #encoding is the expected label.
            if current_encoding is None and stripped:
                current_encoding = stripped.decode("ascii", "ignore")
        else:
            continue

    flush()
    return tests


def _run_encoding_tests(config):
    root = Path("tests")
    fixture_dir = root / "html5lib-tests-encoding"
    if not fixture_dir.exists():
        return 0, 0, 0, {}

    test_files = sorted([p for p in fixture_dir.rglob("*.dat") if p.is_file()])
    if not test_files:
        print("No encoding tests found.")
        return 0, 0, 0, {}

    verbosity = config.get("verbosity", 0)
    quiet = config.get("quiet", False)
    test_specs = config.get("test_specs", [])

    total = 0
    passed = 0
    skipped = 0
    file_results = {}

    for path in test_files:
        filename = path.name
        rel_name = str(path.relative_to(root))

        if test_specs:
            should_run_file = False
            specific_indices = None
            for spec in test_specs:
                if ":" in spec:
                    spec_file, indices_str = spec.split(":", 1)
                    if spec_file in rel_name or spec_file in filename:
                        should_run_file = True
                        specific_indices = set(int(i) for i in indices_str.split(",") if i)
                        break
                else:
                    if spec in rel_name or spec in filename:
                        should_run_file = True
                        break
            if not should_run_file:
                continue
        else:
            specific_indices = None

        tests = _parse_encoding_dat_file(path)
        file_passed = 0
        file_failed = 0
        file_skipped = 0
        test_indices = []

        is_scripted = "scripted" in path.parts

        for idx, (data, expected_label) in enumerate(tests):
            if specific_indices is not None and idx not in specific_indices:
                continue

            total += 1

            expected = normalize_encoding_label(expected_label)
            if expected is None:
                skipped += 1
                file_skipped += 1
                test_indices.append(("skip", idx))
                continue

            if is_scripted:
                skipped += 1
                file_skipped += 1
                test_indices.append(("skip", idx))
                continue

            sniffed = sniff_html_encoding(data)
            actual = sniffed[0] if isinstance(sniffed, tuple) else sniffed

            if actual == expected:
                passed += 1
                file_passed += 1
                test_indices.append(("pass", idx))
            else:
                file_failed += 1
                test_indices.append(("fail", idx))
                if verbosity >= 1 and not quiet:
                    print(f"\nENCODING FAIL: {rel_name}:{idx}")
                    print(f"EXPECTED: {expected!r} (raw: {expected_label!r})")
                    print(f"ACTUAL:   {actual!r}")

        file_results[rel_name] = {
            "passed": file_passed,
            "failed": file_failed,
            "skipped": file_skipped,
            "total": file_passed + file_failed + file_skipped,
            "test_indices": test_indices,
        }

    return passed, total, skipped, file_results


class RecordingTreeBuilder(TreeBuilder):
    """TreeBuilder sink that also records emitted tokens."""

    __slots__ = ("tokens",)

    def __init__(self):
        super().__init__()
        self.tokens = []

    def process_token(self, token):
        # Copy token because tokenizer might reuse it
        if isinstance(token, Tag):
            # Create a new Tag instance with the same data
            # Note: attrs is already a new dict per token in tokenizer, so shallow copy of Tag is enough
            # But to be safe and independent:
            token_copy = Tag(token.kind, token.name, token.attrs, token.self_closing)
            self.tokens.append(token_copy)
        else:
            # Other tokens (CharacterTokens, CommentToken, DoctypeToken) might also be reused?
            # CharacterTokens is created new in _flush_text (currently).
            # CommentToken is reused in tokenizer?
            # Let's check tokenizer.
            # For now, assume we need to copy everything if we want to be safe.
            # But Tag is the main one.
            # Let's use a generic copy if possible, or manual.
            if isinstance(token, CharacterTokens):
                self.tokens.append(CharacterTokens(token.data))
            elif isinstance(token, CommentToken):
                self.tokens.append(CommentToken(token.data))
            elif isinstance(token, DoctypeToken):
                d = token.doctype
                self.tokens.append(DoctypeToken(Doctype(d.name, d.public_id, d.system_id, d.force_quirks)))
            elif isinstance(token, EOFToken):
                self.tokens.append(EOFToken())
            else:
                self.tokens.append(token)

        return super().process_token(token)

    def process_characters(self, data):
        if self.mode == InsertionMode.IN_BODY:
            self.tokens.append(CharacterTokens(data))
        return super().process_characters(data)


def _unescape_unicode(text: str) -> str:
    return re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), text)


def _map_initial_state(name):
    mapping = {
        "Data state": (Tokenizer.DATA, None),
        "PLAINTEXT state": (Tokenizer.PLAINTEXT, None),
        "RCDATA state": (Tokenizer.RCDATA, None),
        "RAWTEXT state": (Tokenizer.RAWTEXT, None),
        "Script data state": (Tokenizer.RAWTEXT, "script"),
        "CDATA section state": (Tokenizer.CDATA_SECTION, None),
    }
    return mapping.get(name)


def _token_to_list(token):
    if isinstance(token, DoctypeToken):
        d = token.doctype
        # Test format uses "correctness" which is !force_quirks
        return ["DOCTYPE", d.name, d.public_id, d.system_id, not d.force_quirks]
    if isinstance(token, CommentToken):
        return ["Comment", token.data]
    if isinstance(token, CharacterTokens):
        return ["Character", token.data]
    if isinstance(token, Tag):
        if token.kind == Tag.START:
            attrs = token.attrs or {}
            arr = ["StartTag", token.name, attrs]
            if token.self_closing:
                arr.append(True)
            return arr
        return ["EndTag", token.name]
    if isinstance(token, EOFToken):
        return None
    return ["Unknown"]


def _collapse_characters(tokens):
    collapsed = []
    for t in tokens:
        if t and t[0] == "Character" and collapsed and collapsed[-1][0] == "Character":
            collapsed[-1][1] += t[1]
        else:
            collapsed.append(t)
    return collapsed


def _run_tokenizer_tests(config):
    root = Path("tests")
    # Use */*.test to match files in subdirectories, including symlinked ones (which ** skips)
    test_files = [p for p in root.glob("*/*.test") if p.parent.name != "html5lib-tests-serializer"]

    if not test_files:
        print("No tokenizer tests found.")
        return 0, 0, {}

    total = 0
    passed = 0
    file_results = {}
    verbosity = config.get("verbosity", 0)
    quiet = config.get("quiet", False)
    test_specs = config.get("test_specs", [])

    for path in sorted(test_files, key=lambda p: p.name):
        filename = path.name
        rel_path = str(path.relative_to(Path("tests")))

        # Parse test_specs to determine which tests to run
        should_run_file = False
        specific_indices = None

        if test_specs:
            for spec in test_specs:
                if ":" in spec:
                    # Format: file:indices (e.g., test2.test:5,10)
                    spec_file, indices_str = spec.split(":", 1)
                    if spec_file in rel_path or spec_file in filename:
                        should_run_file = True
                        specific_indices = set(int(i) for i in indices_str.split(","))
                        break
                else:
                    # Just filename - match any test in that file
                    if spec in rel_path or spec in filename:
                        should_run_file = True
                        break

            if not should_run_file:
                continue
        else:
            should_run_file = True

        data = json.loads(path.read_text())
        key = "tests" if "tests" in data else "xmlViolationTests"
        is_xml_violation = key == "xmlViolationTests"
        tests = data.get(key, [])
        file_passed = 0
        file_failed = 0
        test_indices = []

        for idx, test in enumerate(tests):
            # Skip if specific indices requested and this isn't one of them
            if specific_indices is not None and idx not in specific_indices:
                continue

            total += 1
            ok = _run_single_tokenizer_test(test, xml_coercion=is_xml_violation)
            status = "pass" if ok else "fail"
            test_indices.append((status, idx))
            if ok:
                passed += 1
                file_passed += 1
            else:
                file_failed += 1
                # Print verbose output for failures
                if verbosity >= 1 and not quiet:
                    _print_tokenizer_failure(test, path.name, idx, xml_coercion=is_xml_violation)
        rel_name = str(path.relative_to(Path("tests")))
        file_results[rel_name] = {
            "passed": file_passed,
            "failed": file_failed,
            "skipped": 0,
            "total": file_passed + file_failed,
            "test_indices": test_indices,
        }
    return passed, total, file_results


def _print_tokenizer_failure(test, filename, test_index, xml_coercion=False):
    """Print detailed tokenizer test failure output."""
    input_text = test["input"]
    expected_tokens = test["output"]

    if test.get("doubleEscaped"):
        input_text = _unescape_unicode(input_text)

        def recurse(val):
            if isinstance(val, str):
                return _unescape_unicode(val)
            if isinstance(val, list):
                return [recurse(v) for v in val]
            if isinstance(val, dict):
                return {k: recurse(v) for k, v in val.items()}
            return val

        expected_tokens = recurse(expected_tokens)

    initial_states = test.get("initialStates") or ["Data state"]
    last_start_tag = test.get("lastStartTag")

    print(f"\nFAILED: {filename} test #{test_index}")
    print(f"Description: {test.get('description', 'N/A')}")
    print(f"Input: {input_text!r}")
    print(f"Initial states: {initial_states}")
    if last_start_tag:
        print(f"Last start tag: {last_start_tag}")

    print("\n=== EXPECTED TOKENS ===")
    for tok in expected_tokens:
        print(f"  {tok}")

    # Run the test and show actual output
    for state_name in initial_states:
        mapped = _map_initial_state(state_name)
        if not mapped:
            print(f"\n!!! State {state_name} not mapped !!!")
            continue
        initial_state, raw_tag = mapped
        if last_start_tag:
            raw_tag = last_start_tag
        sink = RecordingTreeBuilder()
        discard_bom = test.get("discardBom", False)
        opts = TokenizerOpts(
            initial_state=initial_state,
            initial_rawtext_tag=raw_tag,
            discard_bom=discard_bom,
            xml_coercion=xml_coercion,
        )
        tok = Tokenizer(sink, opts)
        tok.last_start_tag_name = last_start_tag
        tok.run(input_text)
        actual = [r for t in sink.tokens if (r := _token_to_list(t)) is not None]
        actual = _collapse_characters(actual)

        print(f"\n=== ACTUAL TOKENS (state: {state_name}) ===")
        for t in actual:
            print(f"  {t}")

        if actual != expected_tokens:
            print("\n=== DIFFERENCES ===")
            max_len = max(len(expected_tokens), len(actual))
            for i in range(max_len):
                exp = expected_tokens[i] if i < len(expected_tokens) else "<missing>"
                act = actual[i] if i < len(actual) else "<missing>"
                if exp != act:
                    print(f"  Token {i}: expected {exp}, got {act}")


def _run_single_tokenizer_test(test, xml_coercion=False):
    input_text = test["input"]
    expected_tokens = test["output"]
    if test.get("doubleEscaped"):
        input_text = _unescape_unicode(input_text)

        def recurse(val):
            if isinstance(val, str):
                return _unescape_unicode(val)
            if isinstance(val, list):
                return [recurse(v) for v in val]
            if isinstance(val, dict):
                return {k: recurse(v) for k, v in val.items()}
            return val

        expected_tokens = recurse(expected_tokens)

    initial_states = test.get("initialStates") or ["Data state"]
    last_start_tag = test.get("lastStartTag")

    for state_name in initial_states:
        mapped = _map_initial_state(state_name)
        if not mapped:
            return False
        initial_state, raw_tag = mapped
        # If last_start_tag is provided, use it as the tag to match in RAWTEXT/RCDATA states
        if last_start_tag:
            raw_tag = last_start_tag
        sink = RecordingTreeBuilder()
        discard_bom = test.get("discardBom", False)
        opts = TokenizerOpts(
            initial_state=initial_state,
            initial_rawtext_tag=raw_tag,
            discard_bom=discard_bom,
            xml_coercion=xml_coercion,
        )
        tok = Tokenizer(sink, opts)
        tok.last_start_tag_name = last_start_tag
        tok.run(input_text)
        actual = [r for t in sink.tokens if (r := _token_to_list(t)) is not None]
        actual = _collapse_characters(actual)
        if actual != expected_tokens:
            return False
    return True


def _run_regression_check(runner, reporter):
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
        proc = subprocess.run(
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


if __name__ == "__main__":
    main()
