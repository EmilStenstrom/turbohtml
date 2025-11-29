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


def fuzz_script_escaping():
    """Fuzz script double-escape states - complex script parsing."""
    inner = random_string(1, 20)
    tag = random.choice(["script", "SCRIPT", "ScRiPt"])
    
    variants = [
        # Double escape start: <!--<script>
        f"<script><!--<{tag}>{inner}</script>",
        # Double escaped content with nested script tags  
        f"<script><!--<script><!--{inner}--></script>--></script>",
        # Script with multiple escape sequences
        f"<script><!--<!--{inner}-->--></script>",
        # Escaped dash sequences
        f"<script><!---{inner}---></script>",
        f"<script><!--{inner}--!></script>",
        # Script with null bytes in escape
        f"<script><!--\x00{inner}--></script>",
        # Unclosed comment in script
        f"<script><!--{inner}</script>",
        # Double escape with whitespace variations
        f"<script><!-- <script >{inner}</script> --></script>",
        f"<script><!--<script\t>{inner}</script\n>--></script>",
        # Script ending edge cases
        f"<script>{inner}</SCRIPT>",
        f"<script>{inner}</script >",
        f"<script>{inner}</ script>",
        f"<script>{inner}</script/{random_string(1,5)}>",
    ]
    return random.choice(variants)


def fuzz_integration_points():
    """Fuzz HTML/MathML integration points - complex namespace transitions."""
    content = random_string(1, 10)
    html_tag = random.choice(["div", "span", "p", "table", "tr", "td"])
    
    variants = [
        # annotation-xml with text/html encoding (HTML integration point)
        f"<math><annotation-xml encoding='text/html'><{html_tag}>{content}</{html_tag}></annotation-xml></math>",
        f"<math><annotation-xml encoding='application/xhtml+xml'><{html_tag}>{content}</{html_tag}></annotation-xml></math>",
        # annotation-xml without encoding (NOT an integration point)
        f"<math><annotation-xml><{html_tag}>{content}</{html_tag}></annotation-xml></math>",
        # SVG foreignObject (always integration point)
        f"<svg><foreignObject><{html_tag}>{content}</{html_tag}></foreignObject></svg>",
        # SVG desc/title (integration points)
        f"<svg><desc><{html_tag}>{content}</{html_tag}></desc></svg>",
        f"<svg><title><{html_tag}>{content}</{html_tag}></title></svg>",
        # MathML text integration points (mi, mo, mn, ms, mtext)
        f"<math><mi><{html_tag}>{content}</{html_tag}></mi></math>",
        f"<math><mtext><{html_tag}>{content}</{html_tag}></mtext></math>",
        # Nested integration points
        f"<svg><foreignObject><math><annotation-xml encoding='text/html'><div>{content}</div></annotation-xml></math></foreignObject></svg>",
        # Breakout from foreign content
        f"<svg><{html_tag}>{content}</{html_tag}></svg>",
        f"<math><{html_tag}>{content}</{html_tag}></math>",
        # Table inside integration point
        f"<svg><foreignObject><table><tr><td>{content}</td></tr></table></foreignObject></svg>",
    ]
    return random.choice(variants)


def fuzz_table_scoping():
    """Fuzz table element scoping - complex table parsing rules."""
    content = random_string(1, 10)
    
    variants = [
        # Foster parenting: content directly in table
        f"<table>{content}<tr><td>cell</td></tr></table>",
        f"<table><tbody>{content}<tr><td>cell</td></tr></tbody></table>",
        # Nested tables
        f"<table><tr><td><table><tr><td>{content}</td></tr></table></td></tr></table>",
        # Table with mismatched sections
        f"<table><thead><tr><td>{content}</td></tr></tbody></table>",
        f"<table><tbody></thead><tr><td>{content}</td></tr></table>",
        # Colgroup edge cases
        f"<table><colgroup><col><col></colgroup><colgroup>{content}</colgroup></table>",
        f"<table><colgroup><template>{content}</template></colgroup></table>",
        # Caption edge cases
        f"<table><caption>{content}</caption><caption>second</caption></table>",
        f"<table><tr><td></td></tr><caption>{content}</caption></table>",
        # Table in caption
        f"<table><caption><table><tr><td>{content}</td></tr></table></caption></table>",
        # Missing table structure
        f"<tr><td>{content}</td></tr>",
        f"<td>{content}</td>",
        f"<tbody><tr><td>{content}</td></tr></tbody>",
        # Table end tag edge cases
        f"<table><tr><td>{content}</table></td></tr>",
        f"<table><tr><td>{content}</td></table></tr>",
    ]
    return random.choice(variants)


def fuzz_select_element():
    """Fuzz select element - special parsing mode."""
    content = random_string(1, 10)
    
    variants = [
        # Select with various content
        f"<select><option>{content}</option><optgroup><option>opt</option></optgroup></select>",
        # Select in table (in select in table mode)
        f"<table><tr><td><select><option>{content}</option></select></td></tr></table>",
        # Nested select (should close outer)
        f"<select><option>{content}<select><option>inner</option></select></option></select>",
        # Select with unexpected tags
        f"<select><div>{content}</div></select>",
        f"<select><table><tr><td>{content}</td></tr></table></select>",
        f"<select><script>{content}</script></select>",
        # Select with input (closes select)
        f"<select><option>{content}</option><input></select>",
        f"<select><option>{content}</option><textarea></textarea></select>",
        # Optgroup edge cases
        f"<select><optgroup><optgroup><option>{content}</option></optgroup></optgroup></select>",
        # Select with keygen
        f"<select><option>{content}</option><keygen></select>",
        # Unclosed select
        f"<select><option>{content}",
        f"<div><select><option>{content}</div>",
    ]
    return random.choice(variants)


def fuzz_frameset_mode():
    """Fuzz frameset mode - rarely-used parsing mode."""
    content = random_string(1, 10)
    
    variants = [
        # Basic frameset
        f"<html><head></head><frameset><frame src='a'><frame src='b'></frameset></html>",
        # Nested frameset
        f"<html><frameset><frameset><frame></frameset><frame></frameset></html>",
        # Frameset with noframes
        f"<html><frameset><frame><noframes>{content}</noframes></frameset></html>",
        # Body vs frameset conflict
        f"<html><body>{content}</body><frameset><frame></frameset></html>",
        f"<html><frameset><frame></frameset><body>{content}</body></html>",
        # Content in frameset
        f"<html><frameset>{content}<frame></frameset></html>",
        # Frameset after after frameset mode
        f"<html><frameset><frame></frameset></html>{content}",
        # Invalid elements in frameset
        f"<html><frameset><div>{content}</div><frame></frameset></html>",
        # Frame with attributes
        f"<html><frameset><frame src='{content}' name='f1'></frameset></html>",
        # Deeply nested framesets
        f"<html><frameset><frameset><frameset><frame></frameset></frameset></frameset></html>",
    ]
    return random.choice(variants)


def fuzz_formatting_boundary():
    """Fuzz active formatting elements with markers (applet, object, marquee, etc)."""
    content = random_string(1, 10)
    fmt = random.choice(["b", "i", "em", "strong", "a", "font", "nobr", "s", "u", "code"])
    marker = random.choice(["applet", "object", "marquee", "button"])
    
    variants = [
        # Formatting across marker boundary
        f"<{fmt}><{marker}>{content}</{marker}></{fmt}>",
        f"<{fmt}>{content}<{marker}></{marker}></{fmt}>",
        # Unclosed formatting before marker
        f"<{fmt}><{marker}>{content}</{marker}>",
        f"<{marker}><{fmt}>{content}</{marker}>",
        # Multiple formatting elements with marker
        f"<b><i><{marker}>{content}</{marker}></i></b>",
        f"<b><{marker}><i>{content}</i></{marker}></b>",
        # Nested markers
        f"<{marker}><{marker}>{content}</{marker}></{marker}>",
        # Adoption agency with markers
        f"<{fmt}><div><{marker}><p>{content}</p></{marker}></div></{fmt}>",
        # Table inside marker
        f"<{marker}><table><tr><td><{fmt}>{content}</{fmt}></td></tr></table></{marker}>",
        # Misnested formatting with marker
        f"<{fmt}><{marker}>{content}</{fmt}></{marker}>",
    ]
    return random.choice(variants)


def fuzz_entity_edge_cases():
    """Fuzz HTML entity decoding edge cases."""
    name = random_string(1, 8)
    num = random.randint(0, 0x10FFFF)
    
    variants = [
        # Numeric entities - edge values
        f"&#0;",  # Null
        f"&#x0;",
        f"&#9;",  # Tab
        f"&#10;",  # LF
        f"&#13;",  # CR
        f"&#127;",  # DEL
        f"&#128;",  # Start of Windows-1252 range
        f"&#159;",  # End of Windows-1252 range
        f"&#x80;",
        f"&#x9F;",
        f"&#xD800;",  # Surrogate start
        f"&#xDFFF;",  # Surrogate end
        f"&#xFFFE;",  # Non-character
        f"&#xFFFF;",  # Non-character
        f"&#x10FFFF;",  # Max codepoint
        f"&#x110000;",  # Over max
        f"&#x{num:X};",  # Random codepoint
        f"&#-1;",  # Negative
        f"&#99999999999;",  # Very large
        # Named entities - edge cases
        f"&{name};",  # Random name
        f"&amp",  # Missing semicolon
        f"&amp;amp;",  # Double encoded
        f"&ampamp;",  # Concatenated
        f"&lt&gt",  # Multiple without semicolon
        f"&#x26;amp;",  # Numeric then named
        # Entity in attributes
        f"<div title='&lt;script&gt;'>",
        f"<div title='&#60;script&#62;'>",
        f"<a href='?a=1&b=2'>",  # Ambiguous ampersand
        f"<a href='?a=1&amp;b=2'>",
        # Malformed entities
        f"&;",
        f"&#;",
        f"&#x;",
        f"&#{num};",
        f"&#x{name};",
    ]
    return random.choice(variants)


def fuzz_attribute_states():
    """Fuzz attribute tokenizer states."""
    name = random_string(1, 10)
    value = random_string(1, 20)
    
    # Characters that have special meaning in attribute values
    special = random.choice(['"', "'", '<', '>', '=', '`', '\t', '\n', '\f', ' ', '/', '\x00'])
    
    variants = [
        # Unquoted with special chars
        f"<div {name}={value}{special}>",
        f"<div {name}={special}{value}>",
        # Missing value
        f"<div {name}=>",
        f"<div {name}= >",
        # Equals in attribute name
        f"<div {name}={name}={value}>",
        # Multiple equals
        f"<div {name}=={value}>",
        f"<div {name}==={value}>",
        # Quote mismatches
        f"<div {name}=\"{value}'>",
        f"<div {name}='{value}\">",
        # Unclosed quotes
        f"<div {name}=\"{value}>",
        f"<div {name}='{value}>",
        # Empty attribute variations
        f"<div {name}>",
        f"<div {name}=''>",
        f"<div {name}=\"\">",
        # Attribute after self-closing
        f"<br/{name}={value}>",
        f"<br/ {name}={value}>",
        # Duplicate attributes
        f"<div {name}='{value}' {name}='other'>",
        # Very long attribute name/value
        f"<div {'x'*500}='{value}'>",
        f"<div {name}='{'x'*500}'>",
        # Null in attribute
        f"<div {name}='\x00{value}'>",
        f"<div \x00{name}='{value}'>",
    ]
    return random.choice(variants)


def fuzz_cdata_foreign():
    """Fuzz CDATA sections in foreign content (SVG/MathML)."""
    content = random_string(1, 30)
    
    variants = [
        # CDATA in SVG
        f"<svg><![CDATA[{content}]]></svg>",
        # CDATA in MathML
        f"<math><![CDATA[{content}]]></math>",
        # Nested CDATA-like content
        f"<svg><![CDATA[{content}<![CDATA[nested]]>]]></svg>",
        # CDATA with ]]> inside
        f"<svg><![CDATA[{content}]]>{content}]]></svg>",
        f"<svg><![CDATA[]]>{content}]]></svg>",
        # CDATA with special XML chars
        f"<svg><![CDATA[<>&\"'{content}]]></svg>",
        # Unclosed CDATA
        f"<svg><![CDATA[{content}</svg>",
        # CDATA outside foreign content (bogus comment)
        f"<div><![CDATA[{content}]]></div>",
        # CDATA at different positions
        f"<svg><rect/><![CDATA[{content}]]><circle/></svg>",
        # CDATA with null bytes
        f"<svg><![CDATA[\x00{content}\x00]]></svg>",
        # Empty CDATA
        f"<svg><![CDATA[]]></svg>",
        # CDATA with only brackets
        f"<svg><![CDATA[]]]></svg>",
        f"<svg><![CDATA[[]]]></svg>",
    ]
    return random.choice(variants)


def fuzz_template_nesting():
    """Fuzz deeply nested and complex template usage."""
    content = random_string(1, 10)
    
    variants = [
        # Multiple nested templates
        f"<template><template><template>{content}</template></template></template>",
        # Template with table content
        f"<template><tr><td>{content}</td></tr></template>",
        f"<template><td>{content}</td></template>",
        f"<template><caption>{content}</caption></template>",
        # Template in table
        f"<table><template><tr><td>{content}</td></tr></template></table>",
        f"<table><tr><template><td>{content}</td></template></tr></table>",
        # Template with select
        f"<template><select><option>{content}</option></select></template>",
        # Template with frameset elements
        f"<template><frameset><frame></frameset></template>",
        # Template end tag without start
        f"</template>{content}",
        f"<div></template>{content}</div>",
        # Template with head elements
        f"<template><title>{content}</title><base><link></template>",
        # Mismatched template
        f"<template><div>{content}</template></div>",
        # Template in head
        f"<head><template>{content}</template></head>",
        # Multiple template end tags
        f"<template>{content}</template></template>",
    ]
    return random.choice(variants)


def fuzz_doctype_variations():
    """Fuzz DOCTYPE with various quirks-triggering patterns."""
    name = random_string(1, 10)
    
    variants = [
        # Quirks mode triggers
        f"<!DOCTYPE html PUBLIC \"-//W3C//DTD HTML 4.0 Transitional//EN\">",
        f"<!DOCTYPE html PUBLIC \"-//W3C//DTD HTML 3.2//EN\">",
        f"<!DOCTYPE html SYSTEM \"http://www.ibm.com/data/dtd/v11/ibmxhtml1-transitional.dtd\">",
        # Limited quirks
        f"<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.0 Frameset//EN\">",
        f"<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.0 Transitional//EN\">",
        # Malformed DOCTYPE
        f"<!DOCTYPE>",
        f"<!DOCTYPE >",
        f"<!DOCTYPE\t\n\fhtml>",
        f"<!DOCTYPE html\x00>",
        f"<!DOCTYPE {name}>",
        # DOCTYPE with missing parts
        f"<!DOCTYPE html PUBLIC>",
        f"<!DOCTYPE html PUBLIC \"\">",
        f"<!DOCTYPE html SYSTEM>",
        f"<!DOCTYPE html SYSTEM \"\">",
        # DOCTYPE with extra content
        f"<!DOCTYPE html PUBLIC \"pub\" SYSTEM \"sys\" extra>",
        f"<!DOCTYPE html bogus>",
        # Case variations
        f"<!doctype html>",
        f"<!DoCtYpE html>",
        # DOCTYPE in wrong place
        f"<html><!DOCTYPE html></html>",
        f"<body><!DOCTYPE html></body>",
    ]
    return random.choice(variants)


def fuzz_null_handling():
    """Fuzz NULL byte handling in various contexts."""
    content = random_string(1, 10)
    
    variants = [
        # Null in tag name
        f"<di\x00v>{content}</div>",
        f"<\x00div>{content}</div>",
        # Null in attribute
        f"<div \x00class='a'>{content}</div>",
        f"<div class='\x00a'>{content}</div>",
        f"<div class\x00='a'>{content}</div>",
        # Null in text content
        f"<div>{content}\x00{content}</div>",
        # Null in comment
        f"<!--\x00{content}-->",
        # Null in script
        f"<script>\x00{content}</script>",
        # Null in style
        f"<style>\x00{content}</style>",
        # Null in textarea
        f"<textarea>\x00{content}</textarea>",
        # Null in title
        f"<title>\x00{content}</title>",
        # Null in CDATA
        f"<svg><![CDATA[\x00{content}]]></svg>",
        # Multiple nulls
        f"<div\x00\x00\x00>{content}</div>",
        # Null at EOF
        f"<div>{content}</div>\x00",
    ]
    return random.choice(variants)


def fuzz_whitespace_handling():
    """Fuzz whitespace handling in various contexts."""
    content = random_string(1, 10)
    # Various whitespace characters
    ws = random.choice([' ', '\t', '\n', '\r', '\f', '\r\n', '  ', '\t\t', '\n\n'])
    
    variants = [
        # Whitespace in tag
        f"<{ws}div>{content}</div>",
        f"<div{ws}>{content}</div>",
        f"<div{ws}/>{content}",
        f"</{ws}div>",
        f"</div{ws}>",
        # Whitespace in attribute
        f"<div{ws}class{ws}={ws}'a'{ws}>{content}</div>",
        # Whitespace in DOCTYPE
        f"<!DOCTYPE{ws}html{ws}>",
        # Whitespace in comment
        f"<!{ws}--{content}-->",
        f"<!--{content}--{ws}>",
        # CR/LF normalization
        f"<div>{content}\r\n{content}</div>",
        f"<div>{content}\r{content}</div>",
        f"<pre>\r\n{content}</pre>",
        f"<textarea>\r\n{content}</textarea>",
        # Whitespace in pre (significant)
        f"<pre>   {content}   </pre>",
        f"<pre>\t{content}\t</pre>",
        # Inter-element whitespace
        f"<table>{ws}<tr>{ws}<td>{content}</td>{ws}</tr>{ws}</table>",
    ]
    return random.choice(variants)


def fuzz_eof_handling():
    """Fuzz EOF in various parsing states."""
    content = random_string(1, 10)
    
    variants = [
        # EOF in tag
        f"<div",
        f"<div ",
        f"<div class",
        f"<div class=",
        f"<div class='",
        f"<div class='a",
        f"</div",
        f"</",
        f"<",
        # EOF in comment
        f"<!--",
        f"<!-",
        f"<!--{content}",
        f"<!--{content}-",
        f"<!--{content}--",
        # EOF in DOCTYPE
        f"<!DOCTYPE",
        f"<!DOCTYPE ",
        f"<!DOCTYPE html",
        f"<!DOCTYPE html PUBLIC",
        f"<!DOCTYPE html PUBLIC \"",
        # EOF in script
        f"<script>{content}",
        f"<script><!--{content}",
        # EOF in CDATA
        f"<svg><![CDATA[{content}",
        f"<svg><![CDATA[{content}]",
        f"<svg><![CDATA[{content}]]",
        # EOF in rawtext
        f"<style>{content}",
        f"<textarea>{content}",
        f"<title>{content}",
        # EOF with unclosed elements
        f"<div><span><p>{content}",
        f"<table><tr><td>{content}",
    ]
    return random.choice(variants)


def fuzz_li_dd_dt_nesting():
    """Fuzz li/dd/dt implicit closing rules."""
    content = random_string(1, 10)
    
    variants = [
        # li closes li
        f"<ul><li>{content}<li>{content}</ul>",
        f"<ol><li><li><li>{content}</ol>",
        # li with nested list
        f"<ul><li>{content}<ul><li>nested</ul></li></ul>",
        f"<ul><li>{content}<ul><li>nested</ul><li>after</ul>",
        # dd/dt closing
        f"<dl><dt>{content}<dd>{content}<dt>{content}<dd>{content}</dl>",
        f"<dl><dd><dd><dd>{content}</dl>",
        # dd/dt with nested dl
        f"<dl><dt><dl><dt>nested</dl></dt></dl>",
        # li outside list
        f"<li>{content}</li>",
        f"<div><li>{content}</li></div>",
        # Mixed list types
        f"<ul><li>{content}<ol><li>ordered</ol></ul>",
        # Very nested
        f"<ul><li><ul><li><ul><li>{content}</ul></ul></ul>",
        # li with block content
        f"<ul><li><div>{content}</div><li><p>{content}</p></ul>",
    ]
    return random.choice(variants)


def fuzz_heading_nesting():
    """Fuzz heading element nesting (h1-h6)."""
    content = random_string(1, 10)
    h1 = random.choice(["h1", "h2", "h3", "h4", "h5", "h6"])
    h2 = random.choice(["h1", "h2", "h3", "h4", "h5", "h6"])
    
    variants = [
        # Nested headings (h closes h)
        f"<{h1}>{content}<{h2}>nested</{h2}></{h1}>",
        f"<{h1}><{h2}>{content}</{h1}></{h2}>",
        # Multiple headings
        f"<{h1}>{content}</{h1}><{h2}>{content}</{h2}>",
        # Heading with p
        f"<p>{content}<{h1}>heading</{h1}></p>",
        # Heading with formatting
        f"<{h1}><b>{content}</b></{h1}>",
        f"<b><{h1}>{content}</{h1}></b>",
        # Unclosed heading
        f"<{h1}>{content}",
        f"<div><{h1}>{content}</div>",
        # Heading in unexpected place
        f"<table><tr><td><{h1}>{content}</{h1}></td></tr></table>",
        f"<select><{h1}>{content}</{h1}></select>",
    ]
    return random.choice(variants)


def fuzz_form_nesting():
    """Fuzz form element nesting rules."""
    content = random_string(1, 10)
    
    variants = [
        # Nested forms (inner ignored)
        f"<form><form>{content}</form></form>",
        f"<form><div><form>{content}</form></div></form>",
        # Form in table
        f"<table><form><tr><td>{content}</td></tr></form></table>",
        f"<form><table><tr><td>{content}</td></tr></table></form>",
        # Form with template
        f"<form><template><form>{content}</form></template></form>",
        # Form end without start
        f"</form>{content}",
        f"<div></form>{content}</div>",
        # Form with all input types
        f"<form><input type='text'><input type='submit'><button>{content}</button></form>",
        # Unclosed form
        f"<form>{content}",
        f"<form><div>{content}</div>",
        # Form pointer edge cases
        f"<form><table></table></form>",
        f"<form></form><input>",
    ]
    return random.choice(variants)


def fuzz_ruby_elements():
    """Fuzz ruby element handling (rb, rt, rp, rtc)."""
    content = random_string(1, 10)
    
    variants = [
        # Basic ruby
        f"<ruby>{content}<rt>annotation</rt></ruby>",
        f"<ruby>{content}<rp>(</rp><rt>ann</rt><rp>)</rp></ruby>",
        # Ruby with rb
        f"<ruby><rb>{content}</rb><rt>ann</rt></ruby>",
        # Ruby with rtc
        f"<ruby><rtc><rt>{content}</rt></rtc></ruby>",
        # Implicit closing
        f"<ruby><rt>{content}<rt>second</ruby>",
        f"<ruby><rp>(<rp>another</ruby>",
        # Nested ruby (unusual)
        f"<ruby><ruby>{content}<rt>inner</rt></ruby><rt>outer</rt></ruby>",
        # Ruby elements outside ruby
        f"<rt>{content}</rt>",
        f"<rp>{content}</rp>",
        # Complex ruby
        f"<ruby><rb>{content}</rb><rb>two</rb><rtc><rt>a</rt><rt>b</rt></rtc></ruby>",
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
                # New strategies
                fuzz_script_escaping,
                fuzz_integration_points,
                fuzz_table_scoping,
                fuzz_select_element,
                fuzz_frameset_mode,
                fuzz_formatting_boundary,
                fuzz_entity_edge_cases,
                fuzz_attribute_states,
                fuzz_cdata_foreign,
                fuzz_template_nesting,
                fuzz_doctype_variations,
                fuzz_null_handling,
                fuzz_whitespace_handling,
                fuzz_eof_handling,
                fuzz_li_dd_dt_nesting,
                fuzz_heading_nesting,
                fuzz_form_nesting,
                fuzz_ruby_elements,
            ],
            weights=[
                20, 10, 8, 15, 4, 4, 3, 8, 5, 5, 4, 3, 3, 5, 2, 2, 1, 1, 3, 2,
                # New strategy weights
                4, 4, 5, 4, 2, 4, 5, 4, 3, 3, 2, 4, 3, 4, 3, 2, 3, 2,
            ],
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
