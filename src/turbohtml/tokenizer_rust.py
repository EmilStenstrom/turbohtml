"""Rust tokenizer wrapper for TurboHTML."""

import html

try:
    from rust_tokenizer import RustTokenizer as _RustTokenizer
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    _RustTokenizer = None

from turbohtml.constants import NUMERIC_ENTITY_INVALID_SENTINEL


def _allow_decode_without_semicolon_follow(entity_name, basic_entities):
    """Check if entity can be decoded without semicolon when followed by = or alnum."""
    if entity_name in basic_entities:
        return False
    return entity_name and entity_name[0].isupper() and len(entity_name) > 2


def _codepoint_to_char(codepoint):
    """Convert numeric HTML entity codepoint to character per HTML5 spec."""
    if codepoint == 0 or (0xD800 <= codepoint <= 0xDFFF) or codepoint > 0x10FFFF:
        return "\ufffd"
    replacements = {
        0x80: 0x20AC, 0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E, 0x85: 0x2026,
        0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02C6, 0x89: 0x2030, 0x8A: 0x0160,
        0x8B: 0x2039, 0x8C: 0x0152, 0x8E: 0x017D, 0x91: 0x2018, 0x92: 0x2019,
        0x93: 0x201C, 0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014,
        0x98: 0x02DC, 0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A, 0x9C: 0x0153,
        0x9E: 0x017E, 0x9F: 0x0178
    }
    codepoint = replacements.get(codepoint, codepoint)
    try:
        return chr(codepoint)
    except ValueError:
        return "\ufffd"


class RustTokenizerWrapper:
    """Wrapper around Rust tokenizer to provide compatibility with Python tokenizer interface."""

    # Constants for entity decoding (from Python tokenizer)
    _SEMICOLON_REQUIRED_IN_ATTR = frozenset(["prod"])
    _BASIC_ENTITIES = frozenset(["gt", "lt", "amp", "quot", "apos"])

    def __init__(self, html_str, debug=False):
        if not RUST_AVAILABLE:
            raise ImportError("Rust tokenizer not available. Install with: cd rust_tokenizer && maturin develop --release")

        self.tokenizer = _RustTokenizer(html_str, debug)
        self.debug_enabled = debug
        self.state = "Data"  # Compatibility attribute for Python parser
        self._plaintext_mode = False
        self._plaintext_yielded = False

    def __iter__(self):
        """Iterate over tokens from Rust tokenizer."""
        for token in self.tokenizer:
            # If in PLAINTEXT mode, consume everything else as text
            if self._plaintext_mode and not self._plaintext_yielded:
                # Serialize the current token to text
                remaining_text = self._serialize_token_to_text(token)

                # Collect all remaining tokens and serialize them
                for next_token in self.tokenizer:
                    remaining_text += self._serialize_token_to_text(next_token)

                # Create new Character token with all remaining text
                token.type_ = "Character"
                token.data = remaining_text
                token.tag_name = ""
                self._plaintext_yielded = True

                if self.debug_enabled:
                    self._debug_token(token)
                yield token
                return  # Stop iteration after PLAINTEXT content

            # Decode entities in Character tokens
            if hasattr(token, "type_") and token.type_ == "Character":
                if hasattr(token, "data") and token.data:
                    token.data = self._decode_entities(token.data)

            if self.debug_enabled:
                self._debug_token(token)
            yield token

    def _serialize_token_to_text(self, token):
        """Convert a token back to its HTML text representation."""
        if token.type_ == "Character":
            return token.data
        if token.type_ == "StartTag":
            text = f"<{token.tag_name}"
            if token.attributes:
                for key, value in token.attributes.items():
                    if value:
                        text += f' {key}="{value}"'
                    else:
                        text += f" {key}"
            if token.is_self_closing:
                text += " /"
            text += ">"
            return text
        if token.type_ == "EndTag":
            return f"</{token.tag_name}>"
        if token.type_ == "Comment":
            return f"<!--{token.data}-->"
        if token.type_ == "DOCTYPE":
            return f"<!DOCTYPE {token.data}>"
        return ""

    def _decode_entities(self, text, in_attribute=False):
        """Decode HTML entities in text according to HTML5 spec."""
        # Fast path: no entities at all
        if "&" not in text:
            return text

        result = []
        i = 0
        length = len(text)

        # Cache frequently used methods and constants
        result_append = result.append
        semicolon_required = self._SEMICOLON_REQUIRED_IN_ATTR
        basic_entities = self._BASIC_ENTITIES

        while i < length:
            if text[i] != "&":
                result_append(text[i])
                i += 1
                continue

            # Spec behavior: preserve literal '&gt' when immediately followed by alphanumeric (no semicolon)
            if (
                in_attribute
                and i + 3 < length
                and text[i:i+3] == "&gt"
                and text[i + 3].isalnum()
            ):
                result_append("&gt")
                i += 3
                continue

            # Numeric entity
            if i + 1 < length and text[i + 1] == "#":
                j = i + 2
                is_hex = False
                if j < length and text[j] in ("x", "X"):
                    is_hex = True
                    j += 1
                    start_digits = j
                    while j < length and text[j] in "0123456789abcdefABCDEF":
                        j += 1
                    digits = text[start_digits:j]
                else:
                    start_digits = j
                    while j < length and text[j].isdigit():
                        j += 1
                    digits = text[start_digits:j]
                if not digits:
                    result_append("&")
                    i += 1
                    continue
                has_semicolon = j < length and text[j] == ";"
                if has_semicolon:
                    j += 1
                base = 16 if is_hex else 10
                if digits:
                    codepoint = int(digits, base)
                    decoded_char = _codepoint_to_char(codepoint)
                    if decoded_char == "\ufffd":
                        decoded_char = NUMERIC_ENTITY_INVALID_SENTINEL
                    result_append(decoded_char)
                else:
                    result_append(text[i:j])
                i = j
                continue

            # Named entity
            j = i + 1
            while j < length and text[j].isalnum():
                j += 1
            name = text[i:j]
            has_semicolon = j < length and text[j] == ";"
            if has_semicolon:
                name += ";"
                j += 1
            decoded = html.unescape(name)
            if decoded != name:  # Found a named entity
                entity_name = name[1:-1] if has_semicolon else name[1:]
                if in_attribute and not has_semicolon:
                    next_char = text[j] if j < length else ""
                    if (
                        next_char
                        and (next_char.isalnum() or next_char == "=")
                        and not _allow_decode_without_semicolon_follow(entity_name, basic_entities)
                    ):
                        result_append("&")
                        i += 1
                        continue
                    if entity_name in semicolon_required and not has_semicolon:
                        result_append("&")
                        i += 1
                        continue
                result_append(decoded)
                i = j
                continue
            # Literal '&'
            result_append("&")
            i += 1
        return "".join(result)

    def start_rawtext(self, tag_name):
        """No-op for Rust tokenizer - RAWTEXT handling is automatic."""

    def start_plaintext(self):
        """Switch to PLAINTEXT mode: all subsequent content is consumed as character data."""
        self._plaintext_mode = True
        self._plaintext_yielded = False

    def _debug_token(self, token):
        """Print debug information about a token."""
        if token.type_ == "Character":
            preview = token.data[:20] if len(token.data) > 20 else token.data
            suffix = "..." if len(token.data) > 20 else ""
            print(f"Token: {token.type_} '{preview}{suffix}'")
        elif token.type_ == "Comment":
            preview = token.data[:20] if len(token.data) > 20 else token.data
            suffix = "..." if len(token.data) > 20 else ""
            print(f"Token: {token.type_} '{preview}{suffix}'")
        else:
            print(f"Token: {token.type_} {token.tag_name or token.data}")


def create_tokenizer(html_str, use_rust=False, debug=False):
    """
    Factory function to create a tokenizer.

    Args:
        html_str: HTML string to tokenize
        use_rust: If True, use Rust tokenizer (if available)
        debug: Enable debug output

    Returns:
        HTMLTokenizer (Python) or RustTokenizerWrapper
    """
    if use_rust:
        if not RUST_AVAILABLE:
            raise ImportError(
                "Rust tokenizer not available. "
                "Build it with: cd rust_tokenizer && maturin develop --release",
            )
        return RustTokenizerWrapper(html_str, debug)

    from turbohtml.tokenizer import HTMLTokenizer
    return HTMLTokenizer(html_str, debug)

