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
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
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

SPECIAL_ELEMENTS = [
    # Root elements
    "html",
    "body",
    "head",
    # Sectioning elements
    "address",
    "article",
    "aside",
    "footer",
    "header",
    "nav",
    "section",
    # Form elements
    "button",
    "fieldset",
    "form",
    "input",
    "keygen",
    "select",
    "textarea",
    # Media elements
    "applet",
    "bgsound",
    "embed",
    "iframe",
    "img",
    "object",
    "param",
    "source",
    "track",
    # Table elements
    "table",
    "tbody",
    "thead",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "colgroup",
    # List elements
    "dd",
    "dir",
    "dl",
    "dt",
    "li",
    "menu",
    "ol",
    "ul",
    # Other block elements
    "blockquote",
    "div",
    "figure",
    "figcaption",
    "hr",
    "main",
    "pre",
    # Script and style elements
    "noembed",
    "noframes",
    "noscript",
    "script",
    "style",
    "template",
    "title",
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
    "li": ["li"],
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
    "address": ["p"],
    "article": ["p"],
    "aside": ["p"],
    "blockquote": ["p"],
    "details": ["p"],
    "div": ["p"],
    "dl": ["p"],
    "fieldset": ["p"],
    "figcaption": ["p"],
    "figure": ["p"],
    "footer": ["p"],
    "form": ["p"],
    "header": ["p"],
    "hr": ["p"],
    "main": ["p"],
    "nav": ["p"],
    "ol": ["p"],
    "pre": ["p"],
    "section": ["p"],
    "table": ["p"],
    "ul": ["p"],
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
