use pyo3::prelude::*;
use pyo3::types::PyModule;
use std::collections::HashMap;

#[pyclass]
#[derive(Clone)]
pub struct HTMLToken {
    #[pyo3(get, set)]
    pub type_: String,
    #[pyo3(get, set)]
    pub data: String,
    #[pyo3(get, set)]
    pub tag_name: String,
    #[pyo3(get, set)]
    pub attributes: HashMap<String, String>,
    #[pyo3(get, set)]
    pub is_self_closing: bool,
    #[pyo3(get, set)]
    pub is_last_token: bool,
    #[pyo3(get, set)]
    pub needs_rawtext: bool,
    #[pyo3(get, set)]
    pub ignored_end_tag: bool,
}

#[pymethods]
impl HTMLToken {
    #[new]
    #[pyo3(signature = (type_, data=None, tag_name=None, attributes=None, is_self_closing=None, is_last_token=None, needs_rawtext=None))]
    fn py_new(
        type_: String,
        data: Option<String>,
        tag_name: Option<String>,
        attributes: Option<HashMap<String, String>>,
        is_self_closing: Option<bool>,
        is_last_token: Option<bool>,
        needs_rawtext: Option<bool>,
    ) -> Self {
        HTMLToken {
            type_,
            data: data.unwrap_or_default(),
            tag_name: tag_name.unwrap_or_default().to_lowercase(),
            attributes: attributes.unwrap_or_default(),
            is_self_closing: is_self_closing.unwrap_or(false),
            is_last_token: is_last_token.unwrap_or(false),
            needs_rawtext: needs_rawtext.unwrap_or(false),
            ignored_end_tag: false,
        }
    }

    fn __repr__(&self) -> String {
        match self.type_.as_str() {
            "Character" | "Comment" => {
                let preview: String = self.data.chars().take(20).collect();
                let suffix = if self.data.len() > 20 { "..." } else { "" };
                format!("<{}: '{}{}'>", self.type_, preview, suffix)
            }
            _ => format!(
                "<{}: {}>",
                self.type_,
                if !self.tag_name.is_empty() {
                    &self.tag_name
                } else {
                    &self.data
                }
            ),
        }
    }

    // Compatibility property for Python code that uses .type instead of .type_
    #[pyo3(name = "type")]
    #[getter]
    fn get_type(&self) -> String {
        self.type_.clone()
    }
}


#[pyclass]
pub struct RustTokenizer {
    html: String,
    length: usize,
    pos: usize,
    state: String,
    rawtext_tag: Option<String>,
    last_pos: usize,
    env_debug: bool,
    script_content: String,
    script_non_executable: bool,
    script_suppressed_end_once: bool,
    script_type_value: String,
    pending_tokens: Vec<HTMLToken>,
}

#[pymethods]
impl RustTokenizer {
    #[new]
    #[pyo3(signature = (html, debug=false))]
    fn py_new(html: String, debug: bool) -> Self {
        let length = html.len();
        RustTokenizer {
            html,
            length,
            pos: 0,
            state: "DATA".to_string(),
            rawtext_tag: None,
            last_pos: length,
            env_debug: debug,
            script_content: String::new(),
            script_non_executable: false,
            script_suppressed_end_once: false,
            script_type_value: String::new(),
            pending_tokens: Vec::new(),
        }
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> PyResult<Option<HTMLToken>> {
        loop {
            // Yield pending tokens first
            if !slf.pending_tokens.is_empty() {
                let mut token = slf.pending_tokens.remove(0);
                slf.debug(&format!("PENDING token: {}", token.type_));
                token.is_last_token = slf.pos >= slf.last_pos && slf.pending_tokens.is_empty();
                return Ok(Some(token));
            }

            if slf.pos >= slf.length {
                return Ok(None);
            }

            slf.debug(&format!(
                "tokenize: pos={}, state={}, char={:?}",
                slf.pos,
                slf.state,
                slf.current_char()
            ));

            match slf.state.as_str() {
                "DATA" => {
                    let token = slf.try_tag()?.or_else(|| slf.try_text());
                    if let Some(mut token) = token {
                        slf.debug(&format!("DATA token: {}", token.type_));
                        token.is_last_token = slf.pos >= slf.last_pos;
                        return Ok(Some(token));
                    } else if slf.pos < slf.length {
                        slf.pos += 1;
                        // Continue loop
                    } else {
                        return Ok(None);
                    }
                }
                "RAWTEXT" => {
                    if let Some(mut token) = slf.tokenize_rawtext()? {
                        slf.debug(&format!("RAWTEXT token: {}", token.type_));
                        token.is_last_token = slf.pos >= slf.last_pos;
                        return Ok(Some(token));
                    } else {
                        return Ok(None);
                    }
                }
                "PLAINTEXT" => {
                    if slf.pos < slf.length {
                        let raw = &slf.html[slf.pos..];
                        let data = slf.replace_invalid_characters(raw);
                        slf.pos = slf.length;
                        let token = HTMLToken::py_new(
                            "Character".to_string(),
                            Some(data),
                            None,
                            None,
                            None,
                            Some(true),
                            None,
                        );
                        return Ok(Some(token));
                    } else {
                        return Ok(None);
                    }
                }
                _ => return Ok(None),
            }
        }
    }

    fn start_rawtext(&mut self, tag_name: String) {
        self.state = "RAWTEXT".to_string();
        self.rawtext_tag = Some(tag_name.to_lowercase());
        if self.rawtext_tag.as_deref() == Some("script") {
            self.script_content.clear();
        }
    }

    fn start_plaintext(&mut self) {
        self.state = "PLAINTEXT".to_string();
        self.rawtext_tag = None;
    }

    #[getter]
    fn state(&self) -> String {
        self.state.clone()
    }

    #[setter]
    fn set_state(&mut self, state: String) {
        self.state = state;
    }

    #[getter]
    fn rawtext_tag(&self) -> Option<String> {
        self.rawtext_tag.clone()
    }

    #[setter]
    fn set_rawtext_tag(&mut self, tag: Option<String>) {
        self.rawtext_tag = tag;
    }
}

// Implementation methods (not exposed to Python)
impl RustTokenizer {
    fn current_char(&self) -> Option<char> {
        self.html[self.pos..].chars().next()
    }

    fn debug(&self, msg: &str) {
        if self.env_debug {
            println!("    {}", msg);
        }
    }

    fn replace_invalid_characters(&self, text: &str) -> String {
        text.chars()
            .map(|ch| {
                let code = ch as u32;
                if code == 0x00
                    || (0x01..=0x1F).contains(&code)
                        && !matches!(ch, '\t' | '\n' | '\r' | '\x0C')
                {
                    '\u{FFFD}'
                } else {
                    ch
                }
            })
            .collect()
    }

    fn decode_entities(&self, text: &str) -> String {
        // Full HTML5 entity decoding matching Python tokenizer
        if !text.contains('&') {
            return text.to_string();
        }

        // Use Python's html.unescape for complete entity handling
        Python::with_gil(|py| {
            // Import constants module to get NUMERIC_ENTITY_INVALID_SENTINEL
            let constants = PyModule::import(py, "turbohtml.constants").ok();
            let sentinel = constants
                .and_then(|m| m.getattr("NUMERIC_ENTITY_INVALID_SENTINEL").ok())
                .and_then(|s| s.extract::<String>().ok())
                .unwrap_or_else(|| "\u{f000}".to_string());

            // Call Python's tokenizer decode logic
            let tokenizer_mod = PyModule::import(py, "turbohtml.tokenizer").ok();
            if let Some(tok_mod) = tokenizer_mod {
                // Get _codepoint_to_char function
                if let Ok(codepoint_fn) = tok_mod.getattr("_codepoint_to_char") {
                    // Implement numeric entity parsing
                    let mut result = String::new();
                    let chars: Vec<char> = text.chars().collect();
                    let mut i = 0;

                    while i < chars.len() {
                        if chars[i] != '&' {
                            result.push(chars[i]);
                            i += 1;
                            continue;
                        }

                        // Check for numeric entity &#...
                        if i + 1 < chars.len() && chars[i + 1] == '#' {
                            let mut j = i + 2;
                            let is_hex = j < chars.len() && (chars[j] == 'x' || chars[j] == 'X');

                            if is_hex {
                                j += 1;
                            }

                            let start_digits = j;
                            if is_hex {
                                while j < chars.len() && chars[j].is_ascii_hexdigit() {
                                    j += 1;
                                }
                            } else {
                                while j < chars.len() && chars[j].is_ascii_digit() {
                                    j += 1;
                                }
                            }

                            let digits: String = chars[start_digits..j].iter().collect();
                            if !digits.is_empty() {
                                let has_semicolon = j < chars.len() && chars[j] == ';';
                                if has_semicolon {
                                    j += 1;
                                }

                                let base = if is_hex { 16 } else { 10 };
                                if let Ok(codepoint) = u32::from_str_radix(&digits, base) {
                                    // Call Python's _codepoint_to_char for proper handling
                                    if let Ok(py_result) = codepoint_fn.call1((codepoint,)) {
                                        if let Ok(decoded_char) = py_result.extract::<String>() {
                                            // Check if it's the invalid sentinel
                                            if decoded_char == "\u{fffd}" {
                                                result.push_str(&sentinel);
                                            } else {
                                                result.push_str(&decoded_char);
                                            }
                                        }
                                    }
                                }
                                i = j;
                                continue;
                            }
                        }

                        // Try named entity using html.unescape
                        let html_mod = PyModule::import(py, "html").ok();
                        if let Some(html) = html_mod {
                            let mut j = i + 1;
                            while j < chars.len() && chars[j].is_alphanumeric() {
                                j += 1;
                            }
                            let mut name: String = chars[i..j].iter().collect();
                            let has_semicolon = j < chars.len() && chars[j] == ';';
                            if has_semicolon {
                                name.push(';');
                                j += 1;
                            }

                            if let Ok(unescape_fn) = html.getattr("unescape") {
                                if let Ok(decoded) = unescape_fn.call1((&name,)) {
                                    if let Ok(decoded_str) = decoded.extract::<String>() {
                                        if decoded_str != name {
                                            result.push_str(&decoded_str);
                                            i = j;
                                            continue;
                                        }
                                    }
                                }
                            }
                        }

                        // Literal '&'
                        result.push('&');
                        i += 1;
                    }

                    return result;
                }
            }

            // Fallback to html.unescape
            let html_module = PyModule::import(py, "html");
            if let Ok(html_mod) = html_module {
                if let Ok(unescape_fn) = html_mod.getattr("unescape") {
                    if let Ok(result) = unescape_fn.call1((text,)) {
                        if let Ok(decoded) = result.extract::<String>() {
                            return decoded;
                        }
                    }
                }
            }
            text.to_string()
        })
    }

    fn tokenize_rawtext(&mut self) -> PyResult<Option<HTMLToken>> {
        self.debug(&format!(
            "_tokenize_rawtext: pos={}, next_chars={:?}",
            self.pos,
            &self.html[self.pos..]
                .chars()
                .take(10)
                .collect::<String>()
        ));

        if self.rawtext_tag.as_deref() == Some("script") {
            self.tokenize_script_content()
        } else {
            self.tokenize_regular_rawtext()
        }
    }

    fn tokenize_script_content(&mut self) -> PyResult<Option<HTMLToken>> {
        // Script content with HTML5 comment escaping
        if self.html[self.pos..].starts_with("</") {
            self.debug("  found </: checking if should honor end tag");
            let tag_start = self.pos + 2;

            // Parse tag name
            let mut i = tag_start;
            while i < self.length && self.html.as_bytes()[i].is_ascii_alphabetic() {
                i += 1;
            }

            let potential_tag = self.html[tag_start..i].to_lowercase();

            if potential_tag == "script" {
                // Check if next character after tag name is whitespace, '/', or '>'
                // EOF directly after "</script" (no trailing char) is NOT a candidate - emit as text
                if i >= self.length {
                    // EOF immediately after tag name - not a candidate, emit as text
                    self.debug("  EOF after </script (no trailing char) - treating as text");
                    let frag = &self.html[self.pos..];
                    self.pos = self.length;
                    let frag = self.replace_invalid_characters(frag);
                    self.script_content.push_str(&frag);
                    return Ok(Some(HTMLToken::py_new(
                        "Character".to_string(),
                        Some(frag),
                        None,
                        None,
                        None,
                        None,
                        None,
                    )));
                }

                let next_char = self.html.as_bytes()[i];
                if !matches!(next_char, b' ' | b'\t' | b'\n' | b'\r' | b'\x0c' | b'/' | b'>') {
                    // Not a candidate end tag - emit as text
                    self.debug("  invalid char after </script - treating as text");
                    let frag = &self.html[self.pos..];
                    self.pos = self.length;
                    let frag = self.replace_invalid_characters(frag);
                    self.script_content.push_str(&frag);
                    return Ok(Some(HTMLToken::py_new(
                        "Character".to_string(),
                        Some(frag),
                        None,
                        None,
                        None,
                        None,
                        None,
                    )));
                }

                // Skip whitespace
                while i < self.length && self.html.as_bytes()[i].is_ascii_whitespace() {
                    i += 1;
                }

                // Skip any "/" characters
                while i < self.length && self.html.as_bytes()[i] == b'/' {
                    i += 1;
                }

                // Skip whitespace again
                while i < self.length && self.html.as_bytes()[i].is_ascii_whitespace() {
                    i += 1;
                }

                // Check if there's a closing '>'
                let has_closing_gt = i < self.length && self.html.as_bytes()[i] == b'>';

                // Build script content up to this point
                let text_before = self.html[self.pos..tag_start - 2].to_string();
                let full_content = format!("{}{}", self.script_content, text_before);

                if has_closing_gt {
                    // Complete end tag </script>
                    if self.should_honor_script_end_tag(&full_content) {
                        self.debug("  honoring script end tag");
                        self.pos = i + 1;

                        self.state = "DATA".to_string();
                        self.rawtext_tag = None;
                        self.script_content.clear();
                        self.script_suppressed_end_once = false;

                        if !text_before.is_empty() {
                            let text_before = self.replace_invalid_characters(&text_before);
                            self.pending_tokens.push(HTMLToken::py_new(
                                "EndTag".to_string(),
                                None,
                                Some(potential_tag),
                                None,
                                None,
                                None,
                                None,
                            ));
                            return Ok(Some(HTMLToken::py_new(
                                "Character".to_string(),
                                Some(text_before),
                                None,
                                None,
                                None,
                                None,
                                None,
                            )));
                        }
                        return Ok(Some(HTMLToken::py_new(
                            "EndTag".to_string(),
                            None,
                            Some(potential_tag),
                            None,
                            None,
                            None,
                            None,
                        )));
                    } else {
                        self.debug("  suppressing script end tag (escaped comment)");
                    }
                } else {
                    // Partial end tag </script without '>'
                    // Still check if we should honor for suppression counter
                    let honor_if_complete = self.should_honor_script_end_tag(&full_content);
                    if honor_if_complete {
                        self.debug("  implicit script end on partial </script (no '>')");
                        // Treat as implicit end
                        self.pos = self.length;
                        self.state = "DATA".to_string();
                        self.rawtext_tag = None;
                        self.script_content.clear();
                        self.script_suppressed_end_once = false;

                        if !text_before.is_empty() {
                            let text_before = self.replace_invalid_characters(&text_before);
                            self.pending_tokens.push(HTMLToken::py_new(
                                "EndTag".to_string(),
                                None,
                                Some(potential_tag),
                                None,
                                None,
                                None,
                                None,
                            ));
                            return Ok(Some(HTMLToken::py_new(
                                "Character".to_string(),
                                Some(text_before),
                                None,
                                None,
                                None,
                                None,
                                None,
                            )));
                        }
                        return Ok(Some(HTMLToken::py_new(
                            "EndTag".to_string(),
                            None,
                            Some(potential_tag),
                            None,
                            None,
                            None,
                            None,
                        )));
                    } else {
                        self.debug("  suppressing partial </script (escaped comment)");
                    }
                }
            }
        }

        // Find next potential end tag or EOF
        let start = self.pos;
        if let Some(next_close) = self.html[start + 1..].find("</") {
            self.pos = start + 1 + next_close;
        } else {
            self.pos = self.length;
        }

        let text = self.html[start..self.pos].to_string();
        if !text.is_empty() {
            self.script_content.push_str(&text);
            let text = self.replace_invalid_characters(&text);
            return Ok(Some(HTMLToken::py_new(
                "Character".to_string(),
                Some(text),
                None,
                None,
                None,
                None,
                None,
            )));
        }

        Ok(None)
    }

    fn should_honor_script_end_tag(&mut self, script_content: &str) -> bool {
        self.debug(&format!("  checking script content: {:?}", script_content));
        let lower = script_content.to_lowercase();

        // If no comment opener, always honor
        if !lower.contains("<!--") {
            self.debug("  no comments found, honoring end tag");
            return true;
        }

        // Check if in escaped script comment
        if Self::in_escaped_script_comment(&lower) {
            if !self.script_suppressed_end_once {
                self.script_suppressed_end_once = true;
                self.debug("  suppressing FIRST end tag inside <!-- <script pattern (no --> yet)");
                return false;
            }
            self.debug("  already suppressed once in <!-- <script pattern; honoring end tag");
        }

        self.debug("  honoring end tag");
        true
    }

    fn in_escaped_script_comment(script_content: &str) -> bool {
        let lower = script_content.to_lowercase();

        // If there's a closing -->, not in escaped state
        if lower.contains("-->") {
            return false;
        }

        // Find <!--
        if let Some(idx) = lower.find("<!--") {
            let after = &lower[idx + 4..];

            // Skip whitespace
            let mut k = 0;
            while k < after.len() && matches!(after.as_bytes()[k], b' ' | b'\t' | b'\n' | b'\r' | b'\x0c') {
                k += 1;
            }

            // Must start with '<script'
            if after[k..].starts_with("<script") {
                let tag_end = k + "<script".len();
                if tag_end < after.len() {
                    let following = after.as_bytes()[tag_end];
                    // Must be followed by delimiter
                    return matches!(following, b' ' | b'/' | b'\t' | b'\n' | b'\r' | b'\x0c' | b'>');
                }
            }
        }

        false
    }

    fn tokenize_regular_rawtext(&mut self) -> PyResult<Option<HTMLToken>> {
        // Look for matching end tag
        if self.html[self.pos..].starts_with("</") {
            self.debug("  found </: looking for end tag");
            let tag_start = self.pos + 2;

            // Parse tag name
            let mut i = tag_start;
            while i < self.length {
                let ch = self.html.as_bytes()[i];
                if ch.is_ascii_alphabetic() {
                    i += 1;
                } else {
                    break;
                }
            }

            let potential_tag = self.html[tag_start..i].to_lowercase();

            self.debug(&format!(
                "  potential_tag={:?}, rawtext_tag={:?}",
                potential_tag, self.rawtext_tag
            ));

            // Skip whitespace
            while i < self.length && self.html.as_bytes()[i].is_ascii_whitespace() {
                i += 1;
            }

            // Skip any "/" characters
            while i < self.length && self.html.as_bytes()[i] == b'/' {
                i += 1;
            }

            // Skip whitespace again
            while i < self.length && self.html.as_bytes()[i].is_ascii_whitespace() {
                i += 1;
            }

            // Check if it's our end tag
            if Some(&potential_tag) == self.rawtext_tag.as_ref()
                && i < self.length
                && self.html.as_bytes()[i] == b'>'
            {
                self.debug("  found matching end tag");
                // Found valid end tag
                let text_before = self.html[self.pos..tag_start - 2].to_string();
                self.pos = i + 1;

                let current_rawtext = self.rawtext_tag.clone();
                self.state = "DATA".to_string();
                self.rawtext_tag = None;

                // Return text if any, then queue end tag
                if !text_before.is_empty() {
                    let text_before = self.replace_invalid_characters(&text_before);
                    // Decode entities for RCDATA elements (title/textarea)
                    let text_before = if matches!(current_rawtext.as_deref(), Some("title") | Some("textarea")) {
                        self.decode_entities(&text_before)
                    } else {
                        text_before
                    };
                    self.pending_tokens.push(HTMLToken::py_new(
                        "EndTag".to_string(),
                        None,
                        Some(potential_tag),
                        None,
                        None,
                        None,
                        None,
                    ));
                    return Ok(Some(HTMLToken::py_new(
                        "Character".to_string(),
                        Some(text_before),
                        None,
                        None,
                        None,
                        None,
                        None,
                    )));
                }
                // No text - emit end tag directly
                return Ok(Some(HTMLToken::py_new(
                    "EndTag".to_string(),
                    None,
                    Some(potential_tag),
                    None,
                    None,
                    None,
                    None,
                )));
            }
        }

        // Find next potential end tag or EOF
        let start = self.pos;
        if let Some(next_close) = self.html[start + 1..].find("</") {
            self.pos = start + 1 + next_close;
        } else {
            self.pos = self.length;
        }

        // Return text we found
        let text = self.html[start..self.pos].to_string();
        if !text.is_empty() {
            let text = self.replace_invalid_characters(&text);
            // Decode entities for RCDATA elements (title/textarea)
            let text = if matches!(self.rawtext_tag.as_deref(), Some("title") | Some("textarea")) {
                self.decode_entities(&text)
            } else {
                text
            };
            return Ok(Some(HTMLToken::py_new(
                "Character".to_string(),
                Some(text),
                None,
                None,
                None,
                None,
                None,
            )));
        }

        Ok(None)
    }

    fn try_tag(&mut self) -> PyResult<Option<HTMLToken>> {
        let pos = self.pos;
        let html = &self.html;
        let length = self.length;

        // Must start with '<'
        if pos >= length || !html[pos..].starts_with('<') {
            return Ok(None);
        }

        self.debug(&format!(
            "_try_tag: pos={}, state={}, next_chars={:?}",
            pos,
            self.state,
            &html[pos..].chars().take(10).collect::<String>()
        ));

        // HTML5 spec: After '<' only letter / '!' / '/' / '?' may begin markup
        if pos + 1 < length {
            let nxt = html.as_bytes()[pos + 1];
            if !nxt.is_ascii_alphabetic() && !matches!(nxt, b'!' | b'/' | b'?') {
                self.pos = pos + 1;
                return Ok(Some(HTMLToken::py_new(
                    "Character".to_string(),
                    Some("<".to_string()),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            }
        }

        // If '<' is at EOF, treat as text
        if pos + 1 >= length {
            self.pos = pos + 1;
            return Ok(Some(HTMLToken::py_new(
                "Character".to_string(),
                Some("<".to_string()),
                None,
                None,
                None,
                None,
                None,
            )));
        }

        // Handle DOCTYPE (case-insensitive)
        if pos + 9 <= length && html.as_bytes()[pos + 1] == b'!' {
            let end_check = (pos + 9).min(length);
            if end_check >= pos + 9 {
                let chunk = &html[pos+2..pos+9];
                if chunk.eq_ignore_ascii_case("DOCTYPE") {
                    self.pos = pos + 9;
                    // Skip whitespace
                    while self.pos < length && html.as_bytes()[self.pos].is_ascii_whitespace() {
                        self.pos += 1;
                    }
                    // Find closing '>'
                    if let Some(gt_pos) = html[self.pos..].find('>') {
                        let doctype = html[self.pos..self.pos + gt_pos].trim().to_string();
                        self.pos += gt_pos + 1;
                        return Ok(Some(HTMLToken::py_new(
                            "DOCTYPE".to_string(),
                            Some(doctype),
                            None,
                            None,
                            None,
                            None,
                            None,
                        )));
                    } else {
                        let doctype = html[self.pos..].trim().to_string();
                        self.pos = length;
                        return Ok(Some(HTMLToken::py_new(
                            "DOCTYPE".to_string(),
                            Some(doctype),
                            None,
                            None,
                            None,
                            None,
                            None,
                        )));
                    }
                }
            }
        }

        // Handle comments (only in DATA state)
        if self.state == "DATA" && pos + 4 <= length && html[pos..].starts_with("<!--") {
            // Special case: <!--> is treated as empty comment
            if pos + 4 < length && html.as_bytes()[pos + 4] == b'>' {
                self.pos = pos + 5;
                return Ok(Some(HTMLToken::py_new(
                    "Comment".to_string(),
                    Some(String::new()),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            }
            return self.handle_comment();
        }

        // Handle bogus comments (only in DATA state)
        if self.state == "DATA" {
            let is_end_tag_start = pos + 2 <= length && html[pos..].starts_with("</");
            let has_invalid_char = pos + 2 < length && {
                let ch = html.as_bytes()[pos + 2];
                !ch.is_ascii_alphabetic()
            };

            if (is_end_tag_start && has_invalid_char)
                || (pos + 2 <= length && html[pos..].starts_with("<!"))
                || (pos + 2 <= length && html[pos..].starts_with("<?"))
            {
                self.debug("Found bogus comment case");
                return self.handle_bogus_comment(false);
            }
        }

        // Try to parse a simple tag
        if let Some(token) = self.parse_simple_tag()? {
            return Ok(Some(token));
        }

        // Couldn't parse - emit '<' as character
        self.pos = pos + 1;
        Ok(Some(HTMLToken::py_new(
            "Character".to_string(),
            Some("<".to_string()),
            None,
            None,
            None,
            None,
            None,
        )))
    }

    fn parse_simple_tag(&mut self) -> PyResult<Option<HTMLToken>> {
        // Full tag parser - handles tags with attributes
        let start_pos = self.pos;

        // Already checked that we start with '<'
        self.pos += 1;

        // Check for end tag
        let is_end_tag = self.pos < self.length && self.html.as_bytes()[self.pos] == b'/';
        if is_end_tag {
            self.pos += 1;
        }

        // Parse tag name
        let tag_name_start = self.pos;
        while self.pos < self.length {
            let ch = self.html.as_bytes()[self.pos];
            // Allow alphanumeric, hyphen, colon, and < (for malformed tags like <di<a>)
            // Spec: tag name is anything except whitespace, /, and >
            if !matches!(ch, b' ' | b'\t' | b'\n' | b'\r' | b'\x0c' | b'/' | b'>') {
                self.pos += 1;
            } else {
                break;
            }
        }

        if self.pos == tag_name_start {
            // No tag name found - reset and return None
            self.pos = start_pos;
            return Ok(None);
        }

        let tag_name = self.html[tag_name_start..self.pos].to_lowercase();

        // Skip whitespace
        while self.pos < self.length && self.html.as_bytes()[self.pos].is_ascii_whitespace() {
            self.pos += 1;
        }

        // Parse attributes
        let attr_start = self.pos;
        let mut attr_end = self.pos;

        // Find the end of attributes (either '/>' or '>')
        // Note: We scan for the closing '>' but handle quotes along the way
        // The Python tokenizer has complex unbalanced quote handling, but for now
        // we just track quotes and look for '>'. If we hit '>' even inside quotes,
        // that's where the tag ends (per HTML5 spec for malformed markup).
        let mut in_quote: Option<u8> = None;
        while self.pos < self.length {
            let ch = self.html.as_bytes()[self.pos];

            if ch == b'>' {
                // Always break on '>', even if inside quotes (malformed HTML)
                attr_end = self.pos;
                break;
            }

            if let Some(quote_char) = in_quote {
                if ch == quote_char && self.pos > 0 && self.html.as_bytes()[self.pos - 1] != b'\\' {
                    in_quote = None;
                }
            } else if ch == b'"' || ch == b'\'' {
                in_quote = Some(ch);
            }

            self.pos += 1;
            attr_end = self.pos;
        }

        // Parse the attributes substring
        let attr_string = if attr_end > attr_start {
            self.html[attr_start..attr_end].trim()
        } else {
            ""
        };

        let (is_self_closing, attributes) = self.parse_attributes(attr_string);

        // Handle unclosed tag at EOF
        let unclosed_to_eof = self.pos >= self.length;

        if unclosed_to_eof {
            // EOF without closing '>'
            self.pos = self.length;

            if is_end_tag {
                // End tags at EOF: emit EndTag (attributes are ignored in end tags anyway)
                return Ok(Some(HTMLToken::py_new(
                    "EndTag".to_string(),
                    None,
                    Some(tag_name),
                    None,
                    None,
                    None,
                    None,
                )));
            }

            // Start tags at EOF
            if attr_string.trim().is_empty() {
                // No attributes: emit empty Character token (suppresses both element and text)
                return Ok(Some(HTMLToken::py_new(
                    "Character".to_string(),
                    Some(String::new()),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            } else {
                // Has attributes: emit attributes as text
                return Ok(Some(HTMLToken::py_new(
                    "Character".to_string(),
                    Some(attr_string.to_string()),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            }
        }

        if self.html.as_bytes()[self.pos] != b'>' {
            // Malformed tag - reset
            self.pos = start_pos;
            return Ok(None);
        }

        self.pos += 1; // Skip '>'

        let token_type = if is_end_tag {
            "EndTag"
        } else {
            "StartTag"
        };

        // Check if this starts RAWTEXT mode
        let needs_rawtext = !is_end_tag && matches!(
            tag_name.as_str(),
            "script" | "style" | "xmp" | "iframe" | "noembed" | "noframes" | "noscript" | "textarea" | "title"
        );

        if needs_rawtext {
            self.state = "RAWTEXT".to_string();
            self.rawtext_tag = Some(tag_name.clone());
            if tag_name == "script" {
                self.script_content.clear();
            }
        }

        Ok(Some(HTMLToken::py_new(
            token_type.to_string(),
            None,
            Some(tag_name),
            Some(attributes),
            Some(is_self_closing),
            None,
            Some(needs_rawtext),
        )))
    }

    fn parse_attributes(&self, attr_string: &str) -> (bool, HashMap<String, String>) {
        let mut attributes = HashMap::new();

        if attr_string.is_empty() {
            return (false, attributes);
        }

        let trimmed = attr_string.trim();

        // Check for self-closing slash
        // Only treat as self-closing if / is preceded by whitespace or is at the start
        // Examples: <foo /> or <foo bar="baz" /> but NOT <foo bar=baz/>
        let is_self_closing = trimmed.ends_with(" /") || trimmed == "/";
        let attr_to_parse = if is_self_closing {
            trimmed.trim_end_matches('/').trim()
        } else {
            trimmed
        };

        if attr_to_parse.is_empty() {
            return (is_self_closing, attributes);
        }

        // Handle slash-delimited attribute sequences (like //problem/6869687)
        if attr_to_parse.contains('/')
            && !attr_to_parse.contains(' ')
            && !attr_to_parse.contains('=')
            && !attr_to_parse.contains('"')
            && !attr_to_parse.contains('\'')
            && !attr_to_parse.contains('<')
        {
            if attr_to_parse.starts_with("//") {
                // Double slash: reverse order (//problem/6869687 -> 6869687, problem)
                let parts: Vec<&str> = attr_to_parse.split('/').filter(|p| !p.is_empty()).collect();
                for part in parts.iter().rev() {
                    attributes.insert(part.to_string(), String::new());
                }
            } else {
                // Single leading slash: natural order (/x/y/z -> x, y, z)
                let parts: Vec<&str> = attr_to_parse.split('/').filter(|p| !p.is_empty()).collect();
                for part in parts {
                    attributes.insert(part.to_string(), String::new());
                }
            }
            return (is_self_closing, attributes);
        }

        // Simple attribute parser using a state machine
        let mut i = 0;
        let bytes = attr_to_parse.as_bytes();
        let len = bytes.len();

        while i < len {
            // Skip whitespace and slashes between attributes
            while i < len && (bytes[i].is_ascii_whitespace() || bytes[i] == b'/') {
                i += 1;
            }

            if i >= len {
                break;
            }

            // Parse attribute name
            let name_start = i;
            while i < len {
                let ch = bytes[i];
                if ch.is_ascii_whitespace() || ch == b'=' || ch == b'>' || ch == b'/' {
                    break;
                }
                i += 1;
            }

            if i == name_start {
                break;
            }

            let name = attr_to_parse[name_start..i].to_lowercase();

            // Skip whitespace after name
            while i < len && bytes[i].is_ascii_whitespace() {
                i += 1;
            }

            // Check for '='
            if i < len && bytes[i] == b'=' {
                i += 1; // Skip '='

                // Skip whitespace after '='
                while i < len && bytes[i].is_ascii_whitespace() {
                    i += 1;
                }

                // Parse value
                let value = if i < len {
                    let quote = bytes[i];
                    if quote == b'"' || quote == b'\'' {
                        // Quoted value
                        i += 1; // Skip opening quote
                        let val_start = i;
                        while i < len && bytes[i] != quote {
                            i += 1;
                        }
                        let val = attr_to_parse[val_start..i].to_string();
                        if i < len {
                            i += 1; // Skip closing quote
                        }
                        val
                    } else {
                        // Unquoted value
                        let val_start = i;
                        while i < len {
                            let ch = bytes[i];
                            if ch.is_ascii_whitespace() || ch == b'>' {
                                break;
                            }
                            i += 1;
                        }
                        attr_to_parse[val_start..i].to_string()
                    }
                } else {
                    String::new()
                };

                // Decode entities in attribute values
                let value = self.decode_entities(&value);
                // HTML5 spec: first attribute wins if there are duplicates
                if !attributes.contains_key(&name) {
                    attributes.insert(name, value);
                }
            } else {
                // Boolean attribute (no value)
                // HTML5 spec: first attribute wins if there are duplicates
                if !attributes.contains_key(&name) {
                    attributes.insert(name, String::new());
                }
            }
        }

        (is_self_closing, attributes)
    }

    fn handle_comment(&mut self) -> PyResult<Option<HTMLToken>> {
        self.debug(&format!("_handle_comment: pos={}, state={}", self.pos, self.state));
        self.pos += 4; // Skip <!--
        let start = self.pos;

        // Special case: <!--> already handled
        // Special case: <!--- followed by >
        if self.pos < self.length
            && self.html.as_bytes()[self.pos] == b'-'
            && self.pos + 1 < self.length
            && self.html.as_bytes()[self.pos + 1] == b'>'
        {
            self.pos += 2;
            return Ok(Some(HTMLToken::py_new(
                "Comment".to_string(),
                Some(String::new()),
                None,
                None,
                None,
                None,
                None,
            )));
        }

        // Find -->
        if let Some(end_pos) = self.html[self.pos..].find("-->") {
            let comment_text = self.html[start..self.pos + end_pos].to_string();
            let comment_text = self.replace_invalid_characters(&comment_text);
            self.pos += end_pos + 3;
            return Ok(Some(HTMLToken::py_new(
                "Comment".to_string(),
                Some(comment_text),
                None,
                None,
                None,
                None,
                None,
            )));
        }

        // Find --!>
        if let Some(end_pos) = self.html[self.pos..].find("--!>") {
            let comment_text = self.html[start..self.pos + end_pos].to_string();
            let comment_text = self.replace_invalid_characters(&comment_text);
            self.pos += end_pos + 4;
            return Ok(Some(HTMLToken::py_new(
                "Comment".to_string(),
                Some(comment_text),
                None,
                None,
                None,
                None,
                None,
            )));
        }

        // EOF - emit what we have
        let mut comment_text = self.html[start..].to_string();
        comment_text = self.replace_invalid_characters(&comment_text);

        if comment_text.ends_with("--") {
            comment_text = comment_text[..comment_text.len() - 2].to_string();
        }

        self.pos = self.length;
        Ok(Some(HTMLToken::py_new(
            "Comment".to_string(),
            Some(comment_text),
            None,
            None,
            None,
            None,
            None,
        )))
    }

    fn handle_bogus_comment(&mut self, _from_end_tag: bool) -> PyResult<Option<HTMLToken>> {
        self.debug(&format!(
            "_handle_bogus_comment: pos={}, state={}",
            self.pos, self.state
        ));

        // Handle CDATA specially
        if self.html[self.pos..].starts_with("<![CDATA[") {
            let start_pos = self.pos + 9;
            if let Some(end) = self.html[start_pos..].find("]]>") {
                let inner = self.html[start_pos..start_pos + end].to_string();
                self.pos = start_pos + end + 3;
                let inner = self.replace_invalid_characters(&inner);
                return Ok(Some(HTMLToken::py_new(
                    "Comment".to_string(),
                    Some(format!("[CDATA[{}]]", inner)),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            } else {
                let inner = self.html[start_pos..].to_string();
                self.pos = self.length;
                let inner = self.replace_invalid_characters(&inner);
                let comment_data = if inner.ends_with("]]") {
                    format!("[CDATA[{} ", inner)
                } else {
                    format!("[CDATA[{}", inner)
                };
                return Ok(Some(HTMLToken::py_new(
                    "Comment".to_string(),
                    Some(comment_data),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            }
        }

        // For <?, include the ?
        let start = if self.html[self.pos..].starts_with("<?") {
            self.pos + 1
        } else if self.html[self.pos..].starts_with("</") {
            self.pos + 2
        } else {
            self.pos + 2 // <!
        };

        // Find next >
        if let Some(gt_pos) = self.html[start..].find('>') {
            let comment_text = self.html[start..start + gt_pos].to_string();
            self.pos = start + gt_pos + 1;
            let comment_text = self.replace_invalid_characters(&comment_text);
            return Ok(Some(HTMLToken::py_new(
                "Comment".to_string(),
                Some(comment_text),
                None,
                None,
                None,
                None,
                None,
            )));
        }

        // EOF
        let comment_text = self.html[start..].to_string();
        self.pos = self.length;
        let comment_text = self.replace_invalid_characters(&comment_text);
        Ok(Some(HTMLToken::py_new(
            "Comment".to_string(),
            Some(comment_text),
            None,
            None,
            None,
            None,
            None,
        )))
    }

    fn try_text(&mut self) -> Option<HTMLToken> {
        if self.pos >= self.length {
            return None;
        }

        let start = self.pos;
        let html = &self.html;

        // Don't parse '<' as text
        if html[start..].starts_with('<') {
            return None;
        }

        // Find next '<' or EOF
        let next_lt = html[start..].find('<').map(|i| start + i);
        let end = next_lt.unwrap_or(self.length);

        if end == start {
            return None;
        }

        let text = &html[start..end];
        self.pos = end;

        // Replace invalid characters first, then decode entities
        let text = self.replace_invalid_characters(text);
        let decoded = self.decode_entities(&text);

        Some(HTMLToken::py_new(
            "Character".to_string(),
            Some(decoded),
            None,
            None,
            None,
            None,
            None,
        ))
    }
}

#[pymodule]
fn rust_tokenizer(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<HTMLToken>()?;
    m.add_class::<RustTokenizer>()?;
    Ok(())
}
