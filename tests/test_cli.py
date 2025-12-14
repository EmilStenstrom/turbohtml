import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from tempfile import NamedTemporaryFile

import justhtml.__main__ as cli


class TestCLI(unittest.TestCase):
    def _run_cli(self, argv, stdin_text=""):
        stdout = StringIO()
        stderr = StringIO()

        old_argv = sys.argv
        old_stdin = sys.stdin
        try:
            sys.argv = ["justhtml", *argv]
            sys.stdin = StringIO(stdin_text)
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    cli.main()
                except SystemExit as e:
                    return e.code, stdout.getvalue(), stderr.getvalue()
            return 0, stdout.getvalue(), stderr.getvalue()
        finally:
            sys.argv = old_argv
            sys.stdin = old_stdin

    def test_help(self):
        code, out, err = self._run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage: justhtml", out)
        self.assertIn("--selector", out)
        self.assertIn("--format", out)
        self.assertEqual(err, "")

    def test_version(self):
        code, out, err = self._run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("justhtml "))
        self.assertEqual(err, "")

    def test_no_args_prints_help_and_exits_1(self):
        code, out, err = self._run_cli([])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("usage: justhtml", err)

    def test_stdin_html_default_format_html(self):
        html = "<p>Hello <b>world</b></p>"
        code, out, err = self._run_cli(["-"], stdin_text=html)
        self.assertEqual(code, 0)
        self.assertIn("<p>", out)
        self.assertIn("Hello", out)
        self.assertIn("world", out)
        self.assertEqual(err, "")

    def test_selector_text_multiple_matches(self):
        html = "<article><p>Hi <b>there</b></p><p>Bye</p></article>"
        code, out, err = self._run_cli(["-", "--selector", "p", "--format", "text"], stdin_text=html)
        self.assertEqual(code, 0)
        self.assertEqual(out, "Hi there\nBye\n")
        self.assertEqual(err, "")

    def test_selector_text_first(self):
        html = "<article><p>Hi <b>there</b></p><p>Bye</p></article>"
        code, out, err = self._run_cli(
            ["-", "--selector", "p", "--format", "text", "--first"],
            stdin_text=html,
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "Hi there\n")
        self.assertEqual(err, "")

    def test_selector_markdown(self):
        html = "<article><p>Hello <b>world</b></p></article>"
        code, out, err = self._run_cli(["-", "--selector", "article", "--format", "markdown"], stdin_text=html)
        self.assertEqual(code, 0)
        self.assertEqual(out, "Hello **world**\n")
        self.assertEqual(err, "")

    def test_selector_no_matches_exits_1(self):
        html = "<p>Hello</p>"
        code, out, err = self._run_cli(["-", "--selector", ".does-not-exist"], stdin_text=html)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_invalid_selector_exits_2_and_writes_stderr(self):
        html = "<p>Hello</p>"
        code, out, err = self._run_cli(["-", "--selector", "["], stdin_text=html)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertNotEqual(err, "")

    def test_file_input_path(self):
        html = "<p>Hello</p>"
        with NamedTemporaryFile("w+", suffix=".html") as f:
            f.write(html)
            f.flush()
            code, out, err = self._run_cli([f.name, "--format", "text"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "Hello\n")
        self.assertEqual(err, "")
