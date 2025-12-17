import unittest

from justhtml import JustHTML
from justhtml.node import ElementNode
from justhtml.tokenizer import Tokenizer, TokenizerOpts
from justhtml.treebuilder import InsertionMode, TreeBuilder


class _CoverageSink:
    __slots__ = ("open_elements",)

    def __init__(self) -> None:
        self.open_elements = []

    def process_token(self, token):
        return 0

    def process_characters(self, data):
        return 0


class TestCoverage(unittest.TestCase):
    def test_null_in_body_text_is_removed(self) -> None:
        doc = JustHTML("<body>a\x00b</body>", collect_errors=True)
        text = doc.to_text(strip=False)
        self.assertEqual(text, "ab")
        self.assertNotIn("\x00", text)

    def test_only_null_in_body_text_becomes_empty(self) -> None:
        doc = JustHTML("<body>\x00</body>", collect_errors=True)
        text = doc.to_text(strip=False)
        self.assertEqual(text, "")

    def test_treebuilder_process_characters_strips_null_and_appends(self) -> None:
        tree_builder = TreeBuilder(collect_errors=True)
        tree_builder.mode = InsertionMode.IN_BODY
        tree_builder.open_elements.append(ElementNode("body", {}, None))

        tree_builder.process_characters("a\x00b")
        body = tree_builder.open_elements[-1]
        self.assertEqual(len(body.children), 1)
        self.assertEqual(body.children[0].data, "ab")

    def test_treebuilder_process_characters_only_null_returns_continue(self) -> None:
        tree_builder = TreeBuilder(collect_errors=True)
        tree_builder.mode = InsertionMode.IN_BODY
        tree_builder.open_elements.append(ElementNode("body", {}, None))

        tree_builder.process_characters("\x00")
        body = tree_builder.open_elements[-1]
        self.assertEqual(body.children, [])

    def test_treebuilder_process_characters_empty_returns_continue(self) -> None:
        tree_builder = TreeBuilder(collect_errors=True)
        tree_builder.mode = InsertionMode.IN_BODY
        tree_builder.open_elements.append(ElementNode("body", {}, None))

        tree_builder.process_characters("")
        body = tree_builder.open_elements[-1]
        self.assertEqual(body.children, [])

    def test_tokenizer_after_attribute_name_lowercases_uppercase(self) -> None:
        sink = _CoverageSink()
        tokenizer = Tokenizer(sink, TokenizerOpts(), collect_errors=True)
        tokenizer.initialize("A")
        tokenizer.state = Tokenizer.AFTER_ATTRIBUTE_NAME
        tokenizer.current_tag_attrs = {}
        tokenizer.current_attr_name[:] = ["x"]
        tokenizer.current_attr_value.clear()
        tokenizer.current_attr_value_has_amp = False

        tokenizer._state_after_attribute_name()
        self.assertEqual(tokenizer.current_attr_name, ["a"])

    def test_tokenizer_after_attribute_name_handles_null(self) -> None:
        sink = _CoverageSink()
        tokenizer = Tokenizer(sink, TokenizerOpts(), collect_errors=True)
        tokenizer.initialize("\x00")
        tokenizer.state = Tokenizer.AFTER_ATTRIBUTE_NAME
        tokenizer.current_tag_attrs = {}
        tokenizer.current_attr_name[:] = ["x"]
        tokenizer.current_attr_value.clear()
        tokenizer.current_attr_value_has_amp = False

        tokenizer._state_after_attribute_name()
        self.assertEqual(tokenizer.current_attr_name, ["\ufffd"])

    def test_tokenizer_attribute_name_state_handles_null(self) -> None:
        sink = _CoverageSink()
        tokenizer = Tokenizer(sink, TokenizerOpts(), collect_errors=True)
        tokenizer.initialize("\x00")
        tokenizer.state = Tokenizer.ATTRIBUTE_NAME
        tokenizer.current_tag_attrs = {}

        tokenizer._state_attribute_name()
        self.assertEqual(tokenizer.current_attr_name, ["\ufffd"])

    def test_tokenizer_attribute_name_state_appends_non_ascii(self) -> None:
        sink = _CoverageSink()
        tokenizer = Tokenizer(sink, TokenizerOpts(), collect_errors=True)
        tokenizer.initialize("é")
        tokenizer.state = Tokenizer.ATTRIBUTE_NAME
        tokenizer.current_tag_attrs = {}

        tokenizer._state_attribute_name()
        self.assertEqual(tokenizer.current_attr_name, ["é"])

    def test_tokenizer_after_attribute_name_skips_whitespace_run(self) -> None:
        sink = _CoverageSink()
        tokenizer = Tokenizer(sink, TokenizerOpts(), collect_errors=True)
        tokenizer.initialize("   =")
        tokenizer.state = Tokenizer.AFTER_ATTRIBUTE_NAME
        tokenizer.reconsume = False

        done = tokenizer._state_after_attribute_name()
        self.assertFalse(done)
        self.assertEqual(tokenizer.state, Tokenizer.BEFORE_ATTRIBUTE_VALUE)

    def test_tokenizer_after_attribute_name_whitespace_continue(self) -> None:
        sink = _CoverageSink()
        tokenizer = Tokenizer(sink, TokenizerOpts(), collect_errors=True)
        tokenizer.initialize(" =")
        tokenizer.state = Tokenizer.AFTER_ATTRIBUTE_NAME
        tokenizer.reconsume = True

        done = tokenizer._state_after_attribute_name()
        self.assertFalse(done)
        self.assertEqual(tokenizer.state, Tokenizer.BEFORE_ATTRIBUTE_VALUE)
