"""Minimal TurboHTML parser entry point."""

from .tokenizer import Tokenizer, TokenizerOpts
from .treebuilder import TreeBuilder


class TurboHTML:
    __slots__ = ("debug", "tree_builder", "tokenizer", "root", "fragment_context")

    def __init__(
        self,
        html,
        *,
        debug=False,
        fragment_context=None,
        tokenizer_opts=None,
        tree_builder=None,
    ):
        self.debug = bool(debug)
        self.fragment_context = fragment_context
        self.tree_builder = tree_builder or TreeBuilder(fragment_context=fragment_context)
        opts = tokenizer_opts or TokenizerOpts()
        
        # For RAWTEXT fragment contexts, set initial tokenizer state and rawtext tag
        if fragment_context and not fragment_context.namespace:
            rawtext_elements = {"textarea", "title", "style"}
            tag_name = fragment_context.tag_name.lower()
            if tag_name in rawtext_elements:
                opts.initial_state = 39  # RAWTEXT state
                opts.initial_rawtext_tag = tag_name
        
        self.tokenizer = Tokenizer(self.tree_builder, opts)
        self.tokenizer.run(html or "")
        self.root = self.tree_builder.finish()
