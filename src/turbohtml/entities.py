"""HTML entity decoding for TurboHTML.

Extracted from tokenizer to support Rust tokenizer's entity decoding needs.
Implements HTML5 spec-compliant character reference decoding.
"""

import html

from turbohtml.constants import HTML5_NUMERIC_REPLACEMENTS, NUMERIC_ENTITY_INVALID_SENTINEL


def _allow_decode_without_semicolon_follow(entity_name, basic_entities):
    """Check if entity can be decoded without semicolon when followed by = or alnum."""
    if entity_name in basic_entities:
        return False
    return entity_name and entity_name[0].isupper() and len(entity_name) > 2


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


def decode_entities(text, in_attribute=False):
    """Decode HTML entities in text according to HTML5 spec."""
    # Fast path: no entities at all
    if "&" not in text:
        return text

    result = []
    i = 0
    length = len(text)

    # Cache constants
    semicolon_required = frozenset(["prod"])
    basic_entities = frozenset(["gt", "lt", "amp", "quot", "apos"])

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
                    result.append("&")
                    i += 1
                    continue
                if entity_name in semicolon_required and not has_semicolon:
                    result.append("&")
                    i += 1
                    continue
            result.append(decoded)
            i = j
            continue
        # Literal '&'
        result.append("&")
        i += 1
    return "".join(result)
