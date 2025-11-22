"""HTML5 character entity decoding.

Implements HTML5 character reference (entity) decoding per WHATWG spec §13.2.5.
Supports both named entities (&amp;, &nbsp;) and numeric references (&#60;, &#x3C;).
"""

import html.entities

# Use Python's complete HTML5 entity list (2231 entities)
# Keys include the trailing semicolon (e.g., "amp;", "lang;")
# We'll strip semicolons when looking up to match both forms
_HTML5_ENTITIES = html.entities.html5

# Build a normalized lookup without semicolons for easier access
NAMED_ENTITIES = {}
for key, value in _HTML5_ENTITIES.items():
    # Remove trailing semicolon for lookup
    if key.endswith(';'):
        NAMED_ENTITIES[key[:-1]] = value
    else:
        NAMED_ENTITIES[key] = value

# Legacy named character references that can be used without semicolons
# Per HTML5 spec, these are primarily ISO-8859-1 (Latin-1) entities from HTML4
# Modern entities like "prod", "notin" etc. require semicolons
LEGACY_ENTITIES = {
    "gt", "lt", "amp", "quot", "apos", "nbsp", "AMP",
    "AElig", "Aacute", "Acirc", "Agrave", "Aring", "Atilde", "Auml",
    "Ccedil", "ETH", "Eacute", "Ecirc", "Egrave", "Euml",
    "Iacute", "Icirc", "Igrave", "Iuml",
    "Ntilde", "Oacute", "Ocirc", "Ograve", "Oslash", "Otilde", "Ouml",
    "THORN", "Uacute", "Ucirc", "Ugrave", "Uuml", "Yacute",
    "aacute", "acirc", "acute", "aelig", "agrave", "aring", "atilde", "auml",
    "brvbar", "ccedil", "cedil", "cent", "copy", "curren",
    "deg", "divide",
    "eacute", "ecirc", "egrave", "eth", "euml",
    "frac12", "frac14", "frac34",
    "iacute", "icirc", "iexcl", "igrave", "iquest", "iuml",
    "laquo", "macr", "micro", "middot",
    "not", "ntilde",
    "oacute", "ocirc", "ograve", "ordf", "ordm", "oslash", "otilde", "ouml",
    "para", "plusmn", "pound",
    "raquo", "reg",
    "sect", "shy", "sup1", "sup2", "sup3", "szlig",
    "thorn", "times",
    "uacute", "ucirc", "ugrave", "uml", "uuml",
    "yacute", "yen", "yuml",
}

# HTML5 numeric character reference replacements (§13.2.5.73)
NUMERIC_REPLACEMENTS = {
    0x00: "\ufffd",  # NULL
    0x80: "\u20ac",  # EURO SIGN
    0x82: "\u201a",  # SINGLE LOW-9 QUOTATION MARK
    0x83: "\u0192",  # LATIN SMALL LETTER F WITH HOOK
    0x84: "\u201e",  # DOUBLE LOW-9 QUOTATION MARK
    0x85: "\u2026",  # HORIZONTAL ELLIPSIS
    0x86: "\u2020",  # DAGGER
    0x87: "\u2021",  # DOUBLE DAGGER
    0x88: "\u02c6",  # MODIFIER LETTER CIRCUMFLEX ACCENT
    0x89: "\u2030",  # PER MILLE SIGN
    0x8a: "\u0160",  # LATIN CAPITAL LETTER S WITH CARON
    0x8b: "\u2039",  # SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    0x8c: "\u0152",  # LATIN CAPITAL LIGATURE OE
    0x8e: "\u017d",  # LATIN CAPITAL LETTER Z WITH CARON
    0x91: "\u2018",  # LEFT SINGLE QUOTATION MARK
    0x92: "\u2019",  # RIGHT SINGLE QUOTATION MARK
    0x93: "\u201c",  # LEFT DOUBLE QUOTATION MARK
    0x94: "\u201d",  # RIGHT DOUBLE QUOTATION MARK
    0x95: "\u2022",  # BULLET
    0x96: "\u2013",  # EN DASH
    0x97: "\u2014",  # EM DASH
    0x98: "\u02dc",  # SMALL TILDE
    0x99: "\u2122",  # TRADE MARK SIGN
    0x9a: "\u0161",  # LATIN SMALL LETTER S WITH CARON
    0x9b: "\u203a",  # SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    0x9c: "\u0153",  # LATIN SMALL LIGATURE OE
    0x9e: "\u017e",  # LATIN SMALL LETTER Z WITH CARON
    0x9f: "\u0178",  # LATIN CAPITAL LETTER Y WITH DIAERESIS
}


def decode_numeric_entity(text, is_hex=False):
    """Decode a numeric character reference like &#60; or &#x3C;.
    
    Args:
        text: The numeric part (without &# or ;)
        is_hex: Whether this is hexadecimal (&#x) or decimal (&#)
        
    Returns:
        The decoded character, or None if invalid
    """
    try:
        if is_hex:
            codepoint = int(text, 16)
        else:
            codepoint = int(text, 10)
            
        # Apply HTML5 replacements for certain ranges
        if codepoint in NUMERIC_REPLACEMENTS:
            return NUMERIC_REPLACEMENTS[codepoint]
            
        # Invalid ranges per HTML5 spec
        if codepoint > 0x10FFFF:
            return "\ufffd"  # REPLACEMENT CHARACTER
        if 0xD800 <= codepoint <= 0xDFFF:  # Surrogate range
            return "\ufffd"
            
        return chr(codepoint)
    except (ValueError, OverflowError):
        return None


def decode_entities_in_text(text, in_attribute=False):
    """Decode all HTML entities in text.
    
    This is a simple implementation that handles:
    - Named entities: &amp; &lt; &gt; &quot; &nbsp; etc.
    - Decimal numeric: &#60; &#160; etc.
    - Hex numeric: &#x3C; &#xA0; etc.
    
    Args:
        text: Input text potentially containing entities
        in_attribute: Whether this is attribute value (stricter rules for legacy entities)
        
    Returns:
        Text with entities decoded
    """
    if "&" not in text:
        return text
        
    result = []
    i = 0
    length = len(text)
    while i < length:
        next_amp = text.find("&", i)
        if next_amp == -1:
            result.append(text[i:])
            break
        
        if next_amp > i:
            result.append(text[i:next_amp])
        
        i = next_amp
        # Look for entity
        j = i + 1
        
        # Check for numeric entity
        if j < length and text[j] == "#":
            j += 1
            is_hex = False
            
            if j < length and text[j] in "xX":
                is_hex = True
                j += 1
            
            # Collect digits
            digit_start = j
            if is_hex:
                while j < length and text[j] in "0123456789abcdefABCDEF":
                    j += 1
            else:
                while j < length and text[j].isdigit():
                    j += 1
            
            has_semicolon = j < length and text[j] == ";"
            digit_text = text[digit_start:j]
            
            if digit_text:
                decoded = decode_numeric_entity(digit_text, is_hex=is_hex)
                if decoded:
                    result.append(decoded)
                    if has_semicolon:
                        i = j + 1
                    else:
                        i = j
                    continue
            
            # Invalid numeric entity, keep as-is
            result.append(text[i:j+1 if has_semicolon else j])
            i = j + 1 if has_semicolon else j
            continue
        
        # Named entity
        # Collect alphanumeric characters (entity names are case-sensitive and can include uppercase)
        while j < length and (text[j].isalpha() or text[j].isdigit()):
            j += 1
        
        entity_name = text[i+1:j]
        has_semicolon = j < length and text[j] == ";"
        
        if not entity_name:
            result.append("&")
            i += 1
            continue
        
        # Try exact match first (with semicolon expected)
        if has_semicolon and entity_name in NAMED_ENTITIES:
            result.append(NAMED_ENTITIES[entity_name])
            i = j + 1
            continue
        
        # If we have a semicolon but exact match failed, try prefix matching
        # This handles &notit; -> ¬it; (decode &not, leave it;)
        if has_semicolon:
            best_match = None
            best_match_len = 0
            for k in range(len(entity_name), 0, -1):
                prefix = entity_name[:k]
                if prefix in NAMED_ENTITIES:
                    best_match = NAMED_ENTITIES[prefix]
                    best_match_len = k
                    break
            
            if best_match:
                result.append(best_match)
                # Continue after the matched prefix, not after semicolon
                i = i + 1 + best_match_len
                continue
        
        # Try without semicolon for legacy compatibility
        # Only legacy entities can be used without semicolons
        if entity_name in LEGACY_ENTITIES and entity_name in NAMED_ENTITIES:
            # Legacy entities without semicolon have strict rules:
            # In attributes: don't decode if followed by alphanumeric or '='
            # In text: don't decode if followed by lowercase/digit
            # Per HTML5 spec §13.2.5.72
            next_char = text[j] if j < length else None
            if in_attribute:
                if next_char and (next_char.isalnum() or next_char == "="):
                    result.append("&")
                    i += 1
                    continue
            else:
                if next_char and (next_char.islower() or next_char.isdigit()):
                    result.append("&")
                    i += 1
                    continue
            
            # Decode legacy entity
            result.append(NAMED_ENTITIES[entity_name])
            i = j
            continue
        
        # Try longest prefix match for legacy entities without semicolon
        # This handles cases like &notit where &not is valid but &notit is not
        best_match = None
        best_match_len = 0
        for k in range(len(entity_name), 0, -1):
            prefix = entity_name[:k]
            if prefix in LEGACY_ENTITIES and prefix in NAMED_ENTITIES:
                best_match = NAMED_ENTITIES[prefix]
                best_match_len = k
                break
        
        if best_match:
            # Check legacy entity rules
            end_pos = i + 1 + best_match_len
            next_char = text[end_pos] if end_pos < length else None
            if in_attribute:
                if next_char and (next_char.isalnum() or next_char == "="):
                    result.append("&")
                    i += 1
                    continue
            else:
                if next_char and (next_char.islower() or next_char.isdigit()):
                    result.append("&")
                    i += 1
                    continue
            
            result.append(best_match)
            i = i + 1 + best_match_len
            continue
        
        # No match found
        if has_semicolon:
            result.append(text[i:j+1])
            i = j + 1
        else:
            result.append("&")
            i += 1
            
    return "".join(result)
