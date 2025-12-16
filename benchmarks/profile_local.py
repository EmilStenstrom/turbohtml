#!/usr/bin/env python3
"""Profile JustHTML on real-world HTML."""

import cProfile
import os
import re
import pstats
from pathlib import Path

from justhtml import JustHTML


def collect_test_files(test_dir, include_files=None):
    """Collect .dat test files."""
    files = []
    for root, _, filenames in os.walk(test_dir, followlinks=True):
        for filename in filenames:
            if filename.endswith(".dat"):
                if include_files and filename not in include_files:
                    continue
                files.append(Path(root) / filename)

    def natural_sort_key(path):
        def convert(text):
            return int(text) if text.isdigit() else text.lower()

        return [convert(c) for c in re.split("([0-9]+)", str(path))]

    return sorted(files, key=natural_sort_key)


def parse_dat_file(path):
    """Parse a .dat test file into test cases."""
    with path.open("r", encoding="utf-8", newline="") as f:
        content = f.read()

    tests = []
    lines = content.split("\n")

    current_test_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        current_test_lines.append(line)

        if i + 1 >= len(lines) or (i + 1 < len(lines) and lines[i + 1] == "#data"):
            if current_test_lines and any(line.strip() for line in current_test_lines):
                test = parse_single_test(current_test_lines)
                if test:
                    tests.append(test)
            current_test_lines = []
        i += 1

    return tests


def parse_single_test(lines):
    """Parse a single test from lines."""
    data = []
    document = []
    mode = None

    for line in lines:
        if line.startswith("#"):
            mode = line[1:]
        elif mode == "data":
            data.append(line)
        elif mode == "document":
            document.append(line)

    if data or document:
        return {
            "data": "\n".join(data),
            "document": "\n".join(document),
        }
    return None

test_dirs = [
    "tests/html5lib-tests-tree",
]

# For profiling, let's start with a few files to keep it fast
include_files = ["tests1.dat", "tests2.dat"]

test_files = []
for test_dir in test_dirs:
    test_path = Path(test_dir)
    if test_path.exists():
        test_files.extend(collect_test_files(test_path, include_files=include_files))

if not test_files:
    print("No test files found. Make sure tests/html5lib-tests-tree exists.")
    exit(1)


html_files = []
for file_path in test_files:
    tests = parse_dat_file(file_path)
    for test in tests:
        html_files.append(test["data"])

print(f"Loaded {len(html_files)} documents from {len(test_files)} test files.")

# Profile
profiler = cProfile.Profile()
profiler.enable()

for html in html_files:
    if not html:
        continue
    parser = JustHTML(html)
    _ = parser.root

profiler.disable()

# Print stats
stats = pstats.Stats(profiler)
stats.sort_stats("tottime")
stats.print_stats(30)
