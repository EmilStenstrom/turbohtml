from turbohtml import TurboHTML
import os
import argparse


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

def run_tests(test_dir, fail_fast=False, keyword=None, test_indices=None):
    passed = 0
    failed = 0

    for root, _, files in os.walk(test_dir):
        for file in files:
            if file.endswith('.dat') and (keyword is None or keyword in file):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                tests = parse_dat_file(content)
                for i, test in enumerate(tests):
                    if test_indices is not None and i not in test_indices:
                        continue  # Skip tests not in the specified indices

                    html_input = test['data']
                    errors = test['errors']
                    expected_output = test['document']
                    parser = TurboHTML(html_input)
                    actual_output = parser.root.to_test_format()
                    test_passed = compare_outputs(expected_output, actual_output)
                    verbose = (fail_fast and not test_passed) or (test_indices is not None and i in test_indices) 

                    if verbose:
                        # Print detailed information for specified indices
                        print(f'\nTest {file} #{i} {"passed" if test_passed else "failed"}:')
                        print(f'HTML input: {html_input}')
                        if test_passed:
                            print(f"Errors: {errors}")
                        print(f'Expected:\n{expected_output}')
                        print(f'Actual:\n{actual_output}')
                    else:
                        print("x" if not test_passed else ".", end="", flush=True)

                    if not test_passed:
                        failed += 1
                        if fail_fast:
                            return passed, failed
                    else:
                        passed += 1
        
        return passed, failed

def main(test_dir, fail_fast=False, keyword=None, test_indices=None):
    passed, failed = run_tests(test_dir, fail_fast, keyword, test_indices)
    total = passed + failed
    print(f'\nTests passed: {passed}/{total} ({round(passed*100/total) if total else 0}%)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-x', '--fail-fast', action='store_true',
                       help='Break on first test failure')
    parser.add_argument('-k', '--keyword', type=str, default=None,
                       help='Only run tests from files containing the keyword')
    parser.add_argument('-t', '--test-indices', type=str, default=None,
                       help='Comma-separated list of test indices to run')
    args = parser.parse_args()
    
    # Convert the comma-separated string of indices into a list of integers
    test_indices = list(map(int, args.test_indices.split(','))) if args.test_indices else None
    
    main('../html5lib-tests/tree-construction', args.fail_fast, args.keyword, test_indices)
