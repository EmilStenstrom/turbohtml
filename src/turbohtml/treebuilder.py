import enum

from .constants import (
    BLOCK_WITH_P_START,
    BUTTON_SCOPE_TERMINATORS,
    DEFAULT_SCOPE_TERMINATORS,
    DEFINITION_SCOPE_TERMINATORS,
    FOREIGN_ATTRIBUTE_ADJUSTMENTS,
    FOREIGN_BREAKOUT_ELEMENTS,
    FORMAT_MARKER,
    FORMATTING_ELEMENTS,
    HEADING_ELEMENTS,
    HTML4_PUBLIC_PREFIXES,
    HTML_INTEGRATION_POINT_ELEMENTS,
    HTML_INTEGRATION_POINT_SET,
    IMPLIED_END_TAGS,
    LIMITED_QUIRKY_PUBLIC_PREFIXES,
    LIST_ITEM_SCOPE_TERMINATORS,
    MATHML_ATTRIBUTE_ADJUSTMENTS,
    MATHML_TEXT_INTEGRATION_POINT_ELEMENTS,
    MATHML_TEXT_INTEGRATION_POINT_SET,
    NAMESPACE_URL_TO_PREFIX,
    QUIRKY_PUBLIC_MATCHES,
    QUIRKY_PUBLIC_PREFIXES,
    QUIRKY_SYSTEM_MATCHES,
    SPECIAL_ELEMENTS,
    SVG_ATTRIBUTE_ADJUSTMENTS,
    SVG_TAG_NAME_ADJUSTMENTS,
    TABLE_ALLOWED_CHILDREN,
    TABLE_BODY_SCOPE_TERMINATORS,
    TABLE_FOSTER_TARGETS,
    TABLE_ROW_SCOPE_TERMINATORS,
    TABLE_SCOPE_TERMINATORS,
)
from .tokens import (
    Attribute,
    CharacterTokens,
    CommentToken,
    DoctypeToken,
    EOFToken,
    ParseError,
    Tag,
    TokenSinkResult,
)


class TreeBuilderOpts:
    __slots__ = (
        "exact_errors",
        "scripting_enabled",
        "iframe_srcdoc",
        "drop_doctype",
    )

    def __init__(
        self,
        *,
        exact_errors=False,
        scripting_enabled=True,
        iframe_srcdoc=False,
        drop_doctype=False,
    ):
        self.exact_errors = bool(exact_errors)
        self.scripting_enabled = bool(scripting_enabled)
        self.iframe_srcdoc = bool(iframe_srcdoc)
        self.drop_doctype = bool(drop_doctype)


class InsertionMode(enum.IntEnum):
    INITIAL = 0
    BEFORE_HTML = 1
    BEFORE_HEAD = 2
    IN_HEAD = 3
    IN_HEAD_NOSCRIPT = 4
    AFTER_HEAD = 5
    TEXT = 6
    IN_BODY = 7
    AFTER_BODY = 8
    AFTER_AFTER_BODY = 9
    IN_TABLE = 10
    IN_TABLE_TEXT = 11
    IN_CAPTION = 12
    IN_COLUMN_GROUP = 13
    IN_TABLE_BODY = 14
    IN_ROW = 15
    IN_CELL = 16
    IN_FRAMESET = 17
    AFTER_FRAMESET = 18
    AFTER_AFTER_FRAMESET = 19
    IN_SELECT = 20
    IN_TEMPLATE = 21


def _is_all_whitespace(text):
    return all(ch in "\t\n\f\r " for ch in text)


def _doctype_error_and_quirks(doctype, iframe_srcdoc):
    name = doctype.name.lower() if doctype.name else None
    public_id = doctype.public_id
    system_id = doctype.system_id

    acceptable = (
        ("html", None, None),
        ("html", None, "about:legacy-compat"),
        ("html", "-//W3C//DTD HTML 4.0//EN", None),
        ("html", "-//W3C//DTD HTML 4.0//EN", "http://www.w3.org/TR/REC-html40/strict.dtd"),
        ("html", "-//W3C//DTD HTML 4.01//EN", None),
        ("html", "-//W3C//DTD HTML 4.01//EN", "http://www.w3.org/TR/html4/strict.dtd"),
        ("html", "-//W3C//DTD XHTML 1.0 Strict//EN", "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd"),
        ("html", "-//W3C//DTD XHTML 1.1//EN", "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd"),
    )

    key = (name, public_id, system_id)
    parse_error = key not in acceptable

    public_lower = public_id.lower() if public_id else None
    system_lower = system_id.lower() if system_id else None

    def _contains_prefix(haystack, needle):
        return any(needle.startswith(prefix) for prefix in haystack)

    if doctype.force_quirks:
        quirks_mode = "quirks"
    elif name != "html":
        quirks_mode = "quirks"
    elif iframe_srcdoc:
        quirks_mode = "no-quirks"
    elif public_lower in QUIRKY_PUBLIC_MATCHES:
        quirks_mode = "quirks"
    elif system_lower in QUIRKY_SYSTEM_MATCHES:
        quirks_mode = "quirks"
    elif public_lower and _contains_prefix(QUIRKY_PUBLIC_PREFIXES, public_lower):
        quirks_mode = "quirks"
    elif public_lower and _contains_prefix(LIMITED_QUIRKY_PUBLIC_PREFIXES, public_lower):
        quirks_mode = "limited-quirks"
    elif public_lower and _contains_prefix(HTML4_PUBLIC_PREFIXES, public_lower):
        quirks_mode = "quirks" if system_lower is None else "limited-quirks"
    else:
        quirks_mode = "no-quirks"

    return parse_error, quirks_mode


class SimpleDomNode:
    __slots__ = ("name", "attrs", "children", "parent", "data", "namespace", "template_content")

    def __init__(self, name, attrs=None, data=None, namespace=None):
        self.name = name
        self.attrs = list(attrs) if attrs else []
        self.children = []
        self.parent = None
        self.data = data
        if name in {"#text", "#comment", "!doctype", "#document", "#document-fragment"}:
            self.namespace = namespace
        else:
            self.namespace = namespace or "html"
        # Only HTML template elements have a document fragment for their content
        if name == "template" and self.namespace == "html":
            self.template_content = SimpleDomNode("#document-fragment")
        else:
            self.template_content = None

    def append_child(self, node):
        self.children.append(node)
        node.parent = self

    def insert_before(self, node, reference):
        if reference not in self.children:
            self.append_child(node)
            return
        index = self.children.index(reference)
        self.children.insert(index, node)
        node.parent = self

    def remove_child(self, node):
        if node in self.children:
            self.children.remove(node)
            node.parent = None

    def to_test_format(self, indent=0):
        if self.name in {"#document", "#document-fragment"}:
            parts = [child.to_test_format(0) for child in self.children]
            return "\n".join(part for part in parts if part)
        if self.name == "#text":
            text = self.data or ""
            return f'| {" " * indent}"{text}"'
        if self.name == "#comment":
            comment = self.data or ""
            return f"| {' ' * indent}<!-- {comment} -->"
        if self.name == "!doctype":
            return self._format_doctype()

        line = f"| {' ' * indent}<{self._qualified_name()}>"
        attribute_lines = self._format_attributes(indent)
        
        # Template elements output their content document fragment
        if self.name == "template" and self.template_content:
            content_line = f"| {' ' * (indent + 2)}content"
            content_child_lines = [child.to_test_format(indent + 4) for child in self.template_content.children]
            sections = [line]
            if attribute_lines:
                sections.extend(attribute_lines)
            sections.append(content_line)
            sections.extend(child for child in content_child_lines if child)
            return "\n".join(sections)
        
        child_lines = [child.to_test_format(indent + 2) for child in self.children]

        sections = [line]
        if attribute_lines:
            sections.extend(attribute_lines)
        sections.extend(child for child in child_lines if child)
        return "\n".join(sections)

    def _qualified_name(self):
        if self.namespace and self.namespace not in {"html", None}:
            return f"{self.namespace} {self.name}"
        return self.name

    def _format_attributes(self, indent):
        if not self.attrs:
            return []
        formatted = []
        padding = " " * (indent + 2)
        
        # Prepare display names for sorting
        display_attrs = []
        for attr in self.attrs:
            attr_name = attr.name
            # In foreign content (SVG/MathML), only adjusted attributes use space separator
            # Unknown attributes with colons (e.g., xml:foo) keep their colons
            if self.namespace and self.namespace not in {None, "html"}:
                lower_name = attr_name.lower()
                if lower_name in FOREIGN_ATTRIBUTE_ADJUSTMENTS:
                    attr_name = attr_name.replace(":", " ")
            display_attrs.append((attr_name, attr))
        
        # Sort by display name for canonical test output
        display_attrs.sort(key=lambda x: x[0])
        
        for attr_name, attr in display_attrs:
            value = attr.value or ""
            formatted.append(f'| {padding}{attr_name}="{value}"')
        return formatted

    def _format_doctype(self):
        doctype = self.data
        if not doctype:
            return "| <!DOCTYPE >"

        name = getattr(doctype, "name", None) or ""
        public_id = getattr(doctype, "public_id", None)
        system_id = getattr(doctype, "system_id", None)

        parts = ["| <!DOCTYPE"]
        if name:
            parts.append(f" {name}")
        else:
            parts.append(" ")

        if public_id is not None or system_id is not None:
            pub = public_id if public_id is not None else ""
            sys = system_id if system_id is not None else ""
            parts.append(f' "{pub}"')
            parts.append(f' "{sys}"')

        parts.append(">")
        return "".join(parts)


class TreeBuilder:
    __slots__ = (
        "opts",
        "document",
        "mode",
        "original_mode",
        "table_text_original_mode",
        "open_elements",
        "head_element",
        "form_element",
        "frameset_ok",
        "errors",
        "quirks_mode",
        "fragment_context",
        "fragment_context_element",
        "ignore_lf",
        "active_formatting",
        "insert_from_table",
        "pending_table_text",
        "template_modes",
        "tokenizer_state_override",
    )

    def __init__(self, fragment_context=None, opts=None):
        self.opts = opts or TreeBuilderOpts()
        self.fragment_context = fragment_context
        self.fragment_context_element = None
        if fragment_context is not None:
            self.document = SimpleDomNode("#document-fragment")
        else:
            self.document = SimpleDomNode("#document")
        self.mode = InsertionMode.INITIAL
        self.original_mode = None
        self.table_text_original_mode = None
        self.open_elements = []
        self.head_element = None
        self.form_element = None
        self.frameset_ok = True
        self.errors = []
        self.quirks_mode = "no-quirks"
        self.ignore_lf = False
        self.active_formatting = []
        self.insert_from_table = False
        self.pending_table_text = []
        self.template_modes = []
        self.tokenizer_state_override = None

        if fragment_context is not None:
            # Fragment parsing per HTML5 spec
            root = self._create_element("html", None, [])
            self.document.append_child(root)
            self.open_elements.append(root)
            # Set mode based on context element name
            namespace = fragment_context.namespace
            context_name = fragment_context.tag_name or ""
            name = context_name.lower()

            # Create a fake context element to establish foreign content context
            # Per spec: "Create an element for the token in the given namespace"
            if namespace and namespace not in {None, "html"}:
                adjusted_name = context_name
                if namespace == "svg":
                    adjusted_name = self._adjust_svg_tag_name(context_name)
                context_element = self._create_element(adjusted_name, namespace, [])
                root.append_child(context_element)
                self.open_elements.append(context_element)
                self.fragment_context_element = context_element

            # For html context, don't pre-create head/body - start in BEFORE_HEAD mode
            # This allows frameset and other elements to be inserted properly
            if name == "html":
                self.mode = InsertionMode.BEFORE_HEAD
            # Table modes only apply to HTML namespace fragments (namespace is None or "html")
            elif namespace in {None, "html"} and name in {"tbody", "thead", "tfoot"}:
                self.mode = InsertionMode.IN_TABLE_BODY
            elif namespace in {None, "html"} and name == "tr":
                self.mode = InsertionMode.IN_ROW
            elif namespace in {None, "html"} and name in {"td", "th"}:
                self.mode = InsertionMode.IN_CELL
            elif namespace in {None, "html"} and name == "caption":
                self.mode = InsertionMode.IN_CAPTION
            elif namespace in {None, "html"} and name == "colgroup":
                self.mode = InsertionMode.IN_COLUMN_GROUP
            elif namespace in {None, "html"} and name == "table":
                self.mode = InsertionMode.IN_TABLE
            else:
                self.mode = InsertionMode.IN_BODY
            # For fragments, frameset_ok starts as False per HTML5 spec
            # This prevents frameset from being inserted in fragment contexts
            self.frameset_ok = False

    def process_token(self, token):
        if isinstance(token, ParseError):
            if self.opts.exact_errors:
                self.errors.append(token.message)
            return TokenSinkResult.Continue

        if isinstance(token, DoctypeToken):
            return self._handle_doctype(token)

        reprocess = True
        current_token = token
        force_html_mode = False
        while reprocess:
            reprocess = False
            if force_html_mode:
                # Force processing in HTML mode, bypassing foreign content check
                force_html_mode = False
                result = self._dispatch(current_token)
            elif self._should_use_foreign_content(current_token):
                result = self._process_foreign_content(current_token)
            else:
                if self.open_elements:
                    current = self.open_elements[-1]
                    # Only pop foreign elements if we're NOT at an HTML/MathML integration point
                    # and NOT about to insert a new foreign element (svg/math)
                    if current.namespace not in {None, "html"} and not isinstance(current_token, EOFToken):
                        should_pop = True
                        # Don't pop at integration points - they stay on stack to receive content
                        if self._is_html_integration_point(current) or self._is_mathml_text_integration_point(current):
                            should_pop = False
                        # Don't pop when inserting new svg/math elements
                        if isinstance(current_token, Tag) and current_token.kind == Tag.START:
                            name_lower = self._lower_ascii(current_token.name)
                            if name_lower in {"svg", "math"}:
                                should_pop = False
                        if should_pop:
                            # Pop foreign elements above integration points, but not the integration point itself
                            while self.open_elements and self.open_elements[-1].namespace not in {None, "html"}:
                                node = self.open_elements[-1]
                                # Stop if we reach an integration point - don't pop it
                                if self._is_html_integration_point(node) or self._is_mathml_text_integration_point(node):
                                    break
                                self.open_elements.pop()
                            self._reset_insertion_mode()
                    # Special handling: text at integration points inserts directly, bypassing mode dispatch
                    if isinstance(current_token, CharacterTokens) and current.namespace not in {None, "html"}:
                        if self._is_mathml_text_integration_point(current):
                            data = current_token.data or ""
                            if data:
                                if "\x00" in data:
                                    self._parse_error("invalid-codepoint")
                                    data = data.replace("\x00", "")
                                if "\x0c" in data:
                                    self._parse_error("invalid-codepoint")
                                    data = data.replace("\x0c", "")
                                if not data:
                                    result = None
                                elif _is_all_whitespace(data):
                                    self._append_text(data)
                                    result = None
                                else:
                                    # Reconstruct active formatting elements for non-whitespace text
                                    self._reconstruct_active_formatting_elements()
                                    self.frameset_ok = False
                                    self._append_text(data)
                                    result = None
                            else:
                                result = None
                        else:
                            result = self._dispatch(current_token)
                    else:
                        # At integration points inside foreign content, check if table tags make sense.
                        # If we're in a table mode but NOT inside an actual HTML table element,
                        # use IN_BODY mode to ignore inappropriate table tags.
                        if (current.namespace not in {None, "html"} and
                            (self._is_mathml_text_integration_point(current) or self._is_html_integration_point(current)) and
                            isinstance(current_token, Tag) and current_token.kind == Tag.START and
                            self.mode not in {InsertionMode.IN_BODY}):
                            # Check if we're in a table mode but without an actual table in scope
                            # If so, table tags should be ignored (use IN_BODY mode)
                            is_table_mode = self.mode in {
                                InsertionMode.IN_TABLE, InsertionMode.IN_TABLE_BODY,
                                InsertionMode.IN_ROW, InsertionMode.IN_CELL,
                                InsertionMode.IN_CAPTION, InsertionMode.IN_COLUMN_GROUP
                            }
                            has_table_in_scope = self._has_in_table_scope("table")
                            if is_table_mode and not has_table_in_scope:
                                # Temporarily use IN_BODY mode for this tag
                                saved_mode = self.mode
                                self.mode = InsertionMode.IN_BODY
                                result = self._dispatch(current_token)
                                # Restore mode if no mode change was requested
                                if self.mode == InsertionMode.IN_BODY:
                                    self.mode = saved_mode
                            else:
                                result = self._dispatch(current_token)
                        else:
                            result = self._dispatch(current_token)
                else:
                    result = self._dispatch(current_token)
            if result is None:
                result_to_return = self.tokenizer_state_override or TokenSinkResult.Continue
                self.tokenizer_state_override = None
                return result_to_return
            # Result can be (instruction, mode, token) or (instruction, mode, token, force_html)
            if isinstance(result, tuple) and len(result) >= 3:
                instruction, mode, token_override = result[0], result[1], result[2]
                if len(result) == 4:
                    force_html_mode = result[3]
            else:
                instruction, mode, token_override = result
            if instruction == "reprocess":
                self.mode = mode
                current_token = token_override
                reprocess = True

        result = self.tokenizer_state_override or TokenSinkResult.Continue
        self.tokenizer_state_override = None
        return result

    def _handle_doctype(self, token):
        if self.mode != InsertionMode.INITIAL:
            self._parse_error("Unexpected DOCTYPE")
            return TokenSinkResult.Continue

        doctype = token.doctype
        parse_error, quirks_mode = _doctype_error_and_quirks(doctype, self.opts.iframe_srcdoc)

        if not self.opts.drop_doctype:
            node = SimpleDomNode("!doctype", data=doctype)
            self.document.append_child(node)

        if parse_error:
            self._parse_error("Unexpected DOCTYPE")

        self._set_quirks_mode(quirks_mode)
        self.mode = InsertionMode.BEFORE_HTML
        return TokenSinkResult.Continue

    def finish(self):
        if self.fragment_context is not None:
            # For fragments, remove the html wrapper and promote its children
            if self.document.children and self.document.children[0].name == "html":
                root = self.document.children[0]
                context_elem = self.fragment_context_element
                if (
                    context_elem is not None
                    and context_elem.parent is root
                ):
                    for child in list(context_elem.children):
                        context_elem.remove_child(child)
                        root.append_child(child)
                    root.remove_child(context_elem)
                self._reparent_children(root, self.document)
                self.document.remove_child(root)
        
        # Populate selectedcontent elements per HTML5 spec
        self._populate_selectedcontent(self.document)
        
        return self.document

    # Insertion mode dispatch ------------------------------------------------

    def _dispatch(self, token):
        if self.mode == InsertionMode.INITIAL:
            return self._mode_initial(token)
        if self.mode == InsertionMode.BEFORE_HTML:
            return self._mode_before_html(token)
        if self.mode == InsertionMode.BEFORE_HEAD:
            return self._mode_before_head(token)
        if self.mode == InsertionMode.IN_HEAD:
            return self._mode_in_head(token)
        if self.mode == InsertionMode.IN_HEAD_NOSCRIPT:
            return self._mode_in_head_noscript(token)
        if self.mode == InsertionMode.AFTER_HEAD:
            return self._mode_after_head(token)
        if self.mode == InsertionMode.TEXT:
            return self._mode_text(token)
        if self.mode == InsertionMode.IN_BODY:
            return self._mode_in_body(token)
        if self.mode == InsertionMode.IN_TABLE:
            return self._mode_in_table(token)
        if self.mode == InsertionMode.IN_TABLE_TEXT:
            return self._mode_in_table_text(token)
        if self.mode == InsertionMode.IN_CAPTION:
            return self._mode_in_caption(token)
        if self.mode == InsertionMode.IN_COLUMN_GROUP:
            return self._mode_in_column_group(token)
        if self.mode == InsertionMode.IN_TABLE_BODY:
            return self._mode_in_table_body(token)
        if self.mode == InsertionMode.IN_ROW:
            return self._mode_in_row(token)
        if self.mode == InsertionMode.IN_CELL:
            return self._mode_in_cell(token)
        if self.mode == InsertionMode.IN_SELECT:
            return self._mode_in_select(token)
        if self.mode == InsertionMode.IN_TEMPLATE:
            return self._mode_in_template(token)
        if self.mode == InsertionMode.AFTER_BODY:
            return self._mode_after_body(token)
        if self.mode == InsertionMode.AFTER_AFTER_BODY:
            return self._mode_after_after_body(token)
        if self.mode == InsertionMode.IN_FRAMESET:
            return self._mode_in_frameset(token)
        if self.mode == InsertionMode.AFTER_FRAMESET:
            return self._mode_after_frameset(token)
        if self.mode == InsertionMode.AFTER_AFTER_FRAMESET:
            return self._mode_after_after_frameset(token)
        return self._mode_in_body(token)

    def _mode_initial(self, token):
        if isinstance(token, CharacterTokens):
            if _is_all_whitespace(token.data):
                return None
            if not self.opts.iframe_srcdoc:
                self._set_quirks_mode("quirks")
            return ("reprocess", InsertionMode.BEFORE_HTML, token)
        if isinstance(token, CommentToken):
            self._append_comment_to_document(token.data)
            return None
        if isinstance(token, EOFToken):
            if not self.opts.iframe_srcdoc:
                self._set_quirks_mode("quirks")
            self.mode = InsertionMode.BEFORE_HTML
            return ("reprocess", InsertionMode.BEFORE_HTML, token)
        # Anything else (Tags, etc) - no DOCTYPE seen, so quirks mode
        if not self.opts.iframe_srcdoc:
            self._set_quirks_mode("quirks")
        return ("reprocess", InsertionMode.BEFORE_HTML, token)

    def _mode_before_html(self, token):
        if isinstance(token, CharacterTokens) and _is_all_whitespace(token.data):
            return None
        if isinstance(token, CommentToken):
            self._append_comment_to_document(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                self._create_root(token.attrs)
                self.mode = InsertionMode.BEFORE_HEAD
                return None
            if token.kind == Tag.END and token.name in {"head", "body", "html", "br"}:
                self._create_root([])
                self.mode = InsertionMode.BEFORE_HEAD
                return ("reprocess", InsertionMode.BEFORE_HEAD, token)
            if token.kind == Tag.END:
                # Ignore other end tags
                self._parse_error("Unexpected end tag in before html")
                return None
        if isinstance(token, EOFToken):
            self._create_root([])
            self.mode = InsertionMode.BEFORE_HEAD
            return ("reprocess", InsertionMode.BEFORE_HEAD, token)

        if isinstance(token, CharacterTokens):
            stripped = token.data.lstrip("\t\n\f\r ")
            if not stripped:
                return None
            if len(stripped) != len(token.data):
                token = CharacterTokens(stripped)

        self._create_root([])
        self.mode = InsertionMode.BEFORE_HEAD
        return ("reprocess", InsertionMode.BEFORE_HEAD, token)

    def _mode_before_head(self, token):
        if isinstance(token, CharacterTokens):
            data = token.data or ""
            if not data:
                return None
            if "\x00" in data:
                self._parse_error("invalid-codepoint-before-head")
                data = data.replace("\x00", "")
                if not data:
                    return None
            if _is_all_whitespace(data):
                return None
            token = CharacterTokens(data)
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                # Duplicate html tag - add attributes to existing html element
                if self.open_elements:
                    html = self.open_elements[0]
                    self._add_missing_attributes(html, token.attrs)
                return None
            if token.kind == Tag.START and token.name == "head":
                head = self._insert_element(token, push=True)
                self.head_element = head
                self.mode = InsertionMode.IN_HEAD
                return None
            if token.kind == Tag.END and token.name in {"head", "body", "html", "br"}:
                self.head_element = self._insert_phantom("head")
                self.mode = InsertionMode.IN_HEAD
                return ("reprocess", InsertionMode.IN_HEAD, token)
            if token.kind == Tag.END:
                # Ignore other end tags
                self._parse_error("Unexpected end tag in before head")
                return None
        if isinstance(token, EOFToken):
            self.head_element = self._insert_phantom("head")
            self.mode = InsertionMode.IN_HEAD
            return ("reprocess", InsertionMode.IN_HEAD, token)

        self.head_element = self._insert_phantom("head")
        self.mode = InsertionMode.IN_HEAD
        return ("reprocess", InsertionMode.IN_HEAD, token)

    def _mode_in_head(self, token):
        if isinstance(token, CharacterTokens):
            if _is_all_whitespace(token.data):
                self._append_text(token.data)
                return None
            data = token.data or ""
            i = 0
            while i < len(data) and data[i] in "\t\n\f\r ":
                i += 1
            leading_ws = data[:i]
            remaining = data[i:]
            if leading_ws:
                current = self.open_elements[-1] if self.open_elements else None
                if current is not None and current.children:
                    self._append_text(leading_ws)
            if not remaining:
                return None
            self._pop_current()
            self.mode = InsertionMode.AFTER_HEAD
            return ("reprocess", InsertionMode.AFTER_HEAD, CharacterTokens(remaining))
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                # Pop head and transition to AFTER_HEAD, then reprocess
                self._pop_current()
                self.mode = InsertionMode.AFTER_HEAD
                return ("reprocess", InsertionMode.AFTER_HEAD, token)
            if token.kind == Tag.START and token.name in {"base", "basefont", "bgsound", "link", "meta"}:
                self._insert_element(token, push=False)
                return None
            if token.kind == Tag.START and token.name == "template":
                self._insert_element(token, push=True)
                self._push_formatting_marker()
                self.frameset_ok = False
                self.mode = InsertionMode.IN_TEMPLATE
                self.template_modes.append(InsertionMode.IN_TEMPLATE)
                return None
            if token.kind == Tag.END and token.name == "template":
                # Check if template is on the stack (don't use scope check as table blocks it)
                has_template = any(node.name == "template" for node in self.open_elements)
                if not has_template:
                    return None
                self._generate_implied_end_tags()
                self._pop_until_inclusive("template")
                self._clear_active_formatting_up_to_marker()
                if self.template_modes:
                    self.template_modes.pop()
                self._reset_insertion_mode()
                return None
            if token.kind == Tag.START and token.name in {"title", "style", "script", "noscript", "noframes"}:
                if token.name == "noscript" and not self.opts.scripting_enabled:
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_HEAD_NOSCRIPT
                    return None
                self._insert_element(token, push=True)
                self.original_mode = self.mode
                self.mode = InsertionMode.TEXT
                return None
            if token.kind == Tag.END and token.name == "head":
                self._pop_current()
                self.mode = InsertionMode.AFTER_HEAD
                return None
            if token.kind == Tag.END and token.name in {"body", "html", "br"}:
                self._pop_current()
                self.mode = InsertionMode.AFTER_HEAD
                return ("reprocess", InsertionMode.AFTER_HEAD, token)
        if isinstance(token, EOFToken):
            self._pop_current()
            self.mode = InsertionMode.AFTER_HEAD
            return ("reprocess", InsertionMode.AFTER_HEAD, token)

        self._pop_current()
        self.mode = InsertionMode.AFTER_HEAD
        return ("reprocess", InsertionMode.AFTER_HEAD, token)

    def _mode_in_head_noscript(self, token):
        def anything_else():
            self._parse_error("Unexpected token in head noscript")
            self._pop_current()
            return ("reprocess", InsertionMode.IN_HEAD, token)

        if isinstance(token, CharacterTokens):
            if _is_all_whitespace(token.data):
                # Whitespace is processed using InHead rules
                # but we stay in InHeadNoscript mode
                self._mode_in_head(token)
                return None
            return anything_else()
        if isinstance(token, CommentToken):
            # Comment is processed using InHead rules
            # but we stay in InHeadNoscript mode
            self._mode_in_head(token)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.END and token.name == "noscript":
                self._pop_current()
                self.mode = InsertionMode.IN_HEAD
                return None
            if token.kind == Tag.START and token.name in {"basefont", "bgsound", "link", "meta", "noframes", "style"}:
                return ("reprocess", InsertionMode.IN_HEAD, token)
            if token.kind == Tag.START and token.name == "noscript":
                return anything_else()
            if token.kind == Tag.END and token.name in {"br", "head", "html"}:
                return anything_else()
            return anything_else()
        if isinstance(token, EOFToken):
            self._pop_current()
            return ("reprocess", InsertionMode.IN_HEAD, token)
        return anything_else()

    def _mode_after_head(self, token):
        if isinstance(token, CharacterTokens):
            data = token.data or ""
            if "\x00" in data:
                self._parse_error("invalid-codepoint-in-body")
                data = data.replace("\x00", "")
            if "\x0c" in data:
                self._parse_error("invalid-codepoint-in-body")
                data = data.replace("\x0c", "")
            if not data or _is_all_whitespace(data):
                if data:
                    self._append_text(data)
                return None
            self._insert_body_if_missing()
            return ("reprocess", InsertionMode.IN_BODY, CharacterTokens(data))
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                self._insert_body_if_missing()
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.START and token.name == "body":
                self._insert_element(token, push=True)
                self.mode = InsertionMode.IN_BODY
                self.frameset_ok = False
                return None
            if token.kind == Tag.START and token.name == "frameset":
                self._insert_element(token, push=True)
                self.mode = InsertionMode.IN_FRAMESET
                return None
            # Special handling: input type="hidden" doesn't create body or affect frameset_ok
            if token.kind == Tag.START and token.name == "input":
                input_type = None
                for attr in token.attrs:
                    if attr.name == "type":
                        input_type = (attr.value or "").lower()
                        break
                if input_type == "hidden":
                    # Parse error but ignore - don't create body, don't insert element
                    self._parse_error("unexpected-hidden-input-after-head")
                    return None
                # Non-hidden input creates body
                self._insert_body_if_missing()
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.START and token.name in {"base", "basefont", "bgsound", "link", "meta", "title", "style", "script", "noscript"}:
                if self.head_element is None:
                    self.head_element = self._insert_phantom("head")
                self.open_elements.append(self.head_element)
                result = self._mode_in_head(token)
                # Remove the head element from wherever it is in the stack
                # (it might not be at the end if we inserted other elements like <title>)
                if self.head_element in self.open_elements:
                    self.open_elements.remove(self.head_element)
                return result
            if token.kind == Tag.START and token.name == "template":
                # Template in after-head needs special handling:
                # Process in IN_HEAD mode, which will switch to IN_TEMPLATE
                # Don't remove head from stack - let normal processing continue
                if self.head_element is None:
                    self.head_element = self._insert_phantom("head")
                self.open_elements.append(self.head_element)
                self.mode = InsertionMode.IN_HEAD
                return ("reprocess", InsertionMode.IN_HEAD, token)
            if token.kind == Tag.END and token.name == "template":
                return self._mode_in_head(token)
            if token.kind == Tag.END and token.name == "body":
                self._insert_body_if_missing()
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.END and token.name in {"html", "br"}:
                self._insert_body_if_missing()
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.END:
                # Ignore other end tags
                self._parse_error("Unexpected end tag in after head")
                return None
        if isinstance(token, EOFToken):
            self._insert_body_if_missing()
            self.mode = InsertionMode.IN_BODY
            return ("reprocess", InsertionMode.IN_BODY, token)

        self._insert_body_if_missing()
        return ("reprocess", InsertionMode.IN_BODY, token)

    def _mode_text(self, token):
        if isinstance(token, CharacterTokens):
            self._append_text(token.data)
            return None
        if isinstance(token, EOFToken):
            self._pop_current()
            self.mode = self.original_mode or InsertionMode.IN_BODY
            return ("reprocess", self.mode, token)
        if isinstance(token, Tag) and token.kind == Tag.END:
            self._pop_current()
            self.mode = self.original_mode or InsertionMode.IN_BODY
            return None
        return None

    def _mode_in_body(self, token):
        if isinstance(token, CharacterTokens):
            data = token.data or ""
            if not data:
                return None
            if "\x00" in data:
                self._parse_error("invalid-codepoint")
                data = data.replace("\x00", "")
            if "\x0c" in data:
                self._parse_error("invalid-codepoint")
                data = data.replace("\x0c", "")
            if not data:
                return None
            if _is_all_whitespace(data):
                self._reconstruct_active_formatting_elements()
                self._append_text(data)
                return None
            self._reconstruct_active_formatting_elements()
            self.frameset_ok = False
            self._append_text(data)
            return None
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START:
                name = token.name
                if name == "html":
                    # In a template, html tags are parse errors and ignored
                    if self.template_modes:
                        self._parse_error("Unexpected <html> in template")
                        return None
                    if self.open_elements:
                        html = self.open_elements[0]
                        self._add_missing_attributes(html, token.attrs)
                    return None
                if name == "body":
                    # In a template, body tags are parse errors and ignored
                    if self.template_modes:
                        self._parse_error("Unexpected <body> in template")
                        return None
                    if len(self.open_elements) > 1:
                        self._parse_error("Unexpected <body> inside body")
                        # Merge attributes onto existing body element
                        body = self.open_elements[1] if len(self.open_elements) > 1 else None
                        if body and body.name == "body":
                            self._add_missing_attributes(body, token.attrs)
                        self.frameset_ok = False
                        return None
                    self.frameset_ok = False
                    return None
                if name == "head":
                    # Ignore <head> in body mode (duplicate head)
                    self._parse_error("Unexpected <head> in body")
                    return None
                # Non-template head-related tags: delegate to IN_HEAD
                if name in {"base", "basefont", "bgsound", "link", "meta", "noframes", 
                           "script", "style", "template", "title"}:
                    return self._mode_in_head(token)
                if name in BLOCK_WITH_P_START:
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    self._insert_element(token, push=True)
                    return None
                if name in HEADING_ELEMENTS:
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    if self.open_elements and self.open_elements[-1].name in HEADING_ELEMENTS:
                        self._parse_error("Nested heading")
                        self._pop_current()
                    self._insert_element(token, push=True)
                    self.frameset_ok = False
                    return None
                if name in {"pre", "listing"}:
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    self._insert_element(token, push=True)
                    self.ignore_lf = True
                    self.frameset_ok = False
                    return None
                if name == "form":
                    if self.form_element is not None:
                        self._parse_error("Nested form")
                        return None
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    node = self._insert_element(token, push=True)
                    self.form_element = node
                    self.frameset_ok = False
                    return None
                if name == "button":
                    # Check for nested button in default scope (not button_scope).
                    # Button is a terminator in button_scope, so we'd never find it.
                    # Per spec/html5ever: check if button exists in default scope,
                    # meaning "is there a button between here and html/table/etc?"
                    if self._has_in_scope("button"):
                        self._parse_error("Nested button")
                        self._close_element_by_name("button")
                    self._insert_element(token, push=True)
                    self.frameset_ok = False
                    return None
                if name == "p":
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    self._insert_element(token, push=True)
                    return None
                if name == "math":
                    self._reconstruct_active_formatting_elements()
                    attrs = self._prepare_foreign_attributes("math", token.attrs)
                    new_tag = Tag(Tag.START, token.name, attrs, token.self_closing)
                    # For foreign elements, honor the self-closing flag
                    self._insert_element(new_tag, push=not token.self_closing, namespace="math")
                    return None
                if name == "svg":
                    self._reconstruct_active_formatting_elements()
                    adjusted_name = self._adjust_svg_tag_name(token.name)
                    attrs = self._prepare_foreign_attributes("svg", token.attrs)
                    new_tag = Tag(Tag.START, adjusted_name, attrs, token.self_closing)
                    # For foreign elements, honor the self-closing flag
                    self._insert_element(new_tag, push=not token.self_closing, namespace="svg")
                    return None
                if name == "li":
                    self.frameset_ok = False
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    if self._has_in_list_item_scope("li"):
                        self._pop_until_any_inclusive({"li"})
                    self._insert_element(token, push=True)
                    return None
                if name in {"dd", "dt"}:
                    self.frameset_ok = False
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    if name == "dd":
                        if self._has_in_definition_scope("dd"):
                            self._pop_until_any_inclusive({"dd"})
                        if self._has_in_definition_scope("dt"):
                            self._pop_until_any_inclusive({"dt"})
                    else:
                        if self._has_in_definition_scope("dt"):
                            self._pop_until_any_inclusive({"dt"})
                        if self._has_in_definition_scope("dd"):
                            self._pop_until_any_inclusive({"dd"})
                    self._insert_element(token, push=True)
                    return None
                if name == "a":
                    if self._has_active_formatting_entry("a"):
                        self._adoption_agency("a")
                        self._remove_last_active_formatting_by_name("a")
                        self._remove_last_open_element_by_name("a")
                    self._reconstruct_active_formatting_elements()
                    node = self._insert_element(token, push=True)
                    self._append_active_formatting_entry(name, token.attrs, node)
                    return None
                is_formatting = name in FORMATTING_ELEMENTS
                # Note: font is formatting regardless of attributes per html5lib tests
                if is_formatting:
                    if name == "nobr" and self._in_scope("nobr"):
                        self._adoption_agency("nobr")
                        self._remove_last_active_formatting_by_name("nobr")
                        self._remove_last_open_element_by_name("nobr")
                    self._reconstruct_active_formatting_elements()
                    duplicate_index = self._find_active_formatting_duplicate(name, token.attrs)
                    if duplicate_index is not None:
                        self._remove_formatting_entry(duplicate_index)
                    node = self._insert_element(token, push=True)
                    self._append_active_formatting_entry(name, token.attrs, node)
                    return None
                if name in {"applet", "marquee", "object"}:
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=True)
                    self._push_formatting_marker()
                    self.frameset_ok = False
                    return None
                if name == "hr":
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    self._insert_element(token, push=False)
                    self.frameset_ok = False
                    return None
                if name == "br":
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    # Per html5ever rules.rs:758-774, br reconstructs formatting elements
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=False)
                    self.frameset_ok = False
                    return None
                # Special case: frameset in body mode with frameset_ok flag still true
                if name == "frameset":
                    if not self.frameset_ok:
                        self._parse_error("unexpected-start-tag-ignored")
                        return None
                    # Remove body from open_elements and the tree
                    # Find body element index
                    body_index = None
                    for i, elem in enumerate(self.open_elements):
                        if elem.name == "body":
                            body_index = i
                            break
                    if body_index is not None:
                        # Remove body and all descendants from open_elements
                        body_elem = self.open_elements[body_index]
                        if body_elem.parent:
                            body_elem.parent.remove_child(body_elem)
                        # Remove body and everything after it from the stack
                        self.open_elements = self.open_elements[:body_index]
                    # Insert frameset and switch mode
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_FRAMESET
                    return None
                # Elements that should be ignored in body mode (parse error) in full document parsing
                # In fragment parsing, these may be valid depending on context
                if name in {"colgroup", "head", "tbody", "td", "tfoot", "th", "thead", "tr"}:
                    self._parse_error(f"unexpected-start-tag-ignored")
                    return None
                if self.fragment_context is None and name in {"col", "frame"}:
                    self._parse_error(f"unexpected-start-tag-ignored")
                    return None
                # Metadata void elements (InHead mode elements) - NO formatting reconstruction
                # Per html5ever rules.rs:190, these just insert_and_pop without reconstruct.
                if name in {"base", "basefont", "bgsound", "link", "meta"}:
                    self._insert_element(token, push=False)
                    return None
                # Legacy element: <image> is treated as <img>
                if name == "image":
                    self._parse_error("image-start-tag")
                    # Create new token with img name but same attributes
                    img_token = Tag(Tag.START, "img", token.attrs, token.self_closing)
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(img_token, push=False)
                    self.frameset_ok = False
                    return None
                # Content void elements - reconstruct formatting per html5ever rules.rs:758-774
                # These DO reconstruct active formatting elements before insertion.
                if name in {"area", "br", "embed", "img", "keygen", "wbr"}:
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=False)
                    self.frameset_ok = False
                    return None
                # Other void elements (col, frame, param, source, track) - no reconstruct
                if name in {"col", "frame", "param", "source", "track"}:
                    self._insert_element(token, push=False)
                    return None
                if name == "input":
                    # Special handling: input type="hidden" does NOT set frameset_ok to false
                    input_type = None
                    for attr in token.attrs:
                        if attr.name == "type":
                            input_type = (attr.value or "").lower()
                            break
                    self._insert_element(token, push=False)
                    if input_type != "hidden":
                        self.frameset_ok = False
                    return None
                if name == "table":
                    # HTML5 spec: In standards mode (not quirks), close any open p element before table
                    if self.quirks_mode != "quirks" and self._has_in_button_scope("p"):
                        self._close_p_element()
                    self._insert_element(token, push=True)
                    self.frameset_ok = False
                    self.mode = InsertionMode.IN_TABLE
                    return None
                if name in {"plaintext", "xmp"}:
                    # These elements implicitly close p
                    if self._has_in_button_scope("p"):
                        self._close_p_element()
                    self._insert_element(token, push=True)
                    self.frameset_ok = False
                    # Signal tokenizer to switch to PLAINTEXT mode (plaintext consumes all remaining input)
                    if name == "plaintext":
                        self.tokenizer_state_override = TokenSinkResult.Plaintext
                    return None
                if name == "textarea":
                    self._insert_element(token, push=True)
                    self.ignore_lf = True
                    self.frameset_ok = False
                    return None
                if name == "select":
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=True)
                    self.frameset_ok = False
                    self._reset_insertion_mode()
                    return None
                if name == "option":
                    # Close any open option element, reconstruct formatting, then insert.
                    # Matches html5ever step() InBody optgroup/option handling.
                    if self.open_elements and self.open_elements[-1].name == "option":
                        self.open_elements.pop()
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=True)
                    return None
                if name == "optgroup":
                    # Close open option, close open optgroup, reconstruct, insert.
                    # Matches html5ever step() InBody optgroup/option handling.
                    if self.open_elements and self.open_elements[-1].name == "option":
                        self.open_elements.pop()
                    # Also close any open optgroup
                    if self.open_elements and self.open_elements[-1].name == "optgroup":
                        self.open_elements.pop()
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=True)
                    return None
                # Ruby elements auto-close previous ruby elements
                if name in {"rp", "rt"}:
                    # Generate implied end tags but exclude rtc (rp/rt can appear inside rtc)
                    self._generate_implied_end_tags(exclude="rtc")
                    self._insert_element(token, push=True)
                    return None
                if name in {"rb", "rtc"}:
                    # Close rb, rp, rt, or rtc elements before inserting rb/rtc
                    if self.open_elements and self.open_elements[-1].name in {"rb", "rp", "rt", "rtc"}:
                        self._generate_implied_end_tags()
                    self._insert_element(token, push=True)
                    return None
                # Table elements that appear outside table context are parse errors and ignored
                if name in {"caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr"}:
                    self._parse_error(f"Unexpected <{name}> in body")
                    return None
                # Any other start tag: reconstruct active formatting elements, then insert
                self._reconstruct_active_formatting_elements()
                # Per HTML5 spec: self-closing flag should be ignored for non-void HTML elements
                # Only void elements and foreign elements can be self-closing
                self._insert_element(token, push=True)
                if token.self_closing:
                    self._parse_error("non-void-html-element-start-tag-with-trailing-solidus")
                # Most elements set frameset_ok to false, except certain whitelisted ones
                # Per HTML5 spec, these DON'T set frameset_ok to false:
                # - Formatting elements, paragraph-like block elements, table structure elements
                # - Head metadata elements (already handled above)
                if name not in {"address", "article", "aside", "blockquote", "center", "details", 
                               "dialog", "dir", "div", "dl", "fieldset", "figcaption", "figure", 
                               "footer", "header", "hgroup", "main", "menu", "nav", "ol", "p", 
                               "section", "summary", "ul", "caption", "col", "colgroup", "hr",
                               "pre", "listing"}:
                    if name not in FORMATTING_ELEMENTS:
                        self.frameset_ok = False
                return None
            else:
                name = token.name
                
                # Special case: </br> end tag is treated as <br> start tag
                if name == "br":
                    self._parse_error("Unexpected </br>")
                    br_tag = Tag(Tag.START, "br", [], False)
                    return self._mode_in_body(br_tag)
                
                if name in FORMATTING_ELEMENTS:
                    self._adoption_agency(name)
                    return None
                if name == "body":
                    if self._in_scope("body"):
                        self.mode = InsertionMode.AFTER_BODY
                    return None
                if name == "html":
                    if self._in_scope("body"):
                        return ("reprocess", InsertionMode.AFTER_BODY, token)
                    return None
                if name == "p":
                    if not self._has_in_button_scope("p"):
                        self._parse_error("Unexpected </p>")
                        phantom = Tag(Tag.START, "p", [], False)
                        self._insert_element(phantom, push=True)
                    self._close_p_element()
                    return None
                if name == "li":
                    if not self._has_in_list_item_scope("li"):
                        self._parse_error("Unexpected </li>")
                        return None
                    self._pop_until_any_inclusive({"li"})
                    return None
                if name in {"dd", "dt"}:
                    if not self._has_in_definition_scope(name):
                        self._parse_error("Unexpected closing tag")
                        return None
                    self._pop_until_any_inclusive({"dd", "dt"})
                    return None
                if name == "form":
                    if self.form_element is None:
                        self._parse_error("Unexpected </form>")
                        return None
                    removed = self._remove_from_open_elements(self.form_element)
                    self.form_element = None
                    if not removed:
                        self._parse_error("Form element not in stack")
                    return None
                if name in {"applet", "marquee", "object"}:
                    if not self._in_scope(name):
                        self._parse_error("Unexpected closing tag")
                        return None
                    while self.open_elements:
                        popped = self.open_elements.pop()
                        if popped.name == name:
                            break
                    self._clear_active_formatting_up_to_marker()
                    return None
                # Heading end tags: h1, h2, h3, h4, h5, h6
                if name in HEADING_ELEMENTS:
                    # If no heading element in scope, parse error and ignore
                    if not self._has_any_in_scope(HEADING_ELEMENTS):
                        self._parse_error(f"Unexpected </{name}>")
                        return None
                    # Generate implied end tags
                    self._generate_implied_end_tags()
                    # If current node is not this heading type, parse error
                    if self.open_elements and self.open_elements[-1].name != name:
                        self._parse_error(f"Mismatched heading end tag </{name}>")
                    # Pop until we pop a heading element (any heading, not necessarily matching)
                    while self.open_elements:
                        popped = self.open_elements.pop()
                        if popped.name in HEADING_ELEMENTS:
                            break
                    return None
                # Block-level end tags (address, article, aside, blockquote, etc.)
                if name in {
                    "address", "article", "aside", "blockquote", "button", "center",
                    "details", "dialog", "dir", "div", "dl", "fieldset", "figcaption",
                    "figure", "footer", "header", "hgroup", "listing", "main", "menu",
                    "nav", "ol", "pre", "search", "section", "summary", "table", "ul"
                }:
                    if not self._in_scope(name):
                        self._parse_error(f"No matching <{name}> tag")
                        return None
                    # Generate implied end tags (cursory)
                    self._generate_implied_end_tags()
                    if self.open_elements and self.open_elements[-1].name != name:
                        self._parse_error(f"Unexpected open element while closing {name}")
                    # Pop until we find and pop the target element
                    self._pop_until_any_inclusive({name})
                    return None
                # Template end tag: handle inline (don't delegate to avoid mode corruption)
                if name == "template":
                    # Check if template is on the stack (don't use scope check as table blocks it)
                    has_template = any(node.name == "template" for node in self.open_elements)
                    if not has_template:
                        return None
                    self._generate_implied_end_tags()
                    self._pop_until_inclusive("template")
                    self._clear_active_formatting_up_to_marker()
                    if self.template_modes:
                        self.template_modes.pop()
                    # Reset insertion mode to determine correct mode after template
                    self._reset_insertion_mode()
                    return None
                # Any other end tag
                self._any_other_end_tag(token.name)
                return None
        if isinstance(token, EOFToken):
            # If we're in a template, handle EOF in template mode first
            if self.template_modes:
                return self._mode_in_template(token)
            self.mode = InsertionMode.AFTER_BODY
            return ("reprocess", InsertionMode.AFTER_BODY, token)
        return None

    def _mode_in_table(self, token):
        if isinstance(token, CharacterTokens):
            data = token.data or ""
            if not data:
                return None
            if "\x00" in data:
                self._parse_error("Unexpected null character")
                data = data.replace("\x00", "")
                if not data:
                    return None
                token = CharacterTokens(data)
            self.pending_table_text = []
            self.table_text_original_mode = self.mode
            self.mode = InsertionMode.IN_TABLE_TEXT
            return ("reprocess", InsertionMode.IN_TABLE_TEXT, token)
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            name = token.name
            if token.kind == Tag.START:
                if name == "caption":
                    if self._has_in_table_scope("caption"):
                        self._parse_error("unexpected-start-tag-implies-end-tag")
                        if self._close_caption_element():
                            return ("reprocess", InsertionMode.IN_TABLE, token)
                        return None
                    self._clear_stack_to_table_context()
                    self._push_formatting_marker()
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_CAPTION
                    return None
                if name == "colgroup":
                    self._clear_stack_to_table_context()
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_COLUMN_GROUP
                    return None
                if name == "col":
                    self._clear_stack_to_table_context()
                    implied = Tag(Tag.START, "colgroup", [], False)
                    self._insert_element(implied, push=True)
                    self.mode = InsertionMode.IN_COLUMN_GROUP
                    return ("reprocess", InsertionMode.IN_COLUMN_GROUP, token)
                if name in {"tbody", "tfoot", "thead"}:
                    self._clear_stack_to_table_context()
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_TABLE_BODY
                    return None
                if name in {"td", "th", "tr"}:
                    self._clear_stack_to_table_context()
                    implied = Tag(Tag.START, "tbody", [], False)
                    self._insert_element(implied, push=True)
                    self.mode = InsertionMode.IN_TABLE_BODY
                    return ("reprocess", InsertionMode.IN_TABLE_BODY, token)
                if name == "table":
                    self._parse_error("unexpected-start-tag-implies-end-tag")
                    closed = self._close_table_element()
                    if closed:
                        return ("reprocess", self.mode, token)
                    return None
                if name in {"style", "script"}:
                    # Per HTML5 spec: style and script are inserted directly into the table
                    # (not processed as in-head which would move them)
                    self._insert_element(token, push=True)
                    self.original_mode = self.mode
                    self.mode = InsertionMode.TEXT
                    return None
                if name == "template":
                    # Template is handled by delegating to IN_HEAD
                    return self._mode_in_head(token)
                if name == "input":
                    input_type = None
                    for attr in token.attrs:
                        if attr.name == "type":
                            input_type = (attr.value or "").lower()
                            break
                    if input_type == "hidden":
                        self._parse_error("unexpected-hidden-input-in-table")
                        node = self._insert_element(token, push=True)
                        if self.open_elements and self.open_elements[-1] is node:
                            self.open_elements.pop()
                        return None
                if name == "form":
                    self._parse_error("unexpected-form-in-table")
                    if self.form_element is None:
                        node = self._insert_element(token, push=True)
                        self.form_element = node
                        if self.open_elements and self.open_elements[-1] is node:
                            self.open_elements.pop()
                    return None
                self._parse_error("unexpected-start-tag-implies-table-voodoo")
                previous = self.insert_from_table
                self.insert_from_table = True
                try:
                    return self._mode_in_body(token)
                finally:
                    self.insert_from_table = previous
            else:
                if name == "table":
                    self._close_table_element()
                    return None
                if name in {"body", "caption", "col", "colgroup", "html", "tbody", "td", "tfoot", "th", "thead", "tr"}:
                    self._parse_error("unexpected-end-tag")
                    return None
                self._parse_error("unexpected-end-tag-implies-table-voodoo")
                previous = self.insert_from_table
                self.insert_from_table = True
                try:
                    return self._mode_in_body(token)
                finally:
                    self.insert_from_table = previous
        if isinstance(token, EOFToken):
            # If we're in a template, handle EOF in template mode first
            if self.template_modes:
                return self._mode_in_template(token)
            if self._has_in_table_scope("table"):
                self._parse_error("eof-in-table")
            return None
        return None

    def _mode_in_table_text(self, token):
        if isinstance(token, CharacterTokens):
            data = token.data or ""
            if not data:
                return None
            if "\x00" in data:
                self._parse_error("invalid-codepoint")
                data = data.replace("\x00", "")
            if "\x0c" in data:
                self._parse_error("invalid-codepoint-in-table-text")
                data = data.replace("\x0c", "")
            if data:
                self.pending_table_text.append(data)
            return None
        self._flush_pending_table_text()
        original = self.table_text_original_mode or InsertionMode.IN_TABLE
        self.table_text_original_mode = None
        self.mode = original
        return ("reprocess", original, token)

    def _mode_in_caption(self, token):
        if isinstance(token, CharacterTokens):
            return self._mode_in_body(token)
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            name = token.name
            if token.kind == Tag.START:
                if name in {"caption", "col", "colgroup", "tbody", "tfoot", "thead", "tr", "td", "th"}:
                    self._parse_error("unexpected-start-tag-implies-end-tag")
                    if self._close_caption_element():
                        return ("reprocess", InsertionMode.IN_TABLE, token)
                    # In fragment parsing with caption context, ignore table structure elements (but not table itself)
                    if self.fragment_context and self.fragment_context.tag_name.lower() == "caption":
                        return None
                    # In fragment parsing, if there's no caption to close, process in IN_BODY mode
                    return self._mode_in_body(token)
                if name == "table":
                    self._parse_error("unexpected-start-tag-implies-end-tag")
                    if self._close_caption_element():
                        return ("reprocess", InsertionMode.IN_TABLE, token)
                    # In fragment parsing, if there's no caption to close, process in IN_BODY mode
                    return self._mode_in_body(token)
                return self._mode_in_body(token)
            else:
                if name == "caption":
                    if not self._close_caption_element():
                        return None
                    return None
                if name == "table":
                    if self._close_caption_element():
                        return ("reprocess", InsertionMode.IN_TABLE, token)
                    return None
                if name in {"tbody", "tfoot", "thead"}:
                    if self._has_in_table_scope(name):
                        if self._close_caption_element():
                            return ("reprocess", InsertionMode.IN_TABLE, token)
                    else:
                        self._parse_error("unexpected-end-tag")
                    return None
                return self._mode_in_body(token)
        if isinstance(token, EOFToken):
            return self._mode_in_body(token)
        return None

    def _close_caption_element(self):
        if not self._has_in_table_scope("caption"):
            self._parse_error("unexpected-end-tag")
            return False
        self._generate_implied_end_tags()
        while self.open_elements:
            node = self.open_elements.pop()
            if node.name == "caption":
                break
        self._clear_active_formatting_up_to_marker()
        self.mode = InsertionMode.IN_TABLE
        return True

    def _mode_in_column_group(self, token):
        current = self.open_elements[-1] if self.open_elements else None
        if isinstance(token, CharacterTokens):
            data = token.data or ""
            # Find first non-whitespace character
            stripped = data.lstrip(" \t\n\r\f")
            
            if len(stripped) < len(data):
                # Has leading whitespace - insert it
                ws = data[:len(data) - len(stripped)]
                self._append_text(ws)
            
            if not stripped:
                return None
            
            # Continue processing non-whitespace with a new token
            non_ws_token = CharacterTokens(stripped)
            if current and current.name == "html":
                # In fragment parsing with colgroup context, drop non-whitespace characters
                if self.fragment_context and self.fragment_context.tag_name.lower() == "colgroup":
                    self._parse_error("unexpected-characters-in-column-group")
                    return None
                return ("reprocess", InsertionMode.IN_TABLE, non_ws_token)
            # In a template, non-whitespace characters are parse errors - ignore them
            if current and current.name == "template":
                self._parse_error("unexpected-characters-in-template-column-group")
                return None
            self._parse_error("unexpected-characters-in-column-group")
            self._pop_current()
            self.mode = InsertionMode.IN_TABLE
            return ("reprocess", InsertionMode.IN_TABLE, non_ws_token)
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            name = token.name
            if token.kind == Tag.START:
                if name == "html":
                    return self._mode_in_body(token)
                if name == "col":
                    node = self._insert_element(token, push=True)
                    if self.open_elements and self.open_elements[-1] is node:
                        self.open_elements.pop()
                    return None
                if name == "template":
                    # Template is handled by delegating to IN_HEAD
                    return self._mode_in_head(token)
                if name == "colgroup":
                    self._parse_error("unexpected-start-tag-implies-end-tag")
                    # Don't pop template element - only pop actual colgroup
                    if current and current.name == "colgroup":
                        self._pop_current()
                        self.mode = InsertionMode.IN_TABLE
                        return ("reprocess", InsertionMode.IN_TABLE, token)
                    elif current and current.name == "template":
                        # In template, reject duplicate colgroup
                        return None
                    elif current and current.name != "html":
                        self._pop_current()
                        self.mode = InsertionMode.IN_TABLE
                        return ("reprocess", InsertionMode.IN_TABLE, token)
                    return None
                # Anything else: if we're in a colgroup, pop it and switch to IN_TABLE
                # But if we're in a template, just ignore non-column content
                if current and current.name == "colgroup":
                    self._pop_current()
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                elif current and current.name == "template":
                    # In template column group context, non-column content is ignored
                    self._parse_error("unexpected-start-tag-in-template-column-group")
                    return None
                elif current and current.name != "html":
                    self._pop_current()
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                return ("reprocess", InsertionMode.IN_TABLE, token)
            else:
                if name == "colgroup":
                    if current and current.name == "colgroup":
                        self._pop_current()
                        self.mode = InsertionMode.IN_TABLE
                    else:
                        self._parse_error("unexpected-end-tag")
                    return None
                if name == "col":
                    self._parse_error("unexpected-end-tag")
                    return None
                if name == "template":
                    # Template end tag needs proper handling
                    return self._mode_in_head(token)
                if current and current.name != "html":
                    self._pop_current()
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                return ("reprocess", InsertionMode.IN_TABLE, token)
        if isinstance(token, EOFToken):
            if current and current.name == "colgroup":
                self._pop_current()
                self.mode = InsertionMode.IN_TABLE
                return ("reprocess", InsertionMode.IN_TABLE, token)
            elif current and current.name == "template":
                # In template, delegate EOF handling to IN_TEMPLATE
                return self._mode_in_template(token)
            return None
        return None

    def _mode_in_table_body(self, token):
        if isinstance(token, CharacterTokens) or isinstance(token, CommentToken):
            return self._mode_in_table(token)
        if isinstance(token, Tag):
            name = token.name
            if token.kind == Tag.START:
                if name == "tr":
                    self._clear_stack_to_table_body_context()
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_ROW
                    return None
                if name in {"td", "th"}:
                    self._parse_error("unexpected-cell-in-table-body")
                    self._clear_stack_to_table_body_context()
                    implied = Tag(Tag.START, "tr", [], False)
                    self._insert_element(implied, push=True)
                    self.mode = InsertionMode.IN_ROW
                    return ("reprocess", InsertionMode.IN_ROW, token)
                if name in {"caption", "col", "colgroup", "tbody", "tfoot", "thead", "table"}:
                    current = self.open_elements[-1] if self.open_elements else None
                    if current and current.name in {"tbody", "tfoot", "thead"}:
                        self.open_elements.pop()
                    # When in a template, these tags create invalid structure - treat as "anything else"
                    elif current and current.name == "template":
                        self._parse_error("unexpected-start-tag-in-template-table-context")
                        return None
                    # In fragment parsing with tbody/tfoot/thead context and no tbody on stack, ignore these tags
                    elif (self.fragment_context and current and current.name == "html" and
                          self.fragment_context.tag_name.lower() in {"tbody", "tfoot", "thead"}):
                        self._parse_error("unexpected-start-tag")
                        return None
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                return self._mode_in_table(token)
            else:
                if name in {"tbody", "tfoot", "thead"}:
                    if not self._has_in_table_scope(name):
                        self._parse_error("unexpected-end-tag")
                        return None
                    self._clear_stack_to_table_body_context()
                    self._pop_current()
                    self.mode = InsertionMode.IN_TABLE
                    return None
                if name == "table":
                    current = self.open_elements[-1] if self.open_elements else None
                    # In a template, reject </table> as there's no table element
                    if current and current.name == "template":
                        self._parse_error("unexpected-end-tag")
                        return None
                    # In fragment parsing with tbody/tfoot/thead context and no tbody on stack, ignore </table>
                    if (self.fragment_context and current and current.name == "html" and
                        self.fragment_context.tag_name.lower() in {"tbody", "tfoot", "thead"}):
                        self._parse_error("unexpected-end-tag")
                        return None
                    if current and current.name in {"tbody", "tfoot", "thead"}:
                        self.open_elements.pop()
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                if name in {"caption", "col", "colgroup", "td", "th", "tr"}:
                    self._parse_error("unexpected-end-tag")
                    return None
                return self._mode_in_table(token)
        if isinstance(token, EOFToken):
            return self._mode_in_table(token)
        return None

    def _mode_in_row(self, token):
        if isinstance(token, CharacterTokens) or isinstance(token, CommentToken):
            return self._mode_in_table(token)
        if isinstance(token, Tag):
            name = token.name
            if token.kind == Tag.START:
                if name in {"td", "th"}:
                    self._clear_stack_to_table_row_context()
                    self._insert_element(token, push=True)
                    self._push_formatting_marker()
                    self.mode = InsertionMode.IN_CELL
                    return None
                if name in {"caption", "col", "colgroup", "tbody", "tfoot", "thead", "tr", "table"}:
                    if not self._has_in_table_scope("tr"):
                        self._parse_error("unexpected-start-tag-implies-end-tag")
                        return None
                    self._end_tr_element()
                    return ("reprocess", self.mode, token)
                previous = self.insert_from_table
                self.insert_from_table = True
                try:
                    return self._mode_in_body(token)
                finally:
                    self.insert_from_table = previous
            else:
                if name == "tr":
                    if not self._has_in_table_scope("tr"):
                        self._parse_error("unexpected-end-tag")
                        return None
                    self._end_tr_element()
                    return None
                if name in {"table", "tbody", "tfoot", "thead"}:
                    if self._has_in_table_scope(name):
                        self._end_tr_element()
                        return ("reprocess", self.mode, token)
                    self._parse_error("unexpected-end-tag")
                    return None
                if name in {"caption", "col", "colgroup", "td", "th"}:
                    self._parse_error("unexpected-end-tag")
                    return None
                previous = self.insert_from_table
                self.insert_from_table = True
                try:
                    return self._mode_in_body(token)
                finally:
                    self.insert_from_table = previous
        if isinstance(token, EOFToken):
            return self._mode_in_table(token)
        return None

    def _end_tr_element(self):
        self._clear_stack_to_table_row_context()
        if self.open_elements and self.open_elements[-1].name == "tr":
            self.open_elements.pop()
        # When in a template, restore template mode; otherwise use IN_TABLE_BODY
        if self.template_modes:
            self.mode = self.template_modes[-1]
        else:
            self.mode = InsertionMode.IN_TABLE_BODY

    def _mode_in_cell(self, token):
        if isinstance(token, CharacterTokens):
            previous = self.insert_from_table
            self.insert_from_table = False
            try:
                return self._mode_in_body(token)
            finally:
                self.insert_from_table = previous
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            name = token.name
            if token.kind == Tag.START:
                if name in {"caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr"}:
                    if self._close_table_cell():
                        return ("reprocess", self.mode, token)
                    # If no cell to close, we're not actually in a table - delegate to IN_BODY
                    return self._mode_in_body(token)
                previous = self.insert_from_table
                self.insert_from_table = False
                try:
                    return self._mode_in_body(token)
                finally:
                    self.insert_from_table = previous
            else:
                if name in {"td", "th"}:
                    if not self._has_in_table_scope(name):
                        self._parse_error("unexpected-end-tag")
                        return None
                    self._end_table_cell(name)
                    return None
                if name in {"table", "tbody", "tfoot", "thead", "tr"}:
                    # Per HTML5 spec: only close cell if the element is actually in scope
                    # Otherwise it's a parse error and we ignore the token
                    if not self._has_in_table_scope(name):
                        self._parse_error("unexpected-end-tag")
                        return None
                    if self._close_table_cell():
                        return ("reprocess", self.mode, token)
                    self._parse_error("unexpected-end-tag")
                    return None
                previous = self.insert_from_table
                self.insert_from_table = False
                try:
                    return self._mode_in_body(token)
                finally:
                    self.insert_from_table = previous
        if isinstance(token, EOFToken):
            if self._close_table_cell():
                return ("reprocess", self.mode, token)
            return self._mode_in_table(token)
        return None

    def _mode_in_select(self, token):
        if isinstance(token, CharacterTokens):
            data = token.data or ""
            if "\x00" in data:
                self._parse_error("invalid-codepoint-in-select")
                data = data.replace("\x00", "")
            if "\x0c" in data:
                self._parse_error("invalid-codepoint-in-select")
                data = data.replace("\x0c", "")
            if data:
                self._reconstruct_active_formatting_elements()
                self._append_text(data)
            return None
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            name = token.name
            if token.kind == Tag.START:
                if name == "html":
                    return ("reprocess", InsertionMode.IN_BODY, token)
                if name == "option":
                    # Close any open selectedcontent element (spec behavior for selectedcontent)
                    if self.open_elements and self.open_elements[-1].name == "selectedcontent":
                        self.open_elements.pop()
                    if self.open_elements and self.open_elements[-1].name == "option":
                        self.open_elements.pop()
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=True)
                    return None
                if name == "optgroup":
                    # Close any open selectedcontent element (spec behavior for selectedcontent)
                    if self.open_elements and self.open_elements[-1].name == "selectedcontent":
                        self.open_elements.pop()
                    if self.open_elements and self.open_elements[-1].name == "option":
                        self.open_elements.pop()
                    if self.open_elements and self.open_elements[-1].name == "optgroup":
                        self.open_elements.pop()
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=True)
                    return None
                if name == "select":
                    self._parse_error("Nested select")
                    if self._in_scope("select"):
                        self._pop_until_any_inclusive({"select"})
                        self._reset_insertion_mode()
                    return None
                if name in {"input", "textarea"}:
                    self._parse_error(f"Unexpected <{name}> in select")
                    if self._in_scope("select"):
                        self._pop_until_any_inclusive({"select"})
                        self._reset_insertion_mode()
                        return ("reprocess", self.mode, token)
                    return None
                if name == "keygen":
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=False)
                    return None
                if name in {"caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr", "table"}:
                    self._parse_error(f"Unexpected <{name}> in select")
                    if self._in_scope("select"):
                        self._pop_until_any_inclusive({"select"})
                        self._reset_insertion_mode()
                        return ("reprocess", self.mode, token)
                    return None
                if name in {"script", "template"}:
                    return self._mode_in_head(token)
                if name in {"svg", "math"}:
                    # For foreign elements, honor the self-closing flag
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=not token.self_closing, namespace=name)
                    return None
                if name == "a":
                    if self._has_active_formatting_entry("a"):
                        self._adoption_agency("a")
                        self._remove_last_active_formatting_by_name("a")
                        self._remove_last_open_element_by_name("a")
                    self._reconstruct_active_formatting_elements()
                    node = self._insert_element(token, push=True)
                    self._append_active_formatting_entry(name, token.attrs, node)
                    return None
                if name in FORMATTING_ELEMENTS:
                    if name == "nobr" and self._in_scope("nobr"):
                        self._adoption_agency("nobr")
                        self._remove_last_active_formatting_by_name("nobr")
                        self._remove_last_open_element_by_name("nobr")
                    self._reconstruct_active_formatting_elements()
                    duplicate_index = self._find_active_formatting_duplicate(name, token.attrs)
                    if duplicate_index is not None:
                        self._remove_formatting_entry(duplicate_index)
                    node = self._insert_element(token, push=True)
                    self._append_active_formatting_entry(name, token.attrs, node)
                    return None
                if name == "hr":
                    # Per spec: pop option and optgroup before inserting hr (makes hr sibling, not child)
                    if self.open_elements and self.open_elements[-1].name == "option":
                        self.open_elements.pop()
                    if self.open_elements and self.open_elements[-1].name == "optgroup":
                        self.open_elements.pop()
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=False)
                    return None
                if name == "menuitem":
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=True)
                    return None
                # Allow common HTML elements in select (newer spec)
                if name in {"p", "div", "span", "button", "datalist", "selectedcontent"}:
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=not token.self_closing)
                    return None
                if name in {"br", "img"}:
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=False)
                    return None
                if name == "plaintext":
                    # Per spec: plaintext element is inserted in select (consumes all remaining text)
                    self._reconstruct_active_formatting_elements()
                    self._insert_element(token, push=True)
                    return None
                self._parse_error(f"Unexpected <{name}> in select - ignored")
                return None
            else:
                if name == "optgroup":
                    if self.open_elements and self.open_elements[-1].name == "option":
                        self.open_elements.pop()
                    if self.open_elements and self.open_elements[-1].name == "optgroup":
                        self.open_elements.pop()
                    else:
                        self._parse_error("Unexpected </optgroup>")
                    return None
                if name == "option":
                    if self.open_elements and self.open_elements[-1].name == "option":
                        self.open_elements.pop()
                    else:
                        self._parse_error("Unexpected </option>")
                    return None
                if name == "select":
                    if not self._in_scope("select"):
                        self._parse_error("Unexpected </select>")
                        return None
                    self._pop_until_any_inclusive({"select"})
                    self._reset_insertion_mode()
                    return None
                # Handle end tags for allowed HTML elements in select
                if name == "a" or name in FORMATTING_ELEMENTS:
                    select_node = self._find_last_on_stack("select")
                    if select_node is not None:
                        fmt_index = self._find_active_formatting_index(name)
                        if fmt_index is not None:
                            target = self.active_formatting[fmt_index]["node"]
                            if target in self.open_elements:
                                select_index = self.open_elements.index(select_node)
                                target_index = self.open_elements.index(target)
                                if target_index < select_index:
                                    self._parse_error(f"Unexpected </{name}> in select")
                                    return None
                    self._adoption_agency(name)
                    return None
                if name in {"p", "div", "span", "button", "datalist", "selectedcontent"}:
                    # Pop elements until we find the matching element (or give up)
                    found = False
                    for node in reversed(self.open_elements):
                        if node.name == name:
                            found = True
                            break
                    if found:
                        # Pop elements until we've popped the target
                        while self.open_elements:
                            popped = self.open_elements.pop()
                            if popped.name == name:
                                break
                    else:
                        self._parse_error(f"Unexpected </{name}>")
                    return None
                if name == "template":
                    return self._mode_in_head(token)
                if name in {"caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr", "table"}:
                    self._parse_error(f"Unexpected </{name}> in select")
                    if self._in_scope("select"):
                        self._pop_until_any_inclusive({"select"})
                        self._reset_insertion_mode()
                        return ("reprocess", self.mode, token)
                    return None
                return None
        if isinstance(token, EOFToken):
            return self._mode_in_body(token)
        return None

    def _mode_in_template(self, token):
        # § The "in template" insertion mode
        # https://html.spec.whatwg.org/multipage/parsing.html#parsing-main-intemplate
        if isinstance(token, CharacterTokens):
            return self._mode_in_body(token)
        if isinstance(token, CommentToken):
            return self._mode_in_body(token)
        if isinstance(token, Tag):
            if token.kind == Tag.START:
                # Table-related tags switch template mode
                if token.name in {"caption", "colgroup", "tbody", "tfoot", "thead"}:
                    self.template_modes.pop()
                    self.template_modes.append(InsertionMode.IN_TABLE)
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                if token.name == "col":
                    self.template_modes.pop()
                    self.template_modes.append(InsertionMode.IN_COLUMN_GROUP)
                    self.mode = InsertionMode.IN_COLUMN_GROUP
                    return ("reprocess", InsertionMode.IN_COLUMN_GROUP, token)
                if token.name == "tr":
                    self.template_modes.pop()
                    self.template_modes.append(InsertionMode.IN_TABLE_BODY)
                    self.mode = InsertionMode.IN_TABLE_BODY
                    return ("reprocess", InsertionMode.IN_TABLE_BODY, token)
                if token.name in {"td", "th"}:
                    self.template_modes.pop()
                    self.template_modes.append(InsertionMode.IN_ROW)
                    self.mode = InsertionMode.IN_ROW
                    return ("reprocess", InsertionMode.IN_ROW, token)
                # Default: pop template mode and push IN_BODY
                if token.name not in {"base", "basefont", "bgsound", "link", "meta", "noframes", 
                                      "script", "style", "template", "title"}:
                    self.template_modes.pop()
                    self.template_modes.append(InsertionMode.IN_BODY)
                    self.mode = InsertionMode.IN_BODY
                    return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.END and token.name == "template":
                return self._mode_in_head(token)
            # Head-related tags process in InHead
            if token.name in {"base", "basefont", "bgsound", "link", "meta", "noframes", 
                             "script", "style", "template", "title"}:
                return self._mode_in_head(token)
        if isinstance(token, EOFToken):
            # Check if template is on the stack (don't use _in_scope as table blocks it)
            has_template = any(node.name == "template" for node in self.open_elements)
            if not has_template:
                return None
            # Pop until template, then handle EOF in reset mode
            self._pop_until_inclusive("template")
            self._clear_active_formatting_up_to_marker()
            if self.template_modes:
                self.template_modes.pop()
            self._reset_insertion_mode()
            return ("reprocess", self.mode, token)
        return None

    def _mode_after_body(self, token):
        if isinstance(token, CharacterTokens):
            if _is_all_whitespace(token.data):
                # Whitespace is processed using InBody rules (appended to body)
                # but we stay in AfterBody mode
                self._mode_in_body(token)
                return None
            return ("reprocess", InsertionMode.IN_BODY, token)
        if isinstance(token, CommentToken):
            # Append comment to the html element (root of open_elements stack)
            for node in self.open_elements:
                if node.name == "html":
                    comment = SimpleDomNode("#comment", data=token.data)
                    node.append_child(comment)
                    return None
            self._append_comment_to_document(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.END and token.name == "html":
                self.mode = InsertionMode.AFTER_AFTER_BODY
                return None
            return ("reprocess", InsertionMode.IN_BODY, token)
        if isinstance(token, EOFToken):
            return None
        return None

    def _mode_after_after_body(self, token):
        if isinstance(token, CharacterTokens):
            if _is_all_whitespace(token.data):
                # Per spec: whitespace characters are inserted using the rules for the "in body" mode
                # Process with InBody rules but stay in AfterAfterBody mode
                self._mode_in_body(token)
                return None
            # Non-whitespace character: parse error, reprocess in IN_BODY
            self._parse_error("Unexpected character after </html>")
            return ("reprocess", InsertionMode.IN_BODY, token)
        if isinstance(token, CommentToken):
            self._append_comment_to_document(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                return ("reprocess", InsertionMode.IN_BODY, token)
            # Any other tag: parse error, reprocess in IN_BODY
            self._parse_error("Unexpected tag after </html>")
            return ("reprocess", InsertionMode.IN_BODY, token)
        if isinstance(token, EOFToken):
            return None
        return None

    def _mode_in_frameset(self, token):
        # Per HTML5 spec §13.2.6.4.16: In frameset insertion mode
        if isinstance(token, CharacterTokens):
            # Only whitespace characters allowed; ignore all others
            whitespace = "".join(ch for ch in token.data if ch in "\t\n\f\r ")
            if whitespace:
                self._append_text(whitespace)
            return None
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.START and token.name == "frameset":
                self._insert_element(token, push=True)
                return None
            if token.kind == Tag.END and token.name == "frameset":
                if self.open_elements and self.open_elements[-1].name == "html":
                    # Root frameset, ignore end tag
                    self._parse_error("Unexpected frameset end tag")
                    return None
                self.open_elements.pop()
                if not self.opts.iframe_srcdoc and self.open_elements and self.open_elements[-1].name != "frameset":
                    self.mode = InsertionMode.AFTER_FRAMESET
                return None
            if token.kind == Tag.START and token.name == "frame":
                self._insert_element(token, push=True)
                self.open_elements.pop()
                return None
            if token.kind == Tag.START and token.name == "noframes":
                # Per spec: use IN_HEAD rules but preserve current mode for TEXT restoration
                self._insert_element(token, push=True)
                self.original_mode = self.mode
                self.mode = InsertionMode.TEXT
                return None
        if isinstance(token, EOFToken):
            # If we're in a template, handle EOF in template mode first
            if self.template_modes:
                return self._mode_in_template(token)
            if self.open_elements and self.open_elements[-1].name != "html":
                self._parse_error("Unexpected EOF in frameset")
            return None
        self._parse_error("Unexpected token in frameset")
        return None

    def _mode_after_frameset(self, token):
        # Per HTML5 spec §13.2.6.4.17: After frameset insertion mode
        if isinstance(token, CharacterTokens):
            # Only whitespace characters allowed; ignore all others
            whitespace = "".join(ch for ch in token.data if ch in "\t\n\f\r ")
            if whitespace:
                self._append_text(whitespace)
            return None
        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.END and token.name == "html":
                self.mode = InsertionMode.AFTER_AFTER_FRAMESET
                return None
            if token.kind == Tag.START and token.name == "noframes":
                # Insert noframes element directly and switch to TEXT mode
                self._insert_element(token, push=True)
                self.original_mode = self.mode
                self.mode = InsertionMode.TEXT
                return None
        if isinstance(token, EOFToken):
            # If we're in a template, handle EOF in template mode first
            if self.template_modes:
                return self._mode_in_template(token)
            return None
        self._parse_error("Unexpected token after frameset")
        return None

    def _mode_after_after_frameset(self, token):
        # Per HTML5 spec §13.2.6.4.18: After after frameset insertion mode
        if isinstance(token, CharacterTokens):
            # Whitespace is processed using InBody rules
            # but we stay in AfterAfterFrameset mode
            if _is_all_whitespace(token.data):
                self._mode_in_body(token)
                return None
            # Non-whitespace is ignored (filtered out)
            return None
        if isinstance(token, CommentToken):
            self._append_comment_to_document(token.data)
            return None
        if isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.START and token.name == "noframes":
                # Insert noframes element directly and switch to TEXT mode
                self._insert_element(token, push=True)
                self.original_mode = self.mode
                self.mode = InsertionMode.TEXT
                return None
        if isinstance(token, EOFToken):
            # If we're in a template, handle EOF in template mode first
            if self.template_modes:
                return self._mode_in_template(token)
            return None
        self._parse_error("Unexpected token after after frameset")
        return None

    # Helpers ----------------------------------------------------------------

    def _append_comment_to_document(self, text):
        node = SimpleDomNode("#comment", data=text)
        self.document.append_child(node)

    def _append_comment(self, text):
        parent = self._current_node_or_html()
        # If parent is a template, insert into its content fragment
        if parent.name == "template" and parent.template_content:
            parent = parent.template_content
        node = SimpleDomNode("#comment", data=text)
        parent.append_child(node)

    def _append_text(self, text):
        if not text:
            return
        if self.ignore_lf:
            self.ignore_lf = False
            if text.startswith("\n"):
                text = text[1:]
                if not text:
                    return
        target = self._current_node_or_html()
        foster_parenting = self._should_foster_parenting(target, is_text=True)
        
        # Reconstruct active formatting BEFORE getting insertion location when foster parenting
        if foster_parenting:
            self._reconstruct_active_formatting_elements()
        
        # Always use appropriate insertion location to handle templates
        parent, position = self._appropriate_insertion_location(foster_parenting=foster_parenting)
        if parent is None:
            return
        
        # Coalesce with adjacent text node if possible
        if position > 0 and parent.children[position - 1].name == "#text":
            parent.children[position - 1].data = (parent.children[position - 1].data or "") + text
            return
        if position < len(parent.children) and parent.children[position].name == "#text":
            parent.children[position].data = text + (parent.children[position].data or "")
            return
        
        node = SimpleDomNode("#text", data=text)
        parent.children.insert(position, node)
        node.parent = parent

    def _current_node_or_html(self):
        if self.open_elements:
            return self.open_elements[-1]
        if self.document.children:
            return self.document.children[-1]
        return self.document

    def _create_root(self, attrs):
        for child in self.document.children:
            if child.name == "html":
                if child not in self.open_elements:
                    self.open_elements.append(child)
                return child

        node = SimpleDomNode("html", attrs=[Attribute(attr.name, attr.value) for attr in attrs], namespace="html")
        self.document.append_child(node)
        self.open_elements.append(node)
        return node

    def _insert_element(self, tag, *, push, namespace="html"):
        attrs = [Attribute(attr.name, attr.value) for attr in tag.attrs]
        node = SimpleDomNode(tag.name, attrs=attrs, namespace=namespace)
        target = self._current_node_or_html()
        foster_parenting = self._should_foster_parenting(target, for_tag=tag.name)
        parent, position = self._appropriate_insertion_location(foster_parenting=foster_parenting)
        self._insert_node_at(parent, position, node)
        if push:
            self.open_elements.append(node)
        return node

    def _insert_phantom(self, name):
        tag = Tag(Tag.START, name, [], False)
        return self._insert_element(tag, push=True)

    def _insert_body_if_missing(self):
        for element in self.open_elements:
            if element.name == "body":
                return
        html_node = self._find_last_on_stack("html")
        if html_node is None:
            html_node = self._create_root([])
        node = SimpleDomNode("body", namespace="html")
        html_node.append_child(node)
        node.parent = html_node
        self.open_elements.append(node)

    def _appropriate_insertion_parent(self):
        if self.open_elements:
            return self.open_elements[-1]
        if self.document.children:
            return self.document.children[-1]
        return self.document

    def _create_element(self, name, namespace, attrs):
        attr_copies = [Attribute(attr.name, attr.value) for attr in attrs]
        ns = namespace or "html"
        return SimpleDomNode(name, attrs=attr_copies, namespace=ns)

    def _pop_current(self):
        if not self.open_elements:
            return None
        return self.open_elements.pop()

    def _in_scope(self, name):
        return self._has_element_in_scope(name, DEFAULT_SCOPE_TERMINATORS)

    def _close_element_by_name(self, name):
        # Simple element closing - pops from the named element onwards
        # Used for explicit closing (e.g., when button start tag closes existing button)
        for index in range(len(self.open_elements) - 1, -1, -1):
            if self.open_elements[index].name == name:
                del self.open_elements[index:]
                return

    def _any_other_end_tag(self, name):
        # Spec: "Any other end tag" in IN_BODY mode
        # Step 1: Initialize node to current node (last in stack)
        # Step 2: Loop through stack backwards
        for index in range(len(self.open_elements) - 1, -1, -1):
            node = self.open_elements[index]
            
            # Step 2.1: If node's name matches the end tag name
            if node.name == name:
                # Step 2.2: Generate implied end tags (except for this name)
                # Step 2.3: If current node is not this node, parse error
                if index != len(self.open_elements) - 1:
                    self._parse_error(f"Unexpected end tag </{name}>")
                # Step 2.4: Pop all elements from this node onwards
                del self.open_elements[index:]
                return
            
            # Step 2.5: If node is a special element, parse error and ignore the tag
            if self._is_special_element(node):
                self._parse_error(f"Unexpected end tag </{name}>")
                return  # Ignore the end tag
            
            # Step 2.6: Continue to next node (previous in stack)

    def _close_element_by_node(self, node):
        for index in range(len(self.open_elements) - 1, -1, -1):
            if self.open_elements[index] is node:
                del self.open_elements[index:]
                return True
        return False

    def _add_missing_attributes(self, node, attrs):
        existing = {attr.name for attr in node.attrs}
        for attr in attrs:
            if attr.name not in existing:
                node.attrs.append(Attribute(attr.name, attr.value))
                existing.add(attr.name)

    def _remove_from_open_elements(self, node):
        for index, current in enumerate(self.open_elements):
            if current is node:
                del self.open_elements[index]
                return True
        return False

    def _is_special_element(self, node):
        if node.namespace not in {None, "html"}:
            return False
        return node.name in SPECIAL_ELEMENTS

    def _find_active_formatting_index(self, name):
        for index in range(len(self.active_formatting) - 1, -1, -1):
            entry = self.active_formatting[index]
            if entry is FORMAT_MARKER:
                break
            if entry["name"] == name:
                return index
        return None

    def _find_active_formatting_index_by_node(self, node):
        for index in range(len(self.active_formatting) - 1, -1, -1):
            entry = self.active_formatting[index]
            if entry is FORMAT_MARKER:
                break
            if entry["node"] is node:
                return index
        return None

    def _clone_attributes(self, attrs):
        return [Attribute(attr.name, attr.value) for attr in attrs]

    def _attrs_signature(self, attrs):
        if not attrs:
            return ()
        items = [(attr.name, attr.value or "") for attr in attrs]
        items.sort()
        return tuple(items)

    def _find_active_formatting_duplicate(self, name, attrs):
        signature = self._attrs_signature(attrs)
        matches = []
        for index, entry in enumerate(self.active_formatting):
            if entry is FORMAT_MARKER:
                matches.clear()
                continue
            existing_signature = entry.get("signature")
            if existing_signature is None:
                existing_signature = self._attrs_signature(entry["attrs"])
                entry["signature"] = existing_signature
            if entry["name"] == name and existing_signature == signature:
                matches.append(index)
        if len(matches) >= 3:
            return matches[0]
        return None

    def _has_active_formatting_entry(self, name):
        for index in range(len(self.active_formatting) - 1, -1, -1):
            entry = self.active_formatting[index]
            if entry is FORMAT_MARKER:
                break
            if entry["name"] == name:
                return True
        return False

    def _remove_last_active_formatting_by_name(self, name):
        for index in range(len(self.active_formatting) - 1, -1, -1):
            entry = self.active_formatting[index]
            if entry is FORMAT_MARKER:
                break
            if entry["name"] == name:
                del self.active_formatting[index]
                return

    def _remove_last_open_element_by_name(self, name):
        for index in range(len(self.open_elements) - 1, -1, -1):
            if self.open_elements[index].name == name:
                del self.open_elements[index]
                return

    def _append_active_formatting_entry(self, name, attrs, node):
        entry_attrs = self._clone_attributes(attrs)
        signature = self._attrs_signature(entry_attrs)
        duplicates = 0
        for index in range(len(self.active_formatting) - 1, -1, -1):
            entry = self.active_formatting[index]
            if entry is FORMAT_MARKER:
                break
            existing_signature = entry.get("signature")
            if existing_signature is None:
                existing_signature = self._attrs_signature(entry["attrs"])
                entry["signature"] = existing_signature
            if entry["name"] == name and existing_signature == signature:
                duplicates += 1
                if duplicates >= 3:
                    del self.active_formatting[index]
                    break
        self.active_formatting.append({
            "name": name,
            "attrs": entry_attrs,
            "node": node,
            "signature": signature,
        })

    def _clear_active_formatting_up_to_marker(self):
        while self.active_formatting:
            entry = self.active_formatting.pop()
            if entry is FORMAT_MARKER:
                break

    def _tag_has_any_attrs(self, tag, names):
        if not tag.attrs:
            return False
        for attr in tag.attrs:
            if attr.name in names:
                return True
        return False

    def _push_formatting_marker(self):
        self.active_formatting.append(FORMAT_MARKER)

    def _remove_formatting_entry(self, index):
        if 0 <= index < len(self.active_formatting):
            del self.active_formatting[index]

    def _active_entry_attrs(self, entry):
        return self._clone_attributes(entry["attrs"])

    def _reconstruct_active_formatting_elements(self):
        if not self.active_formatting:
            return
        last_entry = self.active_formatting[-1]
        if last_entry is FORMAT_MARKER or last_entry["node"] in self.open_elements:
            return

        index = len(self.active_formatting) - 1
        while True:
            index -= 1
            if index < 0:
                break
            entry = self.active_formatting[index]
            if entry is FORMAT_MARKER or entry["node"] in self.open_elements:
                index += 1
                break
        if index < 0:
            index = 0
        while index < len(self.active_formatting):
            entry = self.active_formatting[index]
            if entry is FORMAT_MARKER:
                index += 1
                continue
            tag = Tag(Tag.START, entry["name"], self._active_entry_attrs(entry), False)
            new_node = self._insert_element(tag, push=True)
            entry["node"] = new_node
            index += 1

    def _has_node_in_scope(self, node):
        for current in reversed(self.open_elements):
            if current is node:
                return True
            if current.namespace in {None, "html"} and current.name in DEFAULT_SCOPE_TERMINATORS:
                return False
        return False

    def _detach_node(self, node):
        parent = node.parent
        if parent is None:
            return
        parent.remove_child(node)

    def _append_node(self, parent, node):
        if parent is None:
            return
        self._detach_node(node)
        parent.append_child(node)

    def _insert_node_at(self, parent, index, node):
        if parent is None:
            return
        self._detach_node(node)
        if index is None or index >= len(parent.children):
            parent.append_child(node)
            return
        if index < 0:
            index = 0
        parent.children.insert(index, node)
        node.parent = parent

    def _find_last_on_stack(self, name):
        for node in reversed(self.open_elements):
            if node.name == name:
                return node
        return None

    def _ensure_head_element(self):
        if self.head_element is not None:
            return self.head_element
        html_node = self._find_last_on_stack("html")
        if html_node is None and self.document.children:
            html_node = self.document.children[0]
        if html_node is None:
            return None
        head = SimpleDomNode("head")
        html_node.append_child(head)
        self.head_element = head
        return head

    def _clear_stack_to_table_context(self):
        while self.open_elements:
            node = self.open_elements[-1]
            # Only clear HTML elements; stop at table/template/html or foreign content
            if node.namespace not in {None, "html"}:
                break
            if node.name in {"table", "template", "html"}:
                break
            self.open_elements.pop()

    def _clear_stack_to_table_body_context(self):
        while self.open_elements:
            node = self.open_elements[-1]
            # Only clear HTML elements; stop at tbody/tfoot/thead/template/html or foreign content
            if node.namespace not in {None, "html"}:
                break
            if node.name in {"tbody", "tfoot", "thead", "template", "html"}:
                break
            self.open_elements.pop()

    def _clear_stack_to_table_row_context(self):
        while self.open_elements:
            node = self.open_elements[-1]
            # Only clear HTML elements; stop at tr/template/html or foreign content
            if node.namespace not in {None, "html"}:
                break
            if node.name in {"tr", "template", "html"}:
                break
            self.open_elements.pop()

    def _generate_implied_end_tags(self, exclude=None):
        while self.open_elements:
            node = self.open_elements[-1]
            if node.name in IMPLIED_END_TAGS and node.name != exclude:
                self.open_elements.pop()
                continue
            break

    def _has_in_table_scope(self, name):
        return self._has_element_in_scope(name, TABLE_SCOPE_TERMINATORS, check_integration_points=False)

    def _has_in_table_body_scope(self, name):
        return self._has_element_in_scope(name, TABLE_BODY_SCOPE_TERMINATORS, check_integration_points=False)

    def _has_in_table_row_scope(self, name):
        return self._has_element_in_scope(name, TABLE_ROW_SCOPE_TERMINATORS, check_integration_points=False)

    def _close_table_cell(self):
        if self._has_in_table_scope("td"):
            self._end_table_cell("td")
            return True
        if self._has_in_table_scope("th"):
            self._end_table_cell("th")
            return True
        return False

    def _end_table_cell(self, name):
        self._generate_implied_end_tags(name)
        while self.open_elements:
            node = self.open_elements.pop()
            if node.name == name and node.namespace in {None, "html"}:
                break
        self._clear_active_formatting_up_to_marker()
        self.mode = InsertionMode.IN_ROW

    def _flush_pending_table_text(self):
        if not self.pending_table_text:
            return
        data = "".join(self.pending_table_text)
        self.pending_table_text.clear()
        if not data:
            return
        if _is_all_whitespace(data):
            self._append_text(data)
            return
        self._parse_error("unexpected-character-implies-table-voodoo")
        previous = self.insert_from_table
        self.insert_from_table = True
        try:
            self._reconstruct_active_formatting_elements()
            self._append_text(data)
        finally:
            self.insert_from_table = previous

    def _close_table_element(self):
        if not self._has_in_table_scope("table"):
            self._parse_error("unexpected-end-tag")
            return False
        self._generate_implied_end_tags()
        while self.open_elements:
            node = self.open_elements.pop()
            if node.name == "table":
                break
        self._reset_insertion_mode()
        return True

    def _reset_insertion_mode(self):
        for node in reversed(self.open_elements):
            name = node.name
            if name == "select":
                self.mode = InsertionMode.IN_SELECT
                return
            if name == "td" or name == "th":
                self.mode = InsertionMode.IN_CELL
                return
            if name == "tr":
                self.mode = InsertionMode.IN_ROW
                return
            if name in {"tbody", "tfoot", "thead"}:
                self.mode = InsertionMode.IN_TABLE_BODY
                return
            if name == "caption":
                self.mode = InsertionMode.IN_CAPTION
                return
            if name == "table":
                self.mode = InsertionMode.IN_TABLE
                return
            if name == "template":
                # Return the last template mode from the stack
                if self.template_modes:
                    self.mode = self.template_modes[-1]
                    return
            if name == "head":
                # If we're resetting and head is on stack, stay in IN_HEAD
                self.mode = InsertionMode.IN_HEAD
                return
            if name == "html":
                break
        self.mode = InsertionMode.IN_BODY

    def _should_foster_parenting(self, target, *, for_tag=None, is_text=False):
        if target is None:
            return False
        if not self.insert_from_table:
            return False
        if target.name not in TABLE_FOSTER_TARGETS:
            return False
        if is_text:
            return True
        if for_tag in TABLE_ALLOWED_CHILDREN:
            return False
        return True

    def _lower_ascii(self, value):
        return value.lower() if value else ""

    def _adjust_svg_tag_name(self, name):
        lowered = self._lower_ascii(name)
        return SVG_TAG_NAME_ADJUSTMENTS.get(lowered, name)

    def _prepare_foreign_attributes(self, namespace, attrs):
        adjusted = []
        for attr in attrs:
            name = attr.name
            value = attr.value
            lower_name = self._lower_ascii(name)
            if namespace == "math" and lower_name in MATHML_ATTRIBUTE_ADJUSTMENTS:
                name = MATHML_ATTRIBUTE_ADJUSTMENTS[lower_name]
                lower_name = self._lower_ascii(name)
            elif namespace == "svg" and lower_name in SVG_ATTRIBUTE_ADJUSTMENTS:
                name = SVG_ATTRIBUTE_ADJUSTMENTS[lower_name]
                lower_name = self._lower_ascii(name)

            foreign_adjustment = FOREIGN_ATTRIBUTE_ADJUSTMENTS.get(lower_name)
            if foreign_adjustment is not None:
                prefix, local, _ = foreign_adjustment
                if prefix:
                    name = f"{prefix}:{local}"
                else:
                    name = local

            adjusted.append(Attribute(name, value))
        return adjusted

    def _node_attribute_value(self, node, name):
        target = self._lower_ascii(name)
        for attr in node.attrs:
            if self._lower_ascii(attr.name) == target:
                return attr.value or ""
        return None

    def _is_html_integration_point(self, node):
        if node is None:
            return False
        # annotation-xml is an HTML integration point only with specific encoding values
        if node.namespace == "math" and node.name == "annotation-xml":
            encoding = self._node_attribute_value(node, "encoding")
            if encoding:
                enc_lower = encoding.lower()
                if enc_lower in {"text/html", "application/xhtml+xml"}:
                    return True
            return False  # annotation-xml without proper encoding is NOT an integration point
        # SVG foreignObject, desc, and title are always HTML integration points
        return (node.namespace, node.name) in HTML_INTEGRATION_POINT_SET

    def _is_mathml_text_integration_point(self, node):
        if node is None:
            return False
        return (node.namespace, node.name) in MATHML_TEXT_INTEGRATION_POINT_SET

    def _adjusted_current_node(self):
        # Per HTML5 spec: for fragment parsing, if stack has only html element,
        # use the fragment context element instead
        if not self.open_elements:
            return None
        if (self.fragment_context and 
            len(self.open_elements) == 1 and 
            self.open_elements[0].name == "html"):
            # Return a pseudo-node representing the fragment context
            # We need something with .namespace, .name, and .attrs attributes
            class PseudoNode:
                def __init__(self, name, namespace):
                    self.name = name
                    self.namespace = namespace
                    self.attrs = []  # Fragment context has no attributes
            return PseudoNode(
                self.fragment_context.tag_name.lower(),
                self.fragment_context.namespace
            )
        return self.open_elements[-1]

    def _should_use_foreign_content(self, token):
        if not self.open_elements:
            return False
        current = self._adjusted_current_node()
        if current is None or current.namespace in {None, "html"}:
            return False

        if isinstance(token, EOFToken):
            return False

        if self._is_mathml_text_integration_point(current):
            if isinstance(token, CharacterTokens):
                return False
            if isinstance(token, Tag) and token.kind == Tag.START:
                name_lower = self._lower_ascii(token.name)
                if name_lower not in {"mglyph", "malignmark"}:
                    return False

        if current.namespace == "math" and current.name == "annotation-xml":
            if isinstance(token, Tag) and token.kind == Tag.START:
                if self._lower_ascii(token.name) == "svg":
                    return False

        if self._is_html_integration_point(current):
            if isinstance(token, CharacterTokens):
                return False
            if isinstance(token, Tag) and token.kind == Tag.START:
                return False

        return True

    def _foreign_breakout_font(self, tag):
        for attr in tag.attrs:
            if self._lower_ascii(attr.name) in {"color", "face", "size"}:
                return True
        return False

    def _pop_until_html_or_integration_point(self):
        while self.open_elements:
            node = self.open_elements[-1]
            if node.namespace in {None, "html"}:
                break
            if self._is_html_integration_point(node):
                break
            if self._is_mathml_text_integration_point(node):
                break
            self.open_elements.pop()

    def _process_foreign_content(self, token):
        current = self._adjusted_current_node()

        if isinstance(token, CharacterTokens):
            raw = token.data or ""
            if not raw:
                return None
            cleaned = []
            has_non_null_non_ws = False
            for ch in raw:
                if ch == "\x00":
                    self._parse_error("invalid-codepoint-in-foreign-content")
                    cleaned.append("\uFFFD")
                    continue
                if ch == "\x0c":
                    self._parse_error("invalid-codepoint-in-foreign-content")
                    cleaned.append("\uFFFD")
                    continue
                cleaned.append(ch)
                if ch not in "\t\n\f\r ":
                    has_non_null_non_ws = True
            if not cleaned:
                return None
            data = "".join(cleaned)
            if has_non_null_non_ws:
                self.frameset_ok = False
            self._append_text(data)
            return None

        if isinstance(token, CommentToken):
            self._append_comment(token.data)
            return None

        if isinstance(token, DoctypeToken):
            self._parse_error("Unexpected DOCTYPE in foreign content")
            return None

        if isinstance(token, Tag):
            name_lower = self._lower_ascii(token.name)
            if token.kind == Tag.START:
                if name_lower in FOREIGN_BREAKOUT_ELEMENTS or (name_lower == "font" and self._foreign_breakout_font(token)):
                    self._parse_error("Unexpected HTML element in foreign content")
                    self._pop_until_html_or_integration_point()
                    self._reset_insertion_mode()
                    return ("reprocess", self.mode, token, True)
                
                # In MathML/SVG, table structure elements can only be children of:
                # 1. The root foreign element (math/svg), OR
                # 2. Other table structure elements (but not the same element type)
                # If the current element is a non-table foreign element, block the table tag
                table_structure_elements = {"tr", "td", "th", "thead", "tbody", "tfoot", "caption", "col", "colgroup", "table"}
                if current.namespace in {"math", "svg"} and name_lower in table_structure_elements:
                    # Check if current element is a table structure element or root foreign
                    current_name = self._lower_ascii(current.name)
                    # Block if: 1) current is not a table/root element, OR 2) same element type (tr in tr, td in td, etc.)
                    if (current_name not in table_structure_elements and current_name not in {"math", "svg"}) or current_name == name_lower:
                        self._parse_error(f"Unexpected {name_lower} in foreign content")
                        return None

                namespace = current.namespace
                adjusted_name = token.name
                if namespace == "svg":
                    adjusted_name = self._adjust_svg_tag_name(token.name)
                attrs = self._prepare_foreign_attributes(namespace, token.attrs)
                new_tag = Tag(Tag.START, adjusted_name, attrs, token.self_closing)
                # For foreign elements, honor the self-closing flag
                self._insert_element(new_tag, push=not token.self_closing, namespace=namespace)
                return None

            if token.kind == Tag.END:
                name_lower = self._lower_ascii(token.name)
                
                # Special case: </br> and </p> end tags trigger breakout from foreign content
                if name_lower in {"br", "p"}:
                    self._parse_error("Unexpected HTML end tag in foreign content")
                    self._pop_until_html_or_integration_point()
                    self._reset_insertion_mode()
                    return ("reprocess", self.mode, token, True)
                
                # Process foreign end tag per spec: walk stack backwards looking for match
                idx = len(self.open_elements) - 1
                first = True
                while idx >= 0:
                    # Never pop html/body/head (handle at idx=0)
                    if idx == 0:
                        # No match found at all - ignore the end tag with parse error
                        if first:
                            self._parse_error("unexpected-end-tag-in-foreign-content")
                        return None

                    node = self.open_elements[idx]
                    is_html = node.namespace in {None, "html"}
                    name_eq = self._lower_ascii(node.name) == name_lower
                    
                    # Check if this node matches the end tag (case-insensitive)
                    if name_eq:
                        if self.fragment_context_element is not None and node is self.fragment_context_element:
                            self._parse_error("unexpected-end-tag-in-fragment-context")
                            return None
                        # If matched element is HTML namespace, break out to HTML mode
                        if is_html:
                            return ("reprocess", self.mode, token, True)
                        # Otherwise it's a foreign element - pop everything from this point up
                        del self.open_elements[idx:]
                        return None
                    
                    # Per HTML5 spec: if first node doesn't match, it's a parse error
                    if first:
                        self._parse_error("unexpected-end-tag-in-foreign-content")
                        first = False

                    idx -= 1
                
                # Reached here means we scanned entire stack without match - ignore tag
                return None

        if isinstance(token, EOFToken):
            return None

        return None

    def _appropriate_insertion_location(self, override_target=None, *, foster_parenting=False):
        if override_target is not None:
            target = override_target
        elif self.open_elements:
            target = self.open_elements[-1]
        elif self.document.children:
            target = self.document.children[-1]
        else:
            target = self.document

        if foster_parenting and target.name in {"table", "tbody", "tfoot", "thead", "tr"}:
            last_template = self._find_last_on_stack("template")
            last_table = self._find_last_on_stack("table")
            if last_template is not None and (
                last_table is None or self.open_elements.index(last_template) > self.open_elements.index(last_table)
            ):
                # Insert into template's content document fragment
                if last_template.template_content:
                    return last_template.template_content, len(last_template.template_content.children)
                return last_template, len(last_template.children)
            if last_table is None:
                if self.open_elements:
                    return self.open_elements[0], len(self.open_elements[0].children)
                return self.document, len(self.document.children)
            if last_table.parent is not None:
                parent = last_table.parent
                try:
                    position = parent.children.index(last_table)
                except ValueError:
                    position = len(parent.children)
                return parent, position
            table_index = self.open_elements.index(last_table)
            if table_index > 0:
                parent = self.open_elements[table_index - 1]
                return parent, len(parent.children)
            return self.document, len(self.document.children)

        # If target is a template element, insert into its content document fragment
        if target.name == "template" and target.template_content:
            return target.template_content, len(target.template_content.children)

        return target, len(target.children)

    def _clone_shallow(self, node):
        attrs = [Attribute(attr.name, attr.value) for attr in node.attrs]
        return SimpleDomNode(node.name, attrs=attrs, namespace=node.namespace)

    def _replace_node(self, old, new):
        parent = old.parent
        if parent is None:
            return
        try:
            index = parent.children.index(old)
        except ValueError:
            return
        parent.children[index] = new
        new.parent = parent
        old.parent = None

    def _reparent_children(self, source, target):
        children = list(source.children)
        for child in children:
            source.remove_child(child)
            target.append_child(child)

    def _adoption_agency(self, name):
        if self.open_elements and self.open_elements[-1].name == name:
            if self._find_active_formatting_index_by_node(self.open_elements[-1]) is None:
                self._pop_current()
                return

        for _ in range(8):
            fmt_index = self._find_active_formatting_index(name)
            if fmt_index is None:
                self._any_other_end_tag(name)
                return

            entry = self.active_formatting[fmt_index]
            target = entry["node"]
            if target not in self.open_elements:
                self._parse_error("Formatting element not open")
                self._remove_formatting_entry(fmt_index)
                return

            if not self._has_node_in_scope(target):
                self._parse_error("Formatting element not in scope")
                self._remove_formatting_entry(fmt_index)
                return

            if target is not self.open_elements[-1]:
                self._parse_error("Formatting element not current node")

            target_index = self.open_elements.index(target)
            furthest_block = None
            for node in self.open_elements[target_index + 1:]:
                if self._is_special_element(node):
                    furthest_block = node
                    break

            if furthest_block is None:
                del self.open_elements[target_index:]
                self._remove_formatting_entry(fmt_index)
                return

            common_ancestor = self.open_elements[target_index - 1] if target_index > 0 else None
            bookmark_entry = entry
            bookmark_mode = "replace"
            last_node = furthest_block
            node_index = self.open_elements.index(furthest_block)
            inner_counter = 0

            while True:
                inner_counter += 1
                node_index -= 1
                current = self.open_elements[node_index]
                if current is target:
                    break

                current_fmt_index = self._find_active_formatting_index_by_node(current)
                if current_fmt_index is None:
                    self.open_elements.pop(node_index)
                    continue

                if inner_counter > 3:
                    self.open_elements.pop(node_index)
                    self._remove_formatting_entry(current_fmt_index)
                    if current_fmt_index < fmt_index:
                        fmt_index -= 1
                    if bookmark_mode == "after" and bookmark_entry not in self.active_formatting:
                        bookmark_entry = entry
                        bookmark_mode = "replace"
                    continue

                clone = self._clone_shallow(current)
                self.open_elements[node_index] = clone
                fmt_entry = self.active_formatting[current_fmt_index]
                fmt_entry["node"] = clone
                fmt_entry["attrs"] = self._clone_attributes(fmt_entry["attrs"])
                fmt_entry["signature"] = self._attrs_signature(fmt_entry["attrs"])

                if last_node is furthest_block:
                    bookmark_entry = fmt_entry
                    bookmark_mode = "after"

                self._detach_node(last_node)
                clone.append_child(last_node)
                last_node = clone

            parent, position = self._appropriate_insertion_location(common_ancestor, foster_parenting=True)
            self._insert_node_at(parent, position, last_node)

            new_element = SimpleDomNode(target.name, attrs=self._active_entry_attrs(entry), namespace=target.namespace)
            self._reparent_children(furthest_block, new_element)
            furthest_block.append_child(new_element)

            new_entry = {
                "name": entry["name"],
                "attrs": self._clone_attributes(entry["attrs"]),
                "node": new_element,
                "signature": entry.get("signature") or self._attrs_signature(entry["attrs"]),
            }

            def _find_entry(target_entry):
                for idx, fmt in enumerate(self.active_formatting):
                    if fmt is target_entry:
                        return idx
                return None

            if bookmark_mode == "replace":
                idx = _find_entry(entry)
                if idx is not None:
                    self.active_formatting[idx] = new_entry
                else:
                    self.active_formatting.append(new_entry)
            else:
                insert_after = _find_entry(bookmark_entry)
                if insert_after is None:
                    self.active_formatting.append(new_entry)
                else:
                    self.active_formatting.insert(insert_after + 1, new_entry)
                entry_idx = _find_entry(entry)
                if entry_idx is not None:
                    del self.active_formatting[entry_idx]

            target_stack_index = self.open_elements.index(target)
            del self.open_elements[target_stack_index]
            furthest_index = self.open_elements.index(furthest_block)
            self.open_elements.insert(furthest_index + 1, new_element)

            entry = new_entry
            target = new_element

        fmt_index = self._find_active_formatting_index(name)
        if fmt_index is not None:
            self._remove_formatting_entry(fmt_index)

    def _parse_error(self, message):
        if self.opts.exact_errors:
            self.errors.append(message)

    def _set_quirks_mode(self, mode):
        self.quirks_mode = mode

    def _has_element_in_scope(self, name, terminators, check_integration_points=True):
        for node in reversed(self.open_elements):
            if node.name == name:
                return True
            if node.namespace not in {None, "html"}:
                # Foreign elements act as scope boundaries if they are integration points
                # (but only for non-table scopes - table scopes ignore integration points)
                if check_integration_points:
                    if self._is_html_integration_point(node):
                        return False
                    if self._is_mathml_text_integration_point(node):
                        return False
                continue
            if node.name in terminators:
                return False
        return False

    def _has_in_scope(self, name):
        """Check if element is in default scope (html5ever: default_scope)."""
        return self._has_element_in_scope(name, DEFAULT_SCOPE_TERMINATORS)

    def _has_in_button_scope(self, name):
        return self._has_element_in_scope(name, BUTTON_SCOPE_TERMINATORS)

    def _has_in_list_item_scope(self, name):
        return self._has_element_in_scope(name, LIST_ITEM_SCOPE_TERMINATORS)

    def _has_in_definition_scope(self, name):
        return self._has_element_in_scope(name, DEFINITION_SCOPE_TERMINATORS)

    def _has_any_in_scope(self, names):
        """Check if any element from the given set is in scope."""
        terminators = DEFAULT_SCOPE_TERMINATORS
        for node in reversed(self.open_elements):
            if node.name in names:
                return True
            if node.namespace in {None, "html"} and node.name in terminators:
                return False
            if node.namespace not in {None, "html"}:
                return False
        return False

    def _close_p_element(self):
        if not self._has_in_button_scope("p"):
            return
        while self.open_elements:
            node = self.open_elements.pop()
            if node.name == "p":
                break

    def _pop_until_any_inclusive(self, names):
        target = set(names)
        while self.open_elements:
            node = self.open_elements.pop()
            if node.name in target:
                return True
        return False

    def _pop_until_inclusive(self, name):
        while self.open_elements:
            node = self.open_elements.pop()
            if node.name == name:
                return True
        return False

    def _populate_selectedcontent(self, root):
        """Populate selectedcontent elements with content from selected option.
        
        Per HTML5 spec: selectedcontent mirrors the content of the selected option,
        or the first option if none is selected.
        """
        # Find all select elements
        selects = []
        self._find_elements(root, 'select', selects)
        
        for select in selects:
            # Find selectedcontent element in this select
            selectedcontent = self._find_element(select, 'selectedcontent')
            if not selectedcontent:
                continue
            
            # Find all option elements
            options = []
            self._find_elements(select, 'option', options)
            if not options:
                continue
            
            # Find selected option or use first one
            selected_option = None
            for opt in options:
                if opt.attrs:
                    for attr in opt.attrs:
                        if attr.name == 'selected':
                            selected_option = opt
                            break
                if selected_option:
                    break
            
            if not selected_option:
                selected_option = options[0]
            
            # Clone content from selected option to selectedcontent
            self._clone_children(selected_option, selectedcontent)
    
    def _find_elements(self, node, name, result):
        """Recursively find all elements with given name."""
        if hasattr(node, 'name') and node.name == name:
            result.append(node)
        if hasattr(node, 'children'):
            for child in node.children:
                self._find_elements(child, name, result)
    
    def _find_element(self, node, name):
        """Find first element with given name."""
        if hasattr(node, 'name') and node.name == name:
            return node
        if hasattr(node, 'children'):
            for child in node.children:
                result = self._find_element(child, name)
                if result:
                    return result
        return None
    
    def _clone_children(self, source, target):
        """Deep clone all children from source to target."""
        if not hasattr(source, 'children'):
            return
        for child in source.children:
            if hasattr(child, 'name') and child.name == '#text':
                # Text node
                cloned = SimpleDomNode('#text', data=child.data)
                target.children.append(cloned)
                cloned.parent = target
            elif hasattr(child, 'name'):
                # Element node
                cloned = SimpleDomNode(
                    child.name,
                    attrs=[Attribute(a.name, a.value) for a in (child.attrs or [])],
                    namespace=getattr(child, 'namespace', None)
                )
                self._clone_children(child, cloned)
                target.children.append(cloned)
                cloned.parent = target
