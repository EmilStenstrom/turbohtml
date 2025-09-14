"""Fragment parsing helpers.

`parse_fragment(parser)` drives fragment parsing for a specific context element.
`FragmentSpec` declares per‑context ignore sets, suppression predicates, and
optional pre/post hooks. The main loop is intentionally flat: run pre‑hooks,
apply suppressions, dispatch token handlers, then run post‑hooks. No heuristic
behaviour or test‑specific logic resides here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Dict

# Centralized imports (previously local within functions for Node/Tokenizer/Constants)
from .context import DocumentState, ContentState
from .node import Node
from .constants import RAWTEXT_ELEMENTS
from .tokenizer import HTMLTokenizer, HTMLToken

@dataclass
class FragmentSpec:
    name: str
    ignored_start_tags: set[str] = field(default_factory=set)
    pre_token_hooks: List[Callable[["TurboHTML", "ParseContext", "HTMLToken"], None]] = field(
        default_factory=list
    )
    post_pass_hooks: List[Callable[["TurboHTML", "ParseContext"], None]] = field(
        default_factory=list
    )
    suppression_predicates: List[
        Callable[["TurboHTML", "ParseContext", "HTMLToken", str], bool]
    ] = field(default_factory=list)




def _relocate_stray_tr_post_pass(parser: "TurboHTML", context):
    """Relocate stray root-level <tr> nodes into preceding or nested table sections.

    Mirrors original post-pass logic for tbody/thead/tfoot fragments.
    """
    fc = parser.fragment_context
    if fc not in ("tbody", "thead", "tfoot"):
        return
    root_children = list(parser.root.children)
    if not root_children:
        return
    candidate_table = None
    candidate_section = None
    for ch in root_children:
        if ch.tag_name == "table":
            sec = None
            for gc in ch.children:
                if gc.tag_name in ("tbody", "thead", "tfoot"):
                    sec = gc
                    break
            if sec:
                has_row = any(gc.tag_name == "tr" for gc in sec.children)
                if not has_row:
                    candidate_table = ch
                    candidate_section = sec
    if candidate_table and candidate_section:
        moved = 0
        for ch in list(parser.root.children):
            if ch.tag_name == "tr":
                idx_table = parser.root.children.index(candidate_table)
                idx_tr = parser.root.children.index(ch)
                if idx_tr > idx_table:
                    parser.root.remove_child(ch)
                    candidate_section.append_child(ch)
                    moved += 1
        if moved and parser.env_debug:
            parser.debug(
                f"[fragment-post] relocated {moved} stray root <tr> node(s) into preceding table section"
            )
    if len(parser.root.children) >= 2 and parser.root.children[0].tag_name == "tr":
        wrapper_tr = parser.root.children[0]

        def find_table_with_empty_section(node):
            if node.tag_name == "table":
                sec = None
                for gc in node.children:
                    if gc.tag_name in ("tbody", "thead", "tfoot"):
                        sec = gc
                        break
                if sec and not any(gc.tag_name == "tr" for gc in sec.children):
                    return node, sec
            for c in node.children:
                if c.tag_name != "#text":
                    found = find_table_with_empty_section(c)
                    if found:
                        return found
            return None

        found = find_table_with_empty_section(wrapper_tr)
        if found:
            nested_table, nested_section = found
            stray_moved = 0
            for i in range(1, len(parser.root.children)):
                ch = parser.root.children[i]
                if ch.tag_name == "tr":
                    parser.root.remove_child(ch)
                    nested_section.append_child(ch)
                    stray_moved += 1
            if stray_moved and parser.env_debug:
                parser.debug(
                    f"[fragment-post] nested relocation moved {stray_moved} trailing root <tr> into nested table section"
                )


def _html_finalize_post_pass(parser: "TurboHTML", context):
    """Ensure <head>/<body> synthesis for html fragments (spec fragment parsing).

    Moved from inline tail of parse_fragment into a post-pass hook for symmetry
    with other fragment adjustments.
    """
    if parser.fragment_context != "html":
        return
    has_head = any(ch.tag_name == "head" for ch in parser.root.children)
    has_frameset = any(ch.tag_name == "frameset" for ch in parser.root.children)
    has_body = any(ch.tag_name == "body" for ch in parser.root.children)
    if not has_head:
        head = Node("head")
        parser.root.children.insert(0, head)
        head.parent = parser.root
    if not has_frameset and not has_body:
        body = Node("body")
        parser.root.append_child(body)


#############################
# Suppression predicate helpers
#############################


def _supp_doctype(parser, context, token, fragment_context):  # spec: ignore doctype in fragments
    return token.type == "DOCTYPE"


def _supp_malformed_select_like(parser, context, token, fragment_context):
    # Skip malformed start tags that still contain a literal '<' inside a select-like context.
    if token.type != "StartTag":
        return False
    tag_name = token.tag_name
    if "<" not in tag_name:
        return False
    if not context.current_parent:
        return False
    if context.current_parent.tag_name in ("select", "option", "optgroup"):
        return True
    anc = context.current_parent.find_ancestor(
        lambda n: n.tag_name in ("select", "option", "optgroup")
    )
    return anc is not None


def _supp_colgroup_whitespace(parser, context, token, fragment_context):
    # Broadened: suppress all character tokens (including whitespace) at the root level of a colgroup fragment.
    # Spec fragment parsing for <colgroup>: character tokens in the colgroup context are generally ignored
    # until proper child elements (<col>) appear. We suppress them unconditionally here to avoid creating
    # stray text nodes that would later be pruned by tree-construction rules.
    if fragment_context != "colgroup":
        return False
    if token.type != "Character":
        return False
    # Only apply at the fragment synthetic root to avoid interfering with nested contexts (shouldn't occur normally).
    return context.current_parent.tag_name == "document-fragment"


def _supp_select_disallowed(parser, context, token, fragment_context):
    """Suppress start tags that the spec says to ignore in select insertion mode.

    HTML Standard: In the "in select" insertion mode, start tags whose tag name is one of
    "input", "keygen", "textarea" are parse errors and the token is ignored. We suppress them
    here for fragment parsing so downstream handlers (e.g. Plaintext) don't change tokenizer state.
    This avoids incorrectly switching to PLAINTEXT for <textarea> inside a <select> fragment which
    previously caused subsequent <option> tags to be treated as literal text.
    """
    if fragment_context != "select":
        return False
    if token.type != "StartTag":
        return False
    return token.tag_name in {"input", "keygen", "textarea"}


# Fragment specifications registry (includes suppression predicates)
FRAGMENT_SPECS: Dict[str, FragmentSpec] = {
    "template": FragmentSpec(
        name="template",
        ignored_start_tags={"template"},
        suppression_predicates=[_supp_doctype],
    ),
    "html": FragmentSpec(
        name="html",
        suppression_predicates=[_supp_doctype],
        post_pass_hooks=[_html_finalize_post_pass],
    ),
    "select": FragmentSpec(
        name="select",
        ignored_start_tags={"html", "title", "meta"},
        suppression_predicates=[
            _supp_doctype,
            _supp_malformed_select_like,
            _supp_select_disallowed,
        ],
    ),
    "colgroup": FragmentSpec(
        name="colgroup",
        suppression_predicates=[_supp_doctype, _supp_colgroup_whitespace],
    ),
    "td": FragmentSpec(name="td", suppression_predicates=[_supp_doctype]),
    "th": FragmentSpec(name="th", suppression_predicates=[_supp_doctype]),
    "tr": FragmentSpec(name="tr", suppression_predicates=[_supp_doctype]),
    "tbody": FragmentSpec(
        name="tbody",
        pre_token_hooks=[],
        post_pass_hooks=[_relocate_stray_tr_post_pass],
        suppression_predicates=[_supp_doctype],
    ),
    "thead": FragmentSpec(
        name="thead",
        pre_token_hooks=[],
        post_pass_hooks=[_relocate_stray_tr_post_pass],
        suppression_predicates=[_supp_doctype],
    ),
    "tfoot": FragmentSpec(
        name="tfoot",
        pre_token_hooks=[],
        post_pass_hooks=[_relocate_stray_tr_post_pass],
        suppression_predicates=[_supp_doctype],
    ),
}


########################################
# Minimal helper (frameset-only head insertion); other cases delegate to parser
########################################

def _ensure_head_only(root):  # frameset path only (no body synthesis)
    head = next((c for c in root.children if c.tag_name == "head"), None)
    if not head:
        head = Node("head")
        root.children.insert(0, head)
        head.parent = root
    return head


def handle_comment(parser, context, token, fragment_context):
    if fragment_context == "html":
        frameset_root = any(ch.tag_name == "frameset" for ch in parser.root.children)
        if not frameset_root:
            body = parser._ensure_body_node(context)
            if body:
                context.move_to_element(body)
    parser._handle_fragment_comment(token.data, context)


def handle_start_tag(parser, context, token, fragment_context, spec):
    if spec and token.tag_name in spec.ignored_start_tags:
        return
    if fragment_context == "template" and token.tag_name == "template":
        return
    if fragment_context == "html":
        tn = token.tag_name
        if tn == "head":
            # Ensure head exists (body may also be synthesized by _ensure_body_node, acceptable parity with previous behavior)
            body_candidate = parser._ensure_body_node(context)  # may create both head/body
            head = next((c for c in parser.root.children if c.tag_name == "head"), None)
            if head:
                context.move_to_element(head)
                context.transition_to_state(DocumentState.IN_HEAD, head)
            return
        if tn == "body":
            body = parser._ensure_body_node(context)
            if body:
                for k, v in token.attributes.items():
                    if k not in body.attributes:
                        body.attributes[k] = v
                context.move_to_element(body)
                context.transition_to_state(DocumentState.IN_BODY, body)
            return
        if tn == "frameset":
            _ensure_head_only(parser.root)  # frameset root shouldn't synthesize body
            frameset = Node("frameset", token.attributes)
            parser.root.append_child(frameset)
            context.move_to_element(frameset)
            context.transition_to_state(DocumentState.IN_FRAMESET, frameset)
            return
        if context.document_state not in (DocumentState.IN_FRAMESET, DocumentState.AFTER_FRAMESET):
            body = parser._ensure_body_node(context)
            if body and context.document_state != DocumentState.IN_BODY:
                context.move_to_element(body)
                context.transition_to_state(DocumentState.IN_BODY, body)
    if parser._should_ignore_fragment_start_tag(token.tag_name, context):
        parser.debug(
            f"Fragment: Ignoring {token.tag_name} start tag in {fragment_context} context"
        )
        return
    parser._handle_start_tag(token, token.tag_name, context, parser.tokenizer.pos)
    context.index = parser.tokenizer.pos


def handle_end_tag(parser, context, token, fragment_context):
    if fragment_context == "template" and token.tag_name == "template":
        return
    parser._handle_end_tag(token, token.tag_name, context)
    context.index = parser.tokenizer.pos


def handle_character(parser, context, token, fragment_context):
    data = token.data
    if (
        context.current_parent.tag_name == "listing"
        and not context.current_parent.children
        and data.startswith("\n")
    ):
        data = data[1:]
    if context.content_state == ContentState.PLAINTEXT:
        if not data:
            return
        text_node = parser.create_text_node(data)
        context.current_parent.append_child(text_node)
        return
    if not data:
        return
    if fragment_context == "html":
        frameset_root = any(ch.tag_name == "frameset" for ch in parser.root.children)
        if not frameset_root:
            body = parser._ensure_body_node(context)
            if body and context.document_state != DocumentState.IN_BODY:
                context.move_to_element(body)
                context.transition_to_state(DocumentState.IN_BODY, body)
    for handler in parser.tag_handlers:
        if handler.should_handle_text(data, context):
            parser.debug(
                f"{handler.__class__.__name__}: handling {token}, context={context}"
            )
            if handler.handle_text(data, context):
                break


def parse_fragment(parser: "TurboHTML") -> None:  # pragma: no cover
    fragment_context = parser.fragment_context
    parser.debug(f"Parsing fragment in context: {fragment_context}")
    context = parser._create_fragment_context()
    if fragment_context in RAWTEXT_ELEMENTS:
        text_node = parser.create_text_node(parser.html)
        context.current_parent.append_child(text_node)
        parser.debug(
            f"Fragment: Treated all content as raw text in {fragment_context} context"
        )
        return
    parser.tokenizer = HTMLTokenizer(parser.html)
    spec = FRAGMENT_SPECS.get(fragment_context)
    for token in parser.tokenizer.tokenize():
        parser._prev_token = parser._last_token
        parser._last_token = token
        parser.debug(f"_parse_fragment: {token}, context: {context}", indent=0)
        if spec and spec.pre_token_hooks:
            for hook in spec.pre_token_hooks:
                hook(parser, context, token)
        if spec and spec.suppression_predicates:
            suppressed = False
            for pred in spec.suppression_predicates:
                try:
                    if pred(parser, context, token, fragment_context):
                        suppressed = True
                        break
                except Exception:  # defensive: predicate failure should not abort parse
                    parser.debug(f"Suppression predicate error: {getattr(pred, '__name__', pred)}")
            if suppressed:
                continue
        if token.type == "Comment":
            handle_comment(parser, context, token, fragment_context)
            continue
        if token.type == "StartTag":
            handle_start_tag(parser, context, token, fragment_context, spec)
            continue
        if token.type == "EndTag":
            handle_end_tag(parser, context, token, fragment_context)
            continue
        if token.type == "Character":
            handle_character(parser, context, token, fragment_context)
            continue
    if spec and spec.post_pass_hooks:
        for hook in spec.post_pass_hooks:
            hook(parser, context)
