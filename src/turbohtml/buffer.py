from collections import deque


class FromSet:
    __slots__ = ("char",)

    def __init__(self, char):
        self.char = char


class NotFromSet:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class BufferQueue:
    __slots__ = ("_buffers",)

    def __init__(self):
        self._buffers = deque()

    def is_empty(self):
        self._discard_empty_prefix()
        return not self._buffers

    def push_back(self, chunk):
        if chunk:
            self._buffers.append([chunk, 0])

    def push_front(self, chunk):
        if chunk:
            self._buffers.appendleft([chunk, 0])

    def pop_front(self):
        if self._buffers:
            self._buffers.popleft()

    def peek(self):
        self._discard_empty_prefix()
        if not self._buffers:
            return None
        chunk, index = self._buffers[0]
        return chunk[index]

    def next(self):
        self._discard_empty_prefix()
        if not self._buffers:
            return None
        chunk, index = self._buffers[0]
        char = chunk[index]
        index += 1
        if index >= len(chunk):
            self._buffers.popleft()
        else:
            self._buffers[0][1] = index
        return char

    def pop_except_from(self, char_set):
        if self.is_empty():
            return None
        gathered = []
        while True:
            c = self.peek()
            if c is None:
                break
            if char_set.contains(c):
                if gathered:
                    return NotFromSet("".join(gathered))
                self.next()
                return FromSet(c)
            gathered.append(self.next())
        if gathered:
            return NotFromSet("".join(gathered))
        return None

    def eat(self, pattern, eq):
        if not pattern:
            return True
        lookahead = self._peek_chars(len(pattern))
        if len(lookahead) < len(pattern):
            return None
        matched = True
        for have, want in zip(lookahead, pattern):
            if not eq(ord(have), ord(want)):
                matched = False
                break
        if matched:
            for _ in range(len(pattern)):
                self.next()
        return matched

    def _peek_chars(self, count):
        result = []
        for chunk, index in self._buffers:
            upper = len(chunk)
            while index < upper and len(result) < count:
                result.append(chunk[index])
                index += 1
            if len(result) >= count:
                break
        return result

    def _discard_empty_prefix(self):
        while self._buffers and self._buffers[0][1] >= len(self._buffers[0][0]):
            self._buffers.popleft()
