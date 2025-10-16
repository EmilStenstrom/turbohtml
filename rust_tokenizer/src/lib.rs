use pyo3::prelude::*;
use pyo3::types::{PyModule, PyDict, PyIterator, PyAny};
use indexmap::IndexMap;
use std::collections::VecDeque;
use std::sync::Mutex;
use std::env;

// Static string constants for token types to avoid allocations
const TOKEN_CHARACTER: &str = "Character";
const TOKEN_START_TAG: &str = "StartTag";
const TOKEN_END_TAG: &str = "EndTag";
const TOKEN_DOCTYPE: &str = "DOCTYPE";
const TOKEN_COMMENT: &str = "Comment";

// Static string constants for tokenizer states
const STATE_DATA: &str = "DATA";
const STATE_RAWTEXT: &str = "RAWTEXT";
const STATE_PLAINTEXT: &str = "PLAINTEXT";

#[pyclass(freelist = 1024)]
pub struct HTMLToken {
    #[pyo3(get, set)]
    pub type_: String,
    #[pyo3(get, set)]
    pub data: String,
    #[pyo3(get, set)]
    pub tag_name: String,
    // Internal storage - not directly exposed to Python
    attributes_map: IndexMap<String, String>,
    // Cached Python dict - wrapped in Mutex for thread safety
    attributes_cache: Mutex<Option<Py<PyDict>>>,
    #[pyo3(get, set)]
    pub is_self_closing: bool,
    #[pyo3(get, set)]
    pub is_last_token: bool,
    #[pyo3(get, set)]
    pub needs_rawtext: bool,
    #[pyo3(get, set)]
    pub ignored_end_tag: bool,
}

enum PendingBuffer {
    Deque(VecDeque<HTMLToken>),
    Legacy(Vec<HTMLToken>),
}

impl PendingBuffer {
    fn new(use_legacy: bool) -> Self {
        if use_legacy {
            PendingBuffer::Legacy(Vec::new())
        } else {
            PendingBuffer::Deque(VecDeque::new())
        }
    }

    fn enqueue(&mut self, token: HTMLToken) {
        match self {
            PendingBuffer::Deque(queue) => queue.push_back(token),
            PendingBuffer::Legacy(queue) => queue.push(token),
        }
    }

    fn pop_front(&mut self) -> Option<HTMLToken> {
        match self {
            PendingBuffer::Deque(queue) => queue.pop_front(),
            PendingBuffer::Legacy(queue) => {
                if queue.is_empty() {
                    None
                } else {
                    Some(queue.remove(0))
                }
            }
        }
    }

    fn is_empty(&self) -> bool {
        match self {
            PendingBuffer::Deque(queue) => queue.is_empty(),
            PendingBuffer::Legacy(queue) => queue.is_empty(),
        }
    }
}

fn use_legacy_pending_buffer() -> bool {
    env::var("TURBOHTML_PENDING_BUFFER")
        .map(|value| value.eq_ignore_ascii_case("legacy"))
        .unwrap_or(false)
}

impl HTMLToken {
    // Internal Rust constructor for creating tokens
    fn new(
        type_: String,
        data: Option<String>,
        tag_name: Option<String>,
        attributes_map: Option<IndexMap<String, String>>,
        is_self_closing: Option<bool>,
        is_last_token: Option<bool>,
        needs_rawtext: Option<bool>,
    ) -> Self {
        HTMLToken {
            type_,
            data: data.unwrap_or_default(),
            tag_name: tag_name.unwrap_or_default().to_lowercase(),
            attributes_map: attributes_map.unwrap_or_default(),
            attributes_cache: Mutex::new(None),
            is_self_closing: is_self_closing.unwrap_or(false),
            is_last_token: is_last_token.unwrap_or(false),
            needs_rawtext: needs_rawtext.unwrap_or(false),
            ignored_end_tag: false,
        }
    }

    // Optimized constructors for common token types
    #[inline]
    fn new_character(data: String) -> Self {
        HTMLToken {
            type_: TOKEN_CHARACTER.to_string(),
            data,
            tag_name: String::new(),
            attributes_map: IndexMap::new(),
            attributes_cache: Mutex::new(None),
            is_self_closing: false,
            is_last_token: false,
            needs_rawtext: false,
            ignored_end_tag: false,
        }
    }

    #[inline]
    fn new_start_tag(tag_name: String, attributes_map: IndexMap<String, String>, is_self_closing: bool, needs_rawtext: bool) -> Self {
        HTMLToken {
            type_: TOKEN_START_TAG.to_string(),
            data: String::new(),
            tag_name: tag_name.to_lowercase(),
            attributes_map,
            attributes_cache: Mutex::new(None),
            is_self_closing,
            is_last_token: false,
            needs_rawtext,
            ignored_end_tag: false,
        }
    }

    #[inline]
    fn new_end_tag(tag_name: String) -> Self {
        HTMLToken {
            type_: TOKEN_END_TAG.to_string(),
            data: String::new(),
            tag_name: tag_name.to_lowercase(),
            attributes_map: IndexMap::new(),
            attributes_cache: Mutex::new(None),
            is_self_closing: false,
            is_last_token: false,
            needs_rawtext: false,
            ignored_end_tag: false,
        }
    }

    #[inline]
    fn new_comment(data: String) -> Self {
        HTMLToken {
            type_: TOKEN_COMMENT.to_string(),
            data,
            tag_name: String::new(),
            attributes_map: IndexMap::new(),
            attributes_cache: Mutex::new(None),
            is_self_closing: false,
            is_last_token: false,
            needs_rawtext: false,
            ignored_end_tag: false,
        }
    }

    #[inline]
    fn new_doctype(data: String) -> Self {
        HTMLToken {
            type_: TOKEN_DOCTYPE.to_string(),
            data,
            tag_name: String::new(),
            attributes_map: IndexMap::new(),
            attributes_cache: Mutex::new(None),
            is_self_closing: false,
            is_last_token: false,
            needs_rawtext: false,
            ignored_end_tag: false,
        }
    }
}

#[pymethods]
impl HTMLToken {
    #[new]
    #[pyo3(signature = (type_, data=None, tag_name=None, attributes=None, is_self_closing=None, is_last_token=None, needs_rawtext=None))]
    fn py_new(
        py: Python,
        type_: String,
        data: Option<String>,
        tag_name: Option<String>,
        attributes: Option<Py<PyDict>>,
        is_self_closing: Option<bool>,
        is_last_token: Option<bool>,
        needs_rawtext: Option<bool>,
    ) -> PyResult<Self> {
        let mut attributes_map = IndexMap::new();
        if let Some(attrs_dict) = attributes {
            let dict = attrs_dict.bind(py);
            // Iterate dict.items() directly to preserve insertion order (Python 3.7+)
            let items = dict.call_method0("items")?;
            let iter_obj = PyIterator::from_object(&items)?;

            for item in iter_obj {
                let item_bound = item?;
                let tuple = item_bound.downcast::<pyo3::types::PyTuple>()?;
                let key: String = tuple.get_item(0)?.extract()?;
                let val: String = tuple.get_item(1)?.extract()?;
                if !attributes_map.contains_key(&key) {
                    attributes_map.insert(key, val);
                }
            }
        }

        Ok(HTMLToken {
            type_,
            data: data.unwrap_or_default(),
            tag_name: tag_name.unwrap_or_default().to_lowercase(),
            attributes_map,
            attributes_cache: Mutex::new(None),
            is_self_closing: is_self_closing.unwrap_or(false),
            is_last_token: is_last_token.unwrap_or(false),
            needs_rawtext: needs_rawtext.unwrap_or(false),
            ignored_end_tag: false,
        })
    }

    // Custom getter for attributes: convert IndexMap to PyDict preserving order
    // Uses caching to avoid repeated conversions on multiple accesses
    #[getter]
    fn attributes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        // Check if we have a cached dict
        let mut cache = self.attributes_cache.lock().unwrap();
        if let Some(cached) = cache.as_ref() {
            // Return the cached dict
            return Ok(cached.bind(py).clone());
        }
        
        // Build the dict for the first time
        let dict = PyDict::new(py);
        for (k, v) in &self.attributes_map {
            dict.set_item(k, v)?;
        }
        
        // Cache it for future accesses
        *cache = Some(dict.clone().unbind());
        Ok(dict)
    }

    // Custom setter for attributes: convert PyDict to IndexMap preserving order
    #[setter]
    fn set_attributes(&mut self, py: Python, value: Py<PyDict>) -> PyResult<()> {
        // Clear the cache when attributes are modified
        *self.attributes_cache.lock().unwrap() = None;
        
        self.attributes_map.clear();
        let dict = value.bind(py);
        // Iterate dict.items() directly to preserve insertion order (Python 3.7+)
        let items = dict.call_method0("items")?;
        let iter_obj = PyIterator::from_object(&items)?;

        for item in iter_obj {
            let item_bound = item?;
            let tuple = item_bound.downcast::<pyo3::types::PyTuple>()?;
            let key: String = tuple.get_item(0)?.extract()?;
            let val: String = tuple.get_item(1)?.extract()?;
            self.attributes_map.insert(key, val);
        }
        Ok(())
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
    state: &'static str,
    rawtext_tag: Option<String>,
    last_pos: usize,
    env_debug: bool,
    script_content: String,
    script_non_executable: bool,
    script_suppressed_end_once: bool,
    script_type_value: String,
    pending_tokens: PendingBuffer,
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
            state: STATE_DATA,
            rawtext_tag: None,
            last_pos: length,
            env_debug: debug,
            script_content: String::new(),
            script_non_executable: false,
            script_suppressed_end_once: false,
            script_type_value: String::new(),
            pending_tokens: PendingBuffer::new(use_legacy_pending_buffer()),
        }
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> PyResult<Option<HTMLToken>> {
        loop {
            // Yield pending tokens first
            if let Some(mut token) = slf.pending_tokens.pop_front() {
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

            match slf.state {
                STATE_DATA => {
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
                STATE_RAWTEXT => {
                    if let Some(mut token) = slf.tokenize_rawtext()? {
                        slf.debug(&format!("RAWTEXT token: {}", token.type_));
                        token.is_last_token = slf.pos >= slf.last_pos;
                        return Ok(Some(token));
                    } else {
                        return Ok(None);
                    }
                }
                STATE_PLAINTEXT => {
                    if slf.pos < slf.length {
                        let raw = &slf.html[slf.pos..];
                        let data = slf.replace_invalid_characters(raw);
                        slf.pos = slf.length;
                        let mut token = HTMLToken::new_character(data);
                        token.is_last_token = true;
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
        self.state = STATE_RAWTEXT;
        self.rawtext_tag = Some(tag_name.to_lowercase());
        if self.rawtext_tag.as_deref() == Some("script") {
            self.script_content.clear();
        }
    }

    fn start_plaintext(&mut self) {
        self.state = STATE_PLAINTEXT;
        self.rawtext_tag = None;
    }

    #[getter]
    fn state(&self) -> String {
        self.state.to_string()
    }

    #[setter]
    fn set_state(&mut self, state: String) {
        // Map Python strings to static constants
        self.state = match state.as_str() {
            "DATA" => STATE_DATA,
            "RAWTEXT" => STATE_RAWTEXT,
            "PLAINTEXT" => STATE_PLAINTEXT,
            _ => STATE_DATA, // Default to DATA for unknown states
        };
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

    /// Ensure position is on a UTF-8 character boundary by moving forward if needed.
    /// This is necessary because we use byte-based indexing for performance,
    /// but Rust strings require slicing at character boundaries.
    fn ensure_char_boundary(&self, pos: usize) -> usize {
        if pos >= self.html.len() {
            return self.html.len();
        }

        // Check if we're on a character boundary
        if self.html.is_char_boundary(pos) {
            return pos;
        }

        // Move forward to the next character boundary
        // UTF-8 continuation bytes start with 10xxxxxx (0x80-0xBF)
        let mut adjusted = pos;
        while adjusted < self.html.len() && !self.html.is_char_boundary(adjusted) {
            adjusted += 1;
        }
        adjusted
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
        self.decode_entities_impl(text, false)
    }

    fn decode_entities_in_attribute(&self, text: &str) -> String {
        self.decode_entities_impl(text, true)
    }

    fn decode_entities_impl(&self, text: &str, in_attribute: bool) -> String {
        // Fast path: if no '&', no entities to decode
        if !text.contains('&') {
            return text.to_string();
        }

        // Use Python entities module for full spec compliance
        Python::with_gil(|py| {
            let entities_mod = match PyModule::import(py, "turbohtml.entities") {
                Ok(m) => m,
                Err(_) => return text.to_string(),
            };

            let decode_fn = match entities_mod.getattr("decode_entities") {
                Ok(f) => f,
                Err(_) => return text.to_string(),
            };

            match decode_fn.call1((text, in_attribute)) {
                Ok(result) => result.extract::<String>().unwrap_or_else(|_| text.to_string()),
                Err(_) => text.to_string(),
            }
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
                    return Ok(Some(HTMLToken::new_character(frag)));
                }

                let next_char = self.html.as_bytes()[i];
                if !matches!(next_char, b' ' | b'\t' | b'\n' | b'\r' | b'\x0c' | b'/' | b'>') {
                    // Not a candidate end tag - emit as text
                    self.debug("  invalid char after </script - treating as text");
                    let frag = &self.html[self.pos..];
                    self.pos = self.length;
                    let frag = self.replace_invalid_characters(frag);
                    self.script_content.push_str(&frag);
                    return Ok(Some(HTMLToken::new_character(frag)));
                }

                // Scan through attribute-like content until closing '>', handling quotes
                let mut scan = i;
                let mut saw_gt = false;
                let mut quote: Option<u8> = None;

                while scan < self.length {
                    let c = self.html.as_bytes()[scan];

                    if let Some(q) = quote {
                        if c == q {
                            quote = None;
                        }
                        scan += 1;
                        continue;
                    }

                    if c == b'"' || c == b'\'' {
                        quote = Some(c);
                        scan += 1;
                        continue;
                    }

                    if c == b'>' {
                        saw_gt = true;
                        break;
                    }

                    // If we reach a new tag opener for script, stop
                    if c == b'<' && self.html[scan..].starts_with("</script") {
                        break;
                    }

                    scan += 1;
                }

                let has_closing_gt = saw_gt;
                let i = if saw_gt { scan } else { i };

                // Build script content up to this point
                let text_before = self.html[self.pos..tag_start - 2].to_string();
                let full_content = format!("{}{}", self.script_content, text_before);

                if has_closing_gt {
                    // Complete end tag </script>
                    let mut honor = self.should_honor_script_end_tag(&full_content);

                    // Escaped comment pattern: if inside <!--<script with no -->,
                    // defer this </script> if another </script exists later
                    if Self::in_escaped_script_comment(&full_content.to_lowercase()) {
                        let rest = &self.html[i + 1..].to_lowercase();
                        if rest.contains("</script") {
                            self.debug("  escaped pattern: deferring current </script> (another later)");
                            honor = false;
                        } else {
                            self.debug("  escaped pattern: last candidate </script> will terminate script");
                        }
                    }

                    if honor {
                        self.debug("  honoring script end tag");
                        self.pos = i + 1;

                        self.state = STATE_DATA;
                        self.rawtext_tag = None;
                        self.script_content.clear();
                        self.script_suppressed_end_once = false;

                        if !text_before.is_empty() {
                            let text_before = self.replace_invalid_characters(&text_before);
                            self.pending_tokens.enqueue(HTMLToken::new_end_tag(potential_tag));
                            return Ok(Some(HTMLToken::new_character(text_before)));
                        }
                        return Ok(Some(HTMLToken::new_end_tag(potential_tag)));
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
                        self.state = STATE_DATA;
                        self.rawtext_tag = None;
                        self.script_content.clear();
                        self.script_suppressed_end_once = false;

                        if !text_before.is_empty() {
                            let text_before = self.replace_invalid_characters(&text_before);
                            self.pending_tokens.enqueue(HTMLToken::new_end_tag(potential_tag));
                            return Ok(Some(HTMLToken::new_character(text_before)));
                        }
                        return Ok(Some(HTMLToken::new_end_tag(potential_tag)));
                    } else {
                        self.debug("  suppressing partial </script (escaped comment)");
                    }
                }
            }
        }

        // Find next potential end tag or EOF
        let start = self.pos;
        let search_start = self.ensure_char_boundary(start + 1);
        if let Some(next_close) = self.html[search_start..].find("</") {
            self.pos = search_start + next_close;
        } else {
            self.pos = self.length;
        }

        let text_end = self.ensure_char_boundary(self.pos);
        let text = self.html[start..text_end].to_string();
        if !text.is_empty() {
            self.script_content.push_str(&text);
            let text = self.replace_invalid_characters(&text);
            return Ok(Some(HTMLToken::new_character(text)));
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
                self.state = STATE_DATA;
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
                    self.pending_tokens.enqueue(HTMLToken::new_end_tag(potential_tag));
                    return Ok(Some(HTMLToken::new_character(text_before)));
                }
                // No text - emit end tag directly
                return Ok(Some(HTMLToken::new_end_tag(potential_tag)));
            }
        }

        // Find next potential end tag or EOF
        let start = self.pos;
        let search_start = self.ensure_char_boundary(start + 1);
        if let Some(next_close) = self.html[search_start..].find("</") {
            self.pos = search_start + next_close;
        } else {
            self.pos = self.length;
        }

        // Return text we found
        let text_end = self.ensure_char_boundary(self.pos);
        let text = self.html[start..text_end].to_string();
        if !text.is_empty() {
            let text = self.replace_invalid_characters(&text);
            // Decode entities for RCDATA elements (title/textarea)
            let text = if matches!(self.rawtext_tag.as_deref(), Some("title") | Some("textarea")) {
                self.decode_entities(&text)
            } else {
                text
            };
            return Ok(Some(HTMLToken::new_character(text)));
        }

        Ok(None)
    }

    fn try_tag(&mut self) -> PyResult<Option<HTMLToken>> {
        // Ensure we're starting on a character boundary
        self.pos = self.ensure_char_boundary(self.pos);

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
                return Ok(Some(HTMLToken::new(
                    TOKEN_CHARACTER.to_string(),
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
            return Ok(Some(HTMLToken::new(
                TOKEN_CHARACTER.to_string(),
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
                // Ensure we're working with character boundaries
                let doctype_start = self.ensure_char_boundary(pos + 2);
                let doctype_end_check = self.ensure_char_boundary(pos + 9);
                if doctype_end_check > doctype_start && doctype_end_check - doctype_start >= 7 {
                    let chunk = &html[doctype_start..doctype_end_check];
                    if chunk.eq_ignore_ascii_case("DOCTYPE") {
                        self.pos = pos + 9;
                        // Skip whitespace
                        while self.pos < length && html.as_bytes()[self.pos].is_ascii_whitespace() {
                            self.pos += 1;
                        }
                        // Ensure we're on a character boundary after byte-level scanning
                        self.pos = self.ensure_char_boundary(self.pos);
                        // Find closing '>'
                        let search_pos = self.ensure_char_boundary(self.pos);
                        if let Some(gt_pos) = html[search_pos..].find('>') {
                            let doctype_end = self.ensure_char_boundary(search_pos + gt_pos);
                            let doctype = html[search_pos..doctype_end].trim().to_string();
                            self.pos = doctype_end + 1;
                            return Ok(Some(HTMLToken::new_doctype(doctype)));
                        } else {
                            let search_pos = self.ensure_char_boundary(self.pos);
                            let doctype = html[search_pos..].trim().to_string();
                            self.pos = length;
                            return Ok(Some(HTMLToken::new_doctype(doctype)));
                        }
                    }
                }
            }
        }

        // Handle comments (only in DATA state)
        if self.state == "DATA" && pos + 4 <= length && html[pos..].starts_with("<!--") {
            // Special case: <!--> is treated as empty comment
            if pos + 4 < length && html.as_bytes()[pos + 4] == b'>' {
                self.pos = pos + 5;
                return Ok(Some(HTMLToken::new(
                    TOKEN_COMMENT.to_string(),
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
        Ok(Some(HTMLToken::new(
            TOKEN_CHARACTER.to_string(),
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

        // First pass: scan to find the closing '>' like Python's regex [^>]*>
        // We'll check for unbalanced quotes afterwards
        while self.pos < self.length && self.html.as_bytes()[self.pos] != b'>' {
            self.pos += 1;
            attr_end = self.pos;
        }

        // Parse the attributes substring
        let attr_string = if attr_end > attr_start {
            self.html[attr_start..attr_end].trim()
        } else {
            ""
        };

        // Check for unbalanced quotes in attributes (Python's approach)
        // Count quotes, subtracting escaped ones (e.g., \" doesn't count as unbalanced)
        let dbl_count = attr_string.matches('"').count() - attr_string.matches("\\\"").count();
        let sgl_count = attr_string.matches('\'').count() - attr_string.matches("\\'").count();
        let unbalanced = (dbl_count % 2 != 0) || (sgl_count % 2 != 0);

        if unbalanced && attr_end < self.length {
            // Rescan with proper quote tracking to find the real closing '>'
            let quote_char = if dbl_count % 2 != 0 { b'"' } else { b'\'' };
            let mut in_quote = Some(quote_char);
            let mut scan = self.pos;

            while scan < self.length {
                let ch = self.html.as_bytes()[scan];

                if let Some(q) = in_quote {
                    if ch == q {
                        in_quote = None;
                    }
                } else {
                    if ch == b'"' || ch == b'\'' {
                        in_quote = Some(ch);
                    } else if ch == b'>' {
                        // Found real closing '>' outside quotes
                        break;
                    }
                }
                scan += 1;
            }

            // Update position and attributes
            attr_end = scan;
            self.pos = scan;

            // Reconstruct attr_string with extended content
            let extended_attr_string = if attr_end > attr_start {
                self.html[attr_start..attr_end].trim()
            } else {
                ""
            };

            // Check if still in quote at EOF
            if in_quote.is_some() && self.pos >= self.length {
                // Suppress tag: EOF while inside quoted attribute value
                self.pos = self.length;

                // For void elements, consume to EOF
                let is_void = matches!(
                    tag_name.as_str(),
                    "area" | "base" | "br" | "col" | "embed" | "hr" | "img" | "input" | "link" | "meta" | "param" | "source" | "track" | "wbr"
                );
                if is_void {
                    self.pos = self.length;
                }

                return Ok(Some(HTMLToken::new(
                    TOKEN_CHARACTER.to_string(),
                    Some(String::new()),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            }

            // Use extended attributes
            let (is_self_closing, attributes) = self.parse_attributes(extended_attr_string);

            if self.pos >= self.length {
                // EOF without '>' after quote balancing
                if is_end_tag {
                    return Ok(Some(HTMLToken::new_end_tag(tag_name)));
                }

                return Ok(Some(HTMLToken::new(
                    TOKEN_CHARACTER.to_string(),
                    Some(String::new()),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            }

            // Skip the '>'
            self.pos += 1;

            let token_type = if is_end_tag { "EndTag" } else { "StartTag" };

            // Check if this tag requires RAWTEXT mode
            // Per HTML5 spec: RAWTEXT elements switch tokenizer to RAWTEXT state immediately,
            // but only <textarea> defers the parser content state transition (needs_rawtext=true).
            // Other RAWTEXT elements (script, style, title, etc.) don't need deferred activation
            // because the tokenizer handles their content. This allows the parser to treat them
            // as normal elements in foreign (SVG/MathML) contexts where RAWTEXT behavior doesn't apply.
            let is_rawtext_element = !is_end_tag && matches!(
                tag_name.as_str(),
                "script" | "style" | "xmp" | "iframe" | "noembed" | "noframes" | "noscript" | "textarea" | "title"
            );

            // Only <textarea> needs deferred RAWTEXT activation (needs_rawtext=true)
            // This allows the parser to handle foreign content contexts properly
            let needs_rawtext = !is_end_tag && tag_name == "textarea";

            if is_rawtext_element {
                self.state = STATE_RAWTEXT;
                self.rawtext_tag = Some(tag_name.clone());
                if tag_name == "script" {
                    self.script_content.clear();
                }
            }

            return Ok(Some(HTMLToken::new(
                token_type.to_string(),
                None,
                Some(tag_name),
                Some(attributes),
                Some(is_self_closing),
                None,
                Some(needs_rawtext),
            )));
        }

        let (is_self_closing, attributes) = self.parse_attributes(attr_string);

        // Handle unclosed tag at EOF (no unbalanced quotes case)
        let unclosed_to_eof = self.pos >= self.length;

        if unclosed_to_eof {
            // EOF without closing '>'
            self.pos = self.length;

            if is_end_tag {
                // End tags at EOF: emit EndTag
                return Ok(Some(HTMLToken::new_end_tag(tag_name)));
            }

            // Start tags at EOF without unbalanced quotes
            if attr_string.trim().is_empty() {
                return Ok(Some(HTMLToken::new(
                    TOKEN_CHARACTER.to_string(),
                    Some(String::new()),
                    None,
                    None,
                    None,
                    None,
                    None,
                )));
            } else {
                return Ok(Some(HTMLToken::new(
                    TOKEN_CHARACTER.to_string(),
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

        // Check if this tag requires RAWTEXT mode
        // Per HTML5 spec: RAWTEXT elements switch tokenizer to RAWTEXT state immediately,
        // but only <textarea> defers the parser content state transition (needs_rawtext=true).
        // Other RAWTEXT elements (script, style, title, etc.) don't need deferred activation
        // because the tokenizer handles their content. This allows the parser to treat them
        // as normal elements in foreign (SVG/MathML) contexts where RAWTEXT behavior doesn't apply.
        let is_rawtext_element = !is_end_tag && matches!(
            tag_name.as_str(),
            "script" | "style" | "xmp" | "iframe" | "noembed" | "noframes" | "noscript" | "textarea" | "title"
        );

        // Only <textarea> needs deferred RAWTEXT activation (needs_rawtext=true)
        let needs_rawtext = !is_end_tag && tag_name == "textarea";

        if is_rawtext_element {
            self.state = STATE_RAWTEXT;
            self.rawtext_tag = Some(tag_name.clone());
            if tag_name == "script" {
                self.script_content.clear();
            }
        }

        if is_end_tag {
            Ok(Some(HTMLToken::new_end_tag(tag_name)))
        } else {
            Ok(Some(HTMLToken::new_start_tag(tag_name, attributes, is_self_closing, needs_rawtext)))
        }
    }

    fn parse_attributes(&self, attr_string: &str) -> (bool, IndexMap<String, String>) {
        let mut attributes = IndexMap::new();

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

                // Decode entities in attribute values with spec-compliant rules
                let value = self.decode_entities_in_attribute(&value);
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
            return Ok(Some(HTMLToken::new(
                TOKEN_COMMENT.to_string(),
                Some(String::new()),
                None,
                None,
                None,
                None,
                None,
            )));
        }

        // Find -->
        let search_pos = self.ensure_char_boundary(self.pos);
        if let Some(end_pos) = self.html[search_pos..].find("-->") {
            let comment_end = self.ensure_char_boundary(search_pos + end_pos);
            let comment_text = self.html[start..comment_end].to_string();
            let comment_text = self.replace_invalid_characters(&comment_text);
            self.pos = comment_end + 3;
            return Ok(Some(HTMLToken::new_comment(comment_text)));
        }

        // Find --!>
        let search_pos = self.ensure_char_boundary(self.pos);
        if let Some(end_pos) = self.html[search_pos..].find("--!>") {
            let comment_end = self.ensure_char_boundary(search_pos + end_pos);
            let comment_text = self.html[start..comment_end].to_string();
            let comment_text = self.replace_invalid_characters(&comment_text);
            self.pos = comment_end + 4;
            return Ok(Some(HTMLToken::new_comment(comment_text)));
        }

        // EOF - emit what we have
        let mut comment_text = self.html[start..].to_string();
        comment_text = self.replace_invalid_characters(&comment_text);

        if comment_text.ends_with("--") {
            comment_text = comment_text[..comment_text.len() - 2].to_string();
        }

        self.pos = self.length;
        Ok(Some(HTMLToken::new_comment(comment_text)))
    }

    fn handle_bogus_comment(&mut self, _from_end_tag: bool) -> PyResult<Option<HTMLToken>> {
        self.debug(&format!(
            "_handle_bogus_comment: pos={}, state={}",
            self.pos, self.state
        ));

        // Handle CDATA specially
        if self.html[self.pos..].starts_with("<![CDATA[") {
            let start_pos = self.ensure_char_boundary(self.pos + 9);
            let search_pos = self.ensure_char_boundary(start_pos);
            if let Some(end) = self.html[search_pos..].find("]]>") {
                let inner_end = self.ensure_char_boundary(search_pos + end);
                let inner = self.html[start_pos..inner_end].to_string();
                self.pos = inner_end + 3;
                let inner = self.replace_invalid_characters(&inner);
                return Ok(Some(HTMLToken::new(
                    TOKEN_COMMENT.to_string(),
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
                return Ok(Some(HTMLToken::new_comment(comment_data)));
            }
        }

        // For <?, include the ?
        let start = if self.html[self.pos..].starts_with("<?") {
            self.ensure_char_boundary(self.pos + 1)
        } else if self.html[self.pos..].starts_with("</") {
            self.ensure_char_boundary(self.pos + 2)
        } else {
            self.ensure_char_boundary(self.pos + 2) // <!
        };

        // Find next >
        let search_start = self.ensure_char_boundary(start);
        if let Some(gt_pos) = self.html[search_start..].find('>') {
            let comment_end = self.ensure_char_boundary(search_start + gt_pos);
            let comment_text = self.html[start..comment_end].to_string();
            self.pos = comment_end + 1;
            let comment_text = self.replace_invalid_characters(&comment_text);
            return Ok(Some(HTMLToken::new_comment(comment_text)));
        }

        // EOF
        let comment_text = self.html[start..].to_string();
        self.pos = self.length;
        let comment_text = self.replace_invalid_characters(&comment_text);
        Ok(Some(HTMLToken::new_comment(comment_text)))
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

        Some(HTMLToken::new_character(decoded))
    }
}

#[pymodule]
fn rust_tokenizer(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<HTMLToken>()?;
    m.add_class::<RustTokenizer>()?;
    Ok(())
}
