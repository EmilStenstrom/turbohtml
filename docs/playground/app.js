/* global loadPyodide */

const STATUS = {
	INIT: "Loading Pyodide…",
	INSTALL: "Installing justhtml…",
	READY: "Ready.",
	RUNNING: "Running…",
};

let pyodide;
let renderFn;
let scheduledRun = null;
let uiEnabled = true;

function getRadioValue(name) {
	const el = document.querySelector(`input[name="${name}"]:checked`);
	return el ? el.value : "";
}

function escapeHtml(text) {
	return text
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#39;");
}

function highlightHtmlTag(tag) {
	// tag includes <...>
	if (tag.startsWith("<!--")) {
		return `<span class="tok-comment">${escapeHtml(tag)}</span>`;
	}

	if (tag.startsWith("<!")) {
		return `<span class="tok-punct">${escapeHtml(tag)}</span>`;
	}

	const inner = tag.slice(1, -1);
	let i = 0;
	let closing = false;
	if (inner.startsWith("/")) {
		closing = true;
		i = 1;
	}

	while (i < inner.length && inner[i] === " ") i += 1;
	const nameStart = i;
	while (i < inner.length && !" \t\n\r\f/>".includes(inner[i])) i += 1;
	const name = inner.slice(nameStart, i);
	const rest = inner.slice(i);

	let out = "";
	out += `<span class="tok-punct">&lt;${closing ? "/" : ""}</span>`;
	out += `<span class="tok-tag">${escapeHtml(name)}</span>`;

	// Highlight attributes in a conservative way (serializer output is well-formed)
	let r = rest;
	// Preserve trailing "/" before '>' if present
	const selfClose = r.trimEnd().endsWith("/");
	if (selfClose) {
		r = r.replace(/\s*\/\s*$/, "");
	}

	// Tokenize attribute region by scanning
	let j = 0;
	while (j < r.length) {
		const ch = r[j];
		if (
			ch === " " ||
			ch === "\t" ||
			ch === "\n" ||
			ch === "\r" ||
			ch === "\f"
		) {
			out += escapeHtml(ch);
			j += 1;
			continue;
		}

		// Attribute name
		const attrStart = j;
		while (j < r.length && !"= \t\n\r\f".includes(r[j])) j += 1;
		const attrName = r.slice(attrStart, j);
		out += `<span class="tok-attr">${escapeHtml(attrName)}</span>`;

		// Whitespace
		while (
			j < r.length &&
			(r[j] === " " ||
				r[j] === "\t" ||
				r[j] === "\n" ||
				r[j] === "\r" ||
				r[j] === "\f")
		) {
			out += escapeHtml(r[j]);
			j += 1;
		}

		if (j < r.length && r[j] === "=") {
			out += `<span class="tok-punct">=</span>`;
			j += 1;
			// Whitespace after '='
			while (
				j < r.length &&
				(r[j] === " " ||
					r[j] === "\t" ||
					r[j] === "\n" ||
					r[j] === "\r" ||
					r[j] === "\f")
			) {
				out += escapeHtml(r[j]);
				j += 1;
			}

			if (j < r.length && (r[j] === '"' || r[j] === "'")) {
				const quote = r[j];
				let k = j + 1;
				while (k < r.length && r[k] !== quote) k += 1;
				const value = r.slice(j, Math.min(k + 1, r.length));
				out += `<span class="tok-string">${escapeHtml(value)}</span>`;
				j = Math.min(k + 1, r.length);
			}
		}
	}

	if (selfClose) {
		out += `<span class="tok-punct"> /</span>`;
	}
	out += `<span class="tok-punct">&gt;</span>`;
	return out;
}

function highlightHtml(source) {
	const parts = source.split(/(<[^>]+>)/g);
	let out = "";
	for (const part of parts) {
		if (part.startsWith("<") && part.endsWith(">")) {
			out += highlightHtmlTag(part);
		} else {
			out += escapeHtml(part);
		}
	}
	return out;
}

function highlightMarkdown(source) {
	// Keep it intentionally minimal: headings, inline code, and link URLs.
	const lines = source.split("\n");
	const outLines = [];

	for (const line of lines) {
		let html = escapeHtml(line);

		// Headings
		const headingMatch = /^(#{1,6})\s+(.*)$/.exec(line);
		if (headingMatch) {
			const hashes = escapeHtml(headingMatch[1]);
			const text = escapeHtml(headingMatch[2]);
			html = `<span class="tok-md-heading">${hashes} ${text}</span>`;
			outLines.push(html);
			continue;
		}

		// Inline code `...`
		html = html.replace(
			/`([^`]+)`/g,
			(_m, code) => `<span class="tok-md-code">${code}</span>`,
		);
		html = html.replaceAll("", "`");

		// Links: highlight the URL part of [text](url)
		html = html.replace(
			/\]\(([^)]+)\)/g,
			(_m, url) => `](<span class="tok-md-link">${escapeHtml(url)}</span>)`,
		);

		outLines.push(html);
	}

	return outLines.join("\n");
}

function setOutput(text, format, ok) {
	const outputEl = document.getElementById("outputCode");
	if (!ok) {
		outputEl.textContent = text;
		return;
	}

	if (format === "html") {
		outputEl.innerHTML = highlightHtml(text);
		return;
	}

	if (format === "markdown") {
		outputEl.innerHTML = highlightMarkdown(text);
		return;
	}

	outputEl.textContent = text;
}

function setStatus(text) {
	document.getElementById("status").textContent = text;
}

function setEnabled(enabled) {
	uiEnabled = enabled;
	const ids = [
		"input",
		"selector",
		"safe",
		"pretty",
		"indentSize",
		"textSeparator",
		"textStrip",
	];

	for (const id of ids) {
		const el = document.getElementById(id);
		if (el) el.disabled = !enabled;
	}

	for (const el of document.querySelectorAll('input[name="parseMode"]')) {
		el.disabled = !enabled;
	}
	for (const el of document.querySelectorAll('input[name="outputFormat"]')) {
		el.disabled = !enabled;
	}
}

function scheduleRerender() {
	if (!renderFn) return;
	if (!uiEnabled) return;

	if (scheduledRun) clearTimeout(scheduledRun);
	scheduledRun = setTimeout(() => {
		scheduledRun = null;
		void run();
	}, 80);
}

function updateVisibleSettings() {
	const outputFormat = getRadioValue("outputFormat");
	const htmlSettings = document.getElementById("htmlSettings");
	const textSettings = document.getElementById("textSettings");

	htmlSettings.hidden = outputFormat !== "html";
	textSettings.hidden = outputFormat !== "text";
}

function updateFragmentControls() {
	// Fragment mode uses default div context
}

async function initPyodide() {
	setEnabled(false);
	setStatus(STATUS.INIT);

	pyodide = await loadPyodide({
		indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/",
	});

	setStatus(STATUS.INSTALL);
	await pyodide.loadPackage("micropip");

	const installCode = [
		`import micropip`,
		`await micropip.install("justhtml")`,
	].join("\n");
	await pyodide.runPythonAsync(installCode);

	const renderSource = [
		"from justhtml import JustHTML, StrictModeError",
		"from justhtml.context import FragmentContext",
		"",
		"def _serialize_nodes(nodes, output_format, safe, pretty, indent_size, text_separator, text_strip):",
		'    if output_format == "html":',
		'        return "\\n".join(',
		"            node.to_html(pretty=pretty, indent_size=indent_size, safe=safe) for node in nodes",
		"        )",
		"",
		'    if output_format == "markdown":',
		'        return "\\n\\n".join(node.to_markdown(safe=safe) for node in nodes)',
		"",
		'    if output_format == "text":',
		'        return "\\n".join(',
		"            node.to_text(separator=text_separator, strip=text_strip, safe=safe) for node in nodes",
		"        )",
		"",
		'    raise ValueError(f"Unknown output_format: {output_format}")',
		"",
		"def render(",
		"    html,",
		"    parse_mode,",
		"    selector,",
		"    output_format,",
		"    safe,",
		"    pretty,",
		"    indent_size,",
		"    text_separator,",
		"    text_strip,",
		"): ",
		"    try:",
		"        kwargs = {",
		"            'collect_errors': True,",
		"            'strict': False,",
		"        }",
		"",
		"        if parse_mode == 'fragment':",
		"            kwargs['fragment_context'] = FragmentContext('div')",
		"",
		"        doc = JustHTML(html, **kwargs)",
		"",
		"        nodes = doc.query(selector) if selector else [doc.root]",
		"        out = _serialize_nodes(",
		"            nodes,",
		"            output_format=output_format,",
		"            safe=bool(safe),",
		"            pretty=bool(pretty),",
		"            indent_size=int(indent_size),",
		"            text_separator=text_separator,",
		"            text_strip=bool(text_strip),",
		"        )",
		"",
		"        errors = []",
		"        errors = [str(e) for e in doc.errors]",
		"",
		"        return {",
		"            'ok': True,",
		"            'output': out,",
		"            'errors': errors,",
		"        }",
		"",
		"    except StrictModeError as e:",
		"        return {",
		"            'ok': False,",
		"            'output': '',",
		"            'errors': [str(e.error)],",
		"        }",
		"    except Exception as e:",
		"        return {",
		"            'ok': False,",
		"            'output': '',",
		"            'errors': [f'{type(e).__name__}: {e}'],",
		"        }",
		"",
		"render",
	].join("\n");

	renderFn = await pyodide.runPythonAsync(renderSource);

	setStatus(STATUS.READY);
	setEnabled(true);

	updateVisibleSettings();
	updateFragmentControls();
	void run();
}

async function run() {
	if (!renderFn) return;

	setStatus(STATUS.RUNNING);
	setEnabled(false);

	const html = document.getElementById("input").value;
	const parseMode = getRadioValue("parseMode");
	const selector = document.getElementById("selector").value.trim();
	const outputFormat = getRadioValue("outputFormat");

	const safe = document.getElementById("safe").checked;
	const pretty = document.getElementById("pretty").checked;
	const indentSize = document.getElementById("indentSize").value;

	const textSeparator = document.getElementById("textSeparator").value;
	const textStrip = document.getElementById("textStrip").checked;

	const result = renderFn(
		html,
		parseMode,
		selector,
		outputFormat,
		safe,
		pretty,
		indentSize,
		textSeparator,
		textStrip,
	).toJs({ dict_converter: Object.fromEntries });

	if (result.ok) {
		setOutput(result.output || "", outputFormat, true);
		setStatus(STATUS.READY);
	} else {
		const message =
			result.errors && result.errors.length > 0
				? result.errors.join("\n")
				: "Error";
		setOutput(message, "text", false);
		setStatus("Error");
	}

	setEnabled(true);
}

document.getElementById("input").addEventListener("input", scheduleRerender);
document.getElementById("selector").addEventListener("input", scheduleRerender);

for (const el of document.querySelectorAll('input[name="outputFormat"]')) {
	el.addEventListener("change", () => {
		updateVisibleSettings();
		scheduleRerender();
	});
}

for (const el of document.querySelectorAll('input[name="parseMode"]')) {
	el.addEventListener("change", () => {
		scheduleRerender();
	});
}

document.getElementById("safe").addEventListener("change", scheduleRerender);
document.getElementById("pretty").addEventListener("change", scheduleRerender);
document
	.getElementById("indentSize")
	.addEventListener("change", scheduleRerender);
document
	.getElementById("textStrip")
	.addEventListener("change", scheduleRerender);
document
	.getElementById("textSeparator")
	.addEventListener("change", scheduleRerender);

initPyodide().catch((e) => {
	setEnabled(true);
	setStatus("Init failed");
	setOutput(`Init failed: ${e}`, "text", false);
});
