#!/usr/bin/env python3
"""Debug script to inspect specific tokenizer test failures."""

import json
import sys
from pathlib import Path

from run_tests import _run_single_tokenizer_test, _token_to_list, _collapse_characters, _map_initial_state, _unescape_unicode
from turbohtml.tokenizer import Tokenizer, TokenizerOpts
from run_tests import RecordingTreeBuilder

def debug_test(filename, test_index):
    path = Path(f"tests/html5lib-tests-tokenizer/{filename}")
    if not path.exists():
        print(f"File not found: {path}")
        return

    data = json.loads(path.read_text())
    key = "tests" if "tests" in data else "xmlViolationTests"
    tests = data.get(key, [])

    if test_index >= len(tests):
        print(f"Test index {test_index} out of range (max: {len(tests)-1})")
        return

    test = tests[test_index]
    print(f"=== Test {test_index} from {filename} ===")
    print(f"Input: {repr(test['input'])}")
    print(f"Description: {test.get('description', 'N/A')}")

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

    print(f"Initial states: {initial_states}")
    print(f"Last start tag: {last_start_tag}")
    print(f"\nExpected tokens:")
    for tok in expected_tokens:
        print(f"  {tok}")

    for state_name in initial_states:
        mapped = _map_initial_state(state_name)
        if not mapped:
            print(f"\n!!! State {state_name} not mapped !!!")
            continue
        initial_state, raw_tag = mapped
        if initial_state == Tokenizer.RAWTEXT and last_start_tag:
            raw_tag = last_start_tag

        sink = RecordingTreeBuilder()
        opts = TokenizerOpts(initial_state=initial_state, initial_rawtext_tag=raw_tag, discard_bom=False)
        tok = Tokenizer(sink, opts)
        tok.last_start_tag_name = last_start_tag
        tok.run(input_text)
        actual = [r for t in sink.tokens if (r := _token_to_list(t)) is not None]
        actual = _collapse_characters(actual)

        print(f"\nActual tokens (state: {state_name}):")
        for tok in actual:
            print(f"  {tok}")

        if actual != expected_tokens:
            print("\n!!! MISMATCH !!!")
            print("\nDifferences:")
            for i, (exp, act) in enumerate(zip(expected_tokens, actual)):
                if exp != act:
                    print(f"  Token {i}: expected {exp}, got {act}")
            if len(expected_tokens) != len(actual):
                print(f"  Length: expected {len(expected_tokens)}, got {len(actual)}")
        else:
            print("\n✓ PASSED")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python debug_tokenizer.py <filename> <test_index>")
        print("Example: python debug_tokenizer.py contentModelFlags.test 4")
        sys.exit(1)

    debug_test(sys.argv[1], int(sys.argv[2]))
