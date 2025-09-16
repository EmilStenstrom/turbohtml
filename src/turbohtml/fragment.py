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
    treat_all_as_text: bool = False  # For rawtext/RCDATA fragment contexts: emit single Character token


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


def _supp_duplicate_section_wrapper(parser, context, token, fragment_context):
    """Suppress an explicit table section start tag that duplicates the fragment context.

    When parsing a fragment with context <tbody>/<thead>/<tfoot>/<tr>/<td>/<th>, the spec's
    algorithm conceptually starts *inside* that element (except for td/th/tr row/cell specifics
    which we model via DocumentState). If the HTML being parsed begins with the literal tag
    matching the fragment context (e.g. fragment_context='tbody' and incoming '<tbody>'), we
    must NOT create an extra wrapper element: the context element is implicit. The WHATWG test
    expectations treat that token as ignored (parse error recorded separately) rather than
    generating an additional nested section. We restrict suppression to the synthetic fragment
    root level to avoid swallowing legitimate nested sections deeper in the tree (rare but
    spec‑permitted in some malformed inputs).

    Conditions:
      - token is a StartTag
      - fragment_context in target set
      - token.tag_name == fragment_context
      - current_parent is the document-fragment root (no prior element established)
    """
    if token.type != "StartTag":
        return False
    if fragment_context not in {"tbody", "thead", "tfoot", "tr", "td", "th"}:
        return False
    if token.tag_name != fragment_context:
        return False
    # Only suppress when still at the synthetic fragment root (no element parent yet)
    if context.current_parent and context.current_parent.tag_name == "document-fragment":
        return True
    return False


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
    "title": FragmentSpec(name="title", suppression_predicates=[_supp_doctype], treat_all_as_text=True),
    "textarea": FragmentSpec(name="textarea", suppression_predicates=[_supp_doctype], treat_all_as_text=True),
    "style": FragmentSpec(name="style", suppression_predicates=[_supp_doctype], treat_all_as_text=True),
    "script": FragmentSpec(name="script", suppression_predicates=[_supp_doctype], treat_all_as_text=True),
    "xmp": FragmentSpec(name="xmp", suppression_predicates=[_supp_doctype], treat_all_as_text=True),
    "iframe": FragmentSpec(name="iframe", suppression_predicates=[_supp_doctype], treat_all_as_text=True),
    "noembed": FragmentSpec(name="noembed", suppression_predicates=[_supp_doctype], treat_all_as_text=True),
    "noframes": FragmentSpec(name="noframes", suppression_predicates=[_supp_doctype], treat_all_as_text=True),
    "table": FragmentSpec(
        name="table",
        suppression_predicates=[_supp_doctype],
        pre_token_hooks=[],
    ),
    "tbody": FragmentSpec(
        name="tbody",
        pre_token_hooks=[],  # hook added later after definition
        suppression_predicates=[_supp_doctype, _supp_duplicate_section_wrapper],
    ),
    "thead": FragmentSpec(
        name="thead",
        pre_token_hooks=[],
        suppression_predicates=[_supp_doctype, _supp_duplicate_section_wrapper],
    ),
    "tfoot": FragmentSpec(
        name="tfoot",
        pre_token_hooks=[],
        suppression_predicates=[_supp_doctype, _supp_duplicate_section_wrapper],
    ),
}


def _implied_table_section_pre_token(parser: "TurboHTML", context, token: HTMLToken):
    """Spec-aligned implied tbody generation (not a heuristic relocation).

    HTML Standard: When a <tr> start tag is processed in the *in table* insertion mode
    and no table section element (tbody/thead/tfoot) is currently open, the parser
    implicitly creates a <tbody> element and switches insertion mode to *in table body*.

    During fragment parsing we do not run the full insertion mode cascade; to avoid a
    post-pass fix-up we apply the minimal equivalent here: if a StartTag 'tr' is about
    to be handled and the current parent is neither tbody/thead/tfoot nor a properly
    seeded context element, but we are inside (or directly under) a table element, we
    create a tbody as the appropriate parent.

    Conditions (all must hold):
      - token is StartTag 'tr'
      - there exists an ancestor <table> from current_parent upward OR fragment context
        indicates table-adjacent (table, tbody, thead, tfoot, tr, td, th)
      - current_parent is not one of tbody/thead/tfoot/tr (already positioned)
      - there is no existing tbody/thead/tfoot among root children that should be used
    """
    if token.type != "StartTag" or token.tag_name != "tr":
        return

    # If we're already within a proper section, nothing to do.
    cp_tag = context.current_parent.tag_name
    if cp_tag in ("tbody", "thead", "tfoot", "tr"):
        return

    # Ascend to find a table ancestor (stop at document fragment root). We also record the
    # last encountered section (tbody/thead/tfoot) so we can re-enter it if flow content
    # (e.g. <a>) temporarily changed current_parent before the <tr> token.
    node = context.current_parent
    table_ancestor = None
    last_section = None
    while node and node.tag_name != "document-fragment":
        if node.tag_name in ("tbody", "thead", "tfoot") and last_section is None:
            last_section = node
        if node.tag_name == "table":
            table_ancestor = node
            break
        node = node.parent
    if not table_ancestor:
        # Consult open elements stack (fragment cases with fostered content may leave us outside)
        for el in reversed(list(context.open_elements._stack)):
            if el.tag_name == "table":
                table_ancestor = el
                break
    if not table_ancestor:
        return  # No active table to adjust

    # Recovery: if a table ancestor exists and one (or more) section element children already
    # exist under that table, prefer re-entering the *last* such section rather than synthesizing
    # a new tbody (matches spec which would have kept it open).
    if last_section is None:
        # Search direct children of table for an existing section if we climbed from an inline
        # descendant (e.g., <tbody><a> ... <tr>) where current_parent is the table or deeper inline.
        for ch in reversed(table_ancestor.children):  # reverse: prefer most recent
            if ch.tag_name in ("tbody", "thead", "tfoot"):
                last_section = ch
                break
    if last_section is not None:
        context.move_to_element(last_section)
        return

    # No existing section – create implied tbody under the table ancestor (or at current parent if it *is* table)
    attach_parent = table_ancestor
    # (Instrumentation removed) – earlier debug printed table children when synthesizing tbody.
    tbody = Node("tbody")
    # Insert before first <tr> child to preserve ordering if such a row already slipped in.
    for i, ch in enumerate(attach_parent.children):
        if ch.tag_name == "tr":
            attach_parent.children.insert(i, tbody)
            tbody.parent = attach_parent
            context.move_to_element(tbody)
            return
    attach_parent.append_child(tbody)
    context.move_to_element(tbody)


### Note:
# Nested table row placement inside fragment table sections is handled directly in
# table_modes.fragment_table_section_insert (nearest section ancestor). 

# Register implied section hook for table-related fragment contexts
for ctx_name in ("html", "table", "tbody", "thead", "tfoot", "td", "th", "tr"):
    spec = FRAGMENT_SPECS.get(ctx_name)
    if spec:
        spec.pre_token_hooks.append(_implied_table_section_pre_token)


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
    parser.tokenizer = HTMLTokenizer(parser.html)
    spec = FRAGMENT_SPECS.get(fragment_context)

    # NOTE: Earlier experimental synthetic stack seeding (table/tbody/tr) for td/th/tr fragment
    # contexts was removed after introducing regressions (innerHTML pass rate drop). Any required
    # implied section or row alignment now handled via pre‑token hooks and normal insertion logic
    # without seeding non‑DOM ancestors.
    synthetic_stack = []  # retained for pruning logic compatibility (now always empty)

    if spec and spec.treat_all_as_text:
        parser.tokenizer._pending_tokens.append(
            HTMLToken("Character", data=parser.html)
        )
        parser.tokenizer.pos = parser.tokenizer.length
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
                    parser.debug(f"Suppression predicate error: {pred}")
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

    # Synthetic stack pruning no-op (bootstrap disabled).
