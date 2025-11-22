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
    HTML_INTEGRATION_POINT_SET,
    IMPLIED_END_TAGS,
    LIMITED_QUIRKY_PUBLIC_PREFIXES,
    LIST_ITEM_SCOPE_TERMINATORS,
    MATHML_ATTRIBUTE_ADJUSTMENTS,
    MATHML_TEXT_INTEGRATION_POINT_SET,
    QUIRKY_PUBLIC_MATCHES,
    QUIRKY_PUBLIC_PREFIXES,
    QUIRKY_SYSTEM_MATCHES,
    SPECIAL_ELEMENTS,
    SVG_ATTRIBUTE_ADJUSTMENTS,
    SVG_TAG_NAME_ADJUSTMENTS,
    TABLE_ALLOWED_CHILDREN,
    TABLE_FOSTER_TARGETS,
    TABLE_SCOPE_TERMINATORS,
)
from .tokens import CharacterTokens, CommentToken, DoctypeToken, EOFToken, ParseError, Tag, TokenSinkResult


class InsertionMode(enum.IntEnum):
    INITIAL = 0
    BEFORE_HTML = 1
    BEFORE_HEAD = 2
    IN_HEAD = 3
    AFTER_HEAD = 4
    TEXT = 5
    IN_BODY = 6
    AFTER_BODY = 7
    AFTER_AFTER_BODY = 8
    IN_TABLE = 9
    IN_TABLE_TEXT = 10
    IN_CAPTION = 11
    IN_COLUMN_GROUP = 12
    IN_TABLE_BODY = 13
    IN_ROW = 14
    IN_CELL = 15
    IN_FRAMESET = 16
    AFTER_FRAMESET = 17
    AFTER_AFTER_FRAMESET = 18
    IN_SELECT = 19
    IN_TEMPLATE = 20


_BODY_START_IN_HEAD_TAGS = (
    "base",
    "basefont",
    "bgsound",
    "link",
    "meta",
    "noframes",
    "script",
    "style",
    "template",
    "title",
)

_BODY_START_FRAMESET_NEUTRAL = BLOCK_WITH_P_START | {"p", "caption", "col", "colgroup", "hr", "pre", "listing"}

_BODY_APPLET_LIKE_END_TAGS = {"applet", "marquee", "object"}

_BODY_BLOCK_END_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "button",
    "center",
    "details",
    "dialog",
    "dir",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "header",
    "hgroup",
    "listing",
    "main",
    "menu",
    "nav",
    "ol",
    "pre",
    "search",
    "section",
    "summary",
    "table",
    "ul",
}


def _is_all_whitespace(text):
    return text.strip("\t\n\f\r ") == ""


def _contains_prefix(haystack, needle):
    return any(needle.startswith(prefix) for prefix in haystack)


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
    __slots__ = ("attrs", "children", "data", "name", "namespace", "parent")

    def __init__(self, name, attrs=None, data=None, namespace=None):
        self.name = name
        self.parent = None
        self.data = data

        if name.startswith("#") or name == "!doctype":
            self.namespace = namespace
            if name == "#comment" or name == "!doctype":
                self.children = None
                self.attrs = None
            else:
                self.children = []
                self.attrs = attrs if attrs is not None else {}
        else:
            self.namespace = namespace or "html"
            self.children = []
            self.attrs = attrs if attrs is not None else {}

    def append_child(self, node):
        self.children.append(node)
        node.parent = self

    def remove_child(self, node):
        if node in self.children:
            self.children.remove(node)
            node.parent = None

    def to_test_format(self, indent=0):
        if self.name in {"#document", "#document-fragment"}:
            parts = [child.to_test_format(0) for child in self.children]
            return "\n".join(part for part in parts if part)
        if self.name == "#comment":
            comment = self.data or ""
            return f"| {' ' * indent}<!-- {comment} -->"
        if self.name == "!doctype":
            return self._format_doctype()

        line = f"| {' ' * indent}<{self._qualified_name()}>"
        attribute_lines = self._format_attributes(indent)

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
        namespace = self.namespace
        for attr_name, attr_value in self.attrs.items():
            value = attr_value or ""
            display_name = attr_name
            if namespace and namespace not in {None, "html"}:
                lower_name = attr_name.lower()
                if lower_name in FOREIGN_ATTRIBUTE_ADJUSTMENTS:
                    display_name = attr_name.replace(":", " ")
            display_attrs.append((display_name, value))

        # Sort by display name for canonical test output
        display_attrs.sort(key=lambda x: x[0])

        for display_name, value in display_attrs:
            formatted.append(f'| {padding}{display_name}="{value}"')
        return formatted

    def _format_doctype(self):
        doctype = self.data
        if not doctype:
            return "| <!DOCTYPE >"

        name = doctype.name or ""
        public_id = doctype.public_id
        system_id = doctype.system_id

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


class ElementNode(SimpleDomNode):
    __slots__ = ()
    def __init__(self, name, attrs, namespace):
        self.name = name
        self.parent = None
        self.data = None
        self.namespace = namespace
        self.children = []
        self.attrs = attrs


class TemplateNode(ElementNode):
    __slots__ = ("template_content",)

    def __init__(self, name, attrs=None, data=None, namespace=None):
        super().__init__(name, attrs, namespace)
        if self.namespace == "html":
            self.template_content = SimpleDomNode("#document-fragment")
        else:
            self.template_content = None

    def to_test_format(self, indent=0):
        line = f"| {' ' * indent}<{self._qualified_name()}>"
        attribute_lines = self._format_attributes(indent)

        sections = [line]
        if attribute_lines:
            sections.extend(attribute_lines)

        if self.template_content:
            content_line = f"| {' ' * (indent + 2)}content"
            content_child_lines = [child.to_test_format(indent + 4) for child in self.template_content.children]
            sections.append(content_line)
            sections.extend(child for child in content_child_lines if child)

        return "\n".join(sections)


class TextNode:
    __slots__ = ("data", "name", "namespace", "parent")

    def __init__(self, data):
        self.data = data
        self.parent = None
        self.name = "#text"
        self.namespace = None

    def to_test_format(self, indent=0):
        text = self.data or ""
        return f'| {" " * indent}"{text}"'


class TreeBuilder:
    __slots__ = (
        "_body_end_handlers",
        "_body_start_handlers",
        "_body_token_handlers",
        "_mode_handlers",
        "active_formatting",
        "document",
        "errors",
        "form_element",
        "fragment_context",
        "fragment_context_element",
        "frameset_ok",
        "head_element",
        "ignore_lf",
        "insert_from_table",
        "mode",
        "open_elements",
        "original_mode",
        "pending_table_text",
        "quirks_mode",
        "table_text_original_mode",
        "template_modes",
        "tokenizer_state_override",
    )

    def __init__(
        self,
        fragment_context=None,
    ):
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
            root = self._create_element("html", None, {})
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
                context_element = self._create_element(adjusted_name, namespace, {})
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

    def _set_quirks_mode(self, mode):
        self.quirks_mode = mode

    def _parse_error(self, message):
        self.errors.append(message)

    def _has_element_in_scope(self, target, terminators=None, check_integration_points=True):
        if terminators is None:
            terminators = DEFAULT_SCOPE_TERMINATORS
        for node in reversed(self.open_elements):
            if node.name == target:
                return True
            ns = node.namespace
            if ns == "html" or ns is None:
                if node.name in terminators:
                    return False
            elif check_integration_points and (self._is_html_integration_point(node) or self._is_mathml_text_integration_point(node)):
                return False
        return False

    def _has_element_in_button_scope(self, target):
        return self._has_element_in_scope(target, BUTTON_SCOPE_TERMINATORS)

    def _pop_until_inclusive(self, name):
        while self.open_elements:
            node = self.open_elements.pop()
            if node.name == name:
                break

    def _pop_until_any_inclusive(self, names):
        while self.open_elements:
            node = self.open_elements.pop()
            if node.name in names:
                break

    def _close_p_element(self):
        if self._has_element_in_button_scope("p"):
            self._generate_implied_end_tags("p")
            if self.open_elements[-1].name != "p":
                self._parse_error("Unexpected end tag </p>")
            self._pop_until_inclusive("p")
            return True
        return False

    def process_token(self, token):
        if isinstance(token, ParseError):
            self.errors.append(token.message)
            return TokenSinkResult.Continue

        if isinstance(token, DoctypeToken):
            return self._handle_doctype(token)

        reprocess = True
        current_token = token
        force_html_mode = False

        # Cache mode handlers list for speed
        mode_handlers = self._MODE_HANDLERS

        while reprocess:
            reprocess = False

            # Optimization: Check for HTML namespace first (common case)
            current_node = self.open_elements[-1] if self.open_elements else None
            is_html_namespace = current_node is None or current_node.namespace in {None, "html"}

            if force_html_mode or is_html_namespace:
                force_html_mode = False
                if self.mode == InsertionMode.IN_BODY:
                    # Inline _mode_in_body for performance
                    token_type = type(current_token)
                    if token_type is Tag:
                        # Inline _handle_tag_in_body
                        if current_token.kind == 0: # Tag.START
                            name = current_token.name
                            if name == "div" or name == "ul" or name == "ol":
                                # Inline _handle_body_start_block_with_p
                                has_p = False
                                for node in reversed(self.open_elements):
                                    if node.name == "p":
                                        has_p = True
                                        break
                                    if node.namespace in {None, "html"} and node.name in BUTTON_SCOPE_TERMINATORS:
                                        break

                                if has_p:
                                    self._close_p_element()

                                self._insert_element(current_token, push=True)
                                result = None
                            elif name == "p":
                                result = self._handle_body_start_paragraph(current_token)
                            elif name == "span":
                                if self.active_formatting:
                                    self._reconstruct_active_formatting_elements()
                                self._insert_element(current_token, push=True)
                                if current_token.self_closing:
                                    self._parse_error("non-void-html-element-start-tag-with-trailing-solidus")
                                self.frameset_ok = False
                                result = None
                            elif name == "a":
                                result = self._handle_body_start_a(current_token)
                            elif name == "br" or name == "img":
                                if self.active_formatting:
                                    self._reconstruct_active_formatting_elements()
                                self._insert_element(current_token, push=False)
                                self.frameset_ok = False
                                result = None
                            elif name == "hr":
                                has_p = False
                                for node in reversed(self.open_elements):
                                    if node.name == "p":
                                        has_p = True
                                        break
                                    if node.namespace in {None, "html"} and node.name in BUTTON_SCOPE_TERMINATORS:
                                        break

                                if has_p:
                                    self._close_p_element()

                                self._insert_element(current_token, push=False)
                                self.frameset_ok = False
                                result = None
                            else:
                                handler = self._BODY_START_HANDLERS.get(name)
                                if handler:
                                    result = handler(self, current_token)
                                else:
                                    # Inline _handle_body_start_default
                                    if self.active_formatting:
                                        self._reconstruct_active_formatting_elements()
                                    self._insert_element(current_token, push=True)
                                    if current_token.self_closing:
                                        self._parse_error("non-void-html-element-start-tag-with-trailing-solidus")
                                    if name not in _BODY_START_FRAMESET_NEUTRAL and name not in FORMATTING_ELEMENTS:
                                        self.frameset_ok = False
                                    result = None
                        else:
                            name = current_token.name
                            if name == "br":
                                self._parse_error("Unexpected </br>")
                                br_tag = Tag(0, "br", {}, False)
                                result = self._handle_body_start_br(br_tag)
                            elif name in FORMATTING_ELEMENTS:
                                self._adoption_agency(name)
                                result = None
                            else:
                                handler = self._BODY_END_HANDLERS.get(name)
                                if handler:
                                    result = handler(self, current_token)
                                else:
                                    self._any_other_end_tag(name)
                                    result = None
                    elif token_type is CharacterTokens:
                        # Inline _handle_characters_in_body
                        data = current_token.data or ""
                        if data:
                            if "\x00" in data:
                                self._parse_error("invalid-codepoint")
                                data = data.replace("\x00", "")
                            if "\x0c" in data:
                                self._parse_error("invalid-codepoint")
                                data = data.replace("\x0c", "")

                            if data:
                                if _is_all_whitespace(data):
                                    self._reconstruct_active_formatting_elements()
                                    self._append_text(data)
                                else:
                                    self._reconstruct_active_formatting_elements()
                                    self.frameset_ok = False
                                    self._append_text(data)
                        result = None
                    elif token_type is CommentToken:
                        result = self._handle_comment_in_body(current_token)
                    elif token_type is EOFToken:
                        result = self._handle_eof_in_body(current_token)
                    else:
                        result = None
                else:
                    result = mode_handlers[self.mode](self, current_token)
            elif self._should_use_foreign_content(current_token):
                result = self._process_foreign_content(current_token)
            else:
                # Foreign content stack logic
                current = current_node
                # Only pop foreign elements if we're NOT at an HTML/MathML integration point
                # and NOT about to insert a new foreign element (svg/math)
                if not isinstance(current_token, EOFToken):
                    should_pop = True
                    # Don't pop at integration points - they stay on stack to receive content
                    if self._is_html_integration_point(current) or self._is_mathml_text_integration_point(current):
                        should_pop = False
                    # Don't pop when inserting new svg/math elements
                    if isinstance(current_token, Tag) and current_token.kind == Tag.START:
                        # Optimization: Tokenizer already lowercases tag names
                        name_lower = current_token.name
                        if name_lower in {"svg", "math"}:
                            should_pop = False
                    if should_pop:
                        # Pop foreign elements above integration points, but not the integration point itself
                        while self.open_elements and self.open_elements[-1].namespace not in {None, "html"}:
                            node = self.open_elements[-1]
                            # Stop if we reach an integration point - don't pop it
                            if self._is_html_integration_point(node) or self._is_mathml_text_integration_point(
                                node,
                            ):
                                break
                            self.open_elements.pop()
                        self._reset_insertion_mode()

                # Special handling: text at integration points inserts directly, bypassing mode dispatch
                if isinstance(current_token, CharacterTokens):
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
                        result = mode_handlers[self.mode](self, current_token)
                else:
                    # At integration points inside foreign content, check if table tags make sense.
                    if (
                        (
                            self._is_mathml_text_integration_point(current)
                            or self._is_html_integration_point(current)
                        )
                        and isinstance(current_token, Tag)
                        and current_token.kind == Tag.START
                        and self.mode not in {InsertionMode.IN_BODY}
                    ):
                        # Check if we're in a table mode but without an actual table in scope
                        # If so, table tags should be ignored (use IN_BODY mode)
                        is_table_mode = self.mode in {
                            InsertionMode.IN_TABLE,
                            InsertionMode.IN_TABLE_BODY,
                            InsertionMode.IN_ROW,
                            InsertionMode.IN_CELL,
                            InsertionMode.IN_CAPTION,
                            InsertionMode.IN_COLUMN_GROUP,
                        }
                        has_table_in_scope = self._has_in_table_scope("table")
                        if is_table_mode and not has_table_in_scope:
                            # Temporarily use IN_BODY mode for this tag
                            saved_mode = self.mode
                            self.mode = InsertionMode.IN_BODY
                            result = mode_handlers[self.mode](self, current_token)
                            # Restore mode if no mode change was requested
                            if self.mode == InsertionMode.IN_BODY:
                                self.mode = saved_mode
                        else:
                            result = mode_handlers[self.mode](self, current_token)
                    else:
                        result = mode_handlers[self.mode](self, current_token)

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
        parse_error, quirks_mode = _doctype_error_and_quirks(doctype, False)

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
                if context_elem is not None and context_elem.parent is root:
                    for child in list(context_elem.children):
                        context_elem.remove_child(child)
                        root.append_child(child)
                    root.remove_child(context_elem)
                for child in list(root.children):
                    root.remove_child(child)
                    self.document.append_child(child)
                self.document.remove_child(root)

        # Populate selectedcontent elements per HTML5 spec
        self._populate_selectedcontent(self.document)

        return self.document

    # Insertion mode dispatch ------------------------------------------------

    def _dispatch(self, token):
        return self._MODE_HANDLERS[self.mode](self, token)

    def _mode_initial(self, token):
        if isinstance(token, CharacterTokens):
            if _is_all_whitespace(token.data):
                return None
            self._set_quirks_mode("quirks")
            return ("reprocess", InsertionMode.BEFORE_HTML, token)
        if isinstance(token, CommentToken):
            self._append_comment_to_document(token.data)
            return None
        if isinstance(token, EOFToken):
            self._set_quirks_mode("quirks")
            self.mode = InsertionMode.BEFORE_HTML
            return ("reprocess", InsertionMode.BEFORE_HTML, token)
        # Anything else (Tags, etc) - no DOCTYPE seen, so quirks mode
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
                self._create_root({})
                self.mode = InsertionMode.BEFORE_HEAD
                return ("reprocess", InsertionMode.BEFORE_HEAD, token)
            if token.kind == Tag.END:
                # Ignore other end tags
                self._parse_error("Unexpected end tag in before html")
                return None
        if isinstance(token, EOFToken):
            self._create_root({})
            self.mode = InsertionMode.BEFORE_HEAD
            return ("reprocess", InsertionMode.BEFORE_HEAD, token)

        if isinstance(token, CharacterTokens):
            stripped = token.data.lstrip("\t\n\f\r ")
            if not stripped:
                return None
            if len(stripped) != len(token.data):
                token = CharacterTokens(stripped)

        self._create_root({})
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
                for name, value in token.attrs.items():
                    if name == "type":
                        input_type = (value or "").lower()
                        break
                if input_type == "hidden":
                    # Parse error but ignore - don't create body, don't insert element
                    self._parse_error("unexpected-hidden-input-after-head")
                    return None
                # Non-hidden input creates body
                self._insert_body_if_missing()
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.START and token.name in {
                "base",
                "basefont",
                "bgsound",
                "link",
                "meta",
                "title",
                "style",
                "script",
                "noscript",
            }:
                self.open_elements.append(self.head_element)
                result = self._mode_in_head(token)
                # Remove the head element from wherever it is in the stack
                # (it might not be at the end if we inserted other elements like <title>)
                self.open_elements.remove(self.head_element)
                return result
            if token.kind == Tag.START and token.name == "template":
                # Template in after-head needs special handling:
                # Process in IN_HEAD mode, which will switch to IN_TEMPLATE
                # Don't remove head from stack - let normal processing continue
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
        handler = self._BODY_TOKEN_HANDLERS.get(type(token))
        if handler:
            return handler(self, token)
        return None

    def _handle_characters_in_body(self, token):
        data = token.data or ""
        if not data:
            return
        if "\x00" in data:
            self._parse_error("invalid-codepoint")
            data = data.replace("\x00", "")
        if "\x0c" in data:
            self._parse_error("invalid-codepoint")
            data = data.replace("\x0c", "")
        if not data:
            return
        if _is_all_whitespace(data):
            self._reconstruct_active_formatting_elements()
            self._append_text(data)
            return
        self._reconstruct_active_formatting_elements()
        self.frameset_ok = False
        self._append_text(data)
        return

    def _handle_comment_in_body(self, token):
        self._append_comment(token.data)
        return

    def _handle_tag_in_body(self, token):
        if token.kind == Tag.START:
            handler = self._BODY_START_HANDLERS.get(token.name)
            if handler:
                return handler(self, token)
            return self._handle_body_start_default(token)
        name = token.name

        # Special case: </br> end tag is treated as <br> start tag
        if name == "br":
            self._parse_error("Unexpected </br>")
            br_tag = Tag(Tag.START, "br", {}, False)
            return self._mode_in_body(br_tag)

        if name in FORMATTING_ELEMENTS:
            self._adoption_agency(name)
            return None
        handler = self._BODY_END_HANDLERS.get(name)
        if handler:
            return handler(self, token)
        # Any other end tag
        self._any_other_end_tag(token.name)
        return None

    def _handle_eof_in_body(self, token):
        # If we're in a template, handle EOF in template mode first
        if self.template_modes:
            return self._mode_in_template(token)
        self.mode = InsertionMode.AFTER_BODY
        return ("reprocess", InsertionMode.AFTER_BODY, token)

    # ---------------------
    # Body mode start tag handlers
    # ---------------------

    def _handle_body_start_html(self, token):
        if self.template_modes:
            self._parse_error("Unexpected <html> in template")
            return
        if self.open_elements:
            html = self.open_elements[0]
            self._add_missing_attributes(html, token.attrs)
        return

    def _handle_body_start_body(self, token):
        if self.template_modes:
            self._parse_error("Unexpected <body> in template")
            return
        if len(self.open_elements) > 1:
            self._parse_error("Unexpected <body> inside body")
            body = self.open_elements[1] if len(self.open_elements) > 1 else None
            if body and body.name == "body":
                self._add_missing_attributes(body, token.attrs)
            self.frameset_ok = False
            return
        self.frameset_ok = False
        return

    def _handle_body_start_head(self, token):
        self._parse_error("Unexpected <head> in body")
        return

    def _handle_body_start_in_head(self, token):
        return self._mode_in_head(token)

    def _handle_body_start_block_with_p(self, token):
        self._close_p_element()
        self._insert_element(token, push=True)
        return

    def _handle_body_start_heading(self, token):
        self._close_p_element()
        if self.open_elements and self.open_elements[-1].name in HEADING_ELEMENTS:
            self._parse_error("Nested heading")
            self._pop_current()
        self._insert_element(token, push=True)
        self.frameset_ok = False
        return

    def _handle_body_start_pre_listing(self, token):
        self._close_p_element()
        self._insert_element(token, push=True)
        self.ignore_lf = True
        self.frameset_ok = False
        return

    def _handle_body_start_form(self, token):
        if self.form_element is not None:
            self._parse_error("Nested form")
            return
        self._close_p_element()
        node = self._insert_element(token, push=True)
        self.form_element = node
        self.frameset_ok = False
        return

    def _handle_body_start_button(self, token):
        if self._has_in_scope("button"):
            self._parse_error("Nested button")
            self._close_element_by_name("button")
        self._insert_element(token, push=True)
        self.frameset_ok = False
        return

    def _handle_body_start_paragraph(self, token):
        self._close_p_element()
        self._insert_element(token, push=True)
        return

    def _handle_body_start_math(self, token):
        self._reconstruct_active_formatting_elements()
        attrs = self._prepare_foreign_attributes("math", token.attrs)
        new_tag = Tag(Tag.START, token.name, attrs, token.self_closing)
        self._insert_element(new_tag, push=not token.self_closing, namespace="math")
        return

    def _handle_body_start_svg(self, token):
        self._reconstruct_active_formatting_elements()
        adjusted_name = self._adjust_svg_tag_name(token.name)
        attrs = self._prepare_foreign_attributes("svg", token.attrs)
        new_tag = Tag(Tag.START, adjusted_name, attrs, token.self_closing)
        self._insert_element(new_tag, push=not token.self_closing, namespace="svg")
        return

    def _handle_body_start_li(self, token):
        self.frameset_ok = False
        self._close_p_element()
        if self._has_in_list_item_scope("li"):
            self._pop_until_any_inclusive({"li"})
        self._insert_element(token, push=True)
        return

    def _handle_body_start_dd_dt(self, token):
        self.frameset_ok = False
        self._close_p_element()
        name = token.name
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
        return

    def _adoption_agency(self, subject):
        # 1. If the current node is the subject, and it is not in the active formatting elements list...
        if self.open_elements and self.open_elements[-1].name == subject:
            if not self._has_active_formatting_entry(subject):
                self._pop_until_inclusive(subject)
                return

        # 2. Outer loop
        for _ in range(8):
            # 3. Find formatting element
            formatting_element_index = self._find_active_formatting_index(subject)
            if formatting_element_index is None:
                return

            formatting_element_entry = self.active_formatting[formatting_element_index]
            formatting_element = formatting_element_entry["node"]

            # 4. If formatting element is not in open elements
            if formatting_element not in self.open_elements:
                self._parse_error("Adoption agency: formatting element not in open elements")
                self._remove_formatting_entry(formatting_element_index)
                return

            # 5. If formatting element is in open elements but not in scope
            if not self._has_element_in_scope(formatting_element.name):
                self._parse_error("Adoption agency: formatting element not in scope")
                return

            # 6. If formatting element is not the current node
            if formatting_element is not self.open_elements[-1]:
                self._parse_error("Adoption agency: formatting element not current node")

            # 7. Find furthest block
            furthest_block = None
            formatting_element_in_open_index = self.open_elements.index(formatting_element)

            for i in range(formatting_element_in_open_index + 1, len(self.open_elements)):
                node = self.open_elements[i]
                if self._is_special_element(node):
                    furthest_block = node
                    break

            if furthest_block is None:
                while self.open_elements:
                    popped = self.open_elements.pop()
                    if popped is formatting_element:
                        break
                self._remove_formatting_entry(formatting_element_index)
                return

            # 8. Bookmark
            bookmark = formatting_element_index + 1

            # 9. Node and Last Node
            node = furthest_block
            last_node = furthest_block

            # 10. Inner loop
            inner_loop_counter = 0
            while True:
                inner_loop_counter += 1

                # 10.1 Node = element above node
                node_index = self.open_elements.index(node)
                node = self.open_elements[node_index - 1]

                # 10.2 If node is formatting element, break
                if node is formatting_element:
                    break

                # 10.3 Find active formatting entry for node
                node_formatting_index = self._find_active_formatting_index_by_node(node)

                if inner_loop_counter > 3 and node_formatting_index is not None:
                    self._remove_formatting_entry(node_formatting_index)
                    if node_formatting_index < bookmark:
                        bookmark -= 1
                    node_formatting_index = None

                if node_formatting_index is None:
                    node_index = self.open_elements.index(node)
                    self.open_elements.remove(node)
                    node = self.open_elements[node_index]
                    continue

                # 10.4 Replace entry with new element
                entry = self.active_formatting[node_formatting_index]
                new_element = self._create_element(entry["name"], entry["node"].namespace, entry["attrs"])
                entry["node"] = new_element
                self.open_elements[self.open_elements.index(node)] = new_element
                node = new_element

                # 10.5 If last node is furthest block, update bookmark
                if last_node is furthest_block:
                    bookmark = node_formatting_index + 1

                # 10.6 Reparent last_node
                if last_node.parent:
                    last_node.parent.remove_child(last_node)
                node.append_child(last_node)

                # 10.7
                last_node = node

            # 11. Insert last_node into common ancestor
            common_ancestor = self.open_elements[formatting_element_in_open_index - 1]
            if last_node.parent:
                last_node.parent.remove_child(last_node)

            if self._should_foster_parenting(common_ancestor, for_tag=last_node.name):
                parent, position = self._appropriate_insertion_location(common_ancestor, foster_parenting=True)
                self._insert_node_at(parent, position, last_node)
            else:
                if type(common_ancestor) is TemplateNode and common_ancestor.template_content:
                    common_ancestor.template_content.append_child(last_node)
                else:
                    common_ancestor.append_child(last_node)

            # 12. Create new formatting element
            entry = self.active_formatting[formatting_element_index]
            new_formatting_element = self._create_element(entry["name"], entry["node"].namespace, entry["attrs"])
            entry["node"] = new_formatting_element

            # 13. Move children of furthest block
            while furthest_block.children:
                child = furthest_block.children[0]
                furthest_block.remove_child(child)
                new_formatting_element.append_child(child)

            furthest_block.append_child(new_formatting_element)

            # 14. Remove formatting element from active formatting and insert new at bookmark
            self._remove_formatting_entry(formatting_element_index)
            if bookmark > formatting_element_index:
                bookmark -= 1
            self.active_formatting.insert(bookmark, entry)

            # 15. Remove formatting element from open elements and insert new one
            self.open_elements.remove(formatting_element)
            furthest_block_index = self.open_elements.index(furthest_block)
            self.open_elements.insert(furthest_block_index + 1, new_formatting_element)

    def _handle_body_start_a(self, token):
        if self._has_active_formatting_entry("a"):
            self._adoption_agency("a")
            self._remove_last_active_formatting_by_name("a")
            self._remove_last_open_element_by_name("a")
        self._reconstruct_active_formatting_elements()
        node = self._insert_element(token, push=True)
        self._append_active_formatting_entry("a", token.attrs, node)
        return

    def _handle_body_start_formatting(self, token):
        name = token.name
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
        return

    def _handle_body_start_applet_like(self, token):
        self._reconstruct_active_formatting_elements()
        self._insert_element(token, push=True)
        self._push_formatting_marker()
        self.frameset_ok = False
        return

    def _handle_body_start_hr(self, token):
        self._close_p_element()
        self._insert_element(token, push=False)
        self.frameset_ok = False
        return

    def _handle_body_start_br(self, token):
        self._close_p_element()
        self._reconstruct_active_formatting_elements()
        self._insert_element(token, push=False)
        self.frameset_ok = False
        return

    def _handle_body_start_frameset(self, token):
        if not self.frameset_ok:
            self._parse_error("unexpected-start-tag-ignored")
            return
        body_index = None
        for i, elem in enumerate(self.open_elements):
            if elem.name == "body":
                body_index = i
                break
        if body_index is not None:
            body_elem = self.open_elements[body_index]
            if body_elem.parent:
                body_elem.parent.remove_child(body_elem)
            self.open_elements = self.open_elements[:body_index]
        self._insert_element(token, push=True)
        self.mode = InsertionMode.IN_FRAMESET
        return

    # ---------------------
    # Body mode end tag handlers
    # ---------------------

    def _handle_body_end_body(self, token):
        if self._in_scope("body"):
            self.mode = InsertionMode.AFTER_BODY
        return

    def _handle_body_end_html(self, token):
        if self._in_scope("body"):
            return ("reprocess", InsertionMode.AFTER_BODY, token)
        return None

    def _handle_body_end_p(self, token):
        if not self._close_p_element():
            self._parse_error("Unexpected </p>")
            phantom = Tag(Tag.START, "p", {}, False)
            self._insert_element(phantom, push=True)
            self._close_p_element()
        return

    def _handle_body_end_li(self, token):
        if not self._has_in_list_item_scope("li"):
            self._parse_error("Unexpected </li>")
            return
        self._pop_until_any_inclusive({"li"})
        return

    def _handle_body_end_dd_dt(self, token):
        name = token.name
        if not self._has_in_definition_scope(name):
            self._parse_error("Unexpected closing tag")
            return
        self._pop_until_any_inclusive({"dd", "dt"})
        return

    def _handle_body_end_form(self, token):
        if self.form_element is None:
            self._parse_error("Unexpected </form>")
            return
        removed = self._remove_from_open_elements(self.form_element)
        self.form_element = None
        if not removed:
            self._parse_error("Form element not in stack")
        return

    def _handle_body_end_applet_like(self, token):
        name = token.name
        if not self._in_scope(name):
            self._parse_error("Unexpected closing tag")
            return
        while self.open_elements:
            popped = self.open_elements.pop()
            if popped.name == name:
                break
        self._clear_active_formatting_up_to_marker()
        return

    def _handle_body_end_heading(self, token):
        name = token.name
        if not self._has_any_in_scope(HEADING_ELEMENTS):
            self._parse_error(f"Unexpected </{name}>")
            return
        self._generate_implied_end_tags()
        if self.open_elements and self.open_elements[-1].name != name:
            self._parse_error(f"Mismatched heading end tag </{name}>")
        while self.open_elements:
            popped = self.open_elements.pop()
            if popped.name in HEADING_ELEMENTS:
                break
        return

    def _handle_body_end_block(self, token):
        name = token.name
        if not self._in_scope(name):
            self._parse_error(f"No matching <{name}> tag")
            return
        self._generate_implied_end_tags()
        if self.open_elements and self.open_elements[-1].name != name:
            self._parse_error(f"Unexpected open element while closing {name}")
        self._pop_until_any_inclusive({name})
        return

    def _handle_body_end_template(self, token):
        has_template = any(node.name == "template" for node in self.open_elements)
        if not has_template:
            return
        self._generate_implied_end_tags()
        self._pop_until_inclusive("template")
        self._clear_active_formatting_up_to_marker()
        if self.template_modes:
            self.template_modes.pop()
        self._reset_insertion_mode()
        return

    def _handle_body_start_structure_ignored(self, token):
        self._parse_error("unexpected-start-tag-ignored")
        return

    def _handle_body_start_col_or_frame(self, token):
        if self.fragment_context is None:
            self._parse_error("unexpected-start-tag-ignored")
            return
        self._insert_element(token, push=False)
        return

    def _handle_body_start_image(self, token):
        self._parse_error("image-start-tag")
        img_token = Tag(Tag.START, "img", token.attrs, token.self_closing)
        self._reconstruct_active_formatting_elements()
        self._insert_element(img_token, push=False)
        self.frameset_ok = False
        return

    def _handle_body_start_void_with_formatting(self, token):
        self._reconstruct_active_formatting_elements()
        self._insert_element(token, push=False)
        self.frameset_ok = False
        return

    def _handle_body_start_simple_void(self, token):
        self._insert_element(token, push=False)
        return

    def _handle_body_start_input(self, token):
        input_type = None
        for name, value in token.attrs.items():
            if name == "type":
                input_type = (value or "").lower()
                break
        self._insert_element(token, push=False)
        if input_type != "hidden":
            self.frameset_ok = False
        return

    def _handle_body_start_table(self, token):
        if self.quirks_mode != "quirks":
            self._close_p_element()
        self._insert_element(token, push=True)
        self.frameset_ok = False
        self.mode = InsertionMode.IN_TABLE
        return

    def _handle_body_start_plaintext_xmp(self, token):
        self._close_p_element()
        self._insert_element(token, push=True)
        self.frameset_ok = False
        if token.name == "plaintext":
            self.tokenizer_state_override = TokenSinkResult.Plaintext
        return

    def _handle_body_start_textarea(self, token):
        self._insert_element(token, push=True)
        self.ignore_lf = True
        self.frameset_ok = False
        return

    def _handle_body_start_select(self, token):
        self._reconstruct_active_formatting_elements()
        self._insert_element(token, push=True)
        self.frameset_ok = False
        self._reset_insertion_mode()
        return

    def _handle_body_start_option(self, token):
        if self.open_elements and self.open_elements[-1].name == "option":
            self.open_elements.pop()
        self._reconstruct_active_formatting_elements()
        self._insert_element(token, push=True)
        return

    def _handle_body_start_optgroup(self, token):
        if self.open_elements and self.open_elements[-1].name == "option":
            self.open_elements.pop()
        if self.open_elements and self.open_elements[-1].name == "optgroup":
            self.open_elements.pop()
        self._reconstruct_active_formatting_elements()
        self._insert_element(token, push=True)
        return

    def _handle_body_start_rp_rt(self, token):
        self._generate_implied_end_tags(exclude="rtc")
        self._insert_element(token, push=True)
        return

    def _handle_body_start_rb_rtc(self, token):
        if self.open_elements and self.open_elements[-1].name in {"rb", "rp", "rt", "rtc"}:
            self._generate_implied_end_tags()
        self._insert_element(token, push=True)
        return

    def _handle_body_start_table_parse_error(self, token):
        self._parse_error(f"Unexpected <{token.name}> in body")
        return

    def _handle_body_start_default(self, token):
        self._reconstruct_active_formatting_elements()
        self._insert_element(token, push=True)
        if token.self_closing:
            self._parse_error("non-void-html-element-start-tag-with-trailing-solidus")
        name = token.name
        if name not in _BODY_START_FRAMESET_NEUTRAL and name not in FORMATTING_ELEMENTS:
            self.frameset_ok = False
        return

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
                    self._clear_stack_until({"table", "template", "html"})
                    self._push_formatting_marker()
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_CAPTION
                    return None
                if name == "colgroup":
                    self._clear_stack_until({"table", "template", "html"})
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_COLUMN_GROUP
                    return None
                if name == "col":
                    self._clear_stack_until({"table", "template", "html"})
                    implied = Tag(Tag.START, "colgroup", {}, False)
                    self._insert_element(implied, push=True)
                    self.mode = InsertionMode.IN_COLUMN_GROUP
                    return ("reprocess", InsertionMode.IN_COLUMN_GROUP, token)
                if name in {"tbody", "tfoot", "thead"}:
                    self._clear_stack_until({"table", "template", "html"})
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_TABLE_BODY
                    return None
                if name in {"td", "th", "tr"}:
                    self._clear_stack_until({"table", "template", "html"})
                    implied = Tag(Tag.START, "tbody", {}, False)
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
                    for attr_name, attr_value in token.attrs.items():
                        if attr_name == "type":
                            input_type = (attr_value or "").lower()
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
                ws = data[: len(data) - len(stripped)]
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
                    return None
                if (
                    self.fragment_context
                    and self.fragment_context.tag_name.lower() == "colgroup"
                    and not self._has_in_table_scope("table")
                ):
                    self._parse_error("unexpected-start-tag-in-column-group")
                    return None
                # Anything else: if we're in a colgroup, pop it and switch to IN_TABLE
                # But if we're in a template, just ignore non-column content
                if current and current.name == "colgroup":
                    self._pop_current()
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                if current and current.name == "template":
                    # In template column group context, non-column content is ignored
                    self._parse_error("unexpected-start-tag-in-template-column-group")
                    return None
                if current and current.name != "html":
                    self._pop_current()
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                return ("reprocess", InsertionMode.IN_TABLE, token)
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
            if current and current.name == "template":
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
                    self._clear_stack_until({"tbody", "tfoot", "thead", "template", "html"})
                    self._insert_element(token, push=True)
                    self.mode = InsertionMode.IN_ROW
                    return None
                if name in {"td", "th"}:
                    self._parse_error("unexpected-cell-in-table-body")
                    self._clear_stack_until({"tbody", "tfoot", "thead", "template", "html"})
                    implied = Tag(Tag.START, "tr", {}, False)
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
                    elif (
                        self.fragment_context
                        and current
                        and current.name == "html"
                        and self.fragment_context.tag_name.lower() in {"tbody", "tfoot", "thead"}
                    ):
                        self._parse_error("unexpected-start-tag")
                        return None
                    self.mode = InsertionMode.IN_TABLE
                    return ("reprocess", InsertionMode.IN_TABLE, token)
                return self._mode_in_table(token)
            if name in {"tbody", "tfoot", "thead"}:
                if not self._has_in_table_scope(name):
                    self._parse_error("unexpected-end-tag")
                    return None
                self._clear_stack_until({"tbody", "tfoot", "thead", "template", "html"})
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
                if (
                    self.fragment_context
                    and current
                    and current.name == "html"
                    and self.fragment_context.tag_name.lower() in {"tbody", "tfoot", "thead"}
                ):
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
                    self._clear_stack_until({"tr", "template", "html"})
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
                if name in {"caption", "col", "group", "td", "th"}:
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
        self._clear_stack_until({"tr", "template", "html"})
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
                    # If no cell to close and we're in a fragment cell context, ignore the token
                    if (
                        self.fragment_context
                        and self.fragment_context.tag_name.lower() in {"td", "th"}
                        and not self._has_in_table_scope("table")
                    ):
                        self._parse_error("unexpected-start-tag-in-cell-fragment")
                        return None
                    # Otherwise delegate to IN_BODY
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
                if token.name not in {
                    "base",
                    "basefont",
                    "bgsound",
                    "link",
                    "meta",
                    "noframes",
                    "script",
                    "style",
                    "template",
                    "title",
                }:
                    self.template_modes.pop()
                    self.template_modes.append(InsertionMode.IN_BODY)
                    self.mode = InsertionMode.IN_BODY
                    return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.END and token.name == "template":
                return self._mode_in_head(token)
            # Head-related tags process in InHead
            if token.name in {
                "base",
                "basefont",
                "bgsound",
                "link",
                "meta",
                "noframes",
                "script",
                "style",
                "template",
                "title",
            }:
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
            html_node = self._find_last_on_stack("html")
            if html_node is None and self.fragment_context is not None and self.document.children:
                html_node = next((child for child in self.document.children if child.name == "html"), None)
            if html_node is not None:
                html_node.append_child(SimpleDomNode("#comment", data=token.data))
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
            if self.fragment_context is not None:
                html_node = self._find_last_on_stack("html")
                if html_node is None and self.document.children:
                    html_node = next((child for child in self.document.children if child.name == "html"), None)
                if html_node is not None:
                    html_node.append_child(SimpleDomNode("#comment", data=token.data))
                    return None
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
                if self.open_elements and self.open_elements[-1].name != "frameset":
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
        self.mode = InsertionMode.IN_FRAMESET
        return ("reprocess", InsertionMode.IN_FRAMESET, token)

    def _mode_after_after_frameset(self, token):
        # Per HTML5 spec §13.2.6.4.18: After after frameset insertion mode
        if isinstance(token, CharacterTokens):
            # Whitespace is processed using InBody rules
            # but we stay in AfterAfterFrameset mode
            if _is_all_whitespace(token.data):
                self._mode_in_body(token)
                return None
            # Non-whitespace falls through to "Anything else"
        elif isinstance(token, CommentToken):
            self._append_comment_to_document(token.data)
            return None
        elif isinstance(token, Tag):
            if token.kind == Tag.START and token.name == "html":
                return ("reprocess", InsertionMode.IN_BODY, token)
            if token.kind == Tag.START and token.name == "noframes":
                # Insert noframes element directly and switch to TEXT mode
                self._insert_element(token, push=True)
                self.original_mode = self.mode
                self.mode = InsertionMode.TEXT
                return None
        elif isinstance(token, EOFToken):
            # If we're in a template, handle EOF in template mode first
            if self.template_modes:
                return self._mode_in_template(token)
            return None

        self._parse_error("Unexpected token after after frameset")
        self.mode = InsertionMode.IN_FRAMESET
        return ("reprocess", InsertionMode.IN_FRAMESET, token)

    # Helpers ----------------------------------------------------------------

    def _append_comment_to_document(self, text):
        node = SimpleDomNode("#comment", data=text)
        self.document.append_child(node)

    def _append_comment(self, text):
        parent = self._current_node_or_html()
        # If parent is a template, insert into its content fragment
        if type(parent) is TemplateNode and parent.template_content:
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

        # Fast path optimization for common case
        if self.open_elements:
            target = self.open_elements[-1]
        elif self.document.children:
            target = self.document.children[-1]
        else:
            target = self.document

        if target.name not in TABLE_FOSTER_TARGETS and type(target) is not TemplateNode:
             children = target.children
             if children:
                 last_child = children[-1]
                 if type(last_child) is TextNode:
                     last_child.data += text
                     return

             node = TextNode(text)
             children.append(node)
             node.parent = target
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

        node = TextNode(text)
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

        node = SimpleDomNode("html", attrs=attrs, namespace="html")
        self.document.append_child(node)
        self.open_elements.append(node)
        return node

    def _insert_element(self, tag, *, push, namespace="html"):
        if tag.name == "template" and namespace == "html":
            node = TemplateNode(tag.name, attrs=tag.attrs, namespace=namespace)
        else:
            node = ElementNode(tag.name, attrs=tag.attrs, namespace=namespace)

        # Fast path for common case: not inserting from table
        if not self.insert_from_table:
            if self.open_elements:
                target = self.open_elements[-1]
            elif self.document.children:
                target = self.document.children[-1]
            else:
                target = self.document

            # Handle template content insertion
            if type(target) is TemplateNode:
                parent = target.template_content
            else:
                parent = target

            parent.children.append(node)
            node.parent = parent

            if push:
                self.open_elements.append(node)
            return node

        target = self._current_node_or_html()
        foster_parenting = self._should_foster_parenting(target, for_tag=tag.name)
        parent, position = self._appropriate_insertion_location(foster_parenting=foster_parenting)
        self._insert_node_at(parent, position, node)
        if push:
            self.open_elements.append(node)
        return node

    def _insert_phantom(self, name):
        tag = Tag(Tag.START, name, {}, False)
        return self._insert_element(tag, push=True)

    def _insert_body_if_missing(self):
        for element in self.open_elements:
            if element.name == "body":
                return
        html_node = self._find_last_on_stack("html")
        if html_node is None:
            html_node = self._create_root({})
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
        ns = namespace or "html"
        if name == "template" and ns == "html":
            return TemplateNode(name, attrs=attrs, namespace=ns)
        return ElementNode(name, attrs, ns)

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
        if not attrs:
            return
        existing = node.attrs
        for name, value in attrs.items():
            if name not in existing:
                existing[name] = value

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
        return attrs.copy() if attrs else {}

    def _attrs_signature(self, attrs):
        if not attrs:
            return ()
        items = []
        for name, value in attrs.items():
            items.append((name, value or ""))
        items.sort()
        return tuple(items)

    def _find_active_formatting_duplicate(self, name, attrs):
        signature = self._attrs_signature(attrs)
        matches = []
        for index, entry in enumerate(self.active_formatting):
            if entry is FORMAT_MARKER:
                matches.clear()
                continue
            existing_signature = entry["signature"]
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
            existing_signature = entry["signature"]
            if entry["name"] == name and existing_signature == signature:
                duplicates += 1
                if duplicates >= 3:
                    del self.active_formatting[index]
                    break
        self.active_formatting.append(
            {
                "name": name,
                "attrs": entry_attrs,
                "node": node,
                "signature": signature,
            },
        )

    def _clear_active_formatting_up_to_marker(self):
        while self.active_formatting:
            entry = self.active_formatting.pop()
            if entry is FORMAT_MARKER:
                break

    def _push_formatting_marker(self):
        self.active_formatting.append(FORMAT_MARKER)

    def _remove_formatting_entry(self, index):
        if 0 <= index < len(self.active_formatting):
            del self.active_formatting[index]

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
            tag = Tag(Tag.START, entry["name"], self._clone_attributes(entry["attrs"]), False)
            new_node = self._insert_element(tag, push=True)
            entry["node"] = new_node
            index += 1

    def _insert_node_at(self, parent, index, node):
        if index is None or index >= len(parent.children):
            parent.append_child(node)
        else:
            parent.children.insert(index, node)
            node.parent = parent

    def _find_last_on_stack(self, name):
        for node in reversed(self.open_elements):
            if node.name == name:
                return node
        return None

    def _clear_stack_until(self, names):
        while self.open_elements:
            node = self.open_elements[-1]
            if node.name in names and node.namespace in {None, "html"}:
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
        if not attrs:
            return {}
        adjusted = {}
        for name, value in attrs.items():
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

            if name not in adjusted:
                adjusted[name] = value
        return adjusted

    def _node_attribute_value(self, node, name):
        target = self._lower_ascii(name)
        attrs = node.attrs
        if not attrs:
            return None
        for attr_name, attr_value in attrs.items():
            if self._lower_ascii(attr_name) == target:
                return attr_value or ""
        return None

    def _is_html_integration_point(self, node):
        if node is None:
            return False
        if node.namespace in {None, "html"}:
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
        if node.namespace != "math":
            return False
        return (node.namespace, node.name) in MATHML_TEXT_INTEGRATION_POINT_SET

    def _adjusted_current_node(self):
        # Per HTML5 spec: for fragment parsing, if stack has only html element,
        # use the fragment context element instead
        if not self.open_elements:
            return None
        if self.fragment_context and len(self.open_elements) == 1 and self.open_elements[0].name == "html":
            # Return a pseudo-node representing the fragment context
            # We need something with .namespace, .name, and .attrs attributes
            class PseudoNode:
                def __init__(self, name, namespace):
                    self.name = name
                    self.namespace = namespace
                    self.attrs = {}

            return PseudoNode(
                self.fragment_context.tag_name.lower(),
                self.fragment_context.namespace,
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
        for name, _ in tag.attrs.items():
            if self._lower_ascii(name) in {"color", "face", "size"}:
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
            if self.fragment_context_element is not None and node is self.fragment_context_element:
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
                    cleaned.append("\ufffd")
                    continue
                if ch == "\x0c":
                    self._parse_error("invalid-codepoint-in-foreign-content")
                    cleaned.append("\ufffd")
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
                if name_lower in FOREIGN_BREAKOUT_ELEMENTS or (
                    name_lower == "font" and self._foreign_breakout_font(token)
                ):
                    self._parse_error("Unexpected HTML element in foreign content")
                    self._pop_until_html_or_integration_point()
                    self._reset_insertion_mode()
                    return ("reprocess", self.mode, token, True)

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

                    # If we hit an HTML element that doesn't match, process in secondary mode
                    if is_html:
                        return ("reprocess", self.mode, token, True)

                    # If we reached the root (and it wasn't HTML or matched), ignore the token
                    if idx == 0:
                        return None

                    idx -= 1

                # Reached here means we scanned entire stack without match - ignore tag
                return None



    def _appropriate_insertion_location(self, override_target=None, *, foster_parenting=False):
        if override_target is not None:
            target = override_target
        elif self.open_elements:
            target = self.open_elements[-1]
        else:
            target = self.document

        if foster_parenting and target.name in {"table", "tbody", "tfoot", "thead", "tr"}:
            last_template = self._find_last_on_stack("template")
            last_table = self._find_last_on_stack("table")
            if last_template is not None and (
                last_table is None or self.open_elements.index(last_template) > self.open_elements.index(last_table)
            ):
                # Insert into template's content document fragment
                if type(last_template) is TemplateNode and last_template.template_content:
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
        if type(target) is TemplateNode and target.template_content:
            return target.template_content, len(target.template_content.children)

        return target, len(target.children)

    def _populate_selectedcontent(self, root):
        """Populate selectedcontent elements with content from selected option.

        Per HTML5 spec: selectedcontent mirrors the content of the selected option,
        or the first option if none is selected.
        """
        # Find all select elements
        selects = []
        self._find_elements(root, "select", selects)

        for select in selects:
            # Find selectedcontent element in this select
            selectedcontent = self._find_element(select, "selectedcontent")
            if not selectedcontent:
                continue

            # Find all option elements
            options = []
            self._find_elements(select, "option", options)
            if not options:
                continue

            # Find selected option or use first one
            selected_option = None
            for opt in options:
                if opt.attrs:
                    for attr_name, _ in opt.attrs.items():
                        if attr_name == "selected":
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
        if node.name == name:
            result.append(node)

        if type(node) is not TextNode and node.children:
            for child in node.children:
                self._find_elements(child, name, result)

    def _find_element(self, node, name):
        """Find first element with given name."""
        if node.name == name:
            return node

        if type(node) is not TextNode and node.children:
            for child in node.children:
                result = self._find_element(child, name)
                if result:
                    return result
        return None

    def _clone_children(self, source, target):
        """Deep clone all children from source to target."""
        if type(source) is TextNode or not source.children:
            return
        for child in source.children:
            if type(child) is TextNode:
                # Text node
                cloned = TextNode(child.data)
                target.children.append(cloned)
                cloned.parent = target
            else:
                # Element node
                cloned = ElementNode(
                    child.name,
                    attrs=self._clone_attributes(child.attrs),
                    namespace=child.namespace,
                )
                self._clone_children(child, cloned)
                target.children.append(cloned)
                cloned.parent = target

    def _has_in_scope(self, name):
        return self._has_element_in_scope(name, DEFAULT_SCOPE_TERMINATORS)

    def _has_in_list_item_scope(self, name):
        return self._has_element_in_scope(name, LIST_ITEM_SCOPE_TERMINATORS)

    def _has_in_definition_scope(self, name):
        return self._has_element_in_scope(name, DEFINITION_SCOPE_TERMINATORS)

    def _has_any_in_scope(self, names):
        terminators = DEFAULT_SCOPE_TERMINATORS
        for node in reversed(self.open_elements):
            if node.name in names:
                return True
            if node.namespace in {None, "html"} and node.name in terminators:
                return False
            if node.namespace not in {None, "html"}:
                return False
        return False

    _BODY_START_HANDLERS = {
        "a": _handle_body_start_a,
        "address": _handle_body_start_block_with_p,
        "applet": _handle_body_start_applet_like,
        "area": _handle_body_start_void_with_formatting,
        "article": _handle_body_start_block_with_p,
        "aside": _handle_body_start_block_with_p,
        "b": _handle_body_start_formatting,
        "base": _handle_body_start_in_head,
        "basefont": _handle_body_start_in_head,
        "bgsound": _handle_body_start_in_head,
        "big": _handle_body_start_formatting,
        "blockquote": _handle_body_start_block_with_p,
        "body": _handle_body_start_body,
        "br": _handle_body_start_br,
        "button": _handle_body_start_button,
        "caption": _handle_body_start_table_parse_error,
        "center": _handle_body_start_block_with_p,
        "code": _handle_body_start_formatting,
        "col": _handle_body_start_col_or_frame,
        "colgroup": _handle_body_start_structure_ignored,
        "dd": _handle_body_start_dd_dt,
        "details": _handle_body_start_block_with_p,
        "dialog": _handle_body_start_block_with_p,
        "dir": _handle_body_start_block_with_p,
        "div": _handle_body_start_block_with_p,
        "dl": _handle_body_start_block_with_p,
        "dt": _handle_body_start_dd_dt,
        "em": _handle_body_start_formatting,
        "embed": _handle_body_start_void_with_formatting,
        "fieldset": _handle_body_start_block_with_p,
        "figcaption": _handle_body_start_block_with_p,
        "figure": _handle_body_start_block_with_p,
        "font": _handle_body_start_formatting,
        "footer": _handle_body_start_block_with_p,
        "form": _handle_body_start_form,
        "frame": _handle_body_start_col_or_frame,
        "frameset": _handle_body_start_frameset,
        "h1": _handle_body_start_heading,
        "h2": _handle_body_start_heading,
        "h3": _handle_body_start_heading,
        "h4": _handle_body_start_heading,
        "h5": _handle_body_start_heading,
        "h6": _handle_body_start_heading,
        "head": _handle_body_start_head,
        "header": _handle_body_start_block_with_p,
        "hgroup": _handle_body_start_block_with_p,
        "hr": _handle_body_start_hr,
        "html": _handle_body_start_html,
        "i": _handle_body_start_formatting,
        "image": _handle_body_start_image,
        "img": _handle_body_start_void_with_formatting,
        "input": _handle_body_start_input,
        "keygen": _handle_body_start_void_with_formatting,
        "li": _handle_body_start_li,
        "link": _handle_body_start_in_head,
        "listing": _handle_body_start_pre_listing,
        "main": _handle_body_start_block_with_p,
        "marquee": _handle_body_start_applet_like,
        "math": _handle_body_start_math,
        "menu": _handle_body_start_block_with_p,
        "meta": _handle_body_start_in_head,
        "nav": _handle_body_start_block_with_p,
        "nobr": _handle_body_start_formatting,
        "noframes": _handle_body_start_in_head,
        "object": _handle_body_start_applet_like,
        "ol": _handle_body_start_block_with_p,
        "optgroup": _handle_body_start_optgroup,
        "option": _handle_body_start_option,
        "p": _handle_body_start_paragraph,
        "param": _handle_body_start_simple_void,
        "plaintext": _handle_body_start_plaintext_xmp,
        "pre": _handle_body_start_pre_listing,
        "rb": _handle_body_start_rb_rtc,
        "rp": _handle_body_start_rp_rt,
        "rt": _handle_body_start_rp_rt,
        "rtc": _handle_body_start_rb_rtc,
        "s": _handle_body_start_formatting,
        "script": _handle_body_start_in_head,
        "search": _handle_body_start_block_with_p,
        "section": _handle_body_start_block_with_p,
        "select": _handle_body_start_select,
        "small": _handle_body_start_formatting,
        "source": _handle_body_start_simple_void,
        "strike": _handle_body_start_formatting,
        "strong": _handle_body_start_formatting,
        "style": _handle_body_start_in_head,
        "summary": _handle_body_start_block_with_p,
        "svg": _handle_body_start_svg,
        "table": _handle_body_start_table,
        "tbody": _handle_body_start_structure_ignored,
        "td": _handle_body_start_structure_ignored,
        "template": _handle_body_start_in_head,
        "textarea": _handle_body_start_textarea,
        "tfoot": _handle_body_start_structure_ignored,
        "th": _handle_body_start_structure_ignored,
        "thead": _handle_body_start_structure_ignored,
        "title": _handle_body_start_in_head,
        "tr": _handle_body_start_structure_ignored,
        "track": _handle_body_start_simple_void,
        "tt": _handle_body_start_formatting,
        "u": _handle_body_start_formatting,
        "ul": _handle_body_start_block_with_p,
        "wbr": _handle_body_start_void_with_formatting,
        "xmp": _handle_body_start_plaintext_xmp,
    }
    _BODY_END_HANDLERS = {
        "address": _handle_body_end_block,
        "applet": _handle_body_end_applet_like,
        "article": _handle_body_end_block,
        "aside": _handle_body_end_block,
        "blockquote": _handle_body_end_block,
        "body": _handle_body_end_body,
        "button": _handle_body_end_block,
        "center": _handle_body_end_block,
        "dd": _handle_body_end_dd_dt,
        "details": _handle_body_end_block,
        "dialog": _handle_body_end_block,
        "dir": _handle_body_end_block,
        "div": _handle_body_end_block,
        "dl": _handle_body_end_block,
        "dt": _handle_body_end_dd_dt,
        "fieldset": _handle_body_end_block,
        "figcaption": _handle_body_end_block,
        "figure": _handle_body_end_block,
        "footer": _handle_body_end_block,
        "form": _handle_body_end_form,
        "h1": _handle_body_end_heading,
        "h2": _handle_body_end_heading,
        "h3": _handle_body_end_heading,
        "h4": _handle_body_end_heading,
        "h5": _handle_body_end_heading,
        "h6": _handle_body_end_heading,
        "header": _handle_body_end_block,
        "hgroup": _handle_body_end_block,
        "html": _handle_body_end_html,
        "li": _handle_body_end_li,
        "listing": _handle_body_end_block,
        "main": _handle_body_end_block,
        "marquee": _handle_body_end_applet_like,
        "menu": _handle_body_end_block,
        "nav": _handle_body_end_block,
        "object": _handle_body_end_applet_like,
        "ol": _handle_body_end_block,
        "p": _handle_body_end_p,
        "pre": _handle_body_end_block,
        "search": _handle_body_end_block,
        "section": _handle_body_end_block,
        "summary": _handle_body_end_block,
        "table": _handle_body_end_block,
        "template": _handle_body_end_template,
        "ul": _handle_body_end_block,
    }
    _MODE_HANDLERS = [
        _mode_initial,
        _mode_before_html,
        _mode_before_head,
        _mode_in_head,
        _mode_after_head,
        _mode_text,
        _mode_in_body,
        _mode_after_body,
        _mode_after_after_body,
        _mode_in_table,
        _mode_in_table_text,
        _mode_in_caption,
        _mode_in_column_group,
        _mode_in_table_body,
        _mode_in_row,
        _mode_in_cell,
        _mode_in_frameset,
        _mode_after_frameset,
        _mode_after_after_frameset,
        _mode_in_select,
        _mode_in_template,
    ]

    _BODY_TOKEN_HANDLERS = {
        CharacterTokens: _handle_characters_in_body,
        CommentToken: _handle_comment_in_body,
        Tag: _handle_tag_in_body,
        EOFToken: _handle_eof_in_body,
    }
