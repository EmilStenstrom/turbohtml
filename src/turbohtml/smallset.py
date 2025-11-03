class SmallCharSet:
    __slots__ = ("_mask",)

    def __init__(self, chars):
        mask = 0
        for c in chars:
            code = ord(c)
            if code >= 128:
                raise ValueError("SmallCharSet only supports ASCII")
            mask |= 1 << code
        self._mask = mask

    def contains(self, c):
        code = ord(c)
        if code >= 128:
            return False
        return (self._mask >> code) & 1 == 1
