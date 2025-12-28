from __future__ import annotations

import difflib
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class _DocExample:
    doc_path: Path
    code_start_line: int
    code: str
    output_lang: str
    expected_output: str
    expects_raise: bool


def _parse_fence_line(line: str) -> tuple[str, str] | None:
    if not line.startswith("`"):
        return None
    i = 0
    while i < len(line) and line[i] == "`":
        i += 1
    if i < 3:
        return None
    fence = line[:i]
    lang = line[i:].strip().lower()
    return fence, lang


def _iter_doc_examples(docs_dir: Path) -> list[_DocExample]:
    examples: list[_DocExample] = []

    for doc_path in sorted(docs_dir.rglob("*.md")):
        text = doc_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        i = 0
        while i < len(lines):
            line = lines[i]
            parsed = _parse_fence_line(line)
            if parsed is not None:
                code_fence, fence_lang = parsed
                if fence_lang in {"python", "py"}:
                    code_start_line = i + 1  # 1-based line number of fence
                    i += 1
                    code_lines: list[str] = []
                    while i < len(lines) and not lines[i].startswith(code_fence):
                        code_lines.append(lines[i])
                        i += 1
                    # Skip closing fence if present.
                    if i < len(lines) and lines[i].startswith(code_fence):
                        i += 1

                    code = "\n".join(code_lines).rstrip("\n")

                    expects_raise = "doctest: raises" in code

                    # Optional skip marker inside the code block.
                    if "doctest: skip" in code:
                        continue

                    j = i
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1

                    if j < len(lines) and lines[j].strip() == "Output:":
                        k = j + 1
                        while k < len(lines) and lines[k].strip() == "":
                            k += 1
                        out_parsed = _parse_fence_line(lines[k]) if k < len(lines) else None
                        if out_parsed is not None:
                            out_fence, output_lang = out_parsed
                            k += 1
                            out_lines: list[str] = []
                            while k < len(lines) and not lines[k].startswith(out_fence):
                                out_lines.append(lines[k])
                                k += 1
                            if k < len(lines) and lines[k].startswith(out_fence):
                                k += 1

                            expected_output = "\n".join(out_lines).rstrip("\n")
                            examples.append(
                                _DocExample(
                                    doc_path=doc_path,
                                    code_start_line=code_start_line,
                                    code=code,
                                    output_lang=output_lang,
                                    expected_output=expected_output,
                                    expects_raise=expects_raise,
                                )
                            )
                            i = k
                            continue

                    continue

            i += 1

    return examples


def _run_python_snippet(project_root: Path, code: str) -> tuple[int, str, str]:
    env = os.environ.copy()
    src_dir = str(project_root / "src")
    env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("PYTHONUTF8", "1")

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "snippet.py"
        script_path.write_text(code + "\n", encoding="utf-8")

        proc = subprocess.run(  # noqa: S603
            [sys.executable, str(script_path)],
            check=False,
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
        )

    stdout = proc.stdout.replace("\r\n", "\n").rstrip("\n")
    stderr = proc.stderr.replace("\r\n", "\n").rstrip("\n")
    return proc.returncode, stdout, stderr


def _line_matches(expected_line: str, actual_line: str) -> bool:
    if expected_line == actual_line:
        return True

    # Allow single-line wildcards using "..." inside a line.
    if "..." not in expected_line:
        return False

    parts = expected_line.split("...")
    pos = 0
    for part in parts:
        if part == "":
            continue
        idx = actual_line.find(part, pos)
        if idx == -1:
            return False
        pos = idx + len(part)
    return True


def _matches_with_ellipsis(expected: str, actual: str) -> bool:
    expected_lines = expected.splitlines()
    actual_lines = actual.splitlines()

    i = 0
    j = 0
    while i < len(expected_lines):
        el = expected_lines[i]

        # A line that is only "..." (ignoring surrounding whitespace) matches
        # any number of actual lines until the next expected line matches.
        if el.strip() == "...":
            i += 1
            if i >= len(expected_lines):
                return True
            next_el = expected_lines[i]
            while j < len(actual_lines) and not _line_matches(next_el, actual_lines[j]):
                j += 1
            if j >= len(actual_lines):
                return False
            continue

        if j >= len(actual_lines):
            return False
        if not _line_matches(el, actual_lines[j]):
            return False
        i += 1
        j += 1

    return j == len(actual_lines)


def _diff(expected: str, actual: str) -> str:
    expected_lines = expected.splitlines(keepends=True)
    actual_lines = actual.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="expected",
            tofile="actual",
        )
    )


class TestDocsExamples(unittest.TestCase):
    def test_docs_snippets_match_output_blocks(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        docs_dir = project_root / "docs"

        examples = _iter_doc_examples(docs_dir)
        if not examples:
            self.fail("No doc examples with Output blocks found")

        failures: list[str] = []

        for ex in examples:
            returncode, stdout, stderr = _run_python_snippet(project_root, ex.code)
            expected = ex.expected_output.replace("\r\n", "\n").rstrip("\n")

            if ex.expects_raise:
                actual = stderr
                if returncode == 0:
                    failures.append(
                        "\n".join(
                            [
                                f"Doc: {ex.doc_path.relative_to(project_root)}:{ex.code_start_line}",
                                f"Output fence language: {ex.output_lang}",
                                "Expected snippet to raise but it exited 0",
                            ]
                        )
                    )
                    continue
            else:
                actual = stdout
                if returncode != 0:
                    failures.append(
                        "\n".join(
                            [
                                f"Doc: {ex.doc_path.relative_to(project_root)}:{ex.code_start_line}",
                                f"Output fence language: {ex.output_lang}",
                                "Snippet execution failed:",
                                stderr,
                            ]
                        )
                    )
                    continue

            if not _matches_with_ellipsis(expected, actual):
                failures.append(
                    "\n".join(
                        [
                            f"Doc: {ex.doc_path.relative_to(project_root)}:{ex.code_start_line}",
                            f"Output fence language: {ex.output_lang}",
                            _diff(expected, actual),
                        ]
                    )
                )

        if failures:
            self.fail("\n\n".join(failures))
