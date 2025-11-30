#!/usr/bin/env python3
"""Command-line interface for JustHTML."""

import sys
from . import JustHTML


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m justhtml <file.html>", file=sys.stderr)
        print("       python -m justhtml -  (read from stdin)", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if path == "-":
        html = sys.stdin.read()
    else:
        with open(path) as f:
            html = f.read()

    doc = JustHTML(html)
    print(doc.root.to_html())


if __name__ == "__main__":
    main()
