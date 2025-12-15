#!/usr/bin/env python3
"""Command-line interface for JustHTML."""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import NoReturn

from . import JustHTML
from .selector import SelectorError


def _get_version() -> str:
    try:
        return version("justhtml")
    except PackageNotFoundError:  # pragma: no cover
        return "dev"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="justhtml",
        description="Parse HTML5 and output text, pretty-printed HTML, or Markdown.",
        epilog=(
            "Examples:\n"
            "  justhtml page.html\n"
            "  curl -s https://example.com | justhtml -\n"
            "  justhtml page.html --selector 'main p' --format text\n"
            "  justhtml page.html --selector 'a' --format html\n"
            "  justhtml page.html --selector 'article' --format markdown\n"
            "\n"
            "If you don't have the 'justhtml' command available, use:\n"
            "  python -m justhtml ...\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "path",
        nargs="?",
        help="HTML file to parse, or '-' to read from stdin",
    )
    parser.add_argument(
        "--selector",
        help="CSS selector for choosing nodes (defaults to the document root)",
    )
    parser.add_argument(
        "--format",
        choices=["html", "text", "markdown"],
        default="html",
        help="Output format (default: html)",
    )
    parser.add_argument(
        "--first",
        action="store_true",
        help="Only output the first matching node",
    )

    parser.add_argument(
        "--separator",
        default=" ",
        help="Text-only: join string between text nodes (default: a single space)",
    )
    strip_group = parser.add_mutually_exclusive_group()
    strip_group.add_argument(
        "--strip",
        action="store_true",
        default=True,
        help="Text-only: strip each text node and drop empty segments (default)",
    )
    strip_group.add_argument(
        "--no-strip",
        action="store_false",
        dest="strip",
        help="Text-only: preserve text node whitespace",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"justhtml {_get_version()}",
    )

    args = parser.parse_args(argv)

    if not args.path:
        parser.print_help(sys.stderr)
        raise SystemExit(1)

    return args


def _read_html(path: str) -> str:
    if path == "-":
        return sys.stdin.read()

    return Path(path).read_text()


def main() -> NoReturn | None:
    args = _parse_args(sys.argv[1:])
    html = _read_html(args.path)
    doc = JustHTML(html)

    try:
        nodes = doc.query(args.selector) if args.selector else [doc.root]
    except SelectorError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2) from e

    if not nodes:
        raise SystemExit(1)

    if args.first:
        nodes = [nodes[0]]

    if args.format == "html":
        outputs = [node.to_html() for node in nodes]
        sys.stdout.write("\n".join(outputs))
        sys.stdout.write("\n")
        return None

    if args.format == "text":
        outputs = [node.to_text(separator=args.separator, strip=args.strip) for node in nodes]
        sys.stdout.write("\n".join(outputs))
        sys.stdout.write("\n")
        return None

    outputs = [node.to_markdown() for node in nodes]
    sys.stdout.write("\n\n".join(outputs))
    sys.stdout.write("\n")
    return None


if __name__ == "__main__":
    main()
