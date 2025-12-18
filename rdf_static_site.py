#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from jinja2 import BaseLoader, Environment, select_autoescape
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

QUDT = Namespace("http://qudt.org/schema/qudt/")

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
    {% if item.deprecated %}<span class="deprecated">Deprecated</span>{% endif %}
  </li>
{% endfor %}
</ul>

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
    # Convert $...$ to \( ... \) and $$...$$ to \[ ... \] (preserve newlines)
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

NUMERIC_LEX_RE = re.compile(r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?")

# We will scan numeric lexemes *only* in positions that look like Turtle object positions.
# But we do NOT attempt to fully parse Turtle. We just record a conservative set of candidates.


@dataclass(frozen=True)
class NumericOccurrence:
    subject_token: str         # top-level subject token as it appears in the file (e.g., unit:A-PER-A-HR)
    pred_token: str            # predicate token as it appears in the file (e.g., qudt:exponent)
    lexeme: str                # exact numeric token (e.g., -2, 2.777E-4)
    bnode_depth: int           # nesting depth of [ ... ] at that point
    line_no: int               # for stable ordering


@dataclass(frozen=True)
class PathKey:
    subject: URIRef
    path: Tuple[URIRef, ...]   # predicates from subject to the literal


def scan_numeric_occurrences(ttl_text: str) -> List[NumericOccurrence]:
    """
    Conservative scanner:
      - respects long-string delimiters so we don't read numbers inside long strings
      - tracks bracket depth to know whether we're inside a bnode block
      - identifies triples' subject token by looking for non-indented subject starts
      - captures numeric objects in "pred <ws> NUM [;,.]" patterns (as text)
    """
    occurrences: List[NumericOccurrence] = []

    # predicate token (CURIE or <IRI>)
    pred_re = r"(?P<pred>(?:[A-Za-z_][\w.-]*:[\w.-]+)|(?:<[^>]+>))"
    num_re = r"(?P<num>[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?)"
    # only accept if followed by ; , or . (end of object)
    pat = re.compile(rf"\b{pred_re}\b[ \t]+{num_re}\s*(?=[;,.])")

    # long string state (either delimiter)
    delim: Optional[str] = None

    bracket_depth = 0
    current_subject: Optional[str] = None

    for idx, raw in enumerate(ttl_text.splitlines(), start=1):
        line = raw.rstrip("\n")

        # update delimiter state
        # (toggle only on the delimiter we entered with)
        i = 0
        while i < len(line):
            next_d = None
            next_pos = None
            for d in ('"""', "'''"):
                pos = line.find(d, i)
                if pos != -1 and (next_pos is None or pos < next_pos):
                    next_d, next_pos = d, pos
            if next_d is None or next_pos is None:
                break
            if delim is None:
                delim = next_d
            elif delim == next_d:
                delim = None
            i = next_pos + 3

        in_long_string = delim is not None

        # subject detection only when not in long string and at top-level (not indented)
        if not in_long_string:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("@"):
                if not line[:1].isspace():
                    # likely a subject start
                    current_subject = stripped.split()[0]

        # update bracket depth (only when not in long string)
        if not in_long_string:
            bracket_depth += line.count("[")
            bracket_depth -= line.count("]")

        if in_long_string or not current_subject:
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


def compute_literal_paths(
    g: Graph,
    subject: URIRef,
    max_depth: int = 4,
) -> Dict[Tuple[URIRef, ...], List[Literal]]:
    """
    BFS from subject following URIRef/BNode edges up to max_depth.
    Collect paths (predicates) that end in a Literal.
    """
    results: Dict[Tuple[URIRef, ...], List[Literal]] = defaultdict(list)

    # queue holds (node, path_preds)
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


def build_gospel_lexeme_map(
    g: Graph,
    ttl_text: str,
    prefix_map: Dict[str, str],
    max_depth: int = 4,
) -> Dict[Tuple[URIRef, Tuple[URIRef, ...], str], str]:
    """
    Returns a map:
      (subject_uri, predicate_path, object_literal_id_string) -> exact numeric lexeme

    We match occurrences to literals by:
      - subject token -> subject URI
      - pred token -> last predicate in a path
      - lexeme string -> must equal str(literal) for a candidate literal
      - consume matches in file order to disambiguate duplicates
    """
    occs = scan_numeric_occurrences(ttl_text)

    # Map subject token (CURIE) to subject URI
    token_to_subject_uri: Dict[str, URIRef] = {}
    for s in subjects_in_graph(g):
        parts = try_curie_parts(g, s, prefix_map)
        if parts and parts[0] in prefix_map:
            token_to_subject_uri[f"{parts[0]}:{parts[2]}"] = s
        # also allow <IRI> style token matching if needed
        token_to_subject_uri[f"<{str(s)}>"] = s

    # Precompute path->literals per subject
    subject_paths: Dict[URIRef, Dict[Tuple[URIRef, ...], List[Literal]]] = {}
    for s in subjects_in_graph(g):
        subject_paths[s] = compute_literal_paths(g, s, max_depth=max_depth)

    # For each subject and path, prepare a multiset of candidate literals by lexical string
    # We'll consume them as we match occurrences (stable, file-order)
    candidates: Dict[Tuple[URIRef, Tuple[URIRef, ...], str], List[Literal]] = {}
    for s, paths in subject_paths.items():
        for path, lits in paths.items():
            for lit in lits:
                # object key must be stable; use python id string + lexical for tie-breakers
                key = (s, path, str(lit))
                candidates.setdefault(key, []).append(lit)

    gospel: Dict[Tuple[URIRef, Tuple[URIRef, ...], str], str] = {}

    for occ in occs:
        subj = token_to_subject_uri.get(occ.subject_token)
        if subj is None:
            continue
        pred_uri = resolve_token_to_uri(occ.pred_token, prefix_map)
        if pred_uri is None:
            continue

        # Find all paths whose last predicate equals pred_uri and that have a literal whose str() matches occ.lexeme
        paths = subject_paths.get(subj, {})
        matching_paths = [path for path in paths.keys() if path and path[-1] == pred_uri]
        if not matching_paths:
            continue

        # prefer shorter paths (more likely direct) but keep determinism
        matching_paths.sort(key=lambda p: (len(p), p))

        matched = False
        for path in matching_paths:
            lits = [lit for lit in paths.get(path, []) if str(lit) == occ.lexeme]
            if not lits:
                continue

            key = (subj, path, occ.lexeme)
            # consume in order
            if candidates.get(key):
                candidates[key].pop(0)
                gospel[key] = occ.lexeme
                matched = True
                break

        if not matched:
            # fall back: if we cannot match by path, still allow direct predicate on subject
            direct_path = (pred_uri,)
            key = (subj, direct_path, occ.lexeme)
            if key in candidates:
                candidates[key].pop(0)
                gospel[key] = occ.lexeme

    return gospel


# -----------------------------
# Rendering
# -----------------------------

def is_numeric_literal_lex(lit: Literal) -> bool:
    return bool(NUMERIC_LEX_RE.fullmatch(str(lit).strip()))


def render_literal(
    g: Graph,
    lit: Literal,
    prefix_map: Dict[str, str],
    gospel_lexeme: Optional[str],
) -> str:
    # gospel numeric: if we have it, use it verbatim and unquoted
    if gospel_lexeme is not None:
        return f"<span class='prewrap'>{html.escape(gospel_lexeme, quote=False)}</span>"

    # fallback numeric: unquoted if it looks numeric
    if is_numeric_literal_lex(lit):
        return f"<span class='prewrap'>{html.escape(str(lit).strip(), quote=False)}</span>"

    raw = str(lit)

    # anyURI: link
    if lit.datatype and URIRef(lit.datatype) == XSD.anyURI:
        href = html.escape(raw, quote=True)
        text = html.escape(raw, quote=False)
        return f"<a href='{href}' class='prewrap'>{text}</a>"

    # LaTeX
    if is_qudt_latex_string(g, lit, prefix_map) or looks_like_latex(raw):
        converted = convert_dollar_math_to_mathjax(raw)
        return f"<span class='prewrap'>{html.escape(converted, quote=False)}</span>"

    # default quoted literal (no datatype display)
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
    gospel: Dict[Tuple[URIRef, Tuple[URIRef, ...], str], str],
) -> str:
    if isinstance(o, URIRef):
        return render_uri(g, o, prefix_map)
    if isinstance(o, Literal):
        key = (subject, path, str(o))
        gospel_lex = gospel.get(key)
        return render_literal(g, o, prefix_map, gospel_lex)
    if isinstance(o, BNode):
        # bnode value itself hidden by caller; if rendered, don't expose id
        return ""
    return html.escape(str(o))


def expand_bnode(
    g: Graph,
    subject: URIRef,
    start_path: Tuple[URIRef, ...],
    bn: BNode,
    prefix_map: Dict[str, str],
    gospel: Dict[Tuple[URIRef, Tuple[URIRef, ...], str], str],
    max_depth: int = 2,
) -> List[Tuple[str, str]]:
    """
    Expand bnode a couple hops for display.
    """
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
    gospel: Dict[Tuple[URIRef, Tuple[URIRef, ...], str], str],
    bnode_expand_depth: int = 2,
) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for p, o in g.predicate_objects(subject):
        if not isinstance(p, URIRef):
            continue
        pred_disp = render_uri(g, p, prefix_map)
        path = (p,)
        if isinstance(o, BNode):
            rows.append((pred_disp, ""))  # leave blank, no bnode id
            rows.extend(expand_bnode(g, subject, path, o, prefix_map, gospel, max_depth=bnode_expand_depth))
        else:
            rows.append((pred_disp, render_object(g, subject, path, o, prefix_map, gospel)))
    return rows


# -----------------------------
# Main
# -----------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Generate per-resource static HTML pages from Turtle RDF.")
    ap.add_argument("input", help="Input Turtle RDF file")
    ap.add_argument("--format", default=None, help="Optional RDFLib parser format (default: autodetect)")
    ap.add_argument("--out", default="site", help="Output directory for static HTML")
    ap.add_argument("--title", default="RDF Index", help="Title for the index page")
    ap.add_argument("--gospel-max-depth", type=int, default=4, help="Max predicate-path depth for gospel numeric matching")
    ap.add_argument("--bnode-expand-depth", type=int, default=2, help="How many bnode hops to expand in HTML")
    args = ap.parse_args()

    inp = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ttl_text = inp.read_text(encoding="utf-8")
    prefix_map = parse_prefix_map_from_turtle(ttl_text)

    g = Graph()
    g.parse(str(inp), format=args.format)
    bind_prefix_map(g, prefix_map)

    # Build gospel map robustly (semantic paths, file-order disambiguation)
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
        key = (curie + " " + label).lower()
        items.append(
            {
                "href": href,
                "curie": html.escape(curie),
                "label": html.escape(label),
                "deprecated": deprecated,
                "key": html.escape(key),
            }
        )

    items.sort(key=lambda it: it["key"])

    (out_dir / "index.html").write_text(
        index_t.render(title=args.title, count=len(items), items=items),
        encoding="utf-8",
    )

    print(f"Wrote {len(subjects)} pages + index to: {out_dir.resolve()}")
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())