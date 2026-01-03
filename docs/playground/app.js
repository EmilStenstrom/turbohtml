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

function isGitHubPages() {
	const host = window.location.hostname;
	return host === "github.io" || host.endsWith(".github.io");
}

async function installJusthtmlFromPyPI(pyodideInstance) {
	await pyodideInstance.loadPackage("micropip");
	await pyodideInstance.runPythonAsync(
		[`import micropip`, `await micropip.install("justhtml")`].join("\n"),
	);
}

async function installJusthtmlFromLocalRepo(pyodideInstance) {
	// Load the local working tree version of justhtml by fetching the sources
	// from the repo and writing them into Pyodide's virtual filesystem.
	// This requires serving the repository root over HTTP.
	const baseUrl = new URL("/src/justhtml/", window.location.href).toString();
	const files = [
		"__init__.py",
		"__main__.py",
		"constants.py",
		"context.py",
		"encoding.py",
		"entities.py",
		"errors.py",
		"node.py",
		"parser.py",
		"sanitize.py",
		"selector.py",
		"serialize.py",
		"stream.py",
		"tokenizer.py",
		"tokens.py",
		"treebuilder.py",
		"treebuilder_modes.py",
		"treebuilder_utils.py",
	];

	const rootDir = "/justhtml_local/justhtml";
	pyodideInstance.FS.mkdirTree(rootDir);

	for (const file of files) {
		const res = await fetch(`${baseUrl}${file}`, { cache: "no-store" });
		if (!res.ok) {
			throw new Error(
				`Failed to fetch local justhtml source: ${file} (${res.status})`,
			);
		}
		const content = await res.text();
		pyodideInstance.FS.writeFile(`${rootDir}/${file}`, content);
	}

	await pyodideInstance.runPythonAsync(
		["import sys", "sys.path.insert(0, '/justhtml_local')"].join("\n"),
	);
}

async function installJusthtml(pyodideInstance) {
	// Use released builds on GitHub Pages, otherwise prefer the local working tree.
	if (isGitHubPages()) {
		await installJusthtmlFromPyPI(pyodideInstance);
		return;
	}

	await installJusthtmlFromLocalRepo(pyodideInstance);
}

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

function setErrors(errors) {
	const el = document.getElementById("errors");
	if (!el) return;

	el.innerHTML = "";

	if (!errors || errors.length === 0) {
		const empty = document.createElement("div");
		empty.className = "error-empty";
		empty.textContent = "No errors detected.";
		el.appendChild(empty);
		return;
	}

	for (const err of errors) {
		const row = document.createElement("div");
		row.className = "error-row";

		const loc = document.createElement("div");
		loc.className = "error-loc";
		const l = err.line !== null ? err.line : "?";
		const c = err.column !== null ? err.column : "?";
		loc.textContent = `${l}:${c}`;

		const cat = document.createElement("div");
		cat.className = `error-cat cat-${err.category}`;
		cat.textContent = err.category;

		const msg = document.createElement("div");
		msg.className = "error-msg";
		msg.textContent = err.message;

		row.appendChild(loc);
		row.appendChild(cat);
		row.appendChild(msg);
		el.appendChild(row);
	}
}

function setStatus(text) {
	document.getElementById("status").textContent = text;
}

function formatInitError(err) {
	if (err && typeof err === "object") {
		const name = err.name || (err.constructor ? err.constructor.name : "Error");
		const message = err.message ? String(err.message) : "";
		const stack = err.stack ? String(err.stack) : "";

		let out = `${name}${message ? `: ${message}` : ""}`;
		if (stack && !stack.includes(out)) out += `\n\n${stack}`;

		if (name === "SecurityError") {
			out +=
				"\n\nHint: this usually happens when running from `file://` or when the browser blocks local file access. Serve the repo over HTTP (for example `python -m http.server` from the repo root) and open the playground via `http://localhost/...`.";
		}

		if (
			name === "TypeError" &&
			message.toLowerCase().includes("failed to fetch")
		) {
			out +=
				"\n\nHint: local mode fetches `/src/justhtml/*.py` from the same origin. Make sure you are serving the repository root over HTTP and not only the `docs/` folder.";
		}

		return out;
	}

	return String(err);
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
	await installJusthtml(pyodide);

	const renderSource = [
		"from justhtml import JustHTML, StrictModeError",
		"from justhtml.context import FragmentContext",
		"from dataclasses import replace",
		"from justhtml.sanitize import DEFAULT_POLICY, DEFAULT_DOCUMENT_POLICY",
		"",
		"def _format_error(e):",
		"    return {",
		"        'category': getattr(e, 'category', 'parse'),",
		"        'line': getattr(e, 'line', None),",
		"        'column': getattr(e, 'column', None),",
		"        'message': getattr(e, 'message', None) or getattr(e, 'code', None) or str(e)",
		"    }",
		"",
		"def _policy_for(node):",
		"    base = DEFAULT_DOCUMENT_POLICY if node.name == '#document' else DEFAULT_POLICY",
		"    return replace(base, unsafe_handling='collect')",
		"",
		"def _sort_key(e):",
		"    return (",
		"        e.line if getattr(e, 'line', None) is not None else 1_000_000_000,",
		"        e.column if getattr(e, 'column', None) is not None else 1_000_000_000,",
		"    )",
		"",
		"def _merge_sorted_errors(a, b):",
		"    out = []",
		"    i = 0",
		"    j = 0",
		"    while i < len(a) and j < len(b):",
		"        if _sort_key(a[i]) <= _sort_key(b[j]):",
		"            out.append(a[i])",
		"            i += 1",
		"        else:",
		"            out.append(b[j])",
		"            j += 1",
		"    if i < len(a):",
		"        out.extend(a[i:])",
		"    if j < len(b):",
		"        out.extend(b[j:])",
		"    return out",
		"",
		"def _serialize_nodes(nodes, output_format, safe, pretty, indent_size, text_separator, text_strip):",
		"    security_errors = []",
		"",
		"    if output_format == 'html':",
		"        parts = []",
		"        for node in nodes:",
		"            if safe:",
		"                policy = _policy_for(node)",
		"                parts.append(node.to_html(pretty=pretty, indent_size=indent_size, safe=True, policy=policy))",
		"                security_errors.extend(policy.collected_security_errors())",
		"            else:",
		"                parts.append(node.to_html(pretty=pretty, indent_size=indent_size, safe=False))",
		"        return ('\\n'.join(parts), security_errors)",
		"",
		"    if output_format == 'markdown':",
		"        parts = []",
		"        for node in nodes:",
		"            if safe:",
		"                policy = _policy_for(node)",
		"                parts.append(node.to_markdown(safe=True, policy=policy))",
		"                security_errors.extend(policy.collected_security_errors())",
		"            else:",
		"                parts.append(node.to_markdown(safe=False))",
		"        return ('\\n\\n'.join(parts), security_errors)",
		"",
		"    if output_format == 'text':",
		"        parts = []",
		"        for node in nodes:",
		"            if safe:",
		"                policy = _policy_for(node)",
		"                parts.append(node.to_text(separator=text_separator, strip=text_strip, safe=True, policy=policy))",
		"                security_errors.extend(policy.collected_security_errors())",
		"            else:",
		"                parts.append(node.to_text(separator=text_separator, strip=text_strip, safe=False))",
		"        return ('\\n'.join(parts), security_errors)",
		"",
		"    raise ValueError(f'Unknown output_format: {output_format}')",
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
		"            'track_node_locations': True,",
		"            'strict': False,",
		"        }",
		"",
		"        if parse_mode == 'fragment':",
		"            kwargs['fragment_context'] = FragmentContext('div')",
		"",
		"        doc = JustHTML(html, **kwargs)",
		"",
		"        nodes = doc.query(selector) if selector else [doc.root]",
		"        out, security_errors = _serialize_nodes(",
		"            nodes,",
		"            output_format=output_format,",
		"            safe=bool(safe),",
		"            pretty=bool(pretty),",
		"            indent_size=int(indent_size),",
		"            text_separator=text_separator,",
		"            text_strip=bool(text_strip),",
		"        )",
		"",
		"        combined = _merge_sorted_errors(list(doc.errors), list(security_errors))",
		"        errors = [_format_error(e) for e in combined]",
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
		"            'errors': [_format_error(e.error)],",
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
		setErrors(result.errors || []);
		setStatus(STATUS.READY);
	} else {
		const message =
			result.errors && result.errors.length > 0
				? result.errors.join("\n")
				: "Error";
		setOutput(message, "text", false);
		setErrors(result.errors || []);
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
	setOutput(`Init failed:\n\n${formatInitError(e)}`, "text", false);
});
