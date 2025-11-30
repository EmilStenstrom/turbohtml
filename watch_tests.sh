#!/usr/bin/env bash
set -euo pipefail

# Exit the entire script on Ctrl-C
trap 'echo; echo "Interrupted, exiting."; exit 130' INT

while sleep 0.1; do
  # When entr or the test command is interrupted, entr should exit non‑zero.
  # In that case, we break out of the loop.
  find . -type f -name '*.py' -o -name '*.test' -o -name '*.dat' | entr -crd python run_tests.py -q --regressions || continue
done
