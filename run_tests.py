from turbohtml import TurboHTML
import os
import argparse
import re


def parse_dat_file(content):
    tests = []
    for test in content.split('\n\n'):
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

        if data and document:
            tests.append({
                'data': '\n'.join(data),
                'errors': errors,
                'document': '\n'.join(document)
            })

    return tests


def compare_outputs(expected, actual):
    return expected.strip() == actual.strip()

def run_tests(test_dir, fail_fast=False, test_specs=None, verbose=False, filter_files=None):
    passed = 0
    failed = 0

    # Parse test specs into a dictionary if provided
    spec_dict = {}
    if test_specs:
        for spec in test_specs:
            filename, indices = spec.split(':')
            spec_dict[filename] = [int(i) for i in indices.split(',')]

    # Collect and naturally sort all .dat files
    all_files = []
    for root, _, files in os.walk(test_dir):
        for file in files:
            if file.endswith('.dat'):
                # Add filter check
                if filter_files and filter_files not in file:
                    continue
                if not test_specs or file in spec_dict:
                    all_files.append((root, file))
    
    # Sort files naturally using a better natural sort implementation
    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower()
                for text in re.split('([0-9]+)', s)]
    
    all_files.sort(key=lambda x: natural_sort_key(x[1]))

    # Process sorted files
    for root, file in all_files:
        file_path = os.path.join(root, file)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        tests = parse_dat_file(content)
        for i, test in enumerate(tests):
            # Skip tests not in the specified indices for this file
            if test_specs and i not in spec_dict.get(file, []):
                continue

            html_input = test['data']
            errors = test['errors']
            expected_output = test['document']

            should_print_heading = verbose or fail_fast or (test_specs and i in spec_dict.get(file, []))
            if should_print_heading:
                print(f'Test {file} #{i}: {html_input}')

            parser = TurboHTML(html_input)
            actual_output = parser.root.to_test_format()
            test_passed = compare_outputs(expected_output, actual_output)
            should_print_details = verbose or (fail_fast and not test_passed) or (test_specs and i in spec_dict.get(file, []))

            if should_print_details:
                print(f'{"PASSED" if test_passed else "FAILED"}:')
                if errors:
                    print(f"Errors: {errors}")
                print(f'Expected:\n{expected_output}')
                print(f'Actual:\n{actual_output}')
            elif not should_print_heading:
                print("x" if not test_passed else ".", end="", flush=True)

            if not test_passed:
                failed += 1
                if fail_fast:
                    return passed, failed
            else:
                passed += 1
    
    return passed, failed

def main(test_dir, fail_fast=False, test_specs=None, verbose=False, filter_files=None):
    passed, failed = run_tests(test_dir, fail_fast, test_specs, verbose, filter_files)
    total = passed + failed
    print(f'\nTests passed: {passed}/{total} ({round(passed*100/total) if total else 0}%)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-x', '--fail-fast', action='store_true',
                       help='Break on first test failure')
    parser.add_argument('--test-specs', type=str, nargs='+', default=None,
                       help='Space-separated list of test specs in format: file:indices (e.g., test1.dat:0,1,2 test2.dat:5,6)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Print detailed information for all tests')
    parser.add_argument('--filter-files', type=str,
                       help='Only run tests from files containing this string')
    args = parser.parse_args()
    
    # Split the test specs if they contain commas
    test_specs = []
    if args.test_specs:
        for spec in args.test_specs:
            test_specs.extend(spec.split(','))
    
    main('../html5lib-tests/tree-construction', args.fail_fast, test_specs, args.verbose, args.filter_files)
