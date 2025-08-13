import re
from typing import Dict, Iterator, Optional
from .constants import RAWTEXT_ELEMENTS, HTML5_NUMERIC_REPLACEMENTS
import html  # Add to top of file

TAG_OPEN_RE = re.compile(r"<(!?)(/)?([^\s/>]+)(.*?)>")
ATTR_RE = re.compile(r'([^\s=/>]+)(?:\s*=\s*"([^"]*)"|\s*=\s*\'([^\']*)\'|\s*=\s*([^>\s]+)|)(?=\s|$|>)')


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
        # For script parsing
        self.script_content = ""

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
        # For script elements, track content for comment detection
        if tag_name == "script":
            self.script_content = ""

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

        # Special handling for script elements
        if self.rawtext_tag == "script":
            return self._tokenize_script_content()
        
        # Regular RAWTEXT handling for other elements
        return self._tokenize_regular_rawtext()
    
    def _tokenize_script_content(self) -> Optional[HTMLToken]:
        """Handle script content with HTML5 comment rules"""
        # Look for </script> but respect comment context
        if self.html.startswith("</", self.pos):
            self.debug("  found </: checking for script end tag")
            tag_start = self.pos + 2
            i = tag_start
            potential_tag = ""

            # Collect tag name
            while i < self.length and self.html[i].isascii() and self.html[i].isalpha():
                potential_tag += self.html[i].lower()
                i += 1

            self.debug(f"  potential_tag={potential_tag!r}")

            # Skip whitespace and optional /
            while i < self.length and (self.html[i].isspace() or self.html[i] == "/"):
                i += 1

            # Check if it's our end tag
            if potential_tag == "script" and i < self.length and self.html[i] == ">":
                # Check if this end tag should be honored based on comment context
                text_before = self.html[self.pos:tag_start - 2]  # Get text before </
                
                # Use accumulated script content plus text before this end tag
                full_content = self.script_content + text_before
                
                self.debug(f"  full script content: {full_content!r}")
                
                if self._should_honor_script_end_tag(full_content):
                    self.debug("  honoring script end tag")
                    # End the script
                    self.pos = i + 1  # Move past >
                    self.state = "DATA"
                    self.rawtext_tag = None
                    self.script_content = ""  # Reset for next script

                    # First return any text before the tag
                    if text_before:
                        # Replace invalid characters in script content
                        text_before = self._replace_invalid_characters(text_before)
                        return HTMLToken("Character", data=text_before)
                    # Then return the end tag
                    return HTMLToken("EndTag", tag_name=potential_tag)
                else:
                    self.debug("  ignoring script end tag due to comment context")
                    # Treat as regular content, continue parsing

        # If we're here, either no end tag or it should be ignored
        # Find the next potential end tag or EOF
        start = self.pos
        self.pos += 1
        while self.pos < self.length and not self.html.startswith("</", self.pos):
            self.pos += 1

        # Return the text we found
        text = self.html[start:self.pos]
        if text:
            # For script elements, accumulate content for comment detection
            if self.rawtext_tag == "script":
                self.script_content += text
            # Replace invalid characters in script content
            text = self._replace_invalid_characters(text)
            return HTMLToken("Character", data=text)

        return None
    
    def _should_honor_script_end_tag(self, script_content: str) -> bool:
        """
        Determine if a </script> tag should end the script based on HTML5 script parsing rules.

        HTML5 spec section 13.2.5.3: Script data state and escaped states
        """
        self.debug(f"  checking script content: {script_content!r}")

        if "<!--" not in script_content:
            # No comments, always honor end tag (script data state)
            self.debug("  no comments found, honoring end tag")
            return True

        # Advanced HTML5 Script parsing rules:
        # When script contains <!--, it may enter escaped state
        # In escaped state, certain </script> patterns are treated as content

        # Look for specific patterns that suggest content vs end tag
        # Pattern: <!--<script> ... should have the first </script> as content
        # But only count actual </script> tags (case-insensitive), not malformed ones
        if "<!--<script>" in script_content and "-->" not in script_content:
            # Count actual </script> occurrences (case-insensitive)
            content_lower = script_content.lower()
            end_tag_count = content_lower.count("</script>")
            if end_tag_count == 0:
                self.debug("  first </script> after <!--<script>, treating as content")
                return False

        # All other cases: honor the end tag
        self.debug("  honoring end tag")
        return True
    
    def _tokenize_regular_rawtext(self) -> Optional[HTMLToken]:
        """Handle regular RAWTEXT elements (non-script)"""
        if self.html.startswith("</", self.pos):
            self.debug("  found </: looking for end tag")
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

            # Skip any "/" characters (self-closing syntax on end tags should be ignored)
            while i < self.length and self.html[i] == "/":
                i += 1

            # Skip more whitespace after /
            while i < self.length and self.html[i].isspace():
                i += 1

            # Check if it's our end tag
            if potential_tag == self.rawtext_tag and i < self.length and self.html[i] == ">":
                self.debug("  found matching end tag")
                # Found valid end tag
                text_before = self.html[self.pos:tag_start - 2]  # Get text before </
                self.pos = i + 1  # Move past >
                self.state = "DATA"
                self.rawtext_tag = None

                # First return any text before the tag
                if text_before:
                    # Replace invalid characters
                    text_before = self._replace_invalid_characters(text_before)
                    # Decode entities for RCDATA elements (title/textarea)
                    if self.rawtext_tag in ("title", "textarea"):
                        text_before = self._decode_entities(text_before)
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
        text = self.html[start:self.pos]
        if text:
            # Replace invalid characters according to HTML5 spec
            text = self._replace_invalid_characters(text)
            # Decode entities for RCDATA elements (title/textarea)
            if self.rawtext_tag in ("title", "textarea"):
                text = self._decode_entities(text)
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
        if self.html[self.pos:self.pos+9].upper() == "<!DOCTYPE":
            self.pos += 9  # Skip <!DOCTYPE
            # Skip whitespace
            while self.pos < self.length and self.html[self.pos].isspace():
                self.pos += 1
            # Collect DOCTYPE value
            start = self.pos
            while self.pos < self.length and self.html[self.pos] != ">":
                self.pos += 1
            doctype = self.html[start:self.pos].strip()
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
            match = TAG_OPEN_RE.match(self.html[self.pos:]) if is_end_tag_start else None
            has_attributes = match and match.group(2) and match.group(4).strip()

            self.debug("Checking bogus comment conditions:")
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
        match = TAG_OPEN_RE.match(self.html[self.pos:])
        self.debug(f"Trying to match tag: {match and match.groups()}")

        # If no match with >, try to match without it for unclosed tags
        if not match:
            # Look for tag name - be more permissive about what constitutes a tag
            tag_match = re.match(r"<(!?)(/)?([^\s/>]+)", self.html[self.pos:])
            if tag_match:
                self.debug(f"Found unclosed tag: {tag_match.groups()}")
                bang, is_end_tag, tag_name = tag_match.groups()
                # Get rest of the input as attributes
                tag_prefix_len = len(tag_match.group(0))
                attributes = self.html[self.pos + tag_prefix_len:]
                self.pos = self.length

                # Return appropriate token
                if is_end_tag:
                    return HTMLToken("EndTag", tag_name=tag_name)
                else:
                    # Parse attributes and check for self-closing syntax
                    is_self_closing, attrs = self._parse_attributes_and_check_self_closing(attributes)
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
                # Parse attributes and check for self-closing syntax
                is_self_closing, attrs = self._parse_attributes_and_check_self_closing(attributes)
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

        text = self.html[start:self.pos]
        # Only emit non-empty text tokens
        if not text:
            return None

        # Replace invalid characters first, then decode entities
        text = self._replace_invalid_characters(text)
        decoded = self._decode_entities(text)
        return HTMLToken("Character", data=decoded)

    def _parse_attributes_and_check_self_closing(self, attr_string: str) -> tuple[bool, Dict[str, str]]:
        """
        Parse attributes and determine if tag is self-closing.
        
        Returns (is_self_closing, attributes_dict)
        """
        if not attr_string:
            return False, {}
        
        # Trim leading/trailing whitespace
        trimmed = attr_string.strip()
        
        # Simple cases first
        if not trimmed:
            return False, {}
        
        if trimmed == "/":
            return True, {}
        
        if trimmed.endswith(" /"):
            # Clear case: attributes followed by space and slash
            return True, self._parse_attributes(attr_string.rstrip().rstrip("/"))
        
        # More complex case: check if the trailing / is part of an attribute value
        # or self-closing syntax
        if trimmed.endswith("/"):
            # Try parsing without the trailing /
            without_slash = attr_string.rstrip("/")
            attrs_without_slash = self._parse_attributes(without_slash)
            
            # Also try parsing with the slash
            attrs_with_slash = self._parse_attributes(attr_string)
            
            # If parsing without slash gives a quoted attribute value in the last attribute,
            # and parsing with slash gives an unquoted value with quotes and slash,
            # then the slash was self-closing syntax
            if attrs_without_slash and attrs_with_slash:
                # Get the last attribute from each parse
                last_key_without = list(attrs_without_slash.keys())[-1] if attrs_without_slash else None
                last_key_with = list(attrs_with_slash.keys())[-1] if attrs_with_slash else None
                
                if (
                    last_key_without == last_key_with
                    and last_key_without
                    and not attrs_without_slash[last_key_without].startswith('"')  # Clean value
                    and attrs_with_slash[last_key_with].startswith('"')            # Malformed with quotes
                    and attrs_with_slash[last_key_with].endswith('/')               # And ends with slash
                ):
                    # The slash was self-closing syntax
                    return True, attrs_without_slash
            
            # Default: treat as part of attribute value
            return False, attrs_with_slash
        
        # No trailing slash
        return False, self._parse_attributes(attr_string)

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """Parse attributes from a string using the ATTR_RE pattern"""
        self.debug(f"Parsing attributes: {attr_string[:50]}...")
        attr_string = attr_string.strip()  # Remove only leading/trailing whitespace

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
        if (
            self.pos < self.length and self.html[self.pos] == "-"
            and self.pos + 1 < self.length and self.html[self.pos + 1] == ">"
        ):
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

    def _replace_invalid_characters(self, text: str) -> str:
        """Replace invalid characters according to HTML5 spec."""
        if not text:
            return text

        result = []
        for char in text:
            codepoint = ord(char)

            # Replace NULL character with replacement character
            if codepoint == 0x00:
                result.append('\uFFFD')
            # Replace other control characters that should be replaced
            elif codepoint in (
                0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                0x0B, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x14,
                0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C,
                0x1D, 0x1E, 0x1F, 0x7F,
            ):
                result.append('\uFFFD')
            # Replace surrogates (should not appear in valid UTF-8)
            elif 0xD800 <= codepoint <= 0xDFFF:
                result.append('\uFFFD')
            # Replace non-characters
            elif codepoint in (
                0xFDD0, 0xFDD1, 0xFDD2, 0xFDD3, 0xFDD4, 0xFDD5,
                0xFDD6, 0xFDD7, 0xFDD8, 0xFDD9, 0xFDDA, 0xFDDB,
                0xFDDC, 0xFDDD, 0xFDDE, 0xFDDF, 0xFDE0, 0xFDE1,
                0xFDE2, 0xFDE3, 0xFDE4, 0xFDE5, 0xFDE6, 0xFDE7,
                0xFDE8, 0xFDE9, 0xFDEA, 0xFDEB, 0xFDEC, 0xFDED,
                0xFDEE, 0xFDEF,
            ):
                result.append('\uFFFD')
            # Replace other non-characters ending in FFFE/FFFF
            elif (codepoint & 0xFFFF) in (0xFFFE, 0xFFFF):
                result.append('\uFFFD')
            else:
                result.append(char)

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
