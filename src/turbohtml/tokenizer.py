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
        self.pos = 0
        self.length = len(html)

    def tokenize(self) -> Iterator[HTMLToken]:
        """Generate tokens from the HTML string"""
        while self.pos < self.length:
            # 1. Try to match a comment
            if token := self._try_comment():
                yield token
                continue

            # 2. Try to match special tags (bogus comments etc)
            if token := self._try_tag():
                yield token
                continue

            # 3. Try to match a regular tag
            match = TAG_OPEN_RE.match(self.html, self.pos)
            if match and match.start() == self.pos:
                is_exclamation = (match.group(1) == '!')
                is_closing = (match.group(2) == '/')
                tag_name = match.group(3)
                attr_string = match.group(4).strip()

                # Handle DOCTYPE
                if is_exclamation and tag_name.lower() == 'doctype':
                    self.pos = match.end()
                    yield HTMLToken('DOCTYPE')
                    continue

                # Parse attributes
                attributes = self._parse_attributes(attr_string)

                # Check for self-closing
                is_self_closing = attr_string.rstrip().endswith('/')

                self.pos = match.end()

                if is_closing:
                    yield HTMLToken('EndTag', tag_name=tag_name)
                else:
                    yield HTMLToken('StartTag', tag_name=tag_name, 
                                  attributes=attributes, 
                                  is_self_closing=is_self_closing)
                continue

            # 4. Handle character data
            if token := self._consume_character_data():
                yield token
                continue

            # Shouldn't reach here, but advance if we do
            self.pos += 1

    def _try_comment(self) -> Optional[HTMLToken]:
        """Try to match a comment at current position"""
        match = COMMENT_RE.match(self.html, self.pos)
        if not match or match.start() != self.pos:
            return None

        full_match = match.group(0)
        comment_text = match.group(1) or " "

        # Handle special malformed comment cases
        if full_match in ('<!-->', '<!--->'):
            comment_text = ""

        self.pos = match.end()
        return HTMLToken('Comment', data=comment_text)

    def _try_tag(self) -> Optional[HTMLToken]:
        """Try to match a tag at current position"""
        if not self.html.startswith('<', self.pos):
            return None

        # Case 1: </x where x is not an ASCII alpha
        if (self.html.startswith('</', self.pos) and 
            self.pos + 2 < self.length and 
            not self.html[self.pos + 2].isalpha()):
            self.pos += 2  # Skip '</'
            start = self.pos
            while self.pos < self.length and self.html[self.pos] != '>':
                self.pos += 1
            comment_text = self.html[start:self.pos]
            if self.pos < self.length:  # if we found '>', consume it
                self.pos += 1
            return HTMLToken('Comment', data=comment_text)
            
        # Case 2: <? starts bogus comment
        if self.html.startswith('<?', self.pos):
            self.pos += 2  # Skip '<?'
            start = self.pos
            while self.pos < self.length and self.html[self.pos] != '>':
                self.pos += 1
            comment_text = '?' + self.html[start:self.pos]
            if self.pos < self.length:  # if we found '>', consume it
                self.pos += 1
            return HTMLToken('Comment', data=comment_text)
            
        # Case 3: <! not followed by -- or DOCTYPE
        if self.html.startswith('<!', self.pos):
            # Skip proper comments and DOCTYPE
            if (self.html.startswith('<!--', self.pos) or 
                self.html[self.pos:].lower().startswith('<!doctype')):
                return None
            # Otherwise, it's a bogus comment
            self.pos += 2  # Skip '<!'
            start = self.pos
            while self.pos < self.length and self.html[self.pos] != '>':
                self.pos += 1
            comment_text = self.html[start:self.pos]
            if self.pos < self.length:  # if we found '>', consume it
                self.pos += 1
            return HTMLToken('Comment', data=comment_text)

        return None

    def _consume_character_data(self) -> HTMLToken:
        """Consume character data until the next tag or comment"""
        start = self.pos
        while self.pos < self.length:
            if self.html[self.pos] == '<':
                if (COMMENT_RE.match(self.html, self.pos) or 
                    TAG_OPEN_RE.match(self.html, self.pos)):
                    break
            self.pos += 1

        text = self.html[start:self.pos]
        return HTMLToken('Character', data=text)

    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """Parse attributes from a string using the ATTR_RE pattern"""
        attr_string = attr_string.strip().rstrip('/')
        matches = ATTR_RE.findall(attr_string)
        attributes = {}
        for attr_name, val1, val2, val3 in matches:
            attr_value = val1 or val2 or val3 or ""
            attributes[attr_name] = attr_value
        return attributes

    def _handle_bogus_comment(self, prefix: str = '') -> HTMLToken:
        """Handle bogus comment according to spec.
        
        Consumes characters until > or EOF.
        If prefix is provided, it's included at the start of the comment data.
        """
        self.pos += 1  # Skip the current character
        start = self.pos
        # Consume until > or EOF
        while self.pos < self.length and self.html[self.pos] != '>':
            self.pos += 1
            
        comment_text = prefix + self.html[start:self.pos]
        if self.pos < self.length:  # if we found '>', consume it
            self.pos += 1
            
        return HTMLToken('Comment', data=comment_text)
