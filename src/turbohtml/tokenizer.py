import re
from typing import Dict, Iterator, Optional
from .constants import RAWTEXT_ELEMENTS

TAG_OPEN_RE = re.compile(r"<(!?)(/)?([a-zA-Z0-9][-a-zA-Z0-9:]*)(.*?)>")
ATTR_RE = re.compile(
    r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)"|\s*=\s*\'([^\']*)\'|\s*=\s*([^>\s]+)|)(?=\s|$)'
)


class HTMLToken:
    """Represents a token in the HTML stream"""

    def __init__(
        self,
        type_: str,
        data: str = None,
        tag_name: str = None,
        attributes: Dict[str, str] = None,
        is_self_closing: bool = False,
    ):
        self.type = type_  # 'DOCTYPE', 'StartTag', 'EndTag', 'Comment', 'Character'
        self.data = data
        self.tag_name = tag_name.lower() if tag_name is not None else None
        self.attributes = attributes or {}
        self.is_self_closing = is_self_closing

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
            if (potential_tag == self.rawtext_tag and 
                i < self.length and 
                self.html[i] == ">"):
                self.debug(f"  found matching end tag")
                # Found valid end tag
                text_before = self.html[self.pos:tag_start-2]  # Get text before </
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
        text = self.html[start:self.pos]
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

        # Handle DOCTYPE
        if self.html.startswith("<!DOCTYPE", self.pos, self.pos + 9) or self.html.startswith("<!doctype", self.pos, self.pos + 9):
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
            elif (
                (self.html.startswith("</", self.pos)
                and self.pos + 2 < self.length  # Not at EOF
                and not (self.html[self.pos + 2].isascii() and self.html[self.pos + 2].isalpha()))
                or self.html.startswith("<!", self.pos)
                or self.html.startswith("<?", self.pos)
            ):
                return self._handle_bogus_comment()

        # Special case: </ at EOF should be treated as text
        if self.html.startswith("</", self.pos) and self.pos + 2 >= self.length:
            self.pos = self.length  # Consume all remaining input
            return HTMLToken("Character", data="</")

        # Try to match a tag using TAG_OPEN_RE
        match = TAG_OPEN_RE.match(self.html[self.pos:])
        if match:
            bang, is_end_tag, tag_name, attributes = match.groups()
            self.pos += len(match.group(0))  # Advance past the entire tag

            # Handle state transitions for start tags
            if not is_end_tag and tag_name.lower() in RAWTEXT_ELEMENTS:
                self.debug(f"Switching to RAWTEXT mode for {tag_name}")
                self.state = "RAWTEXT"
                self.rawtext_tag = tag_name.lower()

            # Return the appropriate token
            if is_end_tag:
                return HTMLToken("EndTag", tag_name=tag_name)
            else:
                attrs = self._parse_attributes(attributes)
                return HTMLToken("StartTag", tag_name=tag_name, attributes=attrs)

        # If we get here, we found a < that isn't part of a valid tag
        self.pos += 1
        return HTMLToken("Character", data="<")

    def _try_text(self) -> Optional[HTMLToken]:
        """Try to match text at current position"""
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
        return HTMLToken("Character", data=text) if text else None

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """Parse attributes from a string using the ATTR_RE pattern"""
        attr_string = attr_string.strip().rstrip("/")
        matches = ATTR_RE.findall(attr_string)
        attributes = {}
        for attr_name, val1, val2, val3 in matches:
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name] = attr_value
        return attributes

    def _handle_comment(self) -> HTMLToken:
        """Handle comment according to HTML5 spec"""
        self.debug(f"_handle_comment: pos={self.pos}, state={self.state}")
        self.pos += 4  # Skip <!--
        start = self.pos
        
        while self.pos + 2 < self.length:
            if self.html[self.pos:self.pos + 3] == "-->":
                comment_text = self.html[start:self.pos]
                self.pos += 3  # Skip -->
                return HTMLToken("Comment", data=comment_text)
            self.pos += 1
        
        # If we reach here, no proper end to comment was found
        # Consume the rest as comment data
        comment_text = self.html[start:]
        self.pos = self.length
        return HTMLToken("Comment", data=comment_text)

    def _handle_bogus_comment(self) -> HTMLToken:
        """Handle bogus comment according to HTML5 spec"""
        self.debug(f"_handle_bogus_comment: pos={self.pos}, state={self.state}")
        # For <?, include the ? in the comment
        if self.html.startswith("<?", self.pos):
            start = self.pos + 1  # Only skip <
        
        # For </, skip both < and / and start from the next char
        elif self.html.startswith("</", self.pos):
            start = self.pos + 2  # Skip both < and /
        
        # For <!, skip both < and !
        else:  # starts with <!
            start = self.pos + 2  # Skip <!
        
        # Regular bogus comment
        while self.pos < self.length:
            if self.html[self.pos] == ">":
                comment_text = self.html[start : self.pos]
                self.pos += 1
                return HTMLToken("Comment", data=comment_text)
            self.pos += 1

        # EOF: emit what we have
        return HTMLToken("Comment", data=self.html[start:])
