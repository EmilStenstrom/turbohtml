[← Back to docs](index.md)

# Error Codes

Parse errors that JustHTML can detect and report.

## Collecting Errors

By default, JustHTML silently recovers from errors (like browsers do). To collect errors:

```python
from justhtml import JustHTML

doc = JustHTML("<p>Hello", collect_errors=True)
for error in doc.errors:
    print(f"{error.line}:{error.column} - {error.code}")
```

## Strict Mode

To reject malformed HTML entirely:

```python
from justhtml import JustHTML, StrictModeError

try:
    doc = JustHTML("<p>Hello", strict=True)
except StrictModeError as e:
    print(e)  # Shows source location
```

---

## Tokenizer Errors

Errors detected during tokenization (lexical analysis).

### DOCTYPE Errors

| Code | Description |
|------|-------------|
| `eof-in-doctype` | Unexpected end of file in DOCTYPE declaration |
| `missing-whitespace-before-doctype-name` | Missing whitespace after `<!DOCTYPE` |
| `abrupt-doctype-public-identifier` | DOCTYPE public identifier ended abruptly |
| `abrupt-doctype-system-identifier` | DOCTYPE system identifier ended abruptly |
| `missing-quote-before-doctype-public-identifier` | Missing quote before DOCTYPE public identifier |
| `missing-quote-before-doctype-system-identifier` | Missing quote before DOCTYPE system identifier |
| `missing-doctype-public-identifier` | Missing DOCTYPE public identifier |
| `missing-doctype-system-identifier` | Missing DOCTYPE system identifier |

### Comment Errors

| Code | Description |
|------|-------------|
| `eof-in-comment` | Unexpected end of file in comment |
| `abrupt-closing-of-empty-comment` | Comment ended abruptly with `-->` |
| `incorrectly-closed-comment` | Comment ended with `--!>` instead of `-->` |
| `incorrectly-opened-comment` | Incorrectly opened comment |

### Tag Errors

| Code | Description |
|------|-------------|
| `eof-in-tag` | Unexpected end of file in tag |
| `eof-before-tag-name` | Unexpected end of file before tag name |
| `empty-end-tag` | Empty end tag `</>` is not allowed |
| `invalid-first-character-of-tag-name` | Invalid first character of tag name |
| `unexpected-question-mark-instead-of-tag-name` | Unexpected `?` instead of tag name |
| `unexpected-character-after-solidus-in-tag` | Unexpected character after `/` in tag |

### Attribute Errors

| Code | Description |
|------|-------------|
| `duplicate-attribute` | Duplicate attribute name |
| `missing-attribute-value` | Missing attribute value |
| `unexpected-character-in-attribute-name` | Unexpected character in attribute name |
| `unexpected-character-in-unquoted-attribute-value` | Unexpected character in unquoted attribute value |
| `missing-whitespace-between-attributes` | Missing whitespace between attributes |
| `unexpected-equals-sign-before-attribute-name` | Unexpected `=` before attribute name |

### Script Errors

| Code | Description |
|------|-------------|
| `eof-in-script-html-comment-like-text` | Unexpected end of file in script with HTML-like comment |
| `eof-in-script-in-script` | Unexpected end of file in nested script tag |

### CDATA Errors

| Code | Description |
|------|-------------|
| `eof-in-cdata` | Unexpected end of file in CDATA section |
| `cdata-in-html-content` | CDATA section only allowed in SVG/MathML content |

### Character Reference Errors

| Code | Description |
|------|-------------|
| `control-character-reference` | Invalid control character in character reference |
| `illegal-codepoint-for-numeric-entity` | Invalid codepoint in numeric character reference |
| `missing-semicolon-after-character-reference` | Missing semicolon after character reference |
| `named-entity-without-semicolon` | Named entity used without semicolon |

### Other Tokenizer Errors

| Code | Description |
|------|-------------|
| `unexpected-null-character` | Unexpected NULL character (U+0000) |

---

## Tree Builder Errors

Errors detected during tree construction.

### DOCTYPE Errors

| Code | Description |
|------|-------------|
| `unexpected-doctype` | Unexpected DOCTYPE declaration |
| `unknown-doctype` | Unknown DOCTYPE (expected `<!DOCTYPE html>`) |
| `expected-doctype-but-got-chars` | Expected DOCTYPE but got text content |
| `expected-doctype-but-got-eof` | Expected DOCTYPE but reached end of file |
| `expected-doctype-but-got-start-tag` | Expected DOCTYPE but got start tag |
| `expected-doctype-but-got-end-tag` | Expected DOCTYPE but got end tag |

### Unexpected Tag Errors

| Code | Description |
|------|-------------|
| `unexpected-start-tag` | Unexpected start tag in current context |
| `unexpected-end-tag` | Unexpected end tag in current context |
| `unexpected-start-tag-ignored` | Start tag ignored in current context |
| `unexpected-start-tag-implies-end-tag` | Start tag implicitly closes previous element |

### EOF Errors

| Code | Description |
|------|-------------|
| `expected-closing-tag-but-got-eof` | Expected closing tag but reached end of file |
| `expected-named-closing-tag-but-got-eof` | Expected specific closing tag but reached end of file |

### Table Errors

| Code | Description |
|------|-------------|
| `foster-parenting-character` | Text content in table requires foster parenting |
| `foster-parenting-start-tag` | Start tag in table requires foster parenting |
| `unexpected-start-tag-implies-table-voodoo` | Start tag in table triggers foster parenting |
| `unexpected-cell-in-table-body` | Unexpected table cell outside of table row |
| `unexpected-form-in-table` | Form element not allowed in table context |

### Foreign Content Errors

| Code | Description |
|------|-------------|
| `unexpected-doctype-in-foreign-content` | Unexpected DOCTYPE in SVG/MathML content |
| `unexpected-html-element-in-foreign-content` | HTML element breaks out of SVG/MathML content |
| `unexpected-end-tag-in-foreign-content` | Mismatched end tag in SVG/MathML content |

### Miscellaneous Errors

| Code | Description |
|------|-------------|
| `end-tag-too-early` | End tag closed early (unclosed children) |
| `adoption-agency-1.3` | Misnested tags require adoption agency algorithm |
| `non-void-html-element-start-tag-with-trailing-solidus` | Self-closing syntax on non-void element (e.g., `<div/>`) |
| `image-start-tag` | Deprecated `<image>` tag (use `<img>` instead) |
