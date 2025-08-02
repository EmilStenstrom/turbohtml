import re
from typing import Dict, Iterator, Optional
from .constants import RAWTEXT_ELEMENTS, HTML5_NUMERIC_REPLACEMENTS
import html  # Add to top of file

TAG_OPEN_RE = re.compile(r"<(!?)(/)?([a-zA-Z0-9][-a-zA-Z0-9:]*)(.*?)>")
ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)"|\s*=\s*\'([^\']*)\'|\s*=\s*([^>\s]+)|)(?=\s|$)')


class HTMLToken:
    """Represents a token in the HTML stream"""

    def __init__(
        self,
        type_: str,
        data: str = "",
        tag_name: str = "",
        attributes: Optional[Dict[str, str]] = None,
        is_self_closing: bool = False,
        is_last_token: bool = False,
    ):
        self.type = type_  # 'DOCTYPE', 'StartTag', 'EndTag', 'Comment', 'Character'
        self.data = data
        self.tag_name = tag_name.lower() if tag_name else ""
        self.attributes = attributes or {}
        self.is_self_closing = is_self_closing
        self.is_last_token = is_last_token

    def __repr__(self):
        if self.type == "Character":
            preview = self.data[:20]
            suffix = "..." if len(self.data) > 20 else ""
            return f"<{self.type}: '{preview}{suffix}'>"
        if self.type == "Comment":
            preview = self.data[:20]
            suffix = "..." if len(self.data) > 20 else ""
            return f"<{self.type}: '{preview}{suffix}'>"
        return f"<{self.type}: {self.tag_name or self.data}>"


class HTMLTokenizer:
    """
    HTML5 tokenizer that generates tokens from an HTML string.
    Maintains compatibility with existing parser logic while providing
    a cleaner separation of concerns.
    """

    def __init__(self, html: str, debug: bool = False):
        self.html = html
        self.length = len(html)
        self.pos = 0
        self.state = "DATA"
        self.rawtext_tag = None
        self.buffer = []
        self.temp_buffer = []
        self.last_pos = self.length  # Store the last position we'll process
        self.env_debug = debug

    def debug(self, *args, indent: int = 4) -> None:
        """Print debug message if debugging is enabled"""
        if not self.env_debug:
            return
        print(f"{' ' * indent}{args[0]}", *args[1:])

    def start_rawtext(self, tag_name: str) -> None:
        """Switch to RAWTEXT state for the given tag"""
        self.state = "RAWTEXT"
        self.rawtext_tag = tag_name
        self.buffer = []
        self.temp_buffer = []

    def tokenize(self) -> Iterator[HTMLToken]:
        """Generate tokens from the HTML string"""
        while self.pos < self.length:
            self.debug(f"tokenize: pos={self.pos}, state={self.state}, char={self.html[self.pos]!r}")
            if self.state == "DATA":
                token = self._try_tag() or self._try_text()
                if token:
                    self.debug(f"DATA token: {token}")
                    token.is_last_token = self.pos >= self.last_pos
                    yield token
                elif self.pos < self.length:
                    self.pos += 1
            elif self.state == "RAWTEXT":
                token = self._tokenize_rawtext()
                if token:
                    self.debug(f"RAWTEXT token: {token}")
                    token.is_last_token = self.pos >= self.last_pos
                    yield token

    def _tokenize_rawtext(self) -> Optional[HTMLToken]:
        """Tokenize content in RAWTEXT state"""
        self.debug(f"_tokenize_rawtext: pos={self.pos}, next_chars={self.html[self.pos:self.pos+10]!r}")

        # Look for </tag>
        if self.html.startswith("</", self.pos):
            self.debug(f"  found </: looking for end tag")
            tag_start = self.pos + 2
            i = tag_start
            potential_tag = ""

            # Collect tag name
            while i < self.length and self.html[i].isascii() and self.html[i].isalpha():
                potential_tag += self.html[i].lower()
                i += 1

            self.debug(f"  potential_tag={potential_tag!r}, rawtext_tag={self.rawtext_tag!r}")

            # Skip whitespace
            while i < self.length and self.html[i].isspace():
                i += 1

            # Check if it's our end tag
            if potential_tag == self.rawtext_tag and i < self.length and self.html[i] == ">":
                self.debug(f"  found matching end tag")
                # Found valid end tag
                text_before = self.html[self.pos : tag_start - 2]  # Get text before </
                self.pos = i + 1  # Move past >
                self.state = "DATA"
                self.rawtext_tag = None

                # First return any text before the tag
                if text_before:
                    return HTMLToken("Character", data=text_before)
                # Then return the end tag
                return HTMLToken("EndTag", tag_name=potential_tag)

        # If we're here, either no end tag or not our tag
        # Find the next potential end tag or EOF
        start = self.pos
        self.pos += 1
        while self.pos < self.length and not self.html.startswith("</", self.pos):
            self.pos += 1

        # Return the text we found
        text = self.html[start : self.pos]
        if text:
            return HTMLToken("Character", data=text)

        return None

    def _try_tag(self) -> Optional[HTMLToken]:
        """Try to match a tag at current position"""
        if not self.html.startswith("<", self.pos):
            return None

        self.debug(f"_try_tag: pos={self.pos}, state={self.state}, next_chars={self.html[self.pos:self.pos+10]!r}")

        # If this is the last character, treat it as text
        if self.pos + 1 >= self.length:
            self.pos += 1
            return HTMLToken("Character", data="<")

        # Handle DOCTYPE first (case-insensitive per HTML5 spec)
        if self.html[self.pos:self.pos + 9].upper() == "<!DOCTYPE":
            self.pos += 9  # Skip <!DOCTYPE
            # Skip whitespace
            while self.pos < self.length and self.html[self.pos].isspace():
                self.pos += 1
            # Collect DOCTYPE value
            start = self.pos
            while self.pos < self.length and self.html[self.pos] != ">":
                self.pos += 1
            doctype = self.html[start : self.pos].strip()
            if self.pos < self.length:  # Skip closing >
                self.pos += 1
            return HTMLToken("DOCTYPE", data=doctype)

        # Only handle comments in DATA state
        if self.state == "DATA":
            if self.html.startswith("<!--", self.pos):
                # Special case: <!--> is treated as <!-- -->
                if self.pos + 4 < self.length and self.html[self.pos + 4] == ">":
                    self.pos += 5
                    return HTMLToken("Comment", data="")
                return self._handle_comment()
            # Handle all bogus comment cases according to spec:

            # Check for end tag with attributes or invalid char after </
            is_end_tag_start = self.html.startswith("</", self.pos)
            has_invalid_char = self.pos + 2 < self.length and not (
                self.html[self.pos + 2].isascii() and self.html[self.pos + 2].isalpha()
            )
            match = TAG_OPEN_RE.match(self.html[self.pos :]) if is_end_tag_start else None
            has_attributes = match and match.group(2) and match.group(4).strip()

            self.debug(f"Checking bogus comment conditions:")
            self.debug(f"  is_end_tag_start: {is_end_tag_start}")
            self.debug(f"  has_invalid_char: {has_invalid_char}")
            self.debug(f"  tag match: {match and match.groups()}")
            self.debug(f"  has_attributes: {has_attributes}")

            if (
                (is_end_tag_start and (has_invalid_char or has_attributes))
                or self.html.startswith("<!", self.pos)
                or self.html.startswith("<?", self.pos)
            ):
                self.debug("Found bogus comment case")
                # Pass from_end_tag=True for end tags with attributes
                return self._handle_bogus_comment(from_end_tag=is_end_tag_start and has_attributes)

        # Special case: </ at EOF should be treated as text
        if self.html.startswith("</", self.pos) and self.pos + 2 >= self.length:
            self.pos = self.length  # Consume all remaining input
            return HTMLToken("Character", data="</")

        # Try to match a tag using TAG_OPEN_RE
        match = TAG_OPEN_RE.match(self.html[self.pos :])
        self.debug(f"Trying to match tag: {match and match.groups()}")

        # If no match with >, try to match without it
        if not match:
            # Look for tag name
            tag_match = re.match(r"<(!?)(/)?([a-zA-Z0-9][-a-zA-Z0-9:]*)", self.html[self.pos :])
            if tag_match:
                self.debug(f"Found unclosed tag: {tag_match.groups()}")
                bang, is_end_tag, tag_name = tag_match.groups()
                # Get rest of the input as attributes
                tag_prefix_len = len(tag_match.group(0))
                attributes = self.html[self.pos + tag_prefix_len :]
                self.pos = self.length

                # Return appropriate token
                if is_end_tag:
                    return HTMLToken("EndTag", tag_name=tag_name)
                else:
                    # Check for self-closing syntax
                    is_self_closing = attributes and attributes.rstrip().endswith("/")
                    attrs = self._parse_attributes(attributes)
                    return HTMLToken("StartTag", tag_name=tag_name, attributes=attrs, is_self_closing=is_self_closing)

        # Handle normal closed tags
        if match:
            bang, is_end_tag, tag_name, attributes = match.groups()
            self.debug(
                f"Found tag: bang={bang}, is_end_tag={is_end_tag}, tag_name={tag_name}, attributes={attributes}"
            )
            self.pos += len(match.group(0))

            # Handle state transitions for start tags
            if not is_end_tag and tag_name.lower() in RAWTEXT_ELEMENTS:
                self.debug(f"Switching to RAWTEXT mode for {tag_name}")
                self.state = "RAWTEXT"
                self.rawtext_tag = tag_name.lower()

            # Return the appropriate token
            if is_end_tag:
                return HTMLToken("EndTag", tag_name=tag_name)
            else:
                # Check for self-closing syntax (ends with /)
                is_self_closing = attributes and attributes.rstrip().endswith("/")
                attrs = self._parse_attributes(attributes)
                return HTMLToken("StartTag", tag_name=tag_name, attributes=attrs, is_self_closing=is_self_closing)

        # If we get here, we found a < that isn't part of a valid tag
        self.debug("No valid tag found, treating as character")
        self.pos += 1
        return HTMLToken("Character", data="<")

    def _try_text(self) -> Optional[HTMLToken]:
        """Try to match text at current position"""
        if self.pos >= self.length:
            return None

        start = self.pos

        # If we're starting with '<', don't try to parse as text
        if self.html[start] == "<":
            return None

        while self.pos < self.length:
            if self.html[self.pos] == "<":
                break
            self.pos += 1

        text = self.html[start : self.pos]
        # Only emit non-empty text tokens
        if not text:
            return None

        # Decode entities in text
        decoded = self._decode_entities(text)
        return HTMLToken("Character", data=decoded)

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """Parse attributes from a string using the ATTR_RE pattern"""
        self.debug(f"Parsing attributes: {attr_string[:50]}...")
        attr_string = attr_string.strip().rstrip("/")

        # Handle case where entire string is attribute name
        if attr_string and not any(c in attr_string for c in "='\""):
            self.debug("Single attribute without value")
            # Split on / and create empty attributes for each part
            parts = [p.strip() for p in attr_string.split("/") if p.strip()]
            return {part: "" for part in parts}

        matches = ATTR_RE.findall(attr_string)
        attributes = {}
        for attr_name, val1, val2, val3 in matches:
            attr_value = val1 or val2 or val3 or ""
            # Decode HTML entities in attribute values per HTML5 spec
            attr_value = self._decode_entities(attr_value, in_attribute=True)
            attributes[attr_name] = attr_value
        return attributes

    def _handle_comment(self) -> HTMLToken:
        """Handle comment according to HTML5 spec"""
        self.debug(f"_handle_comment: pos={self.pos}, state={self.state}")
        self.pos += 4  # Skip <!--
        start = self.pos

        # Special case: <!--> is treated as <!-- -->
        if self.pos < self.length and self.html[self.pos] == ">":
            self.pos += 1
            return HTMLToken("Comment", data="")

        # Special case: <!--- followed by > should end the comment
        if (self.pos < self.length and self.html[self.pos] == "-" and
            self.pos + 1 < self.length and self.html[self.pos + 1] == ">"):
            self.pos += 2  # Skip ->
            return HTMLToken("Comment", data="")

        # Look for end of comment
        while self.pos + 2 < self.length:
            if self.html[self.pos:self.pos + 3] == "-->":
                comment_text = self.html[start:self.pos]
                self.pos += 3  # Skip -->
                return HTMLToken("Comment", data=comment_text)
            # Handle --!> ending (spec says to ignore the !)
            elif (self.pos + 3 < self.length and
                  self.html[self.pos:self.pos + 2] == "--" and
                  self.html[self.pos + 2] == "!" and
                  self.html[self.pos + 3] == ">"):
                comment_text = self.html[start:self.pos]
                self.pos += 4  # Skip --!>
                return HTMLToken("Comment", data=comment_text)
            self.pos += 1

        # If we reach here, no proper end to comment was found
        comment_text = self.html[start:]

        # Special case: if comment ends with --, remove them and add a space
        if comment_text.endswith("--"):
            comment_text = comment_text[:-2]

        self.pos = self.length
        return HTMLToken("Comment", data=comment_text)

    def _handle_bogus_comment(self, from_end_tag: bool = False) -> Optional[HTMLToken]:
        """Handle bogus comment according to HTML5 spec"""
        self.debug(f"_handle_bogus_comment: pos={self.pos}, state={self.state}, from_end_tag={from_end_tag}")
        # For <?, include the ? in the comment
        if self.html.startswith("<?", self.pos):
            start = self.pos + 1  # Only skip <

        # For </, skip both < and / and start from the next char
        elif self.html.startswith("</", self.pos):
            start = self.pos + 2  # Skip both < and /

        # For <!, skip both < and !
        else:  # starts with <!
            start = self.pos + 2  # Skip <!

        # Look for next > to end the comment
        while self.pos < self.length:
            if self.html[self.pos] == ">":
                comment_text = self.html[start:self.pos]
                self.pos += 1  # Skip >
                # Return None for bogus comments from end tags with attributes
                if from_end_tag:
                    return None
                return HTMLToken("Comment", data=comment_text)
            self.pos += 1

        # EOF: emit what we have
        comment_text = self.html[start:]
        self.pos = self.length  # Make sure we're at the end
        if from_end_tag:
            return None
        return HTMLToken("Comment", data=comment_text)

    def _decode_entities(self, text: str, in_attribute: bool = False) -> str:
        """Decode HTML entities in text according to HTML5 spec."""
        if '&' not in text:
            return text

        result = []
        i = 0
        while i < len(text):
            if text[i] == '&':
                # Find the end of the potential entity name using HTML5 rules
                end_pos = i + 1

                # Check if it's a numeric entity
                if end_pos < len(text) and text[end_pos] == '#':
                    # Numeric entity
                    end_pos += 1
                    if end_pos < len(text) and text[end_pos].lower() == 'x':
                        end_pos += 1  # hex prefix
                    # Include hex/decimal digits
                    while end_pos < len(text) and text[end_pos].isalnum():
                        end_pos += 1
                else:
                    # Named entity - find longest sequence of alphanumeric chars
                    # This may include invalid entity names, we'll validate later
                    while end_pos < len(text) and text[end_pos].isalnum():
                        end_pos += 1

                # Now we have the full potential entity name
                full_entity = text[i:end_pos]
                entity = full_entity
                has_semicolon = False

                # Check for semicolon
                if end_pos < len(text) and text[end_pos] == ';':
                    entity += ';'
                    end_pos += 1
                    has_semicolon = True

                # Try to decode the entity
                decoded = None
                try:
                    if (entity.startswith('&#x') or entity.startswith('&#X')) and has_semicolon:
                        # Hexadecimal numeric entity
                        hex_part = entity[3:-1]
                        if hex_part:
                            codepoint = int(hex_part, 16)
                            decoded = self._codepoint_to_char(codepoint)
                    elif entity.startswith('&#') and has_semicolon:
                        # Decimal numeric entity
                        dec_part = entity[2:-1]
                        if dec_part.isdigit():
                            codepoint = int(dec_part)
                            decoded = self._codepoint_to_char(codepoint)
                    elif has_semicolon:
                        # Named entity with semicolon - always decode
                        decoded = html.unescape(entity)
                        if decoded == entity:
                            decoded = None  # Not a valid entity
                    else:
                        # Named entity without semicolon - find the real entity boundary
                        best_entity = None
                        best_decoded = None
                        best_end_pos = None

                        # Find the shortest valid entity by growing from minimum length
                        for try_len in range(2, len(full_entity) + 1):  # Start from &X minimum
                            try_entity = full_entity[:try_len]
                            test_decoded = html.unescape(try_entity)

                            if test_decoded != try_entity:
                                # This is a valid entity, but check if adding more chars
                                # just adds literal text (indicating we found the boundary)
                                if try_len < len(full_entity):
                                    longer_entity = full_entity[:try_len + 1]
                                    longer_decoded = html.unescape(longer_entity)

                                    # If adding the next char just adds literal text, we found the boundary
                                    if longer_decoded == test_decoded + full_entity[try_len]:
                                        best_entity = try_entity
                                        best_decoded = test_decoded
                                        best_end_pos = i + try_len
                                        break
                                    # If longer version doesn't decode, this is the boundary
                                    elif longer_decoded == longer_entity:
                                        best_entity = try_entity
                                        best_decoded = test_decoded
                                        best_end_pos = i + try_len
                                        break
                                    # Otherwise keep trying longer versions
                                else:
                                    # End of string - use this entity
                                    best_entity = try_entity
                                    best_decoded = test_decoded
                                    best_end_pos = i + try_len
                                    break

                        if best_entity is not None:
                            # Check HTML5 attribute context rules
                            should_decode = True
                            if in_attribute:
                                next_char = text[best_end_pos] if best_end_pos < len(text) else ''
                                if next_char == '=' or next_char.isalnum():
                                    should_decode = False

                            if should_decode:
                                decoded = best_decoded
                                entity = best_entity
                                end_pos = best_end_pos

                    if decoded is not None:
                        result.append(decoded)
                    else:
                        result.append(entity)

                    i = end_pos
                except (ValueError, OverflowError):
                    result.append(text[i])
                    i += 1
            else:
                result.append(text[i])
                i += 1

        return ''.join(result)

    def _codepoint_to_char(self, codepoint: int) -> str:
        """Convert a numeric codepoint to character with HTML5 replacements."""
        # Handle invalid codepoints
        if codepoint > 0x10FFFF:
            return '\uFFFD'
        
        # Handle surrogates (0xD800-0xDFFF) - these are invalid in UTF-8
        if 0xD800 <= codepoint <= 0xDFFF:
            return '\uFFFD'
        
        # Apply HTML5 numeric character reference replacements
        if codepoint in HTML5_NUMERIC_REPLACEMENTS:
            return HTML5_NUMERIC_REPLACEMENTS[codepoint]
        
        # Handle special cases
        if codepoint == 0x10FFFE:
            return '\U0010FFFE'
        elif codepoint == 0x10FFFF:
            return '\U0010FFFF'
        else:
            try:
                return chr(codepoint)
            except ValueError:
                return '\uFFFD'
