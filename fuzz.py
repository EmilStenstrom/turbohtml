#!/usr/bin/env python3
"""
Random fuzzer for HTML5 parsers.
Generates invalid/malformed HTML to test parser robustness.
"""

import argparse
import random
import string
import sys
import time
import traceback

# Fuzzing strategies
TAGS = [
    "div", "span", "p", "a", "img", "table", "tr", "td", "th", "ul", "ol", "li",
    "form", "input", "button", "select", "option", "textarea", "script", "style",
    "head", "body", "html", "title", "meta", "link", "br", "hr", "h1", "h2", "h3",
    "iframe", "object", "embed", "video", "audio", "source", "canvas", "svg", "math",
    "template", "slot", "noscript", "pre", "code", "blockquote", "article", "section",
    "header", "footer", "nav", "aside", "main", "figure", "figcaption", "details",
    "summary", "dialog", "menu", "menuitem", "frameset", "frame", "noframes",
    "plaintext", "xmp", "listing", "image", "isindex", "nextid", "bgsound", "marquee",
]

# Tags that trigger special parsing modes
RAW_TEXT_TAGS = ["script", "style", "xmp", "iframe", "noembed", "noframes", "noscript"]
RCDATA_TAGS = ["title", "textarea"]
VOID_TAGS = ["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]
FORMATTING_TAGS = ["a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike", "strong", "tt", "u"]
SPECIAL_TAGS = ["address", "applet", "area", "article", "aside", "base", "basefont", "bgsound", "blockquote", "body", "br", "button", "caption", "center", "col", "colgroup", "dd", "details", "dir", "div", "dl", "dt", "embed", "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr", "html", "iframe", "img", "input", "keygen", "li", "link", "listing", "main", "marquee", "menu", "meta", "nav", "noembed", "noframes", "noscript", "object", "ol", "p", "param", "plaintext", "pre", "script", "search", "section", "select", "source", "style", "summary", "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "title", "tr", "track", "ul", "wbr", "xmp"]
TABLE_TAGS = ["table", "tbody", "tfoot", "thead", "tr", "td", "th", "caption", "colgroup", "col"]
ADOPTION_AGENCY_TAGS = ["a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike", "strong", "tt", "u"]

ATTRIBUTES = [
    "id", "class", "style", "href", "src", "alt", "title", "name", "value", "type",
    "onclick", "onload", "onerror", "data-x", "aria-label", "role", "tabindex",
    "disabled", "readonly", "checked", "selected", "hidden", "contenteditable",
]

SPECIAL_CHARS = [
    "\x00", "\x01", "\x0b", "\x0c", "\x0e", "\x0f", "\x7f",  # Control chars
    "\ufffd",  # Replacement character
    "\u0000", "\u000b", "\u000c",  # More control chars
    "\u00a0",  # Non-breaking space
    "\u2028", "\u2029",  # Line/paragraph separators
    "\u200b", "\u200c", "\u200d",  # Zero-width chars
    "\ufeff",  # BOM
]

ENTITIES = [
    "&amp;", "&lt;", "&gt;", "&quot;", "&apos;", "&nbsp;",
    "&", "&amp", "&ampamp;", "&am", "&#", "&#x", "&#123", "&#x1f;",
    "&#xdeadbeef;", "&#99999999;", "&#-1;", "&#x;", "&unknown;",
    "&AMP;", "&AMP", "&LT", "&GT",
    # Edge case entities
    "&#0;", "&#x0;", "&#x0D;", "&#13;",  # Null and CR
    "&#128;", "&#x80;",  # C1 control range start
    "&#159;", "&#x9F;",  # C1 control range end
    "&#xD800;", "&#xDFFF;",  # Surrogate range
    "&#x10FFFF;", "&#x110000;",  # Max and over max codepoint
    "&NotExists;", "&notin;", "&notinva;",  # Real named entities
    "&CounterClockwiseContourIntegral;",  # Long entity name
]


def random_string(min_len=0, max_len=20):
    """Generate random ASCII string."""
    length = random.randint(min_len, max_len)
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def random_whitespace():
    """Generate random whitespace (including weird ones)."""
    ws = [" ", "\t", "\n", "\r", "\f", "\v", "\x0c", "\x00", ""]
    return "".join(random.choices(ws, k=random.randint(0, 5)))


def fuzz_tag_name():
    """Generate malformed tag names."""
    strategies = [
        lambda: random.choice(TAGS),  # Valid tag
        lambda: random.choice(TAGS).upper(),  # Uppercase
        lambda: random.choice(TAGS) + random_string(1, 5),  # Tag with suffix
        lambda: random_string(1, 10),  # Random string
        lambda: "",  # Empty
        lambda: random.choice(SPECIAL_CHARS) + random.choice(TAGS),  # Special prefix
        lambda: random.choice(TAGS) + random.choice(SPECIAL_CHARS),  # Special suffix
        lambda: "0" + random.choice(TAGS),  # Numeric prefix
        lambda: "-" + random.choice(TAGS),  # Dash prefix
        lambda: random.choice(TAGS) + "/" + random.choice(TAGS),  # Slash in name
        lambda: " " + random.choice(TAGS),  # Space prefix
        lambda: random.choice(TAGS) + "\x00",  # Null in name
    ]
    return random.choice(strategies)()


def fuzz_attribute():
    """Generate malformed attributes."""
    name_strategies = [
        lambda: random.choice(ATTRIBUTES),
        lambda: random_string(1, 15),
        lambda: "",
        lambda: "on" + random_string(2, 8),  # Event handler
        lambda: random.choice(SPECIAL_CHARS),
        lambda: "=",
        lambda: '"',
        lambda: "'",
        lambda: "<",
        lambda: ">",
    ]
    
    value_strategies = [
        lambda: random_string(0, 50),
        lambda: '"' + random_string() + '"',  # Extra quotes
        lambda: "'" + random_string() + "'",
        lambda: random.choice(ENTITIES),
        lambda: "<script>alert(1)</script>",
        lambda: "javascript:alert(1)",
        lambda: random.choice(SPECIAL_CHARS) * random.randint(1, 10),
        lambda: "\n" * random.randint(1, 5) + random_string(),
        lambda: "",
        lambda: "x" * random.randint(100, 1000),  # Long value
    ]
    
    quote_styles = [
        ('="', '"'),
        ("='", "'"),
        ("=", ""),  # Unquoted
        ("= ", ""),  # Space after equals
        ("", ""),  # No value
        ('="', ""),  # Unclosed quote
        ("='", ""),  # Unclosed single quote
        ("==", ""),  # Double equals
    ]
    
    name = random.choice(name_strategies)()
    value = random.choice(value_strategies)()
    quote_start, quote_end = random.choice(quote_styles)
    
    return f"{name}{quote_start}{value}{quote_end}"


def fuzz_open_tag():
    """Generate malformed opening tags."""
    tag = fuzz_tag_name()
    ws1 = random_whitespace()
    
    # Random number of attributes
    attrs = [fuzz_attribute() for _ in range(random.randint(0, 5))]
    attr_str = " ".join(attrs)
    
    ws2 = random_whitespace()
    
    closings = [">", "/>", " >", "/ >", "", ">>", ">>>", "/>>", ">/", "\x00>"]
    closing = random.choice(closings)
    
    # Sometimes corrupt the opening
    openings = ["<", "< ", "<\x00", "<<", "<!!", "<!", "<?", "</"]
    opening = random.choice(openings) if random.random() < 0.2 else "<"
    
    return f"{opening}{tag}{ws1}{attr_str}{ws2}{closing}"


def fuzz_close_tag():
    """Generate malformed closing tags."""
    tag = fuzz_tag_name()
    ws = random_whitespace()
    
    variants = [
        f"</{tag}>",
        f"</ {tag}>",
        f"</{tag} >",
        f"</{tag}{ws}>",
        f"</{tag}",  # Unclosed
        f"</{tag}/>",  # Self-closing end tag
        f"<//{tag}>",  # Double slash
        f"</{tag} garbage>",  # Extra content
        f"</ {tag} {fuzz_attribute()}>",  # Attribute in end tag
        f"</{tag}\x00>",  # Null byte
    ]
    return random.choice(variants)


def fuzz_comment():
    """Generate malformed comments."""
    content = random_string(0, 50)
    
    variants = [
        f"<!--{content}-->",
        f"<!-{content}-->",
        f"<!--{content}->",
        f"<!--{content}",
        f"<!---{content}--->",
        f"<!--{content}--!>",
        f"<!---->",
        f"<!-->",
        f"<!--->",
        f"<!--{content}---->{content}-->",
        f"<!--{content}--{content}-->",
        f"<! --{content}-->",
        f"<!--{content}>",
        f"<!{content}>",
    ]
    return random.choice(variants)


def fuzz_doctype():
    """Generate malformed doctypes."""
    variants = [
        "<!DOCTYPE html>",
        "<!doctype html>",
        "<!DOCTYPE>",
        "<!DOCTYPE html PUBLIC>",
        "<!DOCTYPE html SYSTEM>",
        "<!DOCTYPE html PUBLIC \"\" \"\">",
        "<!DOCTYPE " + random_string() + ">",
        "<!DOCTYPE html " + random_string(10, 50) + ">",
        "<!DOCTYPE",
        "<! DOCTYPE html>",
        "<!DOCTYPEhtml>",
        "<!DOCTYPE\x00html>",
    ]
    return random.choice(variants)


def fuzz_cdata():
    """Generate malformed CDATA sections."""
    content = random_string(0, 30)
    variants = [
        f"<![CDATA[{content}]]>",
        f"<![CDATA[{content}",
        f"<![CDATA[{content}]>",
        f"<![CDATA[{content}]]",
        f"<![CDATA[]]>",
        f"<![CDATA{content}]]>",
        f"<![ CDATA[{content}]]>",
        f"<![cdata[{content}]]>",
    ]
    return random.choice(variants)


def fuzz_script():
    """Generate malformed script content."""
    content = random_string(0, 30)
    variants = [
        f"<script>{content}</script>",
        f"<script>{content}",
        f"<script>{content}</script",
        f"<script>{content}</scrip>",
        f"<script><!--{content}--></script>",
        f"<script><!--{content}</script>",
        f"<script>{content}</script >{content}</script>",
        f"<script>{content}<script>{content}</script>",
        f"<script>{content}</SCRIPT>",
        f"<script type='text/javascript'>{content}</script>",
        f"<script>{content}<!-- </script> -->{content}</script>",
        f"<script>//<![CDATA[\n{content}\n//]]></script>",
    ]
    return random.choice(variants)


def fuzz_style():
    """Generate malformed style content."""
    content = random_string(0, 30)
    variants = [
        f"<style>{content}</style>",
        f"<style>{content}",
        f"<style>{content}</styl>",
        f"<style><!--{content}--></style>",
        f"<style>{content}</style >{content}</style>",
        f"<style>{content}</STYLE>",
    ]
    return random.choice(variants)


def fuzz_text():
    """Generate text content with edge cases."""
    strategies = [
        lambda: random_string(1, 50),
        lambda: random.choice(ENTITIES),
        lambda: "".join(random.choices(SPECIAL_CHARS, k=random.randint(1, 10))),
        lambda: "<" + random_string(1, 5),  # Incomplete tag
        lambda: "&" + random_string(1, 10),  # Incomplete entity
        lambda: random_string() + ">" + random_string(),  # Stray >
        lambda: "\x00" * random.randint(1, 5),  # Null bytes
        lambda: "\r\n" * random.randint(1, 5),  # Line endings
        lambda: " " * random.randint(10, 100),  # Lots of spaces
    ]
    return random.choice(strategies)()


def fuzz_nested_structure(depth=0, max_depth=10):
    """Generate nested (possibly invalid) structure."""
    if depth >= max_depth or random.random() < 0.3:
        return fuzz_text()
    
    tag = random.choice(TAGS)
    children = [fuzz_nested_structure(depth + 1, max_depth) for _ in range(random.randint(0, 3))]
    content = "".join(children)
    
    # Sometimes don't close tags
    if random.random() < 0.2:
        return f"<{tag}>{content}"
    # Sometimes mismatch tags
    if random.random() < 0.1:
        other_tag = random.choice(TAGS)
        return f"<{tag}>{content}</{other_tag}>"
    
    return f"<{tag}>{content}</{tag}>"


def fuzz_adoption_agency():
    """
    Generate HTML that triggers the adoption agency algorithm.
    This is one of the most complex parts of the HTML5 spec.
    """
    formatting = random.choice(ADOPTION_AGENCY_TAGS)
    other_formatting = random.choice(ADOPTION_AGENCY_TAGS)
    block = random.choice(["div", "p", "blockquote", "article", "section"])
    
    variants = [
        # Classic misnested formatting
        f"<{formatting}>text<{block}>more</{formatting}>content</{block}>",
        # Multiple formatting tags misnested
        f"<{formatting}><{other_formatting}><{block}></{formatting}></{other_formatting}></{block}>",
        # Deep nesting with misnesting
        f"<{formatting}>" * 10 + "text" + f"</{formatting}>" * 5 + f"<{block}></{block}>" + f"</{formatting}>" * 5,
        # Adoption with text nodes
        f"<{formatting}>before<{block}>inside</{formatting}>after</{block}>trailing",
        # Multiple blocks
        f"<{formatting}><{block}>1</{formatting}><{block}>2</{formatting}><{block}>3</{formatting}>",
        # Nested same formatting
        f"<{formatting}><{formatting}><{formatting}>deep</{formatting}></{formatting}></{formatting}>",
        # Interleaved formatting
        f"<a><b><a><b>text</b></a></b></a>",
        f"<b><i><b><i>text</i></b></i></b>",
        # AAA with table
        f"<{formatting}><table><tr><td></{formatting}></td></tr></table>",
        # AAA with form
        f"<{formatting}><form></{formatting}></form>",
        # Bookmark splitting
        f"<{formatting} id='x'>before<{block}>inside</{formatting}>after</{block}>",
    ]
    return random.choice(variants)


def fuzz_foster_parenting():
    """
    Generate HTML that triggers foster parenting.
    Foster parenting happens when content appears in invalid table positions.
    """
    text = random_string(1, 10)
    
    variants = [
        # Text directly in table
        f"<table>{text}<tr><td>cell</td></tr></table>",
        # Text between table elements
        f"<table><tr>{text}<td>cell</td></tr></table>",
        f"<table><tbody>{text}<tr><td>cell</td></tr></tbody></table>",
        # Elements in wrong places
        f"<table><div>foster me</div><tr><td>cell</td></tr></table>",
        f"<table><tr><div>foster</div><td>cell</td></tr></table>",
        # Deeply nested foster parenting
        f"<table><tbody><tr><table><tr>{text}<td>deep</td></tr></table></tr></tbody></table>",
        # Script in table (should foster)
        f"<table><script>var x=1;</script><tr><td>cell</td></tr></table>",
        # Multiple foster children
        f"<table>text1<span>span</span>text2<tr><td>cell</td></tr>text3</table>",
        # Form in table
        f"<table><form><tr><td><input></td></tr></form></table>",
        # Caption edge cases
        f"<table><caption>{text}<table><tr><td>nested</td></tr></table></caption></table>",
        # Colgroup edge cases  
        f"<table><colgroup>{text}<col></colgroup><tr><td>cell</td></tr></table>",
    ]
    return random.choice(variants)


def fuzz_raw_text():
    """
    Generate malformed raw text elements (script, style, etc.).
    These have special parsing rules.
    """
    tag = random.choice(RAW_TEXT_TAGS)
    content = random_string(0, 50)
    
    variants = [
        # Normal
        f"<{tag}>{content}</{tag}>",
        # Fake end tags
        f"<{tag}>{content}</{tag[:-1]}>{content}</{tag}>",
        f"<{tag}>{content}</ {tag}>{content}</{tag}>",
        # Escape sequences in script
        f"<script>var s = '</' + 'script>';</script>",
        f"<script>var s = '<\\/script>';</script>",
        f"<script>var s = '<!--<script>';</script>",
        # Comment-like content
        f"<{tag}><!--{content}--></{tag}>",
        f"<{tag}><!-- </{tag}> --></{tag}>",
        # CDATA-like content
        f"<{tag}>//<![CDATA[\n{content}\n//]]></{tag}>",
        # Null bytes in content
        f"<{tag}>{content}\x00{content}</{tag}>",
        # Very long content
        f"<{tag}>{'x' * 10000}</{tag}>",
        # Nested looking (but not actually)
        f"<script><script>{content}</script></script>",
        # Attributes on end tag (invalid)
        f"<{tag}>{content}</{tag} attr='value'>",
        # Case variations
        f"<SCRIPT>{content}</script>",
        f"<script>{content}</SCRIPT>",
        f"<ScRiPt>{content}</sCrIpT>",
    ]
    return random.choice(variants)


def fuzz_rcdata():
    """
    Generate malformed RCDATA elements (title, textarea).
    These decode entities but don't recognize tags.
    """
    tag = random.choice(RCDATA_TAGS)
    content = random_string(0, 30)
    entity = random.choice(ENTITIES)
    
    variants = [
        f"<{tag}>{content}</{tag}>",
        f"<{tag}>{entity}</{tag}>",
        f"<{tag}><b>{content}</b></{tag}>",  # Tags should be literal
        f"<{tag}></{tag[:-1]}></{tag}>",  # Fake end tag
        f"<{tag}>{content}\x00{content}</{tag}>",  # Null byte
        f"<{tag}>{'&amp;' * 100}</{tag}>",  # Many entities
        f"<{tag}></{tag}>",  # Empty
        f"<{tag}>{content}",  # Unclosed
        f"<TITLE>{content}</title>",  # Case mismatch
        f"<textarea>{content}</TEXTAREA>",
    ]
    return random.choice(variants)


def fuzz_template():
    """
    Generate malformed template elements.
    Templates have their own document fragment.
    """
    content = random_string(0, 20)
    
    variants = [
        f"<template>{content}</template>",
        f"<template><tr><td>{content}</td></tr></template>",  # Table content
        f"<template><template>{content}</template></template>",  # Nested
        f"<template><script>{content}</script></template>",
        f"<template>{content}",  # Unclosed
        f"<table><template><tr><td>cell</td></tr></template></table>",
        f"<template><col></template>",  # Colgroup content
        f"<template><caption>{content}</caption></template>",
        f"<template><html><head></head><body></body></html></template>",
        # Shadow DOM-like
        f"<div><template shadowroot='open'>{content}</template></div>",
    ]
    return random.choice(variants)


def fuzz_svg_math():
    """
    Generate malformed SVG and MathML (foreign content).
    These have different parsing rules.
    """
    content = random_string(0, 20)
    
    variants = [
        # Basic SVG
        f"<svg>{content}</svg>",
        f"<svg><rect width='100' height='100'/></svg>",
        # SVG with HTML integration point
        f"<svg><foreignObject><div>{content}</div></foreignObject></svg>",
        f"<svg><desc><div>{content}</div></desc></svg>",
        f"<svg><title><div>{content}</div></title></svg>",
        # Case sensitivity in SVG
        f"<svg><clipPath><circle/></clipPath></svg>",
        f"<svg viewBox='0 0 100 100'><path d='M0 0'/></svg>",
        # Malformed SVG
        f"<svg><div>{content}</div></svg>",  # HTML in SVG
        f"<svg><svg>{content}</svg></svg>",  # Nested SVG
        f"<svg><script>{content}</script></svg>",
        # Basic MathML
        f"<math>{content}</math>",
        f"<math><mi>x</mi><mo>=</mo><mn>1</mn></math>",
        # MathML integration point
        f"<math><annotation-xml encoding='text/html'><div>{content}</div></annotation-xml></math>",
        f"<math><ms><div>{content}</div></ms></math>",
        # Malformed MathML
        f"<math><div>{content}</div></math>",
        # Switching namespaces
        f"<svg><math>{content}</math></svg>",
        f"<math><svg>{content}</svg></math>",
        # Breakout from foreign content
        f"<svg><p>{content}</p></svg>",
        f"<math><p>{content}</p></math>",
        f"<svg><table><tr><td>{content}</td></tr></table></svg>",
    ]
    return random.choice(variants)


def fuzz_processing_instruction():
    """Generate processing instructions (XML-style)."""
    content = random_string(0, 20)
    
    variants = [
        f"<?xml version='1.0'?>",
        f"<?xml version='1.0' encoding='UTF-8'?>",
        f"<?{content}?>",
        f"<? {content} ?>",
        f"<?xml {content}?>",
        f"<?xml?>",
        f"<??>",
        f"<?{content}",  # Unclosed
        f"<?xml version='1.0'?><html></html>",
        f"<html><?xml version='1.0'?></html>",
    ]
    return random.choice(variants)


def fuzz_encoding_edge_cases():
    """Generate edge cases related to character encoding."""
    content = random_string(0, 20)
    
    variants = [
        # BOM at start
        f"\ufeff<html>{content}</html>",
        # BOM in middle (should be ZWNBSP)
        f"<html>{content}\ufeff{content}</html>",
        # Null bytes
        f"\x00<html>{content}</html>",
        f"<html>\x00{content}</html>",
        f"<html {content}='\x00'>",
        # High bytes
        f"<html>{content}\xff{content}</html>",
        # UTF-8 overlong sequences would be handled by Python's decoder
        # Various line endings
        f"<html>\r{content}\r\n{content}\n</html>",
        f"<html>\r\r\n\n{content}</html>",
        # Form feed
        f"<html>\f{content}\f</html>",
        # Vertical tab
        f"<html>\v{content}\v</html>",
        # Meta charset
        f"<html><head><meta charset='utf-8'></head><body>{content}</body></html>",
        f"<html><head><meta http-equiv='Content-Type' content='text/html; charset=utf-8'></head></html>",
    ]
    return random.choice(variants)


def fuzz_deeply_nested():
    """Generate very deeply nested structures."""
    depth = random.randint(100, 500)
    tag = random.choice(["div", "span", "b", "i", "a"])
    
    variants = [
        # Deep nesting same tag
        f"<{tag}>" * depth + "content" + f"</{tag}>" * depth,
        # Deep nesting mixed tags
        "".join(f"<{random.choice(['div', 'span', 'p'])}>" for _ in range(depth)) + "x",
        # Deep nesting with unclosed
        f"<{tag}>" * depth + "content" + f"</{tag}>" * (depth // 2),
        # Deep formatting (triggers AAA limits)
        "<b>" * depth + "text" + "</b>" * depth,
        "<a>" * depth + "text" + "</a>" * depth,
    ]
    return random.choice(variants)


def fuzz_many_attributes():
    """Generate elements with many/large attributes."""
    num_attrs = random.randint(100, 500)
    tag = random.choice(TAGS)
    
    variants = [
        # Many attributes
        f"<{tag} " + " ".join(f"attr{i}='value{i}'" for i in range(num_attrs)) + ">",
        # Duplicate attributes
        f"<{tag} " + " ".join(f"id='id{i}'" for i in range(100)) + ">",
        # Very long attribute value
        f"<{tag} data-x='{'x' * 100000}'>",
        # Very long attribute name
        f"<{tag} {'x' * 10000}='value'>",
        # Many class names
        f"<{tag} class='" + " ".join(f"class{i}" for i in range(1000)) + "'>",
    ]
    return random.choice(variants)


def fuzz_implicit_tags():
    """Generate HTML that relies on implicit tag opening/closing."""
    content = random_string(1, 10)
    
    variants = [
        # No html/head/body
        f"<title>{content}</title><p>{content}</p>",
        # Just text
        content,
        # Just body content
        f"<p>{content}</p>",
        # Head content after body content
        f"<p>{content}</p><title>{content}</title>",
        # Implicit p closing
        f"<p>{content}<p>{content}<p>{content}",
        # Implicit li closing
        f"<ul><li>{content}<li>{content}<li>{content}</ul>",
        # Implicit dt/dd closing
        f"<dl><dt>{content}<dd>{content}<dt>{content}<dd>{content}</dl>",
        # Implicit tr/td closing
        f"<table><tr><td>{content}<td>{content}<tr><td>{content}</table>",
        # Implicit option closing
        f"<select><option>{content}<option>{content}</select>",
        # Implicit colgroup
        f"<table><col><tr><td>{content}</td></tr></table>",
        # Body implicitly closed by EOF
        f"<html><body>{content}",
    ]
    return random.choice(variants)


def fuzz_document_structure():
    """Generate malformed document structure."""
    content = random_string(1, 10)
    
    variants = [
        # Multiple html tags
        f"<html><html>{content}</html></html>",
        # Multiple head tags
        f"<html><head></head><head></head><body></body></html>",
        # Multiple body tags
        f"<html><body></body><body></body></html>",
        # Head after body
        f"<html><body></body><head></head></html>",
        # Content before html
        f"{content}<html><body></body></html>",
        # Content after html
        f"<html><body></body></html>{content}",
        # Frameset vs body
        f"<html><frameset><frame></frameset><body></body></html>",
        f"<html><body></body><frameset><frame></frameset></html>",
        # DOCTYPE after content
        f"<html><!DOCTYPE html></html>",
        # Multiple DOCTYPEs
        f"<!DOCTYPE html><!DOCTYPE html><html></html>",
    ]
    return random.choice(variants)


def generate_fuzzed_html():
    """Generate a complete fuzzed HTML document."""
    parts = []
    
    # Maybe add doctype
    if random.random() < 0.5:
        parts.append(fuzz_doctype())
    
    # Generate random mix of elements
    num_elements = random.randint(1, 20)
    for _ in range(num_elements):
        element_type = random.choices(
            [
                fuzz_open_tag,
                fuzz_close_tag,
                fuzz_comment,
                fuzz_text,
                fuzz_script,
                fuzz_style,
                fuzz_cdata,
                fuzz_nested_structure,
                fuzz_adoption_agency,
                fuzz_foster_parenting,
                fuzz_raw_text,
                fuzz_rcdata,
                fuzz_template,
                fuzz_svg_math,
                fuzz_processing_instruction,
                fuzz_encoding_edge_cases,
                fuzz_deeply_nested,
                fuzz_many_attributes,
                fuzz_implicit_tags,
                fuzz_document_structure,
            ],
            weights=[20, 10, 8, 15, 4, 4, 3, 8, 5, 5, 4, 3, 3, 5, 2, 2, 1, 1, 3, 2],
        )[0]
        parts.append(element_type())
    
    return "".join(parts)


def run_fuzzer(parser_name, num_tests, seed=None, verbose=False, save_failures=False):
    """Run the fuzzer against a parser."""
    if seed is not None:
        random.seed(seed)
    
    if parser_name == "turbohtml":
        from turbohtml import TurboHTML
        parse_fn = lambda html: TurboHTML(html)
    elif parser_name == "html5lib":
        import html5lib
        parse_fn = lambda html: html5lib.parse(html)
    elif parser_name == "lxml":
        from lxml import html as lxml_html
        parse_fn = lambda html: lxml_html.fromstring(html)
    elif parser_name == "bs4":
        from bs4 import BeautifulSoup
        parse_fn = lambda html: BeautifulSoup(html, "html.parser")
    else:
        print(f"Unknown parser: {parser_name}")
        sys.exit(1)
    
    crashes = []
    hangs = []
    successes = 0
    
    print(f"Fuzzing {parser_name} with {num_tests} test cases...")
    start_time = time.time()
    
    for i in range(num_tests):
        html = generate_fuzzed_html()
        
        if verbose and i % 100 == 0:
            print(f"  Test {i}/{num_tests}...")
        
        try:
            start = time.perf_counter()
            result = parse_fn(html)
            elapsed = time.perf_counter() - start
            
            # Check for hangs (>5 seconds)
            if elapsed > 5.0:
                hangs.append({
                    "test_num": i,
                    "html": html,
                    "time": elapsed,
                })
                if verbose:
                    print(f"  HANG: Test {i} took {elapsed:.2f}s")
            else:
                successes += 1
                
            # Access result to ensure full parsing
            _ = result
            
        except Exception as e:
            crashes.append({
                "test_num": i,
                "html": html,
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
            if verbose:
                print(f"  CRASH: Test {i}: {e}")
    
    elapsed_total = time.time() - start_time
    
    # Report results
    print(f"\n{'='*60}")
    print(f"FUZZING RESULTS: {parser_name}")
    print(f"{'='*60}")
    print(f"Total tests:    {num_tests}")
    print(f"Successes:      {successes}")
    print(f"Crashes:        {len(crashes)}")
    print(f"Hangs (>5s):    {len(hangs)}")
    print(f"Total time:     {elapsed_total:.2f}s")
    print(f"Tests/second:   {num_tests/elapsed_total:.1f}")
    
    if crashes:
        print(f"\n{'='*60}")
        print("CRASH DETAILS:")
        print(f"{'='*60}")
        for crash in crashes[:10]:  # Show first 10
            print(f"\nTest #{crash['test_num']}:")
            print(f"  HTML: {crash['html'][:200]!r}...")
            print(f"  Error: {crash['error']}")
        if len(crashes) > 10:
            print(f"\n... and {len(crashes) - 10} more crashes")
    
    if hangs:
        print(f"\n{'='*60}")
        print("HANG DETAILS:")
        print(f"{'='*60}")
        for hang in hangs[:5]:
            print(f"\nTest #{hang['test_num']} ({hang['time']:.2f}s):")
            print(f"  HTML: {hang['html'][:200]!r}...")
    
    if save_failures and (crashes or hangs):
        filename = f"fuzz_failures_{parser_name}_{int(time.time())}.txt"
        with open(filename, "w") as f:
            f.write(f"Fuzzing results for {parser_name}\n")
            f.write(f"Seed: {seed}\n\n")
            for crash in crashes:
                f.write(f"=== CRASH #{crash['test_num']} ===\n")
                f.write(f"HTML:\n{crash['html']}\n")
                f.write(f"Error: {crash['error']}\n")
                f.write(f"Traceback:\n{crash['traceback']}\n\n")
            for hang in hangs:
                f.write(f"=== HANG #{hang['test_num']} ({hang['time']:.2f}s) ===\n")
                f.write(f"HTML:\n{hang['html']}\n\n")
        print(f"\nFailures saved to {filename}")
    
    return len(crashes) == 0 and len(hangs) == 0


def main():
    parser = argparse.ArgumentParser(description="Fuzz HTML5 parsers with invalid input")
    parser.add_argument(
        "--parser", "-p",
        choices=["turbohtml", "html5lib", "lxml", "bs4"],
        default="turbohtml",
        help="Parser to fuzz (default: turbohtml)",
    )
    parser.add_argument(
        "--num-tests", "-n",
        type=int,
        default=1000,
        help="Number of test cases to generate (default: 1000)",
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--save-failures",
        action="store_true",
        help="Save failures to a file",
    )
    parser.add_argument(
        "--sample",
        type=int,
        metavar="N",
        help="Just print N sample fuzzed HTML documents (no parsing)",
    )
    
    args = parser.parse_args()
    
    if args.sample:
        if args.seed:
            random.seed(args.seed)
        for i in range(args.sample):
            print(f"=== Sample {i+1} ===")
            print(generate_fuzzed_html())
            print()
        return
    
    success = run_fuzzer(
        args.parser,
        args.num_tests,
        seed=args.seed,
        verbose=args.verbose,
        save_failures=args.save_failures,
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
