import re
import sys

from .entities import decode_entities_in_text
from .tokens import (
    CharacterTokens,
    CommentToken,
    Doctype,
    DoctypeToken,
    EOFToken,
    ParseError,
    Tag,
    TokenSinkResult,
)

_ATTR_VALUE_DOUBLE_TERMINATORS = '"&\r\n\0'
_ATTR_VALUE_SINGLE_TERMINATORS = "'&\r\n\0"
_ATTR_VALUE_UNQUOTED_TERMINATORS = "\t\n\f >&\"'<=`\r\0"
_ATTR_NAME_TERMINATORS = "\t\n\f />=\0\"'<"
_ASCII_LOWER_TABLE = str.maketrans({chr(code): chr(code + 32) for code in range(65, 91)})
_RCDATA_ELEMENTS = {"title", "textarea"}

_ATTR_VALUE_DOUBLE_PATTERN = re.compile(f"[{re.escape(_ATTR_VALUE_DOUBLE_TERMINATORS)}]")
_ATTR_VALUE_SINGLE_PATTERN = re.compile(f"[{re.escape(_ATTR_VALUE_SINGLE_TERMINATORS)}]")
_ATTR_VALUE_UNQUOTED_PATTERN = re.compile(f"[{re.escape(_ATTR_VALUE_UNQUOTED_TERMINATORS)}]")
_ATTR_NAME_TERMINATOR_PATTERN = re.compile(f"[{re.escape(_ATTR_NAME_TERMINATORS)}]")


class TokenizerOpts:
    __slots__ = ("discard_bom", "exact_errors", "initial_rawtext_tag", "initial_state")

    def __init__(self, exact_errors=False, discard_bom=True, initial_state=None, initial_rawtext_tag=None):
        self.exact_errors = bool(exact_errors)
        self.discard_bom = bool(discard_bom)
        self.initial_state = initial_state
        self.initial_rawtext_tag = initial_rawtext_tag


class Tokenizer:
    DATA = 0
    TAG_OPEN = 1
    END_TAG_OPEN = 2
    TAG_NAME = 3
    BEFORE_ATTRIBUTE_NAME = 4
    ATTRIBUTE_NAME = 5
    AFTER_ATTRIBUTE_NAME = 6
    BEFORE_ATTRIBUTE_VALUE = 7
    ATTRIBUTE_VALUE_DOUBLE = 8
    ATTRIBUTE_VALUE_SINGLE = 9
    ATTRIBUTE_VALUE_UNQUOTED = 10
    SELF_CLOSING_START_TAG = 11
    MARKUP_DECLARATION_OPEN = 12
    COMMENT_START = 13
    COMMENT_START_DASH = 14
    COMMENT = 15
    COMMENT_END_DASH = 16
    COMMENT_END = 17
    COMMENT_END_BANG = 18
    BOGUS_COMMENT = 19
    DOCTYPE = 20
    BEFORE_DOCTYPE_NAME = 21
    DOCTYPE_NAME = 22
    AFTER_DOCTYPE_NAME = 23
    BOGUS_DOCTYPE = 24
    AFTER_DOCTYPE_PUBLIC_KEYWORD = 25
    AFTER_DOCTYPE_SYSTEM_KEYWORD = 26
    BEFORE_DOCTYPE_PUBLIC_IDENTIFIER = 27
    DOCTYPE_PUBLIC_IDENTIFIER_DOUBLE_QUOTED = 28
    DOCTYPE_PUBLIC_IDENTIFIER_SINGLE_QUOTED = 29
    AFTER_DOCTYPE_PUBLIC_IDENTIFIER = 30
    BETWEEN_DOCTYPE_PUBLIC_AND_SYSTEM_IDENTIFIERS = 31
    BEFORE_DOCTYPE_SYSTEM_IDENTIFIER = 32
    DOCTYPE_SYSTEM_IDENTIFIER_DOUBLE_QUOTED = 33
    DOCTYPE_SYSTEM_IDENTIFIER_SINGLE_QUOTED = 34
    AFTER_DOCTYPE_SYSTEM_IDENTIFIER = 35
    CDATA_SECTION = 36
    CDATA_SECTION_BRACKET = 37
    CDATA_SECTION_END = 38
    RAWTEXT = 39
    RAWTEXT_LESS_THAN_SIGN = 40
    RAWTEXT_END_TAG_OPEN = 41
    RAWTEXT_END_TAG_NAME = 42
    PLAINTEXT = 43
    SCRIPT_DATA_ESCAPED = 44
    SCRIPT_DATA_ESCAPED_DASH = 45
    SCRIPT_DATA_ESCAPED_DASH_DASH = 46
    SCRIPT_DATA_ESCAPED_LESS_THAN_SIGN = 47
    SCRIPT_DATA_ESCAPED_END_TAG_OPEN = 48
    SCRIPT_DATA_ESCAPED_END_TAG_NAME = 49
    SCRIPT_DATA_DOUBLE_ESCAPE_START = 50
    SCRIPT_DATA_DOUBLE_ESCAPED = 51
    SCRIPT_DATA_DOUBLE_ESCAPED_DASH = 52
    SCRIPT_DATA_DOUBLE_ESCAPED_DASH_DASH = 53
    SCRIPT_DATA_DOUBLE_ESCAPED_LESS_THAN_SIGN = 54
    SCRIPT_DATA_DOUBLE_ESCAPE_END = 55

    __slots__ = (
        "_tag_token",
        "buffer",
        "current_attr_name",
        "current_attr_names",
        "current_attr_value",
        "current_attr_value_has_amp",
        "current_char",
        "current_comment",
        "current_doctype_force_quirks",
        "current_doctype_name",
        "current_doctype_public",
        "current_doctype_system",
        "current_tag_attrs",
        "current_tag_kind",
        "current_tag_name",
        "current_tag_self_closing",
        "ignore_lf",
        "last_start_tag_name",
        "length",
        "line",
        "opts",
        "original_tag_name",
        "pos",
        "rawtext_tag_name",
        "reconsume",
        "sink",
        "state",
        "temp_buffer",
        "text_buffer",
    )

    def __init__(self, sink, opts=None):
        self.sink = sink
        self.opts = opts or TokenizerOpts()

        self.state = self.DATA
        self.buffer = ""
        self.length = 0
        self.pos = 0
        self.reconsume = False
        self.current_char = ""
        self.ignore_lf = False
        self.line = 1

        # Reusable buffers to avoid per-token allocations.
        self.text_buffer = []
        self.current_tag_name = []
        self.current_tag_attrs = []  # flat list [name1, value1, ...]
        self.current_attr_names = []
        self.current_attr_name = []
        self.current_attr_value = []
        self.current_attr_value_has_amp = False
        self.current_tag_self_closing = False
        self.current_tag_kind = Tag.START
        self.current_comment = []
        self.current_doctype_name = []
        self.current_doctype_public = []
        self.current_doctype_system = []
        self.current_doctype_force_quirks = False
        self.last_start_tag_name = None
        self.rawtext_tag_name = None
        self.original_tag_name = []
        self.temp_buffer = []
        self._tag_token = Tag(Tag.START, "", [], False)

    def run(self, html):
        if html and html[0] == "\ufeff" and self.opts.discard_bom:
            html = html[1:]

        self.buffer = html or ""
        self.length = len(self.buffer)
        self.pos = 0
        self.reconsume = False
        self.current_char = ""
        self.ignore_lf = False
        self.line = 1
        self.text_buffer.clear()
        self.current_tag_name.clear()
        self.current_tag_attrs.clear()
        self.current_attr_names.clear()
        self.current_attr_name.clear()
        self.current_attr_value.clear()
        self.current_attr_value_has_amp = False
        self.current_comment.clear()
        self.current_doctype_name.clear()
        self.current_doctype_public.clear()
        self.current_doctype_system.clear()
        self.current_doctype_force_quirks = False
        self.current_tag_self_closing = False
        self.current_tag_kind = Tag.START
        self.rawtext_tag_name = self.opts.initial_rawtext_tag
        self.temp_buffer.clear()
        self.last_start_tag_name = None
        self._tag_token.kind = Tag.START
        self._tag_token.name = ""
        self._tag_token.attrs = []
        self._tag_token.self_closing = False

        initial_state = self.opts.initial_state
        if isinstance(initial_state, int):
            self.state = initial_state
        else:
            self.state = self.DATA

        while True:
            state = self.state
            if state == self.DATA:
                if self._state_data():
                    break
            elif state == self.TAG_OPEN:
                if self._state_tag_open():
                    break
            elif state == self.END_TAG_OPEN:
                if self._state_end_tag_open():
                    break
            elif state == self.TAG_NAME:
                if self._state_tag_name():
                    break
            elif state == self.BEFORE_ATTRIBUTE_NAME:
                if self._state_before_attribute_name():
                    break
            elif state == self.ATTRIBUTE_NAME:
                if self._state_attribute_name():
                    break
            elif state == self.AFTER_ATTRIBUTE_NAME:
                if self._state_after_attribute_name():
                    break
            elif state == self.BEFORE_ATTRIBUTE_VALUE:
                if self._state_before_attribute_value():
                    break
            elif state == self.ATTRIBUTE_VALUE_DOUBLE:
                if self._state_attribute_value_double():
                    break
            elif state == self.ATTRIBUTE_VALUE_SINGLE:
                if self._state_attribute_value_single():
                    break
            elif state == self.ATTRIBUTE_VALUE_UNQUOTED:
                if self._state_attribute_value_unquoted():
                    break
            elif state == self.SELF_CLOSING_START_TAG:
                if self._state_self_closing_start_tag():
                    break
            elif state == self.MARKUP_DECLARATION_OPEN:
                if self._state_markup_declaration_open():
                    break
            elif state == self.COMMENT_START:
                if self._state_comment_start():
                    break
            elif state == self.COMMENT_START_DASH:
                if self._state_comment_start_dash():
                    break
            elif state == self.COMMENT:
                if self._state_comment():
                    break
            elif state == self.COMMENT_END_DASH:
                if self._state_comment_end_dash():
                    break
            elif state == self.COMMENT_END:
                if self._state_comment_end():
                    break
            elif state == self.COMMENT_END_BANG:
                if self._state_comment_end_bang():
                    break
            elif state == self.BOGUS_COMMENT:
                if self._state_bogus_comment():
                    break
            elif state == self.DOCTYPE:
                if self._state_doctype():
                    break
            elif state == self.BEFORE_DOCTYPE_NAME:
                if self._state_before_doctype_name():
                    break
            elif state == self.DOCTYPE_NAME:
                if self._state_doctype_name():
                    break
            elif state == self.AFTER_DOCTYPE_NAME:
                if self._state_after_doctype_name():
                    break
            elif state == self.AFTER_DOCTYPE_PUBLIC_KEYWORD:
                if self._state_after_doctype_public_keyword():
                    break
            elif state == self.AFTER_DOCTYPE_SYSTEM_KEYWORD:
                if self._state_after_doctype_system_keyword():
                    break
            elif state == self.BEFORE_DOCTYPE_PUBLIC_IDENTIFIER:
                if self._state_before_doctype_public_identifier():
                    break
            elif state == self.DOCTYPE_PUBLIC_IDENTIFIER_DOUBLE_QUOTED:
                if self._state_doctype_public_identifier_double_quoted():
                    break
            elif state == self.DOCTYPE_PUBLIC_IDENTIFIER_SINGLE_QUOTED:
                if self._state_doctype_public_identifier_single_quoted():
                    break
            elif state == self.AFTER_DOCTYPE_PUBLIC_IDENTIFIER:
                if self._state_after_doctype_public_identifier():
                    break
            elif state == self.BETWEEN_DOCTYPE_PUBLIC_AND_SYSTEM_IDENTIFIERS:
                if self._state_between_doctype_public_and_system_identifiers():
                    break
            elif state == self.BEFORE_DOCTYPE_SYSTEM_IDENTIFIER:
                if self._state_before_doctype_system_identifier():
                    break
            elif state == self.DOCTYPE_SYSTEM_IDENTIFIER_DOUBLE_QUOTED:
                if self._state_doctype_system_identifier_double_quoted():
                    break
            elif state == self.DOCTYPE_SYSTEM_IDENTIFIER_SINGLE_QUOTED:
                if self._state_doctype_system_identifier_single_quoted():
                    break
            elif state == self.AFTER_DOCTYPE_SYSTEM_IDENTIFIER:
                if self._state_after_doctype_system_identifier():
                    break
            elif state == self.BOGUS_DOCTYPE:
                if self._state_bogus_doctype():
                    break
            elif state == self.CDATA_SECTION:
                if self._state_cdata_section():
                    break
            elif state == self.CDATA_SECTION_BRACKET:
                if self._state_cdata_section_bracket():
                    break
            elif state == self.CDATA_SECTION_END:
                if self._state_cdata_section_end():
                    break
            elif state == self.RAWTEXT:
                if self._state_rawtext():
                    break
            elif state == self.RAWTEXT_LESS_THAN_SIGN:
                if self._state_rawtext_less_than_sign():
                    break
            elif state == self.RAWTEXT_END_TAG_OPEN:
                if self._state_rawtext_end_tag_open():
                    break
            elif state == self.RAWTEXT_END_TAG_NAME:
                if self._state_rawtext_end_tag_name():
                    break
            elif state == self.PLAINTEXT:
                if self._state_plaintext():
                    break
            elif state == self.SCRIPT_DATA_ESCAPED:
                if self._state_script_data_escaped():
                    break
            elif state == self.SCRIPT_DATA_ESCAPED_DASH:
                if self._state_script_data_escaped_dash():
                    break
            elif state == self.SCRIPT_DATA_ESCAPED_DASH_DASH:
                if self._state_script_data_escaped_dash_dash():
                    break
            elif state == self.SCRIPT_DATA_ESCAPED_LESS_THAN_SIGN:
                if self._state_script_data_escaped_less_than_sign():
                    break
            elif state == self.SCRIPT_DATA_ESCAPED_END_TAG_OPEN:
                if self._state_script_data_escaped_end_tag_open():
                    break
            elif state == self.SCRIPT_DATA_ESCAPED_END_TAG_NAME:
                if self._state_script_data_escaped_end_tag_name():
                    break
            elif state == self.SCRIPT_DATA_DOUBLE_ESCAPE_START:
                if self._state_script_data_double_escape_start():
                    break
            elif state == self.SCRIPT_DATA_DOUBLE_ESCAPED:
                if self._state_script_data_double_escaped():
                    break
            elif state == self.SCRIPT_DATA_DOUBLE_ESCAPED_DASH:
                if self._state_script_data_double_escaped_dash():
                    break
            elif state == self.SCRIPT_DATA_DOUBLE_ESCAPED_DASH_DASH:
                if self._state_script_data_double_escaped_dash_dash():
                    break
            elif state == self.SCRIPT_DATA_DOUBLE_ESCAPED_LESS_THAN_SIGN:
                if self._state_script_data_double_escaped_less_than_sign():
                    break
            elif state == self.SCRIPT_DATA_DOUBLE_ESCAPE_END:
                if self._state_script_data_double_escape_end():
                    break
            else:
                # Unknown state fallback to data.
                self.state = self.DATA

    # ---------------------
    # Helper methods
    # ---------------------

    def _peek_char(self, offset):
        """Peek ahead at character at current position + offset without consuming"""
        peek_pos = self.pos + offset
        if peek_pos < self.length:
            return self.buffer[peek_pos]
        return None

    # ---------------------
    # State handlers
    # ---------------------

    def _state_data(self):
        buffer = self.buffer
        length = self.length
        pos = self.pos
        while True:
            if self.reconsume:
                self.reconsume = False
                c = self.current_char
                if c is None:
                    self._flush_text()
                    self._emit_token(EOFToken())
                    return True
                if c == "<":
                    self.ignore_lf = False
                    self._flush_text()
                    self.state = self.TAG_OPEN
                    return False
                if c == "\0":
                    self._emit_error("Null character in data state")
                    self.ignore_lf = False
                    self.text_buffer.append("\0")
                else:
                    self._append_text_chunk(c, ends_with_cr=(c == "\r"))
                pos = self.pos
                continue
            if pos >= length:
                self.pos = length
                self.current_char = None
                self._flush_text()
                self._emit_token(EOFToken())
                return True
            start = pos
            while pos < length:
                ch = buffer[pos]
                if ch == "<" or ch == "\0":
                    break
                pos += 1
            if pos > start:
                chunk = buffer[start:pos]
                self._append_text_chunk(chunk, ends_with_cr=chunk.endswith("\r"))
                self.pos = pos
                if pos >= length:
                    continue
            c = buffer[pos]
            pos += 1
            self.pos = pos
            self.current_char = c
            self.ignore_lf = False
            if c == "<":
                self._flush_text()
                self.state = self.TAG_OPEN
                return False
            self._emit_error("Null character in data state")
            self.text_buffer.append("\0")

    def _state_tag_open(self):
        c = self._get_char()
        if c is None:
            self._emit_error("EOF after <")
            self.text_buffer.append("<")
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c == "!":
            self.state = self.MARKUP_DECLARATION_OPEN
            return False
        if c == "/":
            self.state = self.END_TAG_OPEN
            return False
        if c == "?":
            self._emit_error("Unexpected '?' at tag open")
            self.current_comment.clear()
            self._reconsume_current()
            self.state = self.BOGUS_COMMENT
            return False
        if c.isalpha():
            self._start_tag(Tag.START)
            self._append_tag_name(c)
            self.state = self.TAG_NAME
            return False

        self._emit_error("Invalid first character of tag name")
        self.text_buffer.append("<")
        self._reconsume_current()
        self.state = self.DATA
        return False

    def _state_end_tag_open(self):
        c = self._get_char()
        if c is None:
            self._emit_error("EOF after </")
            self.text_buffer.append("<")
            self.text_buffer.append("/")
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c.isalpha():
            self._start_tag(Tag.END)
            self._append_tag_name(c)
            self.state = self.TAG_NAME
            return False
        if c == ">":
            self._emit_error("Empty end tag")
            self.state = self.DATA
            return False

        self._emit_error("Invalid character after </")
        self.current_comment.clear()
        self._reconsume_current()
        self.state = self.BOGUS_COMMENT
        return False

    def _state_tag_name(self):
        replacement = "\ufffd"
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in tag name")
                # Per HTML5 spec: EOF in tag name is a parse error, emit EOF token only
                # The incomplete tag is discarded (not emitted as text)
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                self._finish_attribute()
                self.state = self.BEFORE_ATTRIBUTE_NAME
                return False
            if c == "/":
                self._finish_attribute()
                self.state = self.SELF_CLOSING_START_TAG
                return False
            if c == ">":
                self._finish_attribute()
                if not self._emit_current_tag():
                    self.state = self.DATA
                return False
            if c == "\0":
                self._emit_error("Null character in tag name")
                self._append_tag_name(replacement)
                continue
            self._append_tag_name(c)

    def _state_before_attribute_name(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF before attribute name")
                # If this is an end tag for a RAWTEXT element, flush any pending text first
                if self.current_tag_kind == Tag.END and self.rawtext_tag_name:
                    self._flush_text()
                self._emit_current_tag()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                return False
            if c == "/":
                self.state = self.SELF_CLOSING_START_TAG
                return False
            if c == ">":
                self._finish_attribute()
                if not self._emit_current_tag():
                    self.state = self.DATA
                return False
            if c == "=":
                self._emit_error("Attribute name cannot start with '='")
                self._start_attribute()
                self._append_attr_name(c)
                self.state = self.ATTRIBUTE_NAME
                return False
            self._start_attribute()
            self._append_attr_name(c)
            self.state = self.ATTRIBUTE_NAME
            return False

    def _state_attribute_name(self):
        replacement = "\ufffd"
        while True:
            if self._consume_attribute_name_run():
                continue
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in attribute name")
                self._finish_attribute()
                # If this is an end tag for a RAWTEXT element, flush any pending text first
                if self.current_tag_kind == Tag.END and self.rawtext_tag_name:
                    self._flush_text()
                self._emit_current_tag()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                self._finish_attribute()
                self.state = self.AFTER_ATTRIBUTE_NAME
                return False
            if c == "/":
                self._finish_attribute()
                self.state = self.SELF_CLOSING_START_TAG
                return False
            if c == "=":
                self.state = self.BEFORE_ATTRIBUTE_VALUE
                return False
            if c == ">":
                self._finish_attribute()
                if not self._emit_current_tag():
                    self.state = self.DATA
                return False
            if c == "\0":
                self._emit_error("Null in attribute name")
                self._append_attr_name(replacement)
                continue
            if c in ('"', "'", "<"):
                self._emit_error("Invalid character in attribute name")
            self._append_attr_name(c)

    def _state_after_attribute_name(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF after attribute name")
                self._finish_attribute()
                self._emit_current_tag()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                return False
            if c == "/":
                self.state = self.SELF_CLOSING_START_TAG
                return False
            if c == "=":
                self.state = self.BEFORE_ATTRIBUTE_VALUE
                return False
            if c == ">":
                self._finish_attribute()
                if not self._emit_current_tag():
                    self.state = self.DATA
                return False
            self._finish_attribute()
            self._start_attribute()
            self._append_attr_name(c)
            self.state = self.ATTRIBUTE_NAME
            return False

    def _state_before_attribute_value(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF before attribute value")
                self._finish_attribute()
                self._emit_current_tag()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                return False
            if c == '"':
                self.state = self.ATTRIBUTE_VALUE_DOUBLE
                return False
            if c == "'":
                self.state = self.ATTRIBUTE_VALUE_SINGLE
                return False
            if c == ">":
                self._emit_error("Missing attribute value")
                self._finish_attribute()
                if not self._emit_current_tag():
                    self.state = self.DATA
                return False
            self._reconsume_current()
            self.state = self.ATTRIBUTE_VALUE_UNQUOTED
            return False

    def _state_attribute_value_double(self):
        replacement = "\ufffd"
        stop_pattern = _ATTR_VALUE_DOUBLE_PATTERN
        while True:
            if self._consume_attribute_value_run(stop_pattern):
                continue
            c = self._get_char()
            if c is None:
                # Per HTML5 spec: EOF in attribute value is a parse error
                # The incomplete tag is discarded (not emitted)
                self._emit_error("EOF in attribute value")
                self._emit_token(EOFToken())
                return True
            if c == '"':
                self.state = self.AFTER_ATTRIBUTE_NAME
                return False
            if c == "&":
                self.current_attr_value.append("&")
                self.current_attr_value_has_amp = True
                continue
            if c == "\0":
                self._emit_error("Null in attribute value")
                self.current_attr_value.append(replacement)
                continue
            self.current_attr_value.append(c)

    def _state_attribute_value_single(self):
        replacement = "\ufffd"
        stop_pattern = _ATTR_VALUE_SINGLE_PATTERN
        while True:
            if self._consume_attribute_value_run(stop_pattern):
                continue
            c = self._get_char()
            if c is None:
                # Per HTML5 spec: EOF in attribute value is a parse error
                # The incomplete tag is discarded (not emitted)
                self._emit_error("EOF in attribute value")
                self._emit_token(EOFToken())
                return True
            if c == "'":
                self.state = self.AFTER_ATTRIBUTE_NAME
                return False
            if c == "&":
                self.current_attr_value.append("&")
                self.current_attr_value_has_amp = True
                continue
            if c == "\0":
                self._emit_error("Null in attribute value")
                self.current_attr_value.append(replacement)
                continue
            self.current_attr_value.append(c)

    def _state_attribute_value_unquoted(self):
        replacement = "\ufffd"
        stop_pattern = _ATTR_VALUE_UNQUOTED_PATTERN
        while True:
            if self._consume_attribute_value_run(stop_pattern):
                continue
            c = self._get_char()
            if c is None:
                # Per HTML5 spec: EOF in attribute value is a parse error
                # The incomplete tag is discarded (not emitted)
                self._emit_error("EOF in attribute value")
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                self._finish_attribute()
                self.state = self.BEFORE_ATTRIBUTE_NAME
                return False
            if c == ">":
                self._finish_attribute()
                if not self._emit_current_tag():
                    self.state = self.DATA
                return False
            if c == "&":
                self.current_attr_value.append("&")
                self.current_attr_value_has_amp = True
                continue
            if c in ('"', "'", "<", "=", "`"):
                self._emit_error("Invalid character in unquoted attribute value")
            if c == "\0":
                self._emit_error("Null in attribute value")
                self.current_attr_value.append(replacement)
                continue
            self.current_attr_value.append(c)

    def _state_self_closing_start_tag(self):
        c = self._get_char()
        if c is None:
            self._emit_error("EOF in self-closing tag")
            self._finish_attribute()
            self._emit_current_tag()
            self._emit_token(EOFToken())
            return True
        if c == ">":
            self.current_tag_self_closing = True
            self._emit_current_tag()
            self.state = self.DATA
            return False
        self._emit_error("Unexpected character after '/' in tag")
        self._reconsume_current()
        self.state = self.BEFORE_ATTRIBUTE_NAME
        return False

    def _state_markup_declaration_open(self):
        if self._consume_if("--"):
            self.current_comment.clear()
            self.state = self.COMMENT_START
            return False
        if self._consume_case_insensitive("DOCTYPE"):
            self.current_doctype_name.clear()
            self.current_doctype_public.clear()
            self.current_doctype_system.clear()
            self.current_doctype_force_quirks = False
            self.state = self.DOCTYPE
            return False
        if self._consume_if("[CDATA["):
            # CDATA sections are only valid in foreign content (SVG/MathML)
            # Check if the adjusted current node is in a foreign namespace
            is_foreign = False
            if self.sink.open_elements:
                current = self.sink.open_elements[-1]
                if current.namespace not in {None, "html"}:
                    is_foreign = True

            if is_foreign:
                # Proper CDATA section in foreign content
                self.state = self.CDATA_SECTION
                return False
            # Treat as bogus comment in HTML context, preserving "[CDATA[" prefix
            self._emit_error("CDATA section outside foreign content")
            self.current_comment.clear()
            # Add the consumed "[CDATA[" text to the comment
            for ch in "[CDATA[":
                self.current_comment.append(ch)
            self.state = self.BOGUS_COMMENT
            return False
        self._emit_error("Invalid markup declaration")
        self.current_comment.clear()
        # Don't reconsume - bogus comment starts from current position
        self.state = self.BOGUS_COMMENT
        return False

    def _state_comment_start(self):
        replacement = "\ufffd"
        c = self._get_char()
        if c is None:
            self._emit_error("EOF in comment")
            self._emit_comment()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.state = self.COMMENT_START_DASH
            return False
        if c == ">":
            self._emit_error("Abrupt comment end")
            self._emit_comment()
            self.state = self.DATA
            return False
        if c == "\0":
            self._emit_error("Null in comment")
            self.current_comment.append(replacement)
        else:
            self.current_comment.append(c)
        self.state = self.COMMENT
        return False

    def _state_comment_start_dash(self):
        replacement = "\ufffd"
        c = self._get_char()
        if c is None:
            self._emit_error("EOF in comment")
            self._emit_comment()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.state = self.COMMENT_END
            return False
        if c == ">":
            self._emit_error("Abrupt comment end")
            self._emit_comment()
            self.state = self.DATA
            return False
        if c == "\0":
            self._emit_error("Null in comment")
            self.current_comment.append("-")
            self.current_comment.append(replacement)
        else:
            self.current_comment.append("-")
            self.current_comment.append(c)
        self.state = self.COMMENT
        return False

    def _state_comment(self):
        replacement = "\ufffd"
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in comment")
                self._emit_comment()
                self._emit_token(EOFToken())
                return True
            if c == "-":
                self.state = self.COMMENT_END_DASH
                return False
            if c == "\0":
                self._emit_error("Null in comment")
                self.current_comment.append(replacement)
                continue
            self.current_comment.append(c)

    def _state_comment_end_dash(self):
        replacement = "\ufffd"
        c = self._get_char()
        if c is None:
            self._emit_error("EOF in comment")
            self._emit_comment()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.state = self.COMMENT_END
            return False
        if c == "\0":
            self._emit_error("Null in comment")
            self.current_comment.append("-")
            self.current_comment.append(replacement)
            self.state = self.COMMENT
            return False
        if c == ">":
            self._emit_error("Abrupt comment end")
            self._emit_comment()
            self.state = self.DATA
            return False
        self.current_comment.append("-")
        self.current_comment.append(c)
        self.state = self.COMMENT
        return False

    def _state_comment_end(self):
        replacement = "\ufffd"
        c = self._get_char()
        if c is None:
            self._emit_error("EOF in comment")
            self._emit_comment()
            self._emit_token(EOFToken())
            return True
        if c == ">":
            self._emit_comment()
            self.state = self.DATA
            return False
        if c == "!":
            self.state = self.COMMENT_END_BANG
            return False
        if c == "-":
            self.current_comment.append("-")
            return False
        if c == "\0":
            self._emit_error("Null in comment")
            self.current_comment.append("-")
            self.current_comment.append("-")
            self.current_comment.append(replacement)
            self.state = self.COMMENT
            return False
        self._emit_error("Comment not properly closed")
        self.current_comment.append("-")
        self.current_comment.append("-")
        self.current_comment.append(c)
        self.state = self.COMMENT
        return False

    def _state_comment_end_bang(self):
        replacement = "\ufffd"
        c = self._get_char()
        if c is None:
            self._emit_error("EOF in comment")
            self._emit_comment()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.current_comment.append("-")
            self.current_comment.append("-")
            self.current_comment.append("!")
            self.state = self.COMMENT_END_DASH
            return False
        if c == ">":
            self._emit_error("Comment ended with !")
            self._emit_comment()
            self.state = self.DATA
            return False
        if c == "\0":
            self._emit_error("Null in comment")
            self.current_comment.append("-")
            self.current_comment.append("-")
            self.current_comment.append("!")
            self.current_comment.append(replacement)
            self.state = self.COMMENT
            return False
        self.current_comment.append("-")
        self.current_comment.append("-")
        self.current_comment.append("!")
        self.current_comment.append(c)
        self.state = self.COMMENT
        return False

    def _state_bogus_comment(self):
        replacement = "\ufffd"
        while True:
            c = self._get_char()
            if c is None:
                self._emit_comment()
                self._emit_token(EOFToken())
                return True
            if c == ">":
                self._emit_comment()
                self.state = self.DATA
                return False
            if c == "\0":
                self.current_comment.append(replacement)
            else:
                self.current_comment.append(c)

    def _state_doctype(self):
        c = self._get_char()
        if c is None:
            self._emit_error("EOF in DOCTYPE")
            self.current_doctype_force_quirks = True
            self._emit_doctype()
            self._emit_token(EOFToken())
            return True
        if c in ("\t", "\n", "\f", " "):
            self.state = self.BEFORE_DOCTYPE_NAME
            return False
        if c == ">":
            self._emit_error("Missing DOCTYPE name")
            self.current_doctype_force_quirks = True
            self._emit_doctype()
            self.state = self.DATA
            return False
        self._reconsume_current()
        self.state = self.BEFORE_DOCTYPE_NAME
        return False

    def _state_before_doctype_name(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in DOCTYPE name")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                return False
            if c == ">":
                self._emit_error("Missing DOCTYPE name")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            if "A" <= c <= "Z":
                self.current_doctype_name.append(chr(ord(c) + 32))
            elif c == "\0":
                self._emit_error("Null in DOCTYPE name")
                self.current_doctype_name.append("\ufffd")
            else:
                self.current_doctype_name.append(c)
            self.state = self.DOCTYPE_NAME
            return False

    def _state_doctype_name(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in DOCTYPE name")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                self.state = self.AFTER_DOCTYPE_NAME
                return False
            if c == ">":
                self._emit_doctype()
                self.state = self.DATA
                return False
            if "A" <= c <= "Z":
                self.current_doctype_name.append(chr(ord(c) + 32))
                continue
            if c == "\0":
                self._emit_error("Null in DOCTYPE name")
                self.current_doctype_name.append("\ufffd")
                continue
            self.current_doctype_name.append(c)

    def _state_after_doctype_name(self):
        if self._consume_case_insensitive("PUBLIC"):
            self.state = self.AFTER_DOCTYPE_PUBLIC_KEYWORD
            return False
        if self._consume_case_insensitive("SYSTEM"):
            self.state = self.AFTER_DOCTYPE_SYSTEM_KEYWORD
            return False
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in DOCTYPE")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                continue
            if c == ">":
                self._emit_doctype()
                self.state = self.DATA
                return False
            self._emit_error("Unexpected token after DOCTYPE name")
            self.current_doctype_force_quirks = True
            self._reconsume_current()
            self.state = self.BOGUS_DOCTYPE
            return False

    def _state_after_doctype_public_keyword(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF after DOCTYPE public keyword")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                self.state = self.BEFORE_DOCTYPE_PUBLIC_IDENTIFIER
                return False
            if c == '"':
                self._emit_error("Missing whitespace before DOCTYPE public identifier")
                self.current_doctype_public.clear()
                self.state = self.DOCTYPE_PUBLIC_IDENTIFIER_DOUBLE_QUOTED
                return False
            if c == "'":
                self._emit_error("Missing whitespace before DOCTYPE public identifier")
                self.current_doctype_public.clear()
                self.state = self.DOCTYPE_PUBLIC_IDENTIFIER_SINGLE_QUOTED
                return False
            if c == ">":
                self._emit_error("Missing DOCTYPE public identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            self._emit_error("Unexpected character after DOCTYPE public keyword")
            self.current_doctype_force_quirks = True
            self._reconsume_current()
            self.state = self.BOGUS_DOCTYPE
            return False

    def _state_after_doctype_system_keyword(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF after DOCTYPE system keyword")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                self.state = self.BEFORE_DOCTYPE_SYSTEM_IDENTIFIER
                return False
            if c == '"':
                self._emit_error("Missing whitespace before DOCTYPE system identifier")
                self.current_doctype_system.clear()
                self.state = self.DOCTYPE_SYSTEM_IDENTIFIER_DOUBLE_QUOTED
                return False
            if c == "'":
                self._emit_error("Missing whitespace before DOCTYPE system identifier")
                self.current_doctype_system.clear()
                self.state = self.DOCTYPE_SYSTEM_IDENTIFIER_SINGLE_QUOTED
                return False
            if c == ">":
                self._emit_error("Missing DOCTYPE system identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            self._emit_error("Unexpected character after DOCTYPE system keyword")
            self.current_doctype_force_quirks = True
            self._reconsume_current()
            self.state = self.BOGUS_DOCTYPE
            return False

    def _state_before_doctype_public_identifier(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF before DOCTYPE public identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                continue
            if c == '"':
                self.current_doctype_public.clear()
                self.state = self.DOCTYPE_PUBLIC_IDENTIFIER_DOUBLE_QUOTED
                return False
            if c == "'":
                self.current_doctype_public.clear()
                self.state = self.DOCTYPE_PUBLIC_IDENTIFIER_SINGLE_QUOTED
                return False
            if c == ">":
                self._emit_error("Missing DOCTYPE public identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            self._emit_error("Invalid DOCTYPE public identifier start")
            self.current_doctype_force_quirks = True
            self._reconsume_current()
            self.state = self.BOGUS_DOCTYPE
            return False

    def _state_doctype_public_identifier_double_quoted(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in DOCTYPE public identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c == '"':
                self.state = self.AFTER_DOCTYPE_PUBLIC_IDENTIFIER
                return False
            if c == "\0":
                self._emit_error("Null in DOCTYPE public identifier")
                self.current_doctype_public.append("\ufffd")
                continue
            if c == ">":
                self._emit_error("Abrupt DOCTYPE public identifier end")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            self.current_doctype_public.append(c)

    def _state_doctype_public_identifier_single_quoted(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in DOCTYPE public identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c == "'":
                self.state = self.AFTER_DOCTYPE_PUBLIC_IDENTIFIER
                return False
            if c == "\0":
                self._emit_error("Null in DOCTYPE public identifier")
                self.current_doctype_public.append("\ufffd")
                continue
            if c == ">":
                self._emit_error("Abrupt DOCTYPE public identifier end")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            self.current_doctype_public.append(c)

    def _state_after_doctype_public_identifier(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF after DOCTYPE public identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                self.state = self.BETWEEN_DOCTYPE_PUBLIC_AND_SYSTEM_IDENTIFIERS
                return False
            if c == ">":
                self._emit_doctype()
                self.state = self.DATA
                return False
            if c == '"':
                self._emit_error("Missing whitespace between DOCTYPE public and system identifiers")
                self.current_doctype_system.clear()
                self.state = self.DOCTYPE_SYSTEM_IDENTIFIER_DOUBLE_QUOTED
                return False
            if c == "'":
                self._emit_error("Missing whitespace between DOCTYPE public and system identifiers")
                self.current_doctype_system.clear()
                self.state = self.DOCTYPE_SYSTEM_IDENTIFIER_SINGLE_QUOTED
                return False
            self._emit_error("Unexpected character after DOCTYPE public identifier")
            self.current_doctype_force_quirks = True
            self._reconsume_current()
            self.state = self.BOGUS_DOCTYPE
            return False

    def _state_between_doctype_public_and_system_identifiers(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF between DOCTYPE identifiers")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                continue
            if c == ">":
                self._emit_doctype()
                self.state = self.DATA
                return False
            if c == '"':
                self.current_doctype_system.clear()
                self.state = self.DOCTYPE_SYSTEM_IDENTIFIER_DOUBLE_QUOTED
                return False
            if c == "'":
                self.current_doctype_system.clear()
                self.state = self.DOCTYPE_SYSTEM_IDENTIFIER_SINGLE_QUOTED
                return False
            self._emit_error("Unexpected character between DOCTYPE identifiers")
            self.current_doctype_force_quirks = True
            self._reconsume_current()
            self.state = self.BOGUS_DOCTYPE
            return False

    def _state_before_doctype_system_identifier(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF before DOCTYPE system identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                continue
            if c == '"':
                self.current_doctype_system.clear()
                self.state = self.DOCTYPE_SYSTEM_IDENTIFIER_DOUBLE_QUOTED
                return False
            if c == "'":
                self.current_doctype_system.clear()
                self.state = self.DOCTYPE_SYSTEM_IDENTIFIER_SINGLE_QUOTED
                return False
            if c == ">":
                self._emit_error("Missing DOCTYPE system identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            self._emit_error("Invalid DOCTYPE system identifier start")
            self.current_doctype_force_quirks = True
            self._reconsume_current()
            self.state = self.BOGUS_DOCTYPE
            return False

    def _state_doctype_system_identifier_double_quoted(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in DOCTYPE system identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c == '"':
                self.state = self.AFTER_DOCTYPE_SYSTEM_IDENTIFIER
                return False
            if c == "\0":
                self._emit_error("Null in DOCTYPE system identifier")
                self.current_doctype_system.append("\ufffd")
                continue
            if c == ">":
                self._emit_error("Abrupt DOCTYPE system identifier end")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            self.current_doctype_system.append(c)

    def _state_doctype_system_identifier_single_quoted(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF in DOCTYPE system identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c == "'":
                self.state = self.AFTER_DOCTYPE_SYSTEM_IDENTIFIER
                return False
            if c == "\0":
                self._emit_error("Null in DOCTYPE system identifier")
                self.current_doctype_system.append("\ufffd")
                continue
            if c == ">":
                self._emit_error("Abrupt DOCTYPE system identifier end")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self.state = self.DATA
                return False
            self.current_doctype_system.append(c)

    def _state_after_doctype_system_identifier(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("EOF after DOCTYPE system identifier")
                self.current_doctype_force_quirks = True
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c in ("\t", "\n", "\f", " "):
                continue
            if c == ">":
                self._emit_doctype()
                self.state = self.DATA
                return False
            self._emit_error("Unexpected character after DOCTYPE system identifier")
            self.current_doctype_force_quirks = True
            self._reconsume_current()
            self.state = self.BOGUS_DOCTYPE
            return False

    def _state_bogus_doctype(self):
        while True:
            c = self._get_char()
            if c is None:
                self._emit_doctype()
                self._emit_token(EOFToken())
                return True
            if c == ">":
                self._emit_doctype()
                self.state = self.DATA
                return False

    # ---------------------
    # Low-level helpers
    # ---------------------

    def _get_char(self):
        if self.reconsume:
            self.reconsume = False
            return self.current_char

        while True:
            if self.pos >= self.length:
                self.current_char = None
                return None

            c = self.buffer[self.pos]
            self.pos += 1

            if c == "\r":
                self.ignore_lf = True
                self.current_char = "\n"
                self.line += 1
                return "\n"

            if c == "\n":
                if self.ignore_lf:
                    self.ignore_lf = False
                    continue
                self.line += 1

            else:
                self.ignore_lf = False

            self.current_char = c
            return c

    def _reconsume_current(self):
        self.reconsume = True

    def _flush_text(self):
        if not self.text_buffer:
            return
        data = "".join(self.text_buffer)
        self.text_buffer.clear()
        if data:
            # Per HTML5 spec:
            # - RCDATA elements (title, textarea) decode character references
            # - RAWTEXT elements (style, script, etc) do NOT decode
            # - PLAINTEXT state does NOT decode
            # Our tokenizer uses RAWTEXT state for both RCDATA and RAWTEXT elements
            # so we check the tag name to determine the correct behavior
            if self.state >= self.PLAINTEXT:
                self._emit_token(CharacterTokens(data))
            elif self.state >= self.RAWTEXT and self.rawtext_tag_name not in _RCDATA_ELEMENTS:
                self._emit_token(CharacterTokens(data))
            else:
                if "&" in data:
                    data = decode_entities_in_text(data)
                self._emit_token(CharacterTokens(data))

    def _start_tag(self, kind):
        self.current_tag_kind = kind
        self.current_tag_name.clear()
        self.current_tag_attrs.clear()
        self.current_attr_names.clear()
        self.current_attr_name.clear()
        self.current_attr_value.clear()
        self.current_attr_value_has_amp = False
        self.current_tag_self_closing = False

    def _start_attribute(self):
        self.current_attr_name.clear()
        self.current_attr_value.clear()
        self.current_attr_value_has_amp = False

    def _append_tag_name(self, c):
        if "A" <= c <= "Z":
            c = chr(ord(c) + 32)
        self.current_tag_name.append(c)

    def _append_attr_name(self, c):
        if "A" <= c <= "Z":
            c = chr(ord(c) + 32)
        self.current_attr_name.append(c)

    def _finish_attribute(self):
        attr_name_buffer = self.current_attr_name
        if not attr_name_buffer:
            self.current_attr_value.clear()
            self.current_attr_value_has_amp = False
            return
        if len(attr_name_buffer) == 1:
            name = attr_name_buffer[0]
        else:
            name = "".join(attr_name_buffer)
        attr_value_buffer = self.current_attr_value
        if not attr_value_buffer:
            value = ""
        elif len(attr_value_buffer) == 1:
            value = attr_value_buffer[0]
        else:
            value = "".join(attr_value_buffer)
        if self.current_attr_value_has_amp:
            value = decode_entities_in_text(value, in_attribute=True)
        attr_names = self.current_attr_names
        is_duplicate = False
        for existing in attr_names:
            if existing == name:
                is_duplicate = True
                break
        if is_duplicate:
            self._emit_error("Duplicate attribute")
        else:
            attr_names.append(name)
            self.current_tag_attrs.extend((name, value))
        attr_name_buffer.clear()
        attr_value_buffer.clear()
        self.current_attr_value_has_amp = False

    def _append_text_chunk(self, chunk, *, ends_with_cr=False):
        if not chunk:
            self.ignore_lf = ends_with_cr
            return
        if self.ignore_lf:
            if chunk[0] == "\n":
                chunk = chunk[1:]
                if not chunk:
                    self.ignore_lf = ends_with_cr
                    return
            self.ignore_lf = False
        if "\r" in chunk:
            chunk = chunk.replace("\r\n", "\n").replace("\r", "\n")
        newlines = chunk.count("\n")
        if newlines:
            self.line += newlines
        self.text_buffer.append(chunk)
        self.ignore_lf = ends_with_cr

    def _consume_attribute_value_run(self, stop_pattern):
        if self.reconsume:
            return False
        pos = self.pos
        length = self.length
        if pos >= length:
            return False
        match = stop_pattern.search(self.buffer, pos)
        if match:
            end = match.start()
            if end == pos:
                return False
        else:
            end = length
            if end == pos:
                return False
        self.current_attr_value.append(self.buffer[pos:end])
        self.pos = end
        return True

    def _consume_attribute_name_run(self):
        if self.reconsume:
            return False
        pos = self.pos
        length = self.length
        if pos >= length:
            return False
        match = _ATTR_NAME_TERMINATOR_PATTERN.search(self.buffer, pos)
        if match:
            end = match.start()
            if end == pos:
                return False
        else:
            end = length
            if end == pos:
                return False
        chunk = self.buffer[pos:end]
        if chunk:
            self.current_attr_name.append(chunk.translate(_ASCII_LOWER_TABLE))
        self.pos = end
        return True

    def _emit_current_tag(self):
        self._finish_attribute()
        name = "".join(self.current_tag_name)
        if name:
            name = sys.intern(name)
        attrs = self.current_tag_attrs
        self.current_tag_attrs = []
        tag = self._tag_token
        tag.kind = self.current_tag_kind
        tag.name = name
        tag.attrs = attrs
        tag.self_closing = self.current_tag_self_closing
        switched_to_rawtext = False
        if self.current_tag_kind == Tag.START:
            self.last_start_tag_name = name
            # Only switch to RAWTEXT for these elements in HTML context (not SVG/MathML).
            # Check if we're in foreign content by looking at open_elements.
            current_node = self.sink.open_elements[-1] if self.sink.open_elements else None
            in_foreign = bool(current_node and current_node.namespace not in {None, "html"})
            if not in_foreign and name in (
                "script",
                "style",
                "xmp",
                "iframe",
                "noembed",
                "noframes",
                "noscript",
                "textarea",
                "title",
            ):
                self.state = self.RAWTEXT
                self.rawtext_tag_name = name
                switched_to_rawtext = True
            # PLAINTEXT: everything after is text (no end tag, no parsing)
            if not in_foreign and name == "plaintext":
                self.state = self.PLAINTEXT
                switched_to_rawtext = True
        # Remember current state before emitting
        state_before_emit = self.state
        self._emit_token(tag)
        # Check if tree builder changed the state (e.g., for plaintext in HTML integration points)
        if self.state != state_before_emit:
            switched_to_rawtext = True
        self.current_tag_name.clear()
        self.current_tag_attrs.clear()
        self.current_attr_name.clear()
        self.current_attr_value.clear()
        self.current_tag_self_closing = False
        self.current_tag_kind = Tag.START
        return switched_to_rawtext

    def _emit_comment(self):
        data = "".join(self.current_comment)
        self.current_comment.clear()
        self._emit_token(CommentToken(data))

    def _emit_doctype(self):
        name = "".join(self.current_doctype_name) if self.current_doctype_name else None
        public_id = "".join(self.current_doctype_public) if self.current_doctype_public else None
        system_id = "".join(self.current_doctype_system) if self.current_doctype_system else None
        doctype = Doctype(
            name=name, public_id=public_id, system_id=system_id, force_quirks=self.current_doctype_force_quirks,
        )
        self.current_doctype_name.clear()
        self.current_doctype_public.clear()
        self.current_doctype_system.clear()
        self.current_doctype_force_quirks = False
        self._emit_token(DoctypeToken(doctype))

    def _emit_token(self, token):
        result = self.sink.process_token(token)
        if result == TokenSinkResult.Plaintext:
            self.state = self.PLAINTEXT
        elif result == TokenSinkResult.RawData:
            self.state = self.DATA
        elif result == TokenSinkResult.Script:
            self.state = self.DATA

    def _emit_error(self, message):
        if self.opts.exact_errors:
            self._emit_token(ParseError(message))

    def _consume_if(self, literal):
        end = self.pos + len(literal)
        if end > self.length:
            return False
        segment = self.buffer[self.pos : end]
        if segment != literal:
            return False
        self.pos = end
        return True

    def _consume_case_insensitive(self, literal):
        end = self.pos + len(literal)
        if end > self.length:
            return False
        segment = self.buffer[self.pos : end]
        if segment.lower() != literal.lower():
            return False
        self.pos = end
        return True

    def _state_cdata_section(self):
        # CDATA section state - consume characters until we see ']'
        while True:
            c = self._get_char()
            if c is None:
                self._emit_error("eof-in-cdata")
                self._flush_text()
                self._emit_token(EOFToken())
                return True
            if c == "]":
                self.state = self.CDATA_SECTION_BRACKET
                return False
            self.text_buffer.append(c)

    def _state_cdata_section_bracket(self):
        # Seen one ']', check for second ']'
        c = self._get_char()
        if c == "]":
            self.state = self.CDATA_SECTION_END
            return False
        # False alarm, emit the ']' we saw and continue
        self.text_buffer.append("]")
        if c is None:
            self._emit_error("eof-in-cdata")
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        self._reconsume_current()
        self.state = self.CDATA_SECTION
        return False

    def _state_cdata_section_end(self):
        # Seen ']]', check for '>'
        c = self._get_char()
        if c == ">":
            # End of CDATA section
            self._flush_text()
            self.state = self.DATA
            return False
        # Not the end - we saw ']]' but not '>'. Emit one ']' and check if the next char is another ']'
        self.text_buffer.append("]")
        if c is None:
            # EOF after ']]' - emit the second ']' too
            self.text_buffer.append("]")
            self._emit_error("eof-in-cdata")
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c == "]":
            # Still might be ']]>' sequence, stay in CDATA_SECTION_END
            return False
        # Not a bracket, so emit the second ']', reconsume current char and go back to CDATA_SECTION
        self.text_buffer.append("]")
        self._reconsume_current()
        self.state = self.CDATA_SECTION
        return False

    def _state_rawtext(self):
        buffer = self.buffer
        length = self.length
        pos = self.pos
        while True:
            if self.reconsume:
                self.reconsume = False
                c = self.current_char
                if c is None:
                    self._flush_text()
                    self._emit_token(EOFToken())
                    return True
                if c == "<":
                    if self.rawtext_tag_name == "script":
                        next1 = self._peek_char(0)
                        next2 = self._peek_char(1)
                        next3 = self._peek_char(2)
                        if next1 == "!" and next2 == "-" and next3 == "-":
                            self.text_buffer.extend(["<", "!", "-", "-"])
                            self._get_char()
                            self._get_char()
                            self._get_char()
                            self.state = self.SCRIPT_DATA_ESCAPED
                            return False
                    self.state = self.RAWTEXT_LESS_THAN_SIGN
                    return False
                if c == "\0":
                    self._emit_error("Null character in rawtext")
                    self.text_buffer.append("\ufffd")
                else:
                    self._append_text_chunk(c, ends_with_cr=(c == "\r"))
                pos = self.pos
                continue
            lt_index = buffer.find("<", pos)
            null_index = buffer.find("\0", pos)
            next_special = lt_index if lt_index != -1 else length
            if null_index != -1 and null_index < next_special:
                if null_index > pos:
                    chunk = buffer[pos:null_index]
                    self._append_text_chunk(chunk, ends_with_cr=chunk.endswith("\r"))
                else:
                    self.ignore_lf = False
                self._emit_error("Null character in rawtext")
                self.text_buffer.append("\ufffd")
                pos = null_index + 1
                self.pos = pos
                continue
            if lt_index == -1:
                if pos < length:
                    chunk = buffer[pos:length]
                    if chunk:
                        self._append_text_chunk(chunk, ends_with_cr=chunk.endswith("\r"))
                    else:
                        self.ignore_lf = False
                self.pos = length
                self._flush_text()
                self._emit_token(EOFToken())
                return True
            if lt_index > pos:
                chunk = buffer[pos:lt_index]
                self._append_text_chunk(chunk, ends_with_cr=chunk.endswith("\r"))
            pos = lt_index + 1
            self.pos = pos
            # Handle script escaped transition before treating '<' as markup boundary
            if self.rawtext_tag_name == "script":
                next1 = self._peek_char(0)
                next2 = self._peek_char(1)
                next3 = self._peek_char(2)
                if next1 == "!" and next2 == "-" and next3 == "-":
                    self.text_buffer.extend(["<", "!", "-", "-"])
                    self._get_char()
                    self._get_char()
                    self._get_char()
                    self.state = self.SCRIPT_DATA_ESCAPED
                    return False
            self.state = self.RAWTEXT_LESS_THAN_SIGN
            return False

    def _state_rawtext_less_than_sign(self):
        c = self._get_char()
        if c == "/":
            self.current_tag_name.clear()
            self.state = self.RAWTEXT_END_TAG_OPEN
            return False
        self.text_buffer.append("<")
        self._reconsume_current()
        self.state = self.RAWTEXT
        return False

    def _state_rawtext_end_tag_open(self):
        c = self._get_char()
        if c and c.isalpha():
            self.current_tag_name.append(c.lower())
            self.original_tag_name.append(c)
            self.state = self.RAWTEXT_END_TAG_NAME
            return False
        self.text_buffer.append("<")
        self.text_buffer.append("/")
        self._reconsume_current()
        self.state = self.RAWTEXT
        return False

    def _state_rawtext_end_tag_name(self):
        # Check if this matches the opening tag name
        while True:
            c = self._get_char()
            if c and c.isalpha():
                self.current_tag_name.append(c.lower())
                self.original_tag_name.append(c)
                continue
            # End of tag name - check if it matches
            tag_name = "".join(self.current_tag_name)
            if tag_name == self.rawtext_tag_name and c in (" ", "\t", "\n", "\r", "\f", "/", ">"):
                # Valid end tag - emit it
                if c == ">":
                    attrs = []
                    tag = Tag(Tag.END, tag_name, attrs, False)
                    self._flush_text()
                    self._emit_token(tag)
                    self.state = self.DATA
                    self.rawtext_tag_name = None
                    self.original_tag_name.clear()
                    return False
                if c in (" ", "\t", "\n", "\r", "\f"):
                    # Whitespace after tag name - switch to BEFORE_ATTRIBUTE_NAME
                    self.current_tag_kind = Tag.END
                    self.current_tag_attrs.clear()
                    self.state = self.BEFORE_ATTRIBUTE_NAME
                    return False
                if c == "/":
                    self._flush_text()
                    self.current_tag_kind = Tag.END
                    self.current_tag_attrs.clear()
                    self.state = self.SELF_CLOSING_START_TAG
                    return False
            # If we hit EOF or tag doesn't match, emit as text
            if c is None:
                # EOF - emit incomplete tag as text (preserve original case) then EOF
                self.text_buffer.append("<")
                self.text_buffer.append("/")
                for ch in self.original_tag_name:
                    self.text_buffer.append(ch)
                self.current_tag_name.clear()
                self.original_tag_name.clear()
                self._flush_text()
                self._emit_token(EOFToken())
                return True
            # Not a matching end tag - emit as text (preserve original case)
            self.text_buffer.append("<")
            self.text_buffer.append("/")
            for ch in self.original_tag_name:
                self.text_buffer.append(ch)
            self.current_tag_name.clear()
            self.original_tag_name.clear()
            self._reconsume_current()
            self.state = self.RAWTEXT
            return False

    def _state_plaintext(self):
        # PLAINTEXT state - consume everything as text, no end tag
        if self.pos < self.length:
            remaining = self.buffer[self.pos :]
            # Replace null bytes with replacement character
            if "\0" in remaining:
                remaining = remaining.replace("\0", "\ufffd")
                self._emit_error("Null character in plaintext")
            self.text_buffer.append(remaining)
            self.pos = self.length
        self._flush_text()
        self._emit_token(EOFToken())
        return True

    def _state_script_data_escaped(self):
        c = self._get_char()
        if c is None:
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.text_buffer.append("-")
            self.state = self.SCRIPT_DATA_ESCAPED_DASH
            return False
        if c == "<":
            self.state = self.SCRIPT_DATA_ESCAPED_LESS_THAN_SIGN
            return False
        if c == "\0":
            self._emit_error("unexpected-null-character")
            self.text_buffer.append("\ufffd")
            return False
        self.text_buffer.append(c)
        return False

    def _state_script_data_escaped_dash(self):
        c = self._get_char()
        if c is None:
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.text_buffer.append("-")
            self.state = self.SCRIPT_DATA_ESCAPED_DASH_DASH
            return False
        if c == "<":
            self.state = self.SCRIPT_DATA_ESCAPED_LESS_THAN_SIGN
            return False
        if c == "\0":
            self._emit_error("unexpected-null-character")
            self.text_buffer.append("\ufffd")
            self.state = self.SCRIPT_DATA_ESCAPED
            return False
        self.text_buffer.append(c)
        self.state = self.SCRIPT_DATA_ESCAPED
        return False

    def _state_script_data_escaped_dash_dash(self):
        c = self._get_char()
        if c is None:
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.text_buffer.append("-")
            return False
        if c == "<":
            self.state = self.SCRIPT_DATA_ESCAPED_LESS_THAN_SIGN
            return False
        if c == ">":
            self.text_buffer.append(">")
            self.state = self.RAWTEXT
            return False
        if c == "\0":
            self._emit_error("unexpected-null-character")
            self.text_buffer.append("\ufffd")
            self.state = self.SCRIPT_DATA_ESCAPED
            return False
        self.text_buffer.append(c)
        self.state = self.SCRIPT_DATA_ESCAPED
        return False

    def _state_script_data_escaped_less_than_sign(self):
        c = self._get_char()
        if c == "/":
            self.temp_buffer.clear()
            self.state = self.SCRIPT_DATA_ESCAPED_END_TAG_OPEN
            return False
        if c and c.isalpha():
            self.temp_buffer.clear()
            self.text_buffer.append("<")
            self._reconsume_current()
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPE_START
            return False
        self.text_buffer.append("<")
        self._reconsume_current()
        self.state = self.SCRIPT_DATA_ESCAPED
        return False

    def _state_script_data_escaped_end_tag_open(self):
        c = self._get_char()
        if c and c.isalpha():
            self.current_tag_name.clear()
            self.original_tag_name.clear()
            self._reconsume_current()
            self.state = self.SCRIPT_DATA_ESCAPED_END_TAG_NAME
            return False
        self.text_buffer.append("<")
        self.text_buffer.append("/")
        self._reconsume_current()
        self.state = self.SCRIPT_DATA_ESCAPED
        return False

    def _state_script_data_escaped_end_tag_name(self):
        c = self._get_char()
        if c and c.isalpha():
            self.current_tag_name.append(c.lower())
            self.original_tag_name.append(c)
            self.temp_buffer.append(c)
            return False
        # Check if this is an appropriate end tag
        tag_name = "".join(self.current_tag_name)
        is_appropriate = tag_name == self.rawtext_tag_name

        if is_appropriate and c in (" ", "\t", "\n", "\r", "\f"):
            self.current_tag_kind = Tag.END
            self.current_tag_attrs.clear()
            self.state = self.BEFORE_ATTRIBUTE_NAME
            return False
        if is_appropriate and c == "/":
            self._flush_text()
            self.current_tag_kind = Tag.END
            self.current_tag_attrs.clear()
            self.state = self.SELF_CLOSING_START_TAG
            return False
        if is_appropriate and c == ">":
            self._flush_text()
            attrs = []
            tag = Tag(Tag.END, tag_name, attrs, False)
            self._emit_token(tag)
            self.state = self.DATA
            self.rawtext_tag_name = None
            self.current_tag_name.clear()
            self.original_tag_name.clear()
            return False
        # Not an appropriate end tag
        self.text_buffer.append("<")
        self.text_buffer.append("/")
        for ch in self.temp_buffer:
            self.text_buffer.append(ch)
        self._reconsume_current()
        self.state = self.SCRIPT_DATA_ESCAPED
        return False

    def _state_script_data_double_escape_start(self):
        c = self._get_char()
        if c in (" ", "\t", "\n", "\r", "\f", "/", ">"):
            # Check if temp_buffer contains "script"
            temp = "".join(self.temp_buffer).lower()
            if temp == "script":
                self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED
            else:
                self.state = self.SCRIPT_DATA_ESCAPED
            self.text_buffer.append(c)
            return False
        if c and c.isalpha():
            self.temp_buffer.append(c)
            self.text_buffer.append(c)
            return False
        self._reconsume_current()
        self.state = self.SCRIPT_DATA_ESCAPED
        return False

    def _state_script_data_double_escaped(self):
        c = self._get_char()
        if c is None:
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.text_buffer.append("-")
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED_DASH
            return False
        if c == "<":
            self.text_buffer.append("<")
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED_LESS_THAN_SIGN
            return False
        if c == "\0":
            self._emit_error("unexpected-null-character")
            self.text_buffer.append("\ufffd")
            return False
        self.text_buffer.append(c)
        return False

    def _state_script_data_double_escaped_dash(self):
        c = self._get_char()
        if c is None:
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.text_buffer.append("-")
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED_DASH_DASH
            return False
        if c == "<":
            self.text_buffer.append("<")
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED_LESS_THAN_SIGN
            return False
        if c == "\0":
            self._emit_error("unexpected-null-character")
            self.text_buffer.append("\ufffd")
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED
            return False
        self.text_buffer.append(c)
        self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED
        return False

    def _state_script_data_double_escaped_dash_dash(self):
        c = self._get_char()
        if c is None:
            self._flush_text()
            self._emit_token(EOFToken())
            return True
        if c == "-":
            self.text_buffer.append("-")
            return False
        if c == "<":
            self.text_buffer.append("<")
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED_LESS_THAN_SIGN
            return False
        if c == ">":
            self.text_buffer.append(">")
            self.state = self.RAWTEXT
            return False
        if c == "\0":
            self._emit_error("unexpected-null-character")
            self.text_buffer.append("\ufffd")
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED
            return False
        self.text_buffer.append(c)
        self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED
        return False

    def _state_script_data_double_escaped_less_than_sign(self):
        c = self._get_char()
        if c == "/":
            self.temp_buffer.clear()
            self.text_buffer.append("/")
            self.state = self.SCRIPT_DATA_DOUBLE_ESCAPE_END
            return False
        self._reconsume_current()
        self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED
        return False

    def _state_script_data_double_escape_end(self):
        c = self._get_char()
        if c in (" ", "\t", "\n", "\r", "\f", "/", ">"):
            # Check if temp_buffer contains "script"
            temp = "".join(self.temp_buffer).lower()
            if temp == "script":
                self.state = self.SCRIPT_DATA_ESCAPED
            else:
                self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED
            self.text_buffer.append(c)
            return False
        if c and c.isalpha():
            self.temp_buffer.append(c)
            self.text_buffer.append(c)
            return False
        self._reconsume_current()
        self.state = self.SCRIPT_DATA_DOUBLE_ESCAPED
        return False
