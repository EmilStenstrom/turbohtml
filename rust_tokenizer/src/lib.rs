use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule};
use indexmap::IndexMap;
use std::sync::OnceLock;

// Shared empty IndexMap to avoid allocations for tokens without attributes
static EMPTY_ATTRS: OnceLock<IndexMap<String, String>> = OnceLock::new();

fn get_empty_attrs() -> &'static IndexMap<String, String> {
    EMPTY_ATTRS.get_or_init(|| IndexMap::new())
}

#[pyclass]
struct HTMLToken {
    #[pyo3(get, set)]
    type_: String,
    #[pyo3(get, set)]
    data: String,
    #[pyo3(get, set)]
    tag_name: String,
    // Internal storage as IndexMap (preserves order)
    attributes_map: IndexMap<String, String>,
    #[pyo3(get, set)]
    is_self_closing: bool,
    #[pyo3(get, set)]
    is_last_token: bool,
    #[pyo3(get, set)]
    needs_rawtext: bool,
    #[pyo3(get, set)]
    ignored_end_tag: bool,
}

#[pymethods]
impl HTMLToken {
    #[new]
    #[pyo3(signature = (type_, data="".to_string(), tag_name="".to_string(), attributes=None, is_self_closing=false, is_last_token=false, needs_rawtext=false))]
    fn new(
        py: Python,
        type_: String,
        data: String,
        tag_name: String,
        attributes: Option<Bound<'_, PyDict>>,
        is_self_closing: bool,
        is_last_token: bool,
        needs_rawtext: bool,
    ) -> PyResult<Self> {
        let mut attributes_map = IndexMap::new();
        if let Some(dict) = attributes {
            for (key, value) in dict.iter() {
                attributes_map.insert(
                    key.extract::<String>()?,
                    value.extract::<String>()?,
                );
            }
        }

        Ok(HTMLToken {
            type_,
            data,
            tag_name: tag_name.to_lowercase(),
            attributes_map,
            is_self_closing,
            is_last_token,
            needs_rawtext,
            ignored_end_tag: false,
        })
    }

    #[getter]
    fn attributes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (key, value) in &self.attributes_map {
            dict.set_item(key, value)?;
        }
        Ok(dict)
    }

    #[setter]
    fn set_attributes(&mut self, py: Python, dict: Bound<'_, PyDict>) -> PyResult<()> {
        self.attributes_map.clear();
        for (key, value) in dict.iter() {
            self.attributes_map.insert(
                key.extract::<String>()?,
                value.extract::<String>()?,
            );
        }
        Ok(())
    }

    fn __repr__(&self) -> String {
        match self.type_.as_str() {
            "Character" => {
                let preview: String = self.data.chars().take(20).collect();
                let suffix = if self.data.len() > 20 { "..." } else { "" };
                format!("<{}: '{}{}'>", self.type_, preview, suffix)
            }
            "Comment" => {
                let preview: String = self.data.chars().take(20).collect();
                let suffix = if self.data.len() > 20 { "..." } else { "" };
                format!("<{}: '{}{}'>", self.type_, preview, suffix)
            }
            _ => format!("<{}: {}>", self.type_, if !self.tag_name.is_empty() { &self.tag_name } else { &self.data }),
        }
    }

    #[getter]
    fn r#type(&self) -> String {
        self.type_.clone()
    }
}

#[pyclass]
struct RustTokenizer {
    html: String,
    pos: usize,
    len: usize,
    debug: bool,
    state: String,  // "DATA", "RAWTEXT", or "PLAINTEXT"
    rawtext_tag: String,
}

#[pymethods]
impl RustTokenizer {
    #[new]
    #[pyo3(signature = (html, debug=false))]
    fn new(html: String, debug: bool) -> Self {
        let len = html.len();
        RustTokenizer {
            html,
            pos: 0,
            len,
            debug,
            state: "DATA".to_string(),
            rawtext_tag: String::new(),
        }
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> PyResult<Option<HTMLToken>> {
        if slf.pos >= slf.len {
            return Ok(None);
        }

        // Handle PLAINTEXT mode - consume everything remaining
        if slf.state == "PLAINTEXT" {
            let remaining = slf.html[slf.pos..].to_string();
            slf.pos = slf.len;

            // Decode entities in plaintext content
            let decoded = Python::with_gil(|py| {
                let html_module = PyModule::import(py, "html")?;
                let unescape = html_module.getattr("unescape")?;
                let result = unescape.call1((remaining,))?;
                result.extract::<String>()
            })?;

            return Ok(Some(RustTokenizer::new_token(
                "Character".to_string(),
                decoded,
                String::new(),
                None,
                false,
                true,  // is_last_token
            )));
        }

        // Handle RAWTEXT mode (script, style, etc.)
        if slf.state == "RAWTEXT" {
            if let Some(token) = slf.try_rawtext_end()? {
                return Ok(Some(token));
            }
        }

        // Try to parse a tag
        if slf.current_char() == Some('<') {
            match slf.try_tag()? {
                Some(token) => return Ok(Some(token)),
                None => {
                    // Invalid tag - consume the '<' as character data and continue
                    slf.pos += 1;
                    let text = "<".to_string();
                    return Ok(Some(RustTokenizer::new_token(
                        "Character".to_string(),
                        text,
                        String::new(),
                        None,
                        false,
                        false,
                    )));
                }
            }
        }

        // Otherwise, consume character data
        Ok(Some(slf.consume_character_data()?))
    }
}

impl RustTokenizer {
    // Helper to create tokens with IndexMap attributes directly (internal use)
    fn new_token(
        type_: String,
        data: String,
        tag_name: String,
        attributes: Option<IndexMap<String, String>>,
        is_self_closing: bool,
        needs_rawtext: bool,
    ) -> HTMLToken {
        HTMLToken {
            type_,
            data,
            tag_name: tag_name.to_lowercase(),
            attributes_map: attributes.unwrap_or_default(),
            is_self_closing,
            is_last_token: false,
            needs_rawtext,
            ignored_end_tag: false,
        }
    }

    #[inline(always)]
    fn current_byte(&self) -> Option<u8> {
        self.html.as_bytes().get(self.pos).copied()
    }

    fn current_char(&self) -> Option<char> {
        self.current_byte().map(|b| b as char)
    }

    fn peek_char(&self, offset: usize) -> Option<char> {
        self.html.as_bytes().get(self.pos + offset).map(|&b| b as char)
    }

    #[inline(always)]
    fn consume_char(&mut self) -> Option<char> {
        if self.pos < self.len {
            self.pos += 1;
            Some(self.html.as_bytes()[self.pos - 1] as char)
        } else {
            None
        }
    }

    fn try_rawtext_end(&mut self) -> PyResult<Option<HTMLToken>> {
        // Look for </script>, </style>, etc.
        let remaining = &self.html[self.pos..];
        let end_tag_prefix = format!("</{}", self.rawtext_tag);

        if let Some(idx) = remaining.find(&end_tag_prefix) {
            // Check if this is actually an end tag (followed by space, '/', or '>')
            let check_pos = idx + end_tag_prefix.len();
            let is_valid_end = if check_pos < remaining.len() {
                let next_char = remaining.as_bytes()[check_pos] as char;
                next_char.is_whitespace() || next_char == '>' || next_char == '/'
            } else {
                // At EOF after </tagname - treat as end tag
                true
            };

            if is_valid_end {
                // Consume text before the end tag
                if idx > 0 {
                    let text = remaining[..idx].to_string();
                    self.pos += idx;
                    return Ok(Some(Self::new_token(
                        "Character".to_string(),
                        text,
                        String::new(),
                        None,
                        false,
                        false,
                    )));
                }
                // Parse the end tag
                self.state = "DATA".to_string();
                self.rawtext_tag.clear();
                return self.try_tag();
            } else {
                // False match - continue looking or consume as text
                // For simplicity, consume up to the false match + the prefix
                let consume_len = idx + end_tag_prefix.len();
                if consume_len < remaining.len() {
                    let text = remaining[..consume_len].to_string();
                    self.pos += consume_len;
                    return Ok(Some(Self::new_token(
                        "Character".to_string(),
                        text,
                        String::new(),
                        None,
                        false,
                        false,
                    )));
                }
            }
        }

        // No end tag found, consume rest as text
        let text = remaining.to_string();
        self.pos = self.len;
        Ok(Some(Self::new_token(
            "Character".to_string(),
            text,
            String::new(),
            None,
            false,
            false,
        )))
    }

    fn try_tag(&mut self) -> PyResult<Option<HTMLToken>> {
        let entry_pos = self.pos;

        if self.consume_char() != Some('<') {
            return Ok(None);
        }

        // Check for CDATA section (must check before comment)
        if self.html[self.pos..].starts_with("![CDATA[") {
            return self.parse_cdata();
        }

        // Check for comment
        if self.html[self.pos..].starts_with("!--") {
            return self.parse_comment();
        }

        // Check for DOCTYPE (case-insensitive)
        let remaining = &self.html[self.pos..];
        if remaining.len() >= 8 {
            // Check first 8 bytes (ASCII safe)
            let bytes = remaining.as_bytes();
            if bytes[0] == b'!' &&
               (bytes[1] == b'd' || bytes[1] == b'D') &&
               (bytes[2] == b'o' || bytes[2] == b'O') &&
               (bytes[3] == b'c' || bytes[3] == b'C') &&
               (bytes[4] == b't' || bytes[4] == b'T') &&
               (bytes[5] == b'y' || bytes[5] == b'Y') &&
               (bytes[6] == b'p' || bytes[6] == b'P') &&
               (bytes[7] == b'e' || bytes[7] == b'E') {
                return self.parse_doctype();
            }
        }

        // Check for end tag
        let is_end_tag = self.current_char() == Some('/');
        if is_end_tag {
            self.consume_char();
        }

        // Parse tag name
        let tag_name = self.consume_tag_name();
        if tag_name.is_empty() {
            // Invalid tag, restore position and treat '<' as character data
            self.pos = entry_pos;
            return Ok(None);
        }

        // Skip whitespace
        self.skip_whitespace();

        // Parse attributes (only for start tags)
        let attributes = if !is_end_tag {
            Some(self.parse_attributes()?)
        } else {
            None
        };

        // Check for self-closing
        let is_self_closing = self.current_char() == Some('/');
        if is_self_closing {
            self.consume_char();
        }

        // Consume closing >
        if self.consume_char() != Some('>') {
            // Invalid tag - restore position and treat '<' as character data
            self.pos = entry_pos;
            return Ok(None);
        }

        let token_type = if is_end_tag {
            "EndTag".to_string()
        } else {
            "StartTag".to_string()
        };

        // Check if this starts RAWTEXT mode
        let needs_rawtext = !is_end_tag && matches!(
            tag_name.to_lowercase().as_str(),
            "script" | "style" | "xmp" | "iframe" | "noembed" | "noframes" | "noscript" | "textarea" | "title"
        );

        if needs_rawtext {
            self.state = "RAWTEXT".to_string();
            self.rawtext_tag = tag_name.to_lowercase();
        }

        // Check if this starts PLAINTEXT mode
        let is_plaintext = !is_end_tag && tag_name.to_lowercase() == "plaintext";
        if is_plaintext {
            self.state = "PLAINTEXT".to_string();
        }

        Ok(Some(Self::new_token(
            token_type,
            String::new(),
            tag_name,
            attributes,
            is_self_closing,
            needs_rawtext,
        )))
    }

    fn parse_cdata(&mut self) -> PyResult<Option<HTMLToken>> {
        // Skip "![CDATA["
        self.pos += 8;

        let start_pos = self.pos;
        let remaining = &self.html[self.pos..];

        if let Some(idx) = remaining.find("]]>") {
            let inner = remaining[..idx].to_string();
            self.pos += idx + 3;
            // Return as Comment token with [CDATA[...]] format (per Python tokenizer)
            Ok(Some(Self::new_token(
                "Comment".to_string(),
                format!("[CDATA[{}]]", inner),
                String::new(),
                None,
                false,
                false,
            )))
        } else {
            // Unterminated CDATA
            let inner = remaining.to_string();
            self.pos = self.len;
            // If inner ends with ']]' append space to disambiguate
            let data = if inner.ends_with("]]") {
                format!("[CDATA[{} ", inner)
            } else {
                format!("[CDATA[{}", inner)
            };
            Ok(Some(Self::new_token(
                "Comment".to_string(),
                data,
                String::new(),
                None,
                false,
                false,
            )))
        }
    }

    fn parse_comment(&mut self) -> PyResult<Option<HTMLToken>> {
        // Skip "!--"
        self.pos += 3;

        let remaining = &self.html[self.pos..];

        // Look for comment end markers: --> or --!>
        // Per HTML5 spec, both are valid (though --!> is an error)
        let normal_end = remaining.find("-->");
        let bang_end = remaining.find("--!>");

        let (end_idx, end_len) = match (normal_end, bang_end) {
            (Some(n), Some(b)) if b < n => (b, 4),  // --!> comes first
            (Some(n), _) => (n, 3),                 // --> (or comes first)
            (None, Some(b)) => (b, 4),              // only --!>
            (None, None) => {
                // Unclosed comment, consume rest
                let comment_text = remaining.to_string();
                self.pos = self.len;
                return Ok(Some(Self::new_token(
                    "Comment".to_string(),
                    comment_text,
                    String::new(),
                    None,
                    false,
                    false,
                )));
            }
        };

        let comment_text = remaining[..end_idx].to_string();
        self.pos += end_idx + end_len;
        Ok(Some(Self::new_token(
            "Comment".to_string(),
            comment_text,
            String::new(),
            None,
            false,
            false,
        )))
    }

    fn parse_doctype(&mut self) -> PyResult<Option<HTMLToken>> {
        // Skip "!doctype" (8 bytes, case-insensitive already checked)
        self.pos += 8;

        // Skip whitespace
        self.skip_whitespace();

        // Find closing >
        let remaining = &self.html[self.pos..];
        if let Some(idx) = remaining.find('>') {
            let doctype_content = remaining[..idx].trim().to_string();
            self.pos += idx + 1;
            Ok(Some(Self::new_token(
                "DOCTYPE".to_string(),
                doctype_content,
                String::new(),
                None,
                false,
                false,
            )))
        } else {
            // Unclosed DOCTYPE
            let doctype_content = remaining.trim().to_string();
            self.pos = self.len;
            Ok(Some(Self::new_token(
                "DOCTYPE".to_string(),
                doctype_content,
                String::new(),
                None,
                false,
                false,
            )))
        }
    }

    fn consume_tag_name(&mut self) -> String {
        let start = self.pos;
        while let Some(ch) = self.current_char() {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' || ch == ':' {
                self.consume_char();
            } else {
                break;
            }
        }
        self.html[start..self.pos].to_string()
    }

    fn skip_whitespace(&mut self) {
        while let Some(ch) = self.current_char() {
            if ch.is_whitespace() {
                self.consume_char();
            } else {
                break;
            }
        }
    }

    fn parse_attributes(&mut self) -> PyResult<IndexMap<String, String>> {
        let mut attrs = IndexMap::new();

        loop {
            self.skip_whitespace();

            // Check if we've reached end of tag
            if matches!(self.current_char(), Some('>') | Some('/') | None) {
                break;
            }

            // Parse attribute name
            let attr_name = self.consume_attr_name();
            if attr_name.is_empty() {
                break;
            }

            self.skip_whitespace();

            // Check for = sign
            let attr_value = if self.current_char() == Some('=') {
                self.consume_char();
                self.skip_whitespace();
                self.consume_attr_value()
            } else {
                String::new()
            };

            attrs.insert(attr_name, attr_value);
        }

        Ok(attrs)
    }

    fn consume_attr_name(&mut self) -> String {
        let start = self.pos;
        while let Some(ch) = self.current_char() {
            if matches!(ch, '=' | '>' | '/' ) || ch.is_whitespace() {
                break;
            }
            self.consume_char();
        }
        self.html[start..self.pos].to_string()
    }

    fn consume_attr_value(&mut self) -> String {
        let raw_value = match self.current_char() {
            Some('"') => {
                self.consume_char();
                let start = self.pos;
                while let Some(ch) = self.current_char() {
                    if ch == '"' {
                        break;
                    }
                    self.consume_char();
                }
                let value = self.html[start..self.pos].to_string();
                self.consume_char(); // consume closing "
                value
            }
            Some('\'') => {
                self.consume_char();
                let start = self.pos;
                while let Some(ch) = self.current_char() {
                    if ch == '\'' {
                        break;
                    }
                    self.consume_char();
                }
                let value = self.html[start..self.pos].to_string();
                self.consume_char(); // consume closing '
                value
            }
            _ => {
                // Unquoted attribute value
                let start = self.pos;
                while let Some(ch) = self.current_char() {
                    if matches!(ch, '>' | '/') || ch.is_whitespace() {
                        break;
                    }
                    self.consume_char();
                }
                self.html[start..self.pos].to_string()
            }
        };

        // Decode HTML entities in attribute value
        let decoded = Python::with_gil(|py| {
            let html_module = PyModule::import(py, "html").ok()?;
            let unescape = html_module.getattr("unescape").ok()?;
            let result = unescape.call1((&raw_value,)).ok()?;
            result.extract::<String>().ok()
        });

        decoded.unwrap_or(raw_value)
    }

    fn consume_character_data(&mut self) -> PyResult<HTMLToken> {
        let start = self.pos;

        // Consume until we hit a '<' or end of string
        while self.pos < self.len {
            if self.current_char() == Some('<') {
                break;
            }
            self.consume_char();
        }

        let text = self.html[start..self.pos].to_string();

        // Decode HTML entities using Python's html.unescape
        let decoded_text = Python::with_gil(|py| {
            let html_module = PyModule::import(py, "html")?;
            let unescape = html_module.getattr("unescape")?;
            let result = unescape.call1((text,))?;
            result.extract::<String>()
        })?;

        Ok(Self::new_token(
            "Character".to_string(),
            decoded_text,
            String::new(),
            None,
            false,
            false,
        ))
    }
}

#[pymodule]
fn rust_tokenizer(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<HTMLToken>()?;
    m.add_class::<RustTokenizer>()?;
    Ok(())
}
