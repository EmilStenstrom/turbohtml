from .encoding import decode_html
from .tokenizer import Tokenizer
from .tokens import CommentToken, DoctypeToken, Tag


class StreamSink:
    """A sink that buffers tokens for the stream API."""

    def __init__(self):
        self.tokens = []
        self.open_elements = []  # Required by tokenizer for rawtext checks

    def process_token(self, token):
        # Tokenizer reuses token objects, so we must copy data
        if isinstance(token, Tag):
            # Copy tag data
            self.tokens.append(
                (
                    "start" if token.kind == Tag.START else "end",
                    (token.name, token.attrs.copy()) if token.kind == Tag.START else token.name,
                )
            )
            # Maintain open_elements stack for tokenizer's rawtext checks
            if token.kind == Tag.START:
                # We need a dummy object with namespace for tokenizer checks
                # Tokenizer checks: stack[-1].namespace
                # We can just use a simple object
                class DummyNode:
                    namespace = "html"

                self.open_elements.append(DummyNode())
            else:  # Tag.END
                if self.open_elements:
                    self.open_elements.pop()
                # If open_elements is empty, we ignore the end tag for rawtext tracking purposes
                # (it's an unmatched end tag at the root level)

        elif isinstance(token, CommentToken):
            self.tokens.append(("comment", token.data))

        elif isinstance(token, DoctypeToken):
            dt = token.doctype
            self.tokens.append(("doctype", (dt.name, dt.public_id, dt.system_id)))

        return 0  # TokenSinkResult.Continue

    def process_characters(self, data):
        """Handle character data from tokenizer."""
        self.tokens.append(("text", data))


def stream(html, *, encoding=None):
    """
    Stream HTML events from the given HTML string.
    Yields tuples of (event_type, data).
    """
    if isinstance(html, (bytes, bytearray, memoryview)):
        html, _ = decode_html(bytes(html), transport_encoding=encoding)
    sink = StreamSink()
    tokenizer = Tokenizer(sink)
    tokenizer.initialize(html)

    while True:
        # Run one step of the tokenizer
        is_eof = tokenizer.step()

        # Yield any tokens produced by this step
        if sink.tokens:
            # Coalesce text tokens
            text_buffer = []
            for event, data in sink.tokens:
                if event == "text":
                    text_buffer.append(data)
                else:
                    if text_buffer:
                        yield ("text", "".join(text_buffer))
                        text_buffer = []
                    yield (event, data)

            if text_buffer:
                yield ("text", "".join(text_buffer))

            sink.tokens.clear()

        if is_eof:
            break
