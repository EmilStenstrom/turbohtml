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

from .context import DocumentState, ContentState, ParseContext
from .constants import RAWTEXT_ELEMENTS
from .node import Node
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

def _supp_duplicate_cell_or_initial_row(parser, context, token, fragment_context):
    """Suppress first context-matching cell tag (td/th) or initial stray <tr> in td/th fragment.

    Mirrors legacy parser._should_ignore_fragment_start_tag behavior:
      * In a td or th fragment, ignore the very first td/th start tag encountered at the
        synthetic fragment root (we are conceptually already inside that cell).
      * In a td or th fragment, if a leading <tr> appears before any cell has been accepted,
        suppress it (legacy ignored this as context alignment artifact).
    After one suppression, subsequent cells or rows are allowed.
    """
    if token.type != "StartTag":
        return False
    tn = token.tag_name
    if fragment_context not in {"td", "th"}:
        return False
    # Determine if at fragment root
    cp = context.current_parent
    at_root = cp is parser.root or (cp and cp.tag_name == "document-fragment")
    if not at_root:
        return False
    # Use context.fragment_context_ignored flag consistent with parser logic
    if not context.fragment_context_ignored and tn in {"td", "th"}:
        context.fragment_context_ignored = True
        return True
    if not context.fragment_context_ignored and tn == "tr":
        context.fragment_context_ignored = True
        return True
    return False

def _supp_fragment_nonhtml_structure(parser, context, token, fragment_context):
    """Suppress document/table structural start tags in non-structural fragment contexts.

    Scope:
      * Applies only when fragment_context is NOT one of html, table, tbody, thead, tfoot, tr, td, th
      * Suppresses StartTag tokens for document-level structural elements {'html','head','body','frameset'}
        (first <body> only; subsequent bodies allowed for attribute merge semantics)
      * Suppresses StartTag tokens that are table structural wrappers when the fragment context is a
        non-table phrasing/flow context (e.g. innerHTML of a <span> containing stray <td>)
    """
    if token.type != "StartTag":
        return False
    tn = token.tag_name
    if fragment_context in {"html", "table", "tbody", "thead", "tfoot", "tr", "td", "th"}:
        return False
    if tn in {"html", "head", "frameset"}:
        return True
    if tn == "body":
        has_body = any(ch.tag_name == "body" for ch in parser.root.children)
        if not has_body:
            return True
        return False
    if tn in {"caption", "colgroup", "tbody", "thead", "tfoot", "tr", "td", "th"}:
        return True
    return False

def _supp_fragment_legacy_context(parser, context, token, fragment_context):
    """Aggregate remaining legacy suppression logic previously in parser._should_ignore_fragment_start_tag.

    Responsibilities migrated:
      * Single initial context element suppression for tbody/thead/tfoot/tr/td/th (now covered elsewhere but kept idempotent)
      * Nested <table> start tag suppression inside a table fragment
      * Frameset-mode restrictions inside html fragment (non structural tokens dropped after frameset)
    """
    if token.type != "StartTag":
        return False
    tn = token.tag_name
    # Table fragment: ignore nested <table>
    if fragment_context == "table" and tn == "table":
        return True
    # Additional frameset restrictions (html fragment only)
    if fragment_context == "html" and context.document_state in (DocumentState.IN_FRAMESET, DocumentState.AFTER_FRAMESET):
        if tn not in {"frameset", "frame", "noframes"}:
            return True
    return False

# Fragment specifications registry (includes suppression predicates)
FRAGMENT_SPECS: Dict[str, FragmentSpec] = {
    "template": FragmentSpec(
        name="template",
        ignored_start_tags={"template"},
        suppression_predicates=[_supp_doctype, _supp_fragment_nonhtml_structure],
    ),
    "html": FragmentSpec(
        name="html",
        suppression_predicates=[_supp_doctype, _supp_fragment_legacy_context],
        post_pass_hooks=[_html_finalize_post_pass],
    ),
    "select": FragmentSpec(
        name="select",
        ignored_start_tags={"html", "title", "meta"},
        suppression_predicates=[
            _supp_doctype,
            _supp_malformed_select_like,
            _supp_select_disallowed,
            _supp_fragment_nonhtml_structure,
        ],
    ),
    "colgroup": FragmentSpec(
        name="colgroup",
        suppression_predicates=[_supp_doctype, _supp_colgroup_whitespace, _supp_fragment_nonhtml_structure],
    ),
    "td": FragmentSpec(name="td", suppression_predicates=[_supp_doctype, _supp_duplicate_cell_or_initial_row]),
    "th": FragmentSpec(name="th", suppression_predicates=[_supp_doctype, _supp_duplicate_cell_or_initial_row]),
    "tr": FragmentSpec(name="tr", suppression_predicates=[_supp_doctype, _supp_duplicate_section_wrapper]),
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
        suppression_predicates=[_supp_doctype, _supp_fragment_legacy_context],
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
    # Guarantee html_node exists before delegating to handlers that may reference it.
    # Document parsing calls _ensure_html_node() before non-DOCTYPE/Comment tokens; replicate minimal
    # requirement here to avoid attribute errors in early_start_preprocess hooks during fragment parsing.
    if parser.html_node is None:
        parser._ensure_html_node()
    if fragment_context == "html":
        tn = token.tag_name
        if tn == "head":
            # Ensure head/body exist (acceptable parity with previous behavior)
            parser._ensure_body_node(context)  # may create both head/body
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
    # Fallback suppression for fragment contexts without a FragmentSpec (legacy parser behavior):
    if spec is None:
        tn = token.tag_name
        # Suppress document structural wrappers (except body handled below) and table scaffolding
        if tn in {"html", "head", "frameset"}:
            parser.debug(f"Fragment(fallback): suppressing <{tn}> in context {fragment_context}")
            return
        if tn == "body":
            has_body = any(ch.tag_name == "body" for ch in parser.root.children)
            if not has_body:
                parser.debug("Fragment(fallback): suppressing initial <body>")
                return
        if tn in {"caption", "colgroup", "tbody", "thead", "tfoot", "tr", "td", "th"}:
            parser.debug(f"Fragment(fallback): suppressing stray table structure <{tn}>")
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
    # Defensive: in certain foreign / minimal fragments before first element insertion the
    # current_parent can still be None (synthetic root not yet established). Drop characters
    # until a proper parent exists. This mirrors earlier guard that lived in experimental code.
    if context.current_parent is None:
        return
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
    # Use externalized helper (parser retains wrapper for compatibility)
    context = create_fragment_context(parser)
    parser.tokenizer = HTMLTokenizer(parser.html)
    spec = FRAGMENT_SPECS.get(fragment_context)

    # Some handlers assume parser.html_node exists (mirrors document parsing path). For non-html
    # fragments we still synthesize it lazily ONLY if required; create a minimal <html> so that
    # attribute propagation logic in early_start_preprocess doesn't hit None. This does not affect
    # fragment output because html_node is not attached to parser.root children for non-html contexts.
    if fragment_context != "html" and parser.html_node is None:
        html_node = Node("html")
        parser.html_node = html_node
    # NOTE: Earlier experimental synthetic stack seeding (table/tbody/tr) for td/th/tr fragment
    # contexts was removed after introducing regressions (innerHTML pass rate drop). Any required
    # implied section or row alignment now handled via pre‑token hooks and normal insertion logic
    # without seeding non‑DOM ancestors.

    # Cache spec attributes locally (minor attribute lookup reduction in hot loop)
    pre_hooks = spec.pre_token_hooks if spec and spec.pre_token_hooks else ()
    suppression_preds = (
        spec.suppression_predicates if spec and spec.suppression_predicates else ()
    )
    post_hooks = spec.post_pass_hooks if spec and spec.post_pass_hooks else ()
    treat_all_as_text = spec.treat_all_as_text if spec else False

    if treat_all_as_text:
        parser.tokenizer._pending_tokens.append(
            HTMLToken("Character", data=parser.html)
        )
        parser.tokenizer.pos = parser.tokenizer.length
    for token in parser.tokenizer.tokenize():
        parser._prev_token = parser._last_token
        parser._last_token = token
        parser.debug(f"_parse_fragment: {token}, context: {context}", indent=0)
        if pre_hooks:
            for hook in pre_hooks:
                hook(parser, context, token)
        if suppression_preds:
            suppressed = False
            for pred in suppression_preds:
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
    if post_hooks:
        for hook in post_hooks:
            hook(parser, context)

    # Synthetic stack pruning no-op (bootstrap disabled).


def create_fragment_context(parser: "TurboHTML") -> "ParseContext":
    """Initialize a fragment ParseContext with state derived from the context element.

    Extraction of former TurboHTML._create_fragment_context (no behavior change).
    Lives here with other fragment helpers for cohesion and to keep the parser
    focused on dispatch + high-level orchestration.
    """
    from turbohtml.context import DocumentState as _DS

    fc = parser.fragment_context
    context = ParseContext(len(parser.html), parser.root, debug_callback=parser.debug)

    if fc == "template":
        # Special template: synthesize template/content container then treat as IN_BODY inside content.
        context.transition_to_state(_DS.IN_BODY, parser.root)
        template_node = Node("template")
        parser.root.append_child(template_node)
        content_node = Node("content")
        template_node.append_child(content_node)
        context.move_to_element(content_node)
        return context

    # Map fragment context to initial DocumentState (default IN_BODY)
    state_map = {
        "td": _DS.IN_CELL,
        "th": _DS.IN_CELL,
        "tr": _DS.IN_ROW,
        "thead": _DS.IN_TABLE_BODY,
        "tbody": _DS.IN_TABLE_BODY,
        "tfoot": _DS.IN_TABLE_BODY,
        "html": _DS.INITIAL,
    }
    if fc in state_map:
        target_state = state_map[fc]
    elif fc in RAWTEXT_ELEMENTS:
        target_state = _DS.IN_BODY
    else:
        target_state = _DS.IN_BODY
    context.transition_to_state(target_state, parser.root)

    # Table fragment: adjust to IN_TABLE for section handling
    if fc == "table":
        context.transition_to_state(_DS.IN_TABLE, parser.root)

    # Foreign context detection (math/svg + namespaced)
    if fc:
        if fc in ("math", "svg"):
            context.current_context = fc
            parser.debug(f"Set foreign context to {fc}")
        elif " " in fc:  # namespaced
            namespace_elem = fc.split(" ")[0]
            if namespace_elem in ("math", "svg"):
                context.current_context = namespace_elem
                parser.debug(f"Set foreign context to {namespace_elem}")

    return context
