import re
TAG_OPEN_RE = re.compile(r'<(!?)(/)?([a-zA-Z0-9][-a-zA-Z0-9:]*)(.*?)>')
ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)"|\s*=\s*\'([^\']*)\'|\s*=\s*([^>\s]+)|)(?=\s|$)')
COMMENT_RE = re.compile(r'<!--(.*?)-->')

# HTML Element Sets
VOID_ELEMENTS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr'
}

HTML_ELEMENTS = {
    'b', 'big', 'blockquote', 'body', 'br', 'center', 'code',
    'dd', 'div', 'dl', 'dt', 'em', 'embed', 'h1', 'h2', 'h3', 'h4',
    'h5', 'h6', 'head', 'hr', 'i', 'img', 'li', 'listing',
    'menu', 'meta', 'nobr', 'ol', 'p', 'pre', 's', 'small',
    'span', 'strong', 'strike', 'sub', 'sup', 'table', 'tt',
    'u', 'ul', 'var'
}

SPECIAL_ELEMENTS = {
    'address', 'applet', 'area', 'article', 'aside', 'base', 'basefont',
    'bgsound', 'blockquote', 'body', 'br', 'button', 'caption', 'center',
    'col', 'colgroup', 'dd', 'details', 'dir', 'div', 'dl', 'dt', 'embed',
    'fieldset', 'figcaption', 'figure', 'footer', 'form', 'frame', 'frameset',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'header', 'hgroup', 'hr',
    'html', 'iframe', 'img', 'input', 'keygen', 'li', 'link', 'listing',
    'main', 'marquee', 'menu', 'meta', 'nav', 'noembed', 'noframes',
    'noscript', 'object', 'ol', 'p', 'param', 'plaintext', 'pre', 'script',
    'section', 'select', 'source', 'style', 'summary', 'table', 'tbody',
    'td', 'template', 'textarea', 'tfoot', 'th', 'thead', 'title', 'tr',
    'track', 'ul', 'wbr', 'xmp'
}

BLOCK_ELEMENTS = {
    'address', 'article', 'aside', 'blockquote', 'details', 'dialog', 'dd', 'div',
    'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2',
    'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr', 'li', 'main', 'nav', 'ol',
    'p', 'pre', 'section', 'table', 'ul', 'summary'
}

TABLE_ELEMENTS = {'table', 'tbody', 'thead', 'tfoot', 'tr', 'td', 'th', 'caption', 'colgroup'}

TABLE_CONTAINING_ELEMENTS = {
    'html', 'body', 'div', 'form', 'button', 'ruby', 'td', 'th', 'math', 'svg'
}

# Elements that should be in the head
HEAD_ELEMENTS = {
    'base', 'basefont', 'bgsound', 'link', 'meta', 'title', 'script', 'style', 'template'
}

# Raw text elements (content parsed as raw text)
RAWTEXT_ELEMENTS = {
    'style',
    'script',
    'xmp',
    'iframe',
    'noembed',
    'noframes',
    'title',
    'textarea',
    'noscript'
}

# Elements that can contain both HTML and SVG/MathML content
DUAL_NAMESPACE_ELEMENTS = {
    'title', 'script', 'style'
}

# Elements that can be self-closing
SELF_CLOSING_ELEMENTS = {
    'button', 'a', 'select', 'textarea', 'option', 'optgroup'
}

# Elements that trigger auto-closing of other elements
AUTO_CLOSING_TRIGGERS = {
    'address', 'article', 'aside', 'blockquote', 'details', 'div', 'dl',
    'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'header', 'hr', 'main', 'nav', 'ol', 'p', 'pre',
    'section', 'table', 'ul'
}

# Formatting elements that can be reconstructed
FORMATTING_ELEMENTS = {
    'a', 'b', 'big', 'code', 'em', 'font', 'i', 'nobr', 's',
    'small', 'strike', 'strong', 'tt', 'u'
}

# Elements that define scope boundaries
BOUNDARY_ELEMENTS = {
    'applet', 'button', 'marquee', 'object', 'table', 'td', 'th'
}


# SVG elements that require case-sensitive handling
SVG_CASE_SENSITIVE_ELEMENTS = {
    'foreignobject': 'foreignObject',
    'animatemotion': 'animateMotion',
    'animatetransform': 'animateTransform',
    'clippath': 'clipPath',
    'feblend': 'feBlend',
    'fecolormatrix': 'feColorMatrix',
    'fecomponenttransfer': 'feComponentTransfer',
    'fecomposite': 'feComposite',
    'feconvolvematrix': 'feConvolveMatrix',
    'fediffuselight': 'feDiffuseLighting',
    'fedisplacementmap': 'feDisplacementMap',
    'fedistantlight': 'feDistantLight',
    'fedropshadow': 'feDropShadow',
    'feflood': 'feFlood',
    'fefunca': 'feFuncA',
    'fefuncb': 'feFuncB',
    'fefuncg': 'feFuncG',
    'fefuncr': 'feFuncR',
    'fegaussianblur': 'feGaussianBlur',
    'feimage': 'feImage',
    'femergenode': 'feMergeNode',
    'femorphology': 'feMorphology',
    'feoffset': 'feOffset',
    'fepointlight': 'fePointLight',
    'fespecularlighting': 'feSpecularLighting',
    'fespotlight': 'feSpotLight',
    'fetile': 'feTile',
    'feturbulence': 'feTurbulence',
    'lineargradient': 'linearGradient',
    'radialgradient': 'radialGradient',
    'textpath': 'textPath'
}

# Header elements h1-h6
HEADER_ELEMENTS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

# Elements that auto-close their previous siblings
SIBLING_ELEMENTS = {
    'li',    # List items
    'dt',    # Definition terms
    'dd',    # Definition descriptions
    'tr',    # Table rows
    'th',    # Table headers
    'td',    # Table cells
    'nobr',  # No break
    'button', # Button
    'option', # Select options
    *HEADER_ELEMENTS  # Headers
}
