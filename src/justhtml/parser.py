"""Minimal JustHTML parser entry point."""

from .tokenizer import Tokenizer, TokenizerOpts
from .treebuilder import TreeBuilder


class JustHTML:
    __slots__ = ("debug", "fragment_context", "root", "tokenizer", "tree_builder")

    def __init__(
        self,
        html,
        *,
        debug=False,
        fragment_context=None,
        tokenizer_opts=None,
        tree_builder=None,
        iframe_srcdoc=False,
    ):
        self.debug = bool(debug)
        self.fragment_context = fragment_context
        self.tree_builder = tree_builder or TreeBuilder(fragment_context=fragment_context, iframe_srcdoc=iframe_srcdoc)
        opts = tokenizer_opts or TokenizerOpts()

        # For RAWTEXT fragment contexts, set initial tokenizer state and rawtext tag
        if fragment_context and not fragment_context.namespace:
            rawtext_elements = {"textarea", "title", "style"}
            tag_name = fragment_context.tag_name.lower()
            if tag_name in rawtext_elements:
                opts.initial_state = Tokenizer.RAWTEXT
                opts.initial_rawtext_tag = tag_name
            elif tag_name in ("plaintext", "script"):
                opts.initial_state = Tokenizer.PLAINTEXT

        self.tokenizer = Tokenizer(self.tree_builder, opts)
        self.tokenizer.run(html or "")
        self.root = self.tree_builder.finish()
