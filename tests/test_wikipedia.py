import unittest
from pathlib import Path

from justhtml import JustHTML

DATA_DIR = Path(__file__).parent / "data"


class TestWikipedia(unittest.TestCase):
    def test_wikipedia_markdown_conversion(self):
        html_path = DATA_DIR / "wikipedia.html"
        if not html_path.exists():
            self.skipTest("wikipedia.html not found in tests/data")

        html_content = html_path.read_text(encoding="utf-8")
        doc = JustHTML(html_content)

        md = doc.to_markdown()

        # Regression test: Title text should not be in the body output
        # The title is "Wikipedia"
        # However, "Wikipedia" also appears in the body as a span:
        # <span class="central-textlogo__image sprite svg-Wikipedia_wordmark">Wikipedia</span>
        # So we need to be careful.

        # The title tag is: <title>Wikipedia</title>
        # The body contains:
        # <h1 class="central-textlogo-wrapper">
        # <span class="central-textlogo__image sprite svg-Wikipedia_wordmark">
        # Wikipedia
        # </span>
        # ...

        # So "Wikipedia" SHOULD be in the output, but coming from the h1/span, not the title.
        # In the previous issue, we saw "Wikipedia" appearing at the very top, before the image.

        # Let's check the structure.
        # The markdown should start with the image or the text logo.

        # <div class="central-textlogo">
        # <img ...>
        # <h1>... Wikipedia ...</h1>

        # So we expect:
        # <img ...>
        # # Wikipedia The Free Encyclopedia

        # Let's verify "The Free Encyclopedia" is present.
        self.assertIn("The Free Encyclopedia", md)

        # Verify we don't have the title "Wikipedia" floating at the start.
        # The first non-whitespace thing should be the image tag (since images are preserved as HTML).

        lines = [line.strip() for line in md.splitlines() if line.strip()]
        first_line = lines[0]

        # The first element in body is <main>, then <div class="central-textlogo">, then <img>.
        # So the first output should be the <img> tag.
        self.assertTrue(first_line.startswith("<img"), f"Expected image at start, got: {first_line[:50]}")

        # Verify English language link is present
        self.assertIn("English", md)
        self.assertIn("articles", md)

        # Verify links are preserved (protocol-relative resolved to https)
        # Example: [English](https://en.wikipedia.org/)
        self.assertIn("(https://en.wikipedia.org/)", md)

        # Verify footer links are present and have correct URLs
        expected_links = [
            "[Wikiquote Free quote compendium](https://www.wikiquote.org/)",
            "[MediaWiki Free & open wiki software](https://www.mediawiki.org/)",
            "[Wikisource Free content library](https://www.wikisource.org/)",
            "[Wikispecies Free species directory](https://species.wikimedia.org/)",
            "[Wikifunctions Free function library](https://www.wikifunctions.org/)",
            "[Meta-Wiki Community coordination & documentation](https://meta.wikimedia.org/)",
        ]
        for link in expected_links:
            self.assertIn(link, md)


if __name__ == "__main__":
    unittest.main()
