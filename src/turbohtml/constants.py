"""HTML5 Element Constants

This module defines constants used for HTML5 parsing according to the WHATWG spec.
Elements are organized into lists to maintain consistent iteration order while
still allowing efficient lookups.

Usage:
    from turbohtml.constants import VOID_ELEMENTS, HTML_ELEMENTS

References:
    - https://html.spec.whatwg.org/multipage/syntax.html#void-elements
    - https://html.spec.whatwg.org/multipage/syntax.html#optional-tags
"""

# HTML Element Sets
VOID_ELEMENTS = [
    "area",
    "base",
    "basefont",
    "bgsound",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "keygen",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
]

HTML_ELEMENTS = [
    "a",
    "b",
    "big",
    "blockquote",
    "body",
    "br",
    "center",
    "code",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "embed",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "head",
    "hr",
    "i",
    "img",
    "li",
    "listing",
    "menu",
    "meta",
    "nobr",
    "ol",
    "p",
    "pre",
    "s",
    "small",
    "span",
    "strong",
    "strike",
    "sub",
    "sup",
    "table",
    "tt",
    "u",
    "ul",
    "var",
]

BLOCK_ELEMENTS = [
    "address",
    "article",
    "aside",
    "blockquote",
    "details",
    "dialog",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hgroup",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
    "summary",
]

TABLE_ELEMENTS = [
    # Structure elements
    "table",
    "thead",
    "tbody",
    "tfoot",
    "caption",
    "colgroup",
    # Row elements
    "tr",
    # Cell elements
    "td",
    "th",
]

TABLE_CONTAINING_ELEMENTS = [
    "html",
    "body",
    "div",
    "form",
    "button",
    "ruby",
    "td",
    "th",
    "math",
    "svg",
]

HEAD_ELEMENTS = [
    "base",
    "basefont",
    "bgsound",
    "link",
    "meta",
    "noframes",
    "noscript",
    "script",
    "style",
    "template",
    "title"
]

RAWTEXT_ELEMENTS = [
    "title",
    "textarea",
    "style",
    "script",
    "xmp",
    "iframe",
    "noembed",
    "noframes",
    "noscript"
]

FORMATTING_ELEMENTS = [
    "a",
    "b",
    "big",
    "code",
    "em",
    "font",
    "i",
    "nobr",
    "s",
    "small",
    "strike",
    "strong",
    "tt",
    "u",
    "cite",
]

BOUNDARY_ELEMENTS = {
    "marquee",
    "object",
    "template",
    "math",
    "svg",
    "table",
    "th",
    "td",
}

HEADING_ELEMENTS = ["h1", "h2", "h3", "h4", "h5", "h6"]

OPTIONAL_END_TAG_ELEMENTS = [
    "li",
    "dt",
    "dd",
    "p",
    "rb",
    "rt",
    "rtc",
    "rp",
    "optgroup",
    "option",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
]

AUTO_CLOSING_TAGS = {
    "p": ["address", "article", "aside", "blockquote", "dl", "dt", "dd",
          "fieldset", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", 
          "header", "hr", "menu", "nav", "ol", "p", "pre", "section", "table", "ul", "li"],
    "li": ["li"],
    "menuitem": [],
    "dt": ["dt", "dd"],
    "dd": ["dt", "dd"],
    "tr": ["tr", "td", "th"],
    "td": ["td", "th"],
    "th": ["td", "th"],
    "rt": ["rt", "rp"],
    "rp": ["rt", "rp"],
    "h1": ["h1", "h2", "h3", "h4", "h5", "h6"],
    "h2": ["h1", "h2", "h3", "h4", "h5", "h6"],
    "h3": ["h1", "h2", "h3", "h4", "h5", "h6"],
    "h4": ["h1", "h2", "h3", "h4", "h5", "h6"],
    "h5": ["h1", "h2", "h3", "h4", "h5", "h6"],
    "h6": ["h1", "h2", "h3", "h4", "h5", "h6"],
}

CLOSE_ON_PARENT_CLOSE = {
    "li": ["ul", "ol", "menu"],
    "dt": ["dl"],
    "dd": ["dl"],
    "rb": ["ruby"],
    "rt": ["ruby", "rtc"],
    "rtc": ["ruby"],
    "rp": ["ruby"],
    "optgroup": ["select"],
    "option": ["select", "optgroup", "datalist"],
    "tr": ["table", "thead", "tbody", "tfoot"],
    "td": ["tr"],
    "th": ["tr"],
}

SVG_CASE_SENSITIVE_ELEMENTS = {
    "foreignobject": "foreignObject",
    "animatemotion": "animateMotion",
    "animatetransform": "animateTransform",
    "clippath": "clipPath",
    "feblend": "feBlend",
    "fecolormatrix": "feColorMatrix",
    "fecomponenttransfer": "feComponentTransfer",
    "fecomposite": "feComposite",
    "feconvolvematrix": "feConvolveMatrix",
    "fediffuselighting": "feDiffuseLighting",
    "fedisplacementmap": "feDisplacementMap",
    "fedistantlight": "feDistantLight",
    "fedropshadow": "feDropShadow",
    "feflood": "feFlood",
    "fefunca": "feFuncA",
    "fefuncb": "feFuncB",
    "fefuncg": "feFuncG",
    "fefuncr": "feFuncR",
    "fegaussianblur": "feGaussianBlur",
    "feimage": "feImage",
    "femergenode": "feMergeNode",
    "femorphology": "feMorphology",
    "feoffset": "feOffset",
    "fepointlight": "fePointLight",
    "fespecularlighting": "feSpecularLighting",
    "fespotlight": "feSpotLight",
    "fetile": "feTile",
    "feturbulence": "feTurbulence",
    "lineargradient": "linearGradient",
    "radialgradient": "radialGradient",
    "textpath": "textPath",
    "altglyph": "altGlyph",
    "altglyphdef": "altGlyphDef",
    "altglyphitem": "altGlyphItem",
    "animatecolor": "animateColor",
    "femerge": "feMerge",
    "glyphref": "glyphRef",
}

# HTML5 Numeric Character Reference Replacements
# Per HTML5 spec section 13.2.5.73, certain codepoints have special replacements
# when found in numeric character references
HTML5_NUMERIC_REPLACEMENTS = {
    0x00: '\uFFFD',  # NULL -> REPLACEMENT CHARACTER
    0x80: '\u20AC',  # 0x80 -> EURO SIGN
    0x81: '\u0081',  # 0x81 -> <control>
    0x82: '\u201A',  # 0x82 -> SINGLE LOW-9 QUOTATION MARK
    0x83: '\u0192',  # 0x83 -> LATIN SMALL LETTER F WITH HOOK
    0x84: '\u201E',  # 0x84 -> DOUBLE LOW-9 QUOTATION MARK
    0x85: '\u2026',  # 0x85 -> HORIZONTAL ELLIPSIS
    0x86: '\u2020',  # 0x86 -> DAGGER
    0x87: '\u2021',  # 0x87 -> DOUBLE DAGGER
    0x88: '\u02C6',  # 0x88 -> MODIFIER LETTER CIRCUMFLEX ACCENT
    0x89: '\u2030',  # 0x89 -> PER MILLE SIGN
    0x8A: '\u0160',  # 0x8A -> LATIN CAPITAL LETTER S WITH CARON
    0x8B: '\u2039',  # 0x8B -> SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    0x8C: '\u0152',  # 0x8C -> LATIN CAPITAL LIGATURE OE
    0x8D: '\u008D',  # 0x8D -> <control>
    0x8E: '\u017D',  # 0x8E -> LATIN CAPITAL LETTER Z WITH CARON
    0x8F: '\u008F',  # 0x8F -> <control>
    0x90: '\u0090',  # 0x90 -> <control>
    0x91: '\u2018',  # 0x91 -> LEFT SINGLE QUOTATION MARK
    0x92: '\u2019',  # 0x92 -> RIGHT SINGLE QUOTATION MARK
    0x93: '\u201C',  # 0x93 -> LEFT DOUBLE QUOTATION MARK
    0x94: '\u201D',  # 0x94 -> RIGHT DOUBLE QUOTATION MARK
    0x95: '\u2022',  # 0x95 -> BULLET
    0x96: '\u2013',  # 0x96 -> EN DASH
    0x97: '\u2014',  # 0x97 -> EM DASH
    0x98: '\u02DC',  # 0x98 -> SMALL TILDE
    0x99: '\u2122',  # 0x99 -> TRADE MARK SIGN
    0x9A: '\u0161',  # 0x9A -> LATIN SMALL LETTER S WITH CARON
    0x9B: '\u203A',  # 0x9B -> SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    0x9C: '\u0153',  # 0x9C -> LATIN SMALL LIGATURE OE
    0x9D: '\u009D',  # 0x9D -> <control>
    0x9E: '\u017E',  # 0x9E -> LATIN SMALL LETTER Z WITH CARON
    0x9F: '\u0178',  # 0x9F -> LATIN CAPITAL LETTER Y WITH DIAERESIS
}
