from turbohtml import TurboHTML
import argparse
from io import StringIO
from contextlib import redirect_stdout
from dataclasses import dataclass
from typing import List
from pathlib import Path

@dataclass
class TestCase:
    data: str
    errors: List[str]
    document: str
    
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
        return '\n'.join(line.rstrip() for line in text.strip().splitlines())
    return normalize(expected) == normalize(actual)

class TestRunner:
    def __init__(self, test_dir: Path, config: dict):
        self.test_dir = test_dir
        self.config = config
        self.results = []
    
    def _natural_sort_key(self, path: Path):
        """Convert string to list of string and number chunks for natural sorting
        "z23a" -> ["z", 23, "a"]
        """
        def convert(text):
            return int(text) if text.isdigit() else text.lower()
            
        import re
        return [convert(c) for c in re.split('([0-9]+)', str(path))]

    def _parse_dat_file(self, path: Path) -> List[TestCase]:
        """Parse a .dat file into a list of TestCase objects"""
        content = path.read_text(encoding='utf-8')
        tests = []
        for test in content.split('\n\n'):
            if not test.strip():
                continue
                
            lines = test.split('\n')
            data = []
            errors = []
            document = []
            mode = None

            for line in lines:
                if line.startswith('#'):
                    mode = line[1:]
                else:
                    if mode == 'data':
                        data.append(line)
                    elif mode == 'errors':
                        errors.append(line)
                    elif mode == 'document':
                        document.append(line)

            if data or document:
                tests.append(TestCase(
                    data='\n'.join(data),
                    errors=errors,
                    document='\n'.join(document)
                ))

        return tests

    def _should_run_test(self, filename: str, index: int, test: TestCase) -> bool:
        """Determine if a test should be run based on configuration"""
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
            if any(exclude in error for exclude in self.config["exclude_errors"] 
                  for error in test.errors):
                return False

        if self.config["filter_errors"]:
            if not any(include in error for include in self.config["filter_errors"] 
                      for error in test.errors):
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
            files = [f for f in files if not any(exclude in f.name 
                    for exclude in self.config["exclude_files"])]
            
        if self.config["filter_files"]:
            files = [f for f in files if self.config["filter_files"] in f.name]
            
        return sorted(files, key=self._natural_sort_key)
    
    def run(self) -> tuple[int, int]:
        """Run all tests and return (passed, failed) counts"""
        passed = failed = 0
        
        for file_path, tests in self.load_tests():
            for i, test in enumerate(tests):
                if not self._should_run_test(file_path.name, i, test):
                    continue
                
                try:
                    result = self._run_single_test(test)
                    self.results.append(result)
                    
                    if result.passed:
                        passed += 1
                        self._print_progress(".")
                    else:
                        failed += 1
                        self._handle_failure(file_path, i, result)
                except Exception as e:
                    print(f"\nError in test {file_path.name}:{i}")
                    print(f"Input HTML:\n{test.data}\n")
                    raise  # Re-raise the exception to show the full traceback
                    
                if failed and self.config["fail_fast"]:
                    return passed, failed
                    
        return passed, failed
    
    def _run_single_test(self, test: TestCase) -> TestResult:
        """Run a single test and return the result"""
        debug_output = ""
        
        # Capture debug output if debug mode is enabled
        if self.config["debug"]:
            f = StringIO()
            with redirect_stdout(f):
                parser = TurboHTML(test.data, debug=True)
                actual_tree = parser.root.to_test_format()
            debug_output = f.getvalue()
        else:
            parser = TurboHTML(test.data)
            actual_tree = parser.root.to_test_format()
            
        # Compare the actual output with expected
        passed = compare_outputs(test.document, actual_tree)
        
        return TestResult(
            passed=passed,
            input_html=test.data,
            expected_errors=test.errors,
            expected_output=test.document,
            actual_output=actual_tree,
            debug_output=debug_output
        )
        
    def _print_progress(self, indicator: str):
        """Print progress indicator unless in quiet mode"""
        if not self.config["quiet"]:
            print(indicator, end='', flush=True)
            
    def _handle_failure(self, file_path: Path, test_index: int, result: TestResult):
        """Handle test failure - print indicator and report if configured"""
        self._print_progress("x")
        if self.config["print_fails"]:
            print(f"\nTest failed in {file_path.name}:{test_index}")
            TestReporter(self.config).print_test_result(result)

class TestReporter:
    def __init__(self, config: dict):
        self.config = config
        
    def print_test_result(self, result: TestResult):
        """Print detailed test result based on configuration"""
        if not result.passed or self.config["print_fails"]:
            lines = [
                f'{"PASSED" if result.passed else "FAILED"}:',
                f'=== INCOMING HTML ===\n{result.input_html}\n',
                f'Errors to handle when parsing: {result.expected_errors}\n',
            ]
            
            if result.debug_output:
                lines.extend([
                    f'=== DEBUG PRINTS WHEN PARSING ===',
                    f'{result.debug_output.rstrip()}\n'  # Remove trailing whitespace and add linebreak
                ])
                
            lines.extend([
                f'=== WHATWG HTML5 SPEC COMPLIANT TREE ===\n{result.expected_output}\n',
                f'=== CURRENT PARSER OUTPUT TREE ===\n{result.actual_output}'
            ])
            
            print('\n'.join(lines))
    
    def print_summary(self, passed: int, failed: int):
        """Print test summary and optionally save to file"""
        total = passed + failed
        summary = f'Tests passed: {passed}/{total}'
        
        if not self.config["fail_fast"]:
            percentage = round(passed*100/total) if total else 0
            summary += f' ({percentage}%)'
            
            # Only save to file if no filters are applied (running all tests)
            if self._is_running_all_tests():
                Path('test-summary.txt').write_text(summary)
            
        print(f'\n{summary}')

    def _is_running_all_tests(self) -> bool:
        """Check if we're running all tests (no filters applied)"""
        return not any([
            self.config.get("test_specs"),
            self.config.get("filter_files"),
            self.config.get("exclude_errors"),
            self.config.get("exclude_files"),
            self.config.get("exclude_html"),
            self.config.get("filter_html"),
            self.config.get("filter_errors")
        ])

def parse_args() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument('-x', '--fail-fast', action='store_true',
                       help='Break on first test failure')
    parser.add_argument('--test-specs', type=str, nargs='+', default=None,
                       help='Space-separated list of test specs in format: file:indices (e.g., test1.dat:0,1,2 test2.dat:5,6)')
    parser.add_argument('-d', '--debug', action='store_true',
                       help='Print debug information')
    parser.add_argument('--filter-files', type=str,
                       help='Only run tests from files containing this string')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Suppress progress indicators (dots and x\'s)')
    parser.add_argument('--exclude-errors', type=str,
                       help='Skip tests containing any of these strings in their errors (comma-separated)')
    parser.add_argument('--exclude-files', type=str,
                       help='Skip files containing any of these strings in their names (comma-separated)')
    parser.add_argument('--exclude-html', type=str,
                       help='Skip tests containing any of these strings in their HTML input (comma-separated)')
    parser.add_argument('--filter-html', type=str,
                       help='Only run tests containing any of these strings in their HTML input (comma-separated)')
    parser.add_argument('--print-fails', action='store_true',
                       help='Print details for all failing tests')
    parser.add_argument('--filter-errors', type=str,
                       help='Only run tests containing any of these strings in their errors (comma-separated)')
    args = parser.parse_args()
    
    # Split the test specs if they contain commas
    test_specs = []
    if args.test_specs:
        for spec in args.test_specs:
            test_specs.extend(spec.split(','))
    
    # Split exclude lists on commas
    exclude_errors = args.exclude_errors.split(',') if args.exclude_errors else None
    exclude_files = args.exclude_files.split(',') if args.exclude_files else None
    exclude_html = args.exclude_html.split(',') if args.exclude_html else None
    filter_html = args.filter_html.split(',') if args.filter_html else None
    filter_errors = args.filter_errors.split(',') if args.filter_errors else None
    
    return {
        'fail_fast': args.fail_fast,
        'test_specs': test_specs,
        'debug': args.debug,
        'filter_files': args.filter_files,
        'quiet': args.quiet,
        'exclude_errors': exclude_errors,
        'exclude_files': exclude_files,
        'exclude_html': exclude_html,
        'filter_html': filter_html,
        'filter_errors': filter_errors,
        'print_fails': args.print_fails
    }

def main():
    config = parse_args()
    test_dir = Path('../html5lib-tests/tree-construction')
    
    runner = TestRunner(test_dir, config)
    reporter = TestReporter(config)
    
    passed, failed = runner.run()
    reporter.print_summary(passed, failed)

if __name__ == '__main__':
    main()
