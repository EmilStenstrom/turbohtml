"""HTML entity decoding for TurboHTML.

Extracted from tokenizer to support Rust tokenizer's entity decoding needs.
Implements HTML5 spec-compliant character reference decoding.

Uses trie-based prefix matching for efficient named entity parsing: rejects
invalid entity prefixes early without reading unnecessary characters.
"""

import html

from turbohtml.constants import HTML5_NUMERIC_REPLACEMENTS, NUMERIC_ENTITY_INVALID_SENTINEL
from turbohtml.entity_trie import Trie


def _allow_decode_without_semicolon_follow(entity_name):
    """Check if entity can be decoded without semicolon when followed by = or alnum."""
    if entity_name in _BASIC_ENTITIES:
        return False
    return entity_name and entity_name[0].isupper() and len(entity_name) > 2


# Build trie once at module load time for O(1) initialization amortized across all parses
_ENTITIES_TRIE = Trie(html.entities.html5)


def _codepoint_to_char(codepoint):
    """Convert a numeric codepoint to character with HTML5 replacements."""
    if codepoint > 0x10FFFF:
        return "\ufffd"

    if 0xD800 <= codepoint <= 0xDFFF:
        return "\ufffd"

    if codepoint in HTML5_NUMERIC_REPLACEMENTS:
        return HTML5_NUMERIC_REPLACEMENTS[codepoint]

    if codepoint == 0x10FFFE:
        return "\U0010fffe"
    if codepoint == 0x10FFFF:
        return "\U0010ffff"
    return chr(codepoint)


# Pre-compute constants (outside function for better performance)
_SEMICOLON_REQUIRED = frozenset(["prod"])
_BASIC_ENTITIES = frozenset(["gt", "lt", "amp", "quot", "apos"])


def decode_entities(text, in_attribute=False):
    """Decode HTML entities in text according to HTML5 spec."""
    # Fast path: no entities at all
    if "&" not in text:
        return text

    result = []
    i = 0
    length = len(text)

    while i < length:
        ch = text[i]
        if ch != "&":
            result.append(ch)
            i += 1
            continue

        # Spec behavior: preserve literal '&gt' when immediately followed by alphanumeric (no semicolon)
        if in_attribute and i + 3 < length and text[i : i + 3] == "&gt" and text[i + 3].isalnum():
            result.append("&gt")
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
                result.append("&")
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
                result.append(decoded_char)
            else:
                result.append(text[i:j])
            i = j
            continue

        # Named entity: read all alphanumeric chars, then use trie to find longest match
        j = i + 1
        while j < length and text[j].isalnum():
            j += 1

        name_without_ampersand = text[i + 1 : j]
        has_semicolon = j < length and text[j] == ";"

        # Try to find longest entity match using trie
        found_entity = False
        entity_name = None  # Entity name without semicolon
        decoded = None
        consumed_len = 0  # How many chars after '&' were consumed

        if has_semicolon:
            # Try with semicolon first (preferred)
            try:
                matched_name, decoded = _ENTITIES_TRIE.longest_prefix_item(
                    name_without_ampersand + ";"
                )
                # matched_name might be "lt;" or "lt" depending on what's in trie
                entity_name = matched_name.rstrip(";")
                consumed_len = len(matched_name)  # This includes the semicolon if matched
                found_entity = True
            except KeyError:
                pass

        if not found_entity:
            # Try without semicolon
            try:
                matched_name, decoded = _ENTITIES_TRIE.longest_prefix_item(name_without_ampersand)
                entity_name = matched_name
                consumed_len = len(matched_name)
                found_entity = True
            except KeyError:
                pass

        if found_entity:
            if in_attribute and not has_semicolon:
                next_char = text[i + 1 + consumed_len] if i + 1 + consumed_len < length else ""
                if (
                    next_char
                    and (next_char.isalnum() or next_char == "=")
                    and not _allow_decode_without_semicolon_follow(entity_name)
                ):
                    result.append("&")
                    i += 1
                    continue
                if entity_name in _SEMICOLON_REQUIRED and not has_semicolon:
                    result.append("&")
                    i += 1
                    continue
            result.append(decoded)
            i += 1 + consumed_len  # Advance past '&' + matched entity name
            continue
        # Literal '&'
        result.append("&")
        i += 1
    return "".join(result)
