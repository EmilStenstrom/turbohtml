from dataclasses import replace

from justhtml import JustHTML
from justhtml.context import FragmentContext
from justhtml.sanitize import DEFAULT_DOCUMENT_POLICY, DEFAULT_POLICY
from justhtml.transforms import Drop, PruneEmpty, Sanitize, Unwrap


def _format_error(e):
    return {
        "category": getattr(e, "category", "parse"),
        "line": getattr(e, "line", None),
        "column": getattr(e, "column", None),
        "message": getattr(e, "message", None) or getattr(e, "code", None) or str(e),
    }


def _policy_for(node):
    base = DEFAULT_DOCUMENT_POLICY if node.name == "#document" else DEFAULT_POLICY
    return replace(base, unsafe_handling="collect")


def _sort_key(e):
    return (
        e.line if getattr(e, "line", None) is not None else 1_000_000_000,
        e.column if getattr(e, "column", None) is not None else 1_000_000_000,
    )


def _merge_sorted_errors(a, b):
    out = []
    i = 0
    j = 0
    while i < len(a) and j < len(b):
        if _sort_key(a[i]) <= _sort_key(b[j]):
            out.append(a[i])
            i += 1
        else:
            out.append(b[j])
            j += 1
    if i < len(a):
        out.extend(a[i:])
    if j < len(b):
        out.extend(b[j:])
    return out


def _dedupe_sorted_errors(errors):
    out = []
    last_key = None
    for e in errors:
        key = (
            getattr(e, "category", "parse"),
            getattr(e, "line", None),
            getattr(e, "column", None),
            getattr(e, "message", None) or getattr(e, "code", None) or str(e),
        )
        if key == last_key:
            continue
        out.append(e)
        last_key = key
    return out


def _serialize_nodes(
    nodes,
    output_format,
    safe,
    pretty,
    indent_size,
    text_separator,
    text_strip,
):
    security_errors = []

    if output_format == "html":
        parts = []
        for node in nodes:
            if safe:
                policy = _policy_for(node)
                parts.append(
                    node.to_html(
                        pretty=pretty,
                        indent_size=indent_size,
                        safe=True,
                        policy=policy,
                    )
                )
                security_errors.extend(policy.collected_security_errors())
            else:
                parts.append(node.to_html(pretty=pretty, indent_size=indent_size, safe=False))
        return ("\n".join(parts), security_errors)

    if output_format == "markdown":
        parts = []
        for node in nodes:
            if safe:
                policy = _policy_for(node)
                parts.append(node.to_markdown(safe=True, policy=policy))
                security_errors.extend(policy.collected_security_errors())
            else:
                parts.append(node.to_markdown(safe=False))
        return ("\n\n".join(parts), security_errors)

    if output_format == "text":
        parts = []
        for node in nodes:
            if safe:
                policy = _policy_for(node)
                parts.append(
                    node.to_text(
                        separator=text_separator,
                        strip=text_strip,
                        safe=True,
                        policy=policy,
                    )
                )
                security_errors.extend(policy.collected_security_errors())
            else:
                parts.append(node.to_text(separator=text_separator, strip=text_strip, safe=False))
        return ("\n".join(parts), security_errors)

    raise ValueError(f"Unknown output_format: {output_format}")


def render(
    html,
    parse_mode,
    selector,
    output_format,
    safe,
    cleanup,
    pretty,
    indent_size,
    text_separator,
    text_strip,
):
    try:
        transforms = []
        sanitize_policy = None
        if safe:
            base = DEFAULT_DOCUMENT_POLICY if parse_mode == "document" else DEFAULT_POLICY
            sanitize_policy = replace(base, unsafe_handling="collect")
            transforms.append(Sanitize(policy=sanitize_policy))

        if cleanup:
            transforms.append(Unwrap("a:not([href])"))
            transforms.append(Drop("img:not([src])"))
            transforms.append(PruneEmpty("*"))

        kwargs = {
            "collect_errors": True,
            "track_node_locations": True,
            "strict": False,
            "transforms": transforms,
        }

        if parse_mode == "fragment":
            kwargs["fragment_context"] = FragmentContext("div")

        doc = JustHTML(html, **kwargs)

        nodes = doc.query(selector) if selector else [doc.root]
        out, security_errors = _serialize_nodes(
            nodes,
            output_format=output_format,
            safe=bool(safe),
            pretty=bool(pretty),
            indent_size=int(indent_size),
            text_separator=text_separator,
            text_strip=bool(text_strip),
        )

        tree_security_errors = []
        if sanitize_policy is not None:
            tree_security_errors = sanitize_policy.collected_security_errors()

        combined = _merge_sorted_errors(
            sorted(list(doc.errors), key=_sort_key),
            sorted(list(tree_security_errors) + list(security_errors), key=_sort_key),
        )
        combined = _dedupe_sorted_errors(combined)
        errors = [_format_error(e) for e in combined]
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "output": "",
            "errors": [f"{type(e).__name__}: {e}"],
        }
    else:
        return {
            "ok": True,
            "output": out,
            "errors": errors,
        }
