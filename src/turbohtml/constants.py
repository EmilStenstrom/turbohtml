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
    "font",
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
    "object",
    "ol",
    "p",
    "pre",
    "ruby",
    "s",
    "small",
    "span",
    "strong",
    "strike",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
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
    "button",
    "center",
    "details",
    "dialog",
    "dir",
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
    "isindex",
    "li",
    "listing",
    "main",
    "menu",
    "nav",
    "ol",
    "p",
    "pre",
    "search",
    "section",
    "table",
    "ul",
    "summary",
]

# Elements considered "special" for various tree construction steps (e.g.,
# Adoption Agency Algorithm furthest block calculations). This consolidates the
# previously duplicated sets in adoption.py so that category membership remains
# deterministic and centrally maintained.
SPECIAL_CATEGORY_ELEMENTS = {
    "address",
    "applet",
    "area",
    "article",
    "aside",
    "base",
    "basefont",
    "bgsound",
    "blockquote",
    "body",
    "br",
    "button",
    "caption",
    "center",
    "col",
    "colgroup",
    "dd",
    "details",
    "dir",
    "div",
    "dl",
    "dt",
    "embed",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "frame",
    "frameset",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "head",
    "header",
    "hgroup",
    "hr",
    "html",
    "iframe",
    "img",
    "input",
    "isindex",
    "li",
    "link",
    "listing",
    "main",
    "marquee",
    "menu",
    "meta",
    "nav",
    "noembed",
    "noframes",
    "noscript",
    "object",
    "ol",
    "p",
    "param",
    "plaintext",
    "pre",
    "script",
    "section",
    "select",
    "source",
    "style",
    "summary",
    "table",
    "tbody",
    "td",
    "template",
    "textarea",
    "tfoot",
    "th",
    "thead",
    "title",
    "tr",
    "track",
    "ul",
    "wbr",
    "xmp",
}

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

# Canonical table category constant sets (centralized from table_modes):
# Maintained here so membership logic stays deterministic and not duplicated across modules.
TABLE_SECTION_TAGS = {"tbody", "thead", "tfoot"}
TABLE_ROW_TAGS = {"tr"}
TABLE_CELL_TAGS = {"td", "th"}
TABLE_PRELUDE_TAGS = {"caption", "col", "colgroup"} | TABLE_SECTION_TAGS

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
    "title",
]

# Sentinel used during tokenization to mark invalid numeric character references whose
# resulting replacement character (U+FFFD) must be preserved (entities tests) and not
# stripped by generic replacement-character sanitation. We perform a second-stage
# conversion in parser tree post-processing, replacing occurrences of this sentinel with
# actual U+FFFD while leaving other replacement characters subject to context-specific
# stripping rules.
NUMERIC_ENTITY_INVALID_SENTINEL = "\uf000"  # Private Use Area codepoint unlikely in input

RAWTEXT_ELEMENTS = [
    "title",
    "textarea",
    "style",
    "script",
    "xmp",
    "iframe",
    "noembed",
    "noframes",
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
]

# HTML elements that break out of foreign content (SVG/MathML)
# Per WHATWG HTML5 spec - these are specifically the HTML elements that
# cause a break-out from foreign content context
HTML_BREAK_OUT_ELEMENTS = [
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
    "fieldset",
    "figcaption",
    "figure",
    "font",
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
    "ruby",
    "s",
    "small",
    "span",
    "strong",
    "strike",
    "sub",
    "sup",
    "tt",
    "u",
    "ul",
    "var",
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
    "p": [
        "address",
        "article",
        "aside",
        "blockquote",
        "center",
        "details",
        "dialog",
        "dir",
        "div",
        "dl",
        "dt",
        "dd",
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
        "listing",
        "main",
        "menu",
        "nav",
        "ol",
        "p",
        "pre",
        "search",
        "section",
        "summary",
        "table",
        "ul",
        "li",
        "plaintext",
        "rb",
        "rt",
        "rp",
        "rtc",
    ],
    "li": ["li"],
    "menuitem": [],
    "dt": ["dt", "dd"],
    "dd": ["dt", "dd"],
    "tr": ["tr", "td", "th"],
    "td": ["td", "th"],
    "th": ["td", "th"],
    "rt": ["rt", "rp"],
    "rp": ["rt", "rp"],
    "button": ["button"],
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

# MathML elements that should automatically enter MathML context
MATHML_ELEMENTS = [
    "math",
    "mi",
    "mo",
    "mn",
    "ms",
    "mtext",
    "mspace",
    "merror",
    "mfrac",
    "msup",
    "msub",
    "msubsup",
    "mover",
    "munder",
    "munderover",
    "mmultiscripts",
    "mtable",
    "mtr",
    "mtd",
    "maligngroup",
    "malignmark",
    "mfenced",
    "menclose",
    "mrow",
    "mstyle",
    "msqrt",
    "mroot",
    "mpadded",
    "mphantom",
    "mglyph",
    "annotation-xml",
]

# SVG attributes that should have their case preserved
SVG_CASE_SENSITIVE_ATTRIBUTES = {
    "attributename": "attributeName",
    "attributetype": "attributeType",
    "basefrequency": "baseFrequency",
    "baseprofile": "baseProfile",
    "calcmode": "calcMode",
    "clippathunits": "clipPathUnits",
    "diffuseconstant": "diffuseConstant",
    "edgemode": "edgeMode",
    "filterunits": "filterUnits",
    "glyphref": "glyphRef",
    "gradienttransform": "gradientTransform",
    "gradientunits": "gradientUnits",
    "kernelmatrix": "kernelMatrix",
    "kernelunitlength": "kernelUnitLength",
    "keypoints": "keyPoints",
    "keysplines": "keySplines",
    "keytimes": "keyTimes",
    "lengthadjust": "lengthAdjust",
    "limitingconeangle": "limitingConeAngle",
    "markerheight": "markerHeight",
    "markerunits": "markerUnits",
    "markerwidth": "markerWidth",
    "maskcontentunits": "maskContentUnits",
    "maskunits": "maskUnits",
    "numoctaves": "numOctaves",
    "pathlength": "pathLength",
    "patterncontentunits": "patternContentUnits",
    "patterntransform": "patternTransform",
    "patternunits": "patternUnits",
    "pointsatx": "pointsAtX",
    "pointsaty": "pointsAtY",
    "pointsatz": "pointsAtZ",
    "preservealpha": "preserveAlpha",
    "preserveaspectratio": "preserveAspectRatio",
    "primitiveunits": "primitiveUnits",
    "refx": "refX",
    "refy": "refY",
    "repeatcount": "repeatCount",
    "repeatdur": "repeatDur",
    "requiredextensions": "requiredExtensions",
    "requiredfeatures": "requiredFeatures",
    "specularconstant": "specularConstant",
    "specularexponent": "specularExponent",
    "spreadmethod": "spreadMethod",
    "startoffset": "startOffset",
    "stddeviation": "stdDeviation",
    "stitchtiles": "stitchTiles",
    "surfacescale": "surfaceScale",
    "systemlanguage": "systemLanguage",
    "tablevalues": "tableValues",
    "targetx": "targetX",
    "targety": "targetY",
    "textlength": "textLength",
    "viewbox": "viewBox",
    "viewtarget": "viewTarget",
    "xchannelselector": "xChannelSelector",
    "ychannelselector": "yChannelSelector",
    "zoomandpan": "zoomAndPan",
    # The spec keeps some attributes lowercase; tests expect these untouched
    # contentscripttype, contentstyletype, externalresourcesrequired, filterres remain lowercase
}

# MathML case-sensitive attribute adjustments per HTML5 spec
MATHML_CASE_SENSITIVE_ATTRIBUTES = {
    "definitionurl": "definitionURL",
}

# HTML5 Numeric Character Reference Replacements
# Per HTML5 spec section 13.2.5.73, certain codepoints have special replacements
# when found in numeric character references
HTML5_NUMERIC_REPLACEMENTS = {
    0x00: "\ufffd",  # NULL -> REPLACEMENT CHARACTER
    0x80: "\u20ac",  # 0x80 -> EURO SIGN
    0x81: "\u0081",  # 0x81 -> <control>
    0x82: "\u201a",  # 0x82 -> SINGLE LOW-9 QUOTATION MARK
    0x83: "\u0192",  # 0x83 -> LATIN SMALL LETTER F WITH HOOK
    0x84: "\u201e",  # 0x84 -> DOUBLE LOW-9 QUOTATION MARK
    0x85: "\u2026",  # 0x85 -> HORIZONTAL ELLIPSIS
    0x86: "\u2020",  # 0x86 -> DAGGER
    0x87: "\u2021",  # 0x87 -> DOUBLE DAGGER
    0x88: "\u02c6",  # 0x88 -> MODIFIER LETTER CIRCUMFLEX ACCENT
    0x89: "\u2030",  # 0x89 -> PER MILLE SIGN
    0x8A: "\u0160",  # 0x8A -> LATIN CAPITAL LETTER S WITH CARON
    0x8B: "\u2039",  # 0x8B -> SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    0x8C: "\u0152",  # 0x8C -> LATIN CAPITAL LIGATURE OE
    0x8D: "\u008d",  # 0x8D -> <control>
    0x8E: "\u017d",  # 0x8E -> LATIN CAPITAL LETTER Z WITH CARON
    0x8F: "\u008f",  # 0x8F -> <control>
    0x90: "\u0090",  # 0x90 -> <control>
    0x91: "\u2018",  # 0x91 -> LEFT SINGLE QUOTATION MARK
    0x92: "\u2019",  # 0x92 -> RIGHT SINGLE QUOTATION MARK
    0x93: "\u201c",  # 0x93 -> LEFT DOUBLE QUOTATION MARK
    0x94: "\u201d",  # 0x94 -> RIGHT DOUBLE QUOTATION MARK
    0x95: "\u2022",  # 0x95 -> BULLET
    0x96: "\u2013",  # 0x96 -> EN DASH
    0x97: "\u2014",  # 0x97 -> EM DASH
    0x98: "\u02dc",  # 0x98 -> SMALL TILDE
    0x99: "\u2122",  # 0x99 -> TRADE MARK SIGN
    0x9A: "\u0161",  # 0x9A -> LATIN SMALL LETTER S WITH CARON
    0x9B: "\u203a",  # 0x9B -> SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    0x9C: "\u0153",  # 0x9C -> LATIN SMALL LIGATURE OE
    0x9D: "\u009d",  # 0x9D -> <control>
    0x9E: "\u017e",  # 0x9E -> LATIN SMALL LETTER Z WITH CARON
    0x9F: "\u0178",  # 0x9F -> LATIN CAPITAL LETTER Y WITH DIAERESIS
}
