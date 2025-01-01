from typing import Dict, Optional, Iterator
from .constants import TAG_OPEN_RE, ATTR_RE, COMMENT_RE

class HTMLToken:
    """Represents a token in the HTML stream"""
    def __init__(self, type_: str, data: str = None, tag_name: str = None, 
                 attributes: Dict[str, str] = None, is_self_closing: bool = False):
        self.type = type_  # 'DOCTYPE', 'StartTag', 'EndTag', 'Comment', 'Character'
        self.data = data
        self.tag_name = tag_name.lower() if tag_name is not None else None
        self.attributes = attributes or {}
        self.is_self_closing = is_self_closing

    def __repr__(self):
        if self.type == 'Character':
            preview = self.data[:20]
            suffix = '...' if len(self.data) > 20 else ''
            return f"<{self.type}: '{preview}{suffix}'>"
        if self.type == 'Comment':
            preview = self.data[:20]
            suffix = '...' if len(self.data) > 20 else ''
            return f"<{self.type}: '{preview}{suffix}'>"
        return f"<{self.type}: {self.tag_name or self.data}>"

class HTMLTokenizer:
    """
    HTML5 tokenizer that generates tokens from an HTML string.
    Maintains compatibility with existing parser logic while providing
    a cleaner separation of concerns.
    """
    def __init__(self, html: str):
        self.html = html
        self.length = len(html)
        self.pos = 0
        self.state = "DATA"
        self.rawtext_tag = None
        self.buffer = []
        self.temp_buffer = []
        self.last_pos = self.length  # Store the last position we'll process

    def start_rawtext(self, tag_name: str) -> None:
        """Switch to RAWTEXT state for the given tag"""
        self.state = "RAWTEXT"
        self.rawtext_tag = tag_name
        self.buffer = []
        self.temp_buffer = []

    def tokenize(self) -> Iterator[HTMLToken]:
        """Generate tokens from the HTML string"""
        while self.pos < self.length:
            if self.state == "DATA":
                token = self._try_tag() or self._try_text()
                if token:
                    token.is_last_token = (self.pos >= self.last_pos)
                    yield token
                elif self.pos < self.length:
                    # If neither method produced a token, force advance
                    self.pos += 1
            elif self.state == "RAWTEXT":
                token = self._handle_rawtext()
                if token:
                    token.is_last_token = (self.pos >= self.last_pos)
                    yield token
            else:
                # Handle other states...
                pass

    def _handle_rawtext(self) -> Optional[HTMLToken]:
        """Handle RAWTEXT content according to HTML5 spec"""
        while self.pos < self.length:
            char = self.html[self.pos]

            if char == '<':
                # If we have buffered content, emit it first
                if self.buffer:
                    text = ''.join(self.buffer)
                    self.buffer = []
                    return HTMLToken('Character', data=text)

                # Look for potential end tag
                if (self.pos + 2 < self.length and 
                    self.html[self.pos + 1] == '/'):
                    # Start collecting potential end tag name
                    self.pos += 2  # Skip </
                    self.temp_buffer = []
                    start_pos = self.pos  # Remember where tag name started
                    
                    # Collect tag name
                    while (self.pos < self.length and 
                           self.html[self.pos].isascii() and 
                           self.html[self.pos].isalpha()):
                        self.temp_buffer.append(self.html[self.pos].lower())
                        self.pos += 1
                    
                    # Check if it matches our current tag
                    tag_name = ''.join(self.temp_buffer)
                    if (tag_name == self.rawtext_tag):
                        # Skip whitespace
                        while self.pos < self.length and self.html[self.pos].isspace():
                            self.pos += 1
                        
                        if self.pos < self.length and self.html[self.pos] == '>':
                            self.pos += 1  # Skip >
                            # Look for whitespace after end tag
                            whitespace = []
                            while self.pos < self.length and self.html[self.pos].isspace():
                                whitespace.append(self.html[self.pos])
                                self.pos += 1
                            
                            # If we found whitespace, emit it as a separate token
                            if whitespace:
                                self.state = "DATA"
                                self.rawtext_tag = None
                                return HTMLToken('EndTag', tag_name=tag_name, attributes={'trailing_space': ''.join(whitespace)})
                            
                            self.state = "DATA"
                            self.rawtext_tag = None
                            return HTMLToken('EndTag', tag_name=tag_name)
                        
                        # Not a proper end tag, reset position
                        self.pos = start_pos
                        self.buffer.append('</')
                    else:
                        # Not our tag, reset position
                        self.pos = start_pos
                        self.buffer.append('</')
                else:
                    # Just a < character
                    self.buffer.append(char)
                    self.pos += 1
            else:
                self.buffer.append(char)
                self.pos += 1

        # If we reach end of input, emit what we have
        if self.buffer:
            text = ''.join(self.buffer)
            self.buffer = []
            return HTMLToken('Character', data=text)
        return None

    def _try_tag(self) -> Optional[HTMLToken]:
        """Try to match a tag at current position"""
        if not self.html.startswith('<', self.pos):
            return None

        # If this is the last character, treat it as text
        if self.pos + 1 >= self.length:
            self.pos += 1
            return HTMLToken('Character', data='<')

        # Handle DOCTYPE
        if self.html.startswith('<!DOCTYPE', self.pos, self.pos + 9) or \
           self.html.startswith('<!doctype', self.pos, self.pos + 9):
            end_pos = self.html.find('>', self.pos)
            if end_pos == -1:
                end_pos = self.length
            doctype_text = self.html[self.pos + 9:end_pos].strip()
            self.pos = end_pos + 1
            return HTMLToken('DOCTYPE', data=doctype_text)

        # Handle comments and special cases
        if self.html.startswith('<!--', self.pos):
            # Special case: <!--> is treated as <!-- -->
            if self.pos + 4 < self.length and self.html[self.pos + 4] == '>':
                self.pos += 5
                return HTMLToken('Comment', data='')
            return self._handle_comment()
        elif self.html.startswith('<!', self.pos):
            return self._handle_bogus_comment()
        elif self.html.startswith('</', self.pos):
            # Special case: </# should be treated as a bogus comment
            if self.pos + 2 < self.length and not self.html[self.pos + 2].isalpha():
                self.pos += 2  # Skip </
                start = self.pos
                while self.pos < self.length and self.html[self.pos] != '>':
                    self.pos += 1
                comment_text = self.html[start:self.pos]
                if self.pos < self.length:  # Skip closing >
                    self.pos += 1
                return HTMLToken('Comment', data=comment_text)
        elif self.html.startswith('<?', self.pos):
            # Special case: <? should be treated as a bogus comment
            self.pos += 1  # Skip <
            start = self.pos
            while self.pos < self.length and self.html[self.pos] != '>':
                self.pos += 1
            comment_text = self.html[start:self.pos]
            if self.pos < self.length:  # Skip closing >
                self.pos += 1
            return HTMLToken('Comment', data=comment_text)

        # Try to match a tag using TAG_OPEN_RE
        match = TAG_OPEN_RE.match(self.html[self.pos:])
        if match:
            bang, is_end_tag, tag_name, attributes = match.groups()
            self.pos += len(match.group(0))  # Advance past the entire tag

            # Normal tag
            if is_end_tag:
                return HTMLToken('EndTag', tag_name=tag_name)
            else:
                attrs = self._parse_attributes(attributes)
                return HTMLToken('StartTag', tag_name=tag_name, attributes=attrs)

        # If we get here, we found a < that isn't part of a valid tag
        self.pos += 1
        return HTMLToken('Character', data='<')

    def _handle_comment(self) -> HTMLToken:
        """Handle comment according to HTML5 spec"""
        self.pos += 4  # Skip <!--
        
        # Special case: <!--> is treated as <!--  -->
        if self.pos < self.length and self.html[self.pos] == '>':
            self.pos += 1
            return HTMLToken('Comment', data='')
        
        buffer = []
        while self.pos < self.length:
            # Check for comment end
            if self.html.startswith('-->', self.pos):
                self.pos += 3
                return HTMLToken('Comment', data=''.join(buffer))
            
            # Regular character
            buffer.append(self.html[self.pos])
            self.pos += 1
        
        # EOF: emit what we have
        return HTMLToken('Comment', data=''.join(buffer))

    def _handle_bogus_comment(self) -> HTMLToken:
        """Handle bogus comment according to HTML5 spec"""
        self.pos += 2  # Skip <!
        
        # Special case: <!-> is treated as <!--  -->
        if self.pos < self.length and self.html[self.pos] == '-':
            if self.pos + 1 < self.length and self.html[self.pos + 1] == '>':
                self.pos += 2
                return HTMLToken('Comment', data='')
        
        # Regular bogus comment
        start = self.pos
        while self.pos < self.length:
            if self.html[self.pos] == '>':
                comment_text = self.html[start:self.pos]
                self.pos += 1
                return HTMLToken('Comment', data=comment_text)
            self.pos += 1
        
        # EOF: emit what we have
        return HTMLToken('Comment', data=self.html[start:])

    def _try_text(self) -> Optional[HTMLToken]:
        """Try to match text at current position"""
        start = self.pos
        
        # If we're starting with '<', don't try to parse as text
        if self.html[start] == '<':
            return None
        
        while self.pos < self.length:
            if self.html[self.pos] == '<':
                break
            self.pos += 1

        text = self.html[start:self.pos]
        # Only emit non-empty text tokens
        return HTMLToken('Character', data=text) if text else None

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """Parse attributes from a string using the ATTR_RE pattern"""
        attr_string = attr_string.strip().rstrip('/')
        matches = ATTR_RE.findall(attr_string)
        attributes = {}
        for attr_name, val1, val2, val3 in matches:
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name] = attr_value
        return attributes
