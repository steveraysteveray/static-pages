#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from jinja2 import BaseLoader, Environment, select_autoescape
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

QUDT = Namespace("http://qudt.org/schema/qudt/")
DCTERMS = Namespace("http://purl.org/dc/terms/")

# -----------------------------
# HTML templates
# -----------------------------

PAGE_TMPL = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ title }}</title>

  <!-- MathJax (LaTeX rendering) -->
  <script>
    window.MathJax = {
      tex: {
        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
        displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
        processEscapes: true
      },
      options: {
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      }
    };
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>

  <style>
    body { font-family: Calibri, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; line-height: 1.35; }
    header { margin-bottom: 1.25rem; }
    .meta { color: #555; font-size: 0.95rem; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border: 1px solid #ddd; padding: 0.6rem 0.7rem; vertical-align: top; }
    th { text-align: left; background: #f7f7f7; width: 18rem; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    a { text-decoration: none; }
    a:hover { text-decoration: underline; }
    .small { font-size: 0.9rem; color: #666; }
    .prewrap { white-space: pre-wrap; }
    .tiny { font-size: 0.75rem; color: #888; margin-top: 2rem; }
  </style>
</head>
<body>
<header>
  <h1>{{ subject_display|safe }}</h1>
  <div class="meta">
    <a href="{{ index_href }}">← Index</a>
    {% if types %}
      <div class="small">rdf:type:
        {% for t in types %}
          {{ t|safe }}{% if not loop.last %}, {% endif %}
        {% endfor %}
      </div>
    {% endif %}
  </div>
</header>

<table>
  <thead><tr><th>Predicate</th><th>Object</th></tr></thead>
  <tbody>
  {% for p, o in triples %}
    <tr>
      <td>{{ p|safe }}</td>
      <td>{{ o|safe }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<div class="tiny">Generated {{ generated_at }}</div>
</body>
</html>
"""

INDEX_TMPL = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ title }}</title>
  <style>
    body { font-family: Calibri, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; }
    input { width: 100%; padding: 0.6rem; font-size: 1rem; margin: 1rem 0; }
    ul { padding-left: 1.2rem; }
    li { margin: 0.35rem 0; }
    .meta { color:#555; }
    .curie { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .label { color:#333; margin-left: 0.5rem; }
    .deprecated { color:#8a2c2c; margin-left: 0.5rem; font-weight: 600; }
    .replacement { color:#8a2c2c; margin-left: 0.25rem; font-weight: 600; }
    .tiny { font-size: 0.75rem; color: #888; margin-top: 2rem; }
  </style>
</head>
<body>
<h1>{{ title }}</h1>
<div class="meta">{{ count }} resources</div>

<input id="q" placeholder="Filter…" />

<ul id="list">
{% for item in items %}
  <li data-key="{{ item.key }}{% if item.deprecated %} deprecated{% endif %}">
    <a href="{{ item.href }}"><span class="curie">{{ item.curie }}</span></a>
    {% if item.label %}<span class="label">{{ item.label }}</span>{% endif %}
    {% if item.deprecated %}
      <span class="deprecated">Deprecated</span>{% if item.replaced_by_html %}<span class="replacement">, use {{ item.replaced_by_html|safe }}</span>{% endif %}
    {% endif %}
  </li>
{% endfor %}
</ul>

<div class="tiny">Generated {{ generated_at }}</div>

<script>
  const q = document.getElementById('q');
  const list = document.getElementById('list');
  const items = Array.from(list.querySelectorAll('li'));
  q.addEventListener('input', () => {
    const needle = q.value.toLowerCase();
    for (const li of items) {
      const key = li.getAttribute('data-key');
      li.style.display = key.includes(needle) ? '' : 'none';
    }
  });
</script>
</body>
</html>
"""

# -----------------------------
# Prefix handling
# -----------------------------

PREFIX_LINE = re.compile(r"^\s*@prefix\s+([A-Za-z_][\w.-]*)\s*:\s*<([^>]+)>\s*\.\s*$")


def parse_prefix_map_from_turtle(ttl_text: str) -> Dict[str, str]:
    prefix_map: Dict[str, str] = {}
    for line in ttl_text.splitlines():
        m = PREFIX_LINE.match(line)
        if m:
            prefix_map[m.group(1)] = m.group(2)
    return prefix_map


def bind_prefix_map(g: Graph, prefix_map: Dict[str, str]) -> None:
    for pfx, ns in prefix_map.items():
        g.namespace_manager.bind(pfx, Namespace(ns), override=True, replace=True)


def try_curie_parts(g: Graph, uri: URIRef, prefix_map: Dict[str, str]) -> Optional[Tuple[str, str, str]]:
    u = str(uri)
    for pfx, ns in sorted(prefix_map.items(), key=lambda kv: len(kv[1]), reverse=True):
        if u.startswith(ns):
            return pfx, ns, u[len(ns) :]
    try:
        prefix, namespace, local = g.namespace_manager.compute_qname(uri)
        return prefix, str(namespace), local
    except Exception:
        return None


def render_uri(g: Graph, uri: URIRef, prefix_map: Dict[str, str]) -> str:
    parts = try_curie_parts(g, uri, prefix_map)
    if parts and parts[0] in prefix_map:
        prefix, namespace, local = parts
        curie = f"{prefix}:{local}"
        href = namespace + local
        return f"<a href='{html.escape(href, quote=True)}'><code>{html.escape(curie)}</code></a>"

    full = str(uri)
    return f"<a href='{html.escape(full, quote=True)}'>{html.escape(full, quote=False)}</a>"


def linkified_curie_or_iri(g: Graph, uri: URIRef, prefix_map: Dict[str, str]) -> str:
    parts = try_curie_parts(g, uri, prefix_map)
    href = str(uri)
    if parts and parts[0] in prefix_map:
        display = f"{parts[0]}:{parts[2]}"
        return (
            f"<a href='{html.escape(href, quote=True)}'>"
            f"<span class='curie'>{html.escape(display, quote=False)}</span></a>"
        )
    return f"<a href='{html.escape(href, quote=True)}'>{html.escape(href, quote=False)}</a>"


# -----------------------------
# LaTeX rendering support
# -----------------------------

_LATEX_HINTS = ("\\cdot", "\\frac", "\\sqrt", "\\mathrm", "\\mathbf", "\\left", "\\right", "\\times", "\\pm")


def looks_like_latex(s: str) -> bool:
    t = s.strip()
    if not t:
        return False
    return "$" in t or any(h in t for h in _LATEX_HINTS) or t.startswith("\\(") or t.startswith("\\[")


def is_qudt_latex_string(g: Graph, lit: Literal, prefix_map: Dict[str, str]) -> bool:
    if not lit.datatype:
        return False
    dt_uri = URIRef(lit.datatype)
    parts = try_curie_parts(g, dt_uri, prefix_map)
    if parts and parts[2] == "LatexString":
        return True
    return str(dt_uri).rstrip("/#").endswith("LatexString")


def convert_dollar_math_to_mathjax(s: str) -> str:
    out: list[str] = []
    i = 0
    n = len(s)

    def is_escaped(pos: int) -> bool:
        k = pos - 1
        bs = 0
        while k >= 0 and s[k] == "\\":
            bs += 1
            k -= 1
        return (bs % 2) == 1

    while i < n:
        if s[i] == "$" and not is_escaped(i):
            if i + 1 < n and s[i + 1] == "$" and not is_escaped(i + 1):
                j = i + 2
                while j + 1 < n:
                    if s[j] == "$" and s[j + 1] == "$" and not is_escaped(j) and not is_escaped(j + 1):
                        out.append("\\[" + s[i + 2 : j] + "\\]")
                        i = j + 2
                        break
                    j += 1
                else:
                    out.append("$")
                    i += 1
                continue

            j = i + 1
            while j < n:
                if s[j] == "$" and not is_escaped(j):
                    out.append("\\(" + s[i + 1 : j] + "\\)")
                    i = j + 1
                    break
                j += 1
            else:
                out.append("$")
                i += 1
            continue

        out.append(s[i])
        i += 1

    return "".join(out)


# -----------------------------
# “Gospel numeric” capture
# -----------------------------

NUMERIC_TOKEN_RE = re.compile(r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?")

_NUMERIC_DT_URIS = {
    str(XSD.integer),
    str(XSD.decimal),
    str(XSD.double),
    str(XSD.float),
}


def _decimal_or_none(s: str) -> Optional[Decimal]:
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


NumericSig = Tuple[str, str, Union[int, Tuple[int, Tuple[int, ...], int], str]]
# (datatype_uri_str, kind, value)
#   kind: "int" -> int
#         "decimal" -> Decimal.as_tuple()
#         "float" -> float.hex() string


def literal_numeric_signature(lit: Literal) -> Optional[NumericSig]:
    dt = str(lit.datatype) if lit.datatype else ""
    if dt and dt not in _NUMERIC_DT_URIS:
        return None

    py = lit.toPython()
    # exclude bool (bool is subclass of int)
    if isinstance(py, bool):
        return None
    if isinstance(py, int):
        return (dt, "int", py)
    if isinstance(py, Decimal):
        return (dt, "decimal", py.as_tuple())
    if isinstance(py, float):
        return (dt, "float", py.hex())

    # fallback: if it looks numeric, treat as decimal signature by parsing its string
    lex = str(lit).strip()
    if not NUMERIC_TOKEN_RE.fullmatch(lex):
        return None
    d = _decimal_or_none(lex)
    if d is None:
        return None
    return (dt, "decimal", d.as_tuple())


def occ_matches_literal(occ_lexeme: str, lit: Literal) -> bool:
    """
    Decide whether a numeric lexeme from the file corresponds to an rdflib Literal.
    Handles float-rounding cases by matching using float(Decimal(lexeme)) when lit.toPython() is float.
    """
    d = _decimal_or_none(occ_lexeme)
    if d is None:
        return False

    py = lit.toPython()
    if isinstance(py, bool):
        return False
    if isinstance(py, int):
        # only match if lexeme is integral
        try:
            return d == d.to_integral_value() and int(d) == py
        except Exception:
            return False
    if isinstance(py, Decimal):
        return py == d
    if isinstance(py, float):
        try:
            return py == float(d)
        except Exception:
            return False

    # fallback (string-based) last resort
    try:
        return _decimal_or_none(str(lit).strip()) == d
    except Exception:
        return False


@dataclass(frozen=True)
class NumericOccurrence:
    subject_token: str
    pred_token: str
    lexeme: str
    bnode_depth: int
    line_no: int


def scan_numeric_occurrences(ttl_text: str) -> List[NumericOccurrence]:
    """
    Conservative scanner:
      - ignores numbers inside triple-double-quote and triple-single-quote blocks
      - tracks current top-level subject token
      - finds: predicate <ws> numeric  followed by ; , or .
    """
    occurrences: List[NumericOccurrence] = []

    pred_re = r"(?P<pred>(?:[A-Za-z_][\w.-]*:[\w.-]+)|(?:<[^>]+>))"
    num_re = r"(?P<num>[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?)"
    pat = re.compile(rf"\b{pred_re}\b[ \t]+{num_re}\s*(?=[;,.])")

    delim: Optional[str] = None
    bracket_depth = 0
    current_subject: Optional[str] = None

    for idx, raw in enumerate(ttl_text.splitlines(), start=1):
        line = raw.rstrip("\n")

        in_before = delim is not None

        # toggle long-string state (triple quotes)
        i = 0
        while i < len(line):
            next_d = None
            next_pos = None
            for dmark in ('"""', "'''"):
                pos = line.find(dmark, i)
                if pos != -1 and (next_pos is None or pos < next_pos):
                    next_d, next_pos = dmark, pos
            if next_d is None or next_pos is None:
                break
            if delim is None:
                delim = next_d
            elif delim == next_d:
                delim = None
            i = next_pos + 3

        in_after = delim is not None
        line_in_long_string = in_before or in_after

        if not line_in_long_string:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("@"):
                if not line[:1].isspace():
                    current_subject = stripped.split()[0]

        if not line_in_long_string:
            bracket_depth += line.count("[")
            bracket_depth -= line.count("]")

        if line_in_long_string or not current_subject:
            continue

        for m in pat.finditer(line):
            occurrences.append(
                NumericOccurrence(
                    subject_token=current_subject,
                    pred_token=m.group("pred"),
                    lexeme=m.group("num"),
                    bnode_depth=max(bracket_depth, 0),
                    line_no=idx,
                )
            )

    return occurrences


def resolve_token_to_uri(token: str, prefix_map: Dict[str, str]) -> Optional[URIRef]:
    if token.startswith("<") and token.endswith(">"):
        return URIRef(token[1:-1])
    if ":" in token:
        pfx, local = token.split(":", 1)
        if pfx in prefix_map:
            return URIRef(prefix_map[pfx] + local)
    return None


def subjects_in_graph(g: Graph) -> List[URIRef]:
    seen: set[URIRef] = set()
    out: list[URIRef] = []
    for s in g.subjects():
        if isinstance(s, URIRef) and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def compute_literal_paths(
    g: Graph,
    subject: URIRef,
    max_depth: int = 4,
) -> Dict[Tuple[URIRef, ...], List[Literal]]:
    results: Dict[Tuple[URIRef, ...], List[Literal]] = defaultdict(list)

    q = deque([(subject, tuple())])
    visited = set([(subject, tuple())])

    while q:
        node, path = q.popleft()
        if len(path) >= max_depth:
            continue
        for p, o in g.predicate_objects(node):
            if not isinstance(p, URIRef):
                continue
            new_path = path + (p,)
            if isinstance(o, Literal):
                results[new_path].append(o)
            elif isinstance(o, (URIRef, BNode)):
                key = (o, new_path)
                if key not in visited:
                    visited.add(key)
                    q.append((o, new_path))

    return results


GospelKey = Tuple[URIRef, Tuple[URIRef, ...], NumericSig]


def build_gospel_lexeme_map(
    g: Graph,
    ttl_text: str,
    prefix_map: Dict[str, str],
    max_depth: int = 4,
) -> Dict[GospelKey, str]:
    """
    Build mapping: (subject, predicate-path, literal-numeric-signature) -> exact numeric lexeme from file.

    Matching uses occ_matches_literal(), which handles float-rounding cases by comparing against float(Decimal(lexeme)).
    """
    occs = scan_numeric_occurrences(ttl_text)

    token_to_subject_uri: Dict[str, URIRef] = {}
    for s in subjects_in_graph(g):
        parts = try_curie_parts(g, s, prefix_map)
        if parts and parts[0] in prefix_map:
            token_to_subject_uri[f"{parts[0]}:{parts[2]}"] = s
        token_to_subject_uri[f"<{str(s)}>"] = s

    subject_paths: Dict[URIRef, Dict[Tuple[URIRef, ...], List[Literal]]] = {}
    for s in subjects_in_graph(g):
        subject_paths[s] = compute_literal_paths(g, s, max_depth=max_depth)

    gospel: Dict[GospelKey, str] = {}

    for occ in occs:
        subj = token_to_subject_uri.get(occ.subject_token)
        if subj is None:
            continue
        pred_uri = resolve_token_to_uri(occ.pred_token, prefix_map)
        if pred_uri is None:
            continue

        paths = subject_paths.get(subj, {})
        candidate_paths = [p for p in paths.keys() if p and p[-1] == pred_uri]
        if not candidate_paths:
            continue
        candidate_paths.sort(key=lambda p: (len(p), p))

        matched = False
        for path in candidate_paths:
            for lit in paths.get(path, []):
                sig = literal_numeric_signature(lit)
                if sig is None:
                    continue
                if occ_matches_literal(occ.lexeme, lit):
                    key: GospelKey = (subj, path, sig)
                    if key not in gospel:
                        gospel[key] = occ.lexeme
                    matched = True
                    break
            if matched:
                break

    return gospel


# -----------------------------
# Rendering
# -----------------------------

def render_literal(
    g: Graph,
    subject: URIRef,
    path: Tuple[URIRef, ...],
    lit: Literal,
    prefix_map: Dict[str, str],
    gospel: Dict[GospelKey, str],
) -> str:
    sig = literal_numeric_signature(lit)
    if sig is not None:
        key: GospelKey = (subject, path, sig)
        lex = gospel.get(key)
        if lex is not None:
            return f"<span class='prewrap'>{html.escape(lex, quote=False)}</span>"
        # fallback: show unquoted numeric form rdflib provides
        return f"<span class='prewrap'>{html.escape(str(lit).strip(), quote=False)}</span>"

    raw = str(lit)

    if lit.datatype and URIRef(lit.datatype) == XSD.anyURI:
        href = html.escape(raw, quote=True)
        text = html.escape(raw, quote=False)
        return f"<a href='{href}' class='prewrap'>{text}</a>"

    if is_qudt_latex_string(g, lit, prefix_map) or looks_like_latex(raw):
        converted = convert_dollar_math_to_mathjax(raw)
        return f"<span class='prewrap'>{html.escape(converted, quote=False)}</span>"

    s = f"“{html.escape(raw, quote=False)}”"
    if lit.language:
        s += f"<span class='small'>@{html.escape(lit.language)}</span>"
    return f"<span class='prewrap'>{s}</span>"


def render_object(
    g: Graph,
    subject: URIRef,
    path: Tuple[URIRef, ...],
    o: Any,
    prefix_map: Dict[str, str],
    gospel: Dict[GospelKey, str],
) -> str:
    if isinstance(o, URIRef):
        return render_uri(g, o, prefix_map)
    if isinstance(o, Literal):
        return render_literal(g, subject, path, o, prefix_map, gospel)
    if isinstance(o, BNode):
        return ""
    return html.escape(str(o))


def expand_bnode(
    g: Graph,
    subject: URIRef,
    start_path: Tuple[URIRef, ...],
    bn: BNode,
    prefix_map: Dict[str, str],
    gospel: Dict[GospelKey, str],
    max_depth: int = 2,
) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    if max_depth <= 0:
        return rows

    for p, o in g.predicate_objects(bn):
        if not isinstance(p, URIRef):
            continue
        pred_disp = render_uri(g, p, prefix_map)
        new_path = start_path + (p,)
        if isinstance(o, BNode):
            rows.append((f"↳ {pred_disp}", ""))
            rows.extend(expand_bnode(g, subject, new_path, o, prefix_map, gospel, max_depth=max_depth - 1))
        else:
            rows.append((f"↳ {pred_disp}", render_object(g, subject, new_path, o, prefix_map, gospel)))
    return rows


def subject_rows(
    g: Graph,
    subject: URIRef,
    prefix_map: Dict[str, str],
    gospel: Dict[GospelKey, str],
    bnode_expand_depth: int = 2,
) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for p, o in g.predicate_objects(subject):
        if not isinstance(p, URIRef):
            continue
        pred_disp = render_uri(g, p, prefix_map)
        path = (p,)
        if isinstance(o, BNode):
            rows.append((pred_disp, ""))  # hide bnode identifier
            rows.extend(expand_bnode(g, subject, path, o, prefix_map, gospel, max_depth=bnode_expand_depth))
        else:
            rows.append((pred_disp, render_object(g, subject, path, o, prefix_map, gospel)))
    return rows


# -----------------------------
# Index helpers
# -----------------------------

def best_label_for_subject(g: Graph, s: URIRef) -> str:
    labels = [o for o in g.objects(s, RDFS.label) if isinstance(o, Literal)]
    for lit in labels:
        if (lit.language or "").lower() == "en":
            return str(lit)
    for lit in labels:
        if lit.language is None:
            return str(lit)
    return ""


def is_deprecated(g: Graph, s: URIRef) -> bool:
    for o in g.objects(s, QUDT.deprecated):
        if isinstance(o, Literal) and (str(o).strip().lower() in {"true", "1", "yes"} or o.value is True):
            return True
    return False


def replacement_link_html(g: Graph, s: URIRef, prefix_map: Dict[str, str]) -> Optional[str]:
    for o in g.objects(s, DCTERMS.isReplacedBy):
        if isinstance(o, URIRef):
            return linkified_curie_or_iri(g, o, prefix_map)
    return None


# -----------------------------
# Main
# -----------------------------

def slugify(s: str) -> str:
    keep = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_", "."):
            keep.append(ch)
        elif ch in (":", "/", "#"):
            keep.append("_")
        else:
            keep.append("_")
    out = "".join(keep).strip("_")
    return out or "resource"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate per-resource static HTML pages from Turtle RDF.")
    ap.add_argument("input", help="Input Turtle RDF file")
    ap.add_argument("--format", default=None, help="Optional RDFLib parser format (default: autodetect)")
    ap.add_argument("--out", default="site", help="Output directory for static HTML")
    ap.add_argument("--title", default="RDF Index", help="Title for the index page")
    ap.add_argument("--gospel-max-depth", type=int, default=4, help="Max predicate-path depth for gospel numeric matching")
    ap.add_argument("--bnode-expand-depth", type=int, default=2, help="How many bnode hops to expand in HTML")
    args = ap.parse_args()

    generated_at = datetime.now().astimezone().isoformat(timespec="milliseconds")

    inp = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ttl_text = inp.read_text(encoding="utf-8")
    prefix_map = parse_prefix_map_from_turtle(ttl_text)

    g = Graph()
    g.parse(str(inp), format=args.format)
    bind_prefix_map(g, prefix_map)

    gospel = build_gospel_lexeme_map(g, ttl_text, prefix_map, max_depth=args.gospel_max_depth)

    env = Environment(loader=BaseLoader(), autoescape=select_autoescape(enabled_extensions=("html", "xml")))
    page_t = env.from_string(PAGE_TMPL)
    index_t = env.from_string(INDEX_TMPL)

    subjects = subjects_in_graph(g)

    for s in subjects:
        triples = subject_rows(g, s, prefix_map, gospel, bnode_expand_depth=args.bnode_expand_depth)

        types = []
        for t in g.objects(s, RDF.type):
            if isinstance(t, URIRef):
                types.append(render_uri(g, t, prefix_map))
            else:
                types.append(html.escape(str(t)))

        subject_display = render_uri(g, s, prefix_map)

        (out_dir / f"{slugify(str(s))}.html").write_text(
            page_t.render(
                title=str(s),
                subject_display=subject_display,
                types=types,
                triples=triples,
                index_href="index.html",
                generated_at=generated_at,
            ),
            encoding="utf-8",
        )

    items = []
    for s in subjects:
        href = f"{slugify(str(s))}.html"
        parts = try_curie_parts(g, s, prefix_map)
        curie = f"{parts[0]}:{parts[2]}" if parts else str(s)
        label = best_label_for_subject(g, s)
        deprecated = is_deprecated(g, s)
        replaced_by_html = replacement_link_html(g, s, prefix_map) if deprecated else None

        key_bits = [curie, label]
        if deprecated:
            key_bits.append("deprecated")
        if replaced_by_html:
            key_bits.append(re.sub(r"<[^>]+>", "", replaced_by_html))
        key = " ".join(k for k in key_bits if k).lower()

        items.append(
            {
                "href": href,
                "curie": html.escape(curie),
                "label": html.escape(label),
                "deprecated": deprecated,
                "replaced_by_html": replaced_by_html,
                "key": html.escape(key),
            }
        )

    items.sort(key=lambda it: it["key"])

    (out_dir / "index.html").write_text(
        index_t.render(title=args.title, count=len(items), items=items, generated_at=generated_at),
        encoding="utf-8",
    )

    print(f"Wrote {len(subjects)} pages + index to: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())