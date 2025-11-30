# ruff: noqa: PERF401, S603

import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from justhtml import JustHTML
from justhtml.context import FragmentContext
from justhtml.tokenizer import Tokenizer, TokenizerOpts
from justhtml.tokens import CharacterTokens, CommentToken, Doctype, DoctypeToken, EOFToken, Tag
from justhtml.treebuilder import InsertionMode, TreeBuilder
from tests.test_format import node_to_test_format

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
        "actual_output",
        "debug_output",
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
        debug_output="",
    ):
        self.passed = passed
        self.input_html = input_html
        self.expected_errors = expected_errors
        self.expected_output = expected_output
        self.actual_output = actual_output
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
        # Skip script-dependent tests since HTML parsers don't execute JavaScript
        if test.script_directive in ("script-on", "script-off"):
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
                    self.file_results[str(relative_path)] = {
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
                )
                actual_tree = node_to_test_format(parser.root)
            debug_output = f.getvalue()
        else:
            parser = JustHTML(
                test.data,
                fragment_context=test.fragment_context,
                tokenizer_opts=opts,
                iframe_srcdoc=test.iframe_srcdoc,
            )
            actual_tree = node_to_test_format(parser.root)

        passed = compare_outputs(test.document, actual_tree)

        return TestResult(
            passed=passed,
            input_html=test.data,
            expected_errors=test.errors,
            expected_output=test.document,
            actual_output=actual_tree,
            debug_output=debug_output,
        )

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
                f"Errors to handle when parsing: {result.expected_errors}\n",
                f"=== WHATWG HTML5 SPEC COMPLIANT TREE ===\n{result.expected_output}\n",
                f"=== CURRENT PARSER OUTPUT TREE ===\n{result.actual_output}",
            ]
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
    }


def main():
    config = parse_args()
    test_dir = Path("tests")

    runner = TestRunner(test_dir, config)
    reporter = TestReporter(config)

    tree_passed, tree_failed, skipped = runner.run()

    tok_passed, tok_total, tok_file_results = _run_tokenizer_tests(config)

    total_passed = tree_passed + tok_passed
    total_failed = tree_failed + (tok_total - tok_passed)
    (tree_passed + tree_failed) + tok_total

    # Combine file results to show tokenizer files alongside tree tests
    combined_results = dict(runner.file_results)
    combined_results.update(tok_file_results)

    reporter.print_summary(total_passed, total_failed, skipped, combined_results)

    if total_failed:
        sys.exit(1)

    # Integrated regression detection
    if config.get("regressions"):
        # Only meaningful for full unfiltered run
        if not reporter.is_full_run():
            return
        _run_regression_check(runner, reporter)


# ---------------- Tokenizer test runner (html5lib tokenizer JSON) ----------------


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
    test_files = list(root.glob("*/*.test"))

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
