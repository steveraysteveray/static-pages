#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from jinja2 import BaseLoader, Environment, select_autoescape
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

QUDT = Namespace("http://qudt.org/schema/qudt/")


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
    .bnode { color: #444; }
    .lit { color: #111; }
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


_NUMERIC_TOKEN_RE = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$")


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


def parse_prefix_map_from_turtle(ttl_text: str) -> Dict[str, str]:
    prefix_map: Dict[str, str] = {}
    pat = re.compile(r"^\s*@prefix\s+([A-Za-z_][\w.-]*)\s*:\s*<([^>]+)>\s*\.\s*$")
    for line in ttl_text.splitlines():
        m = pat.match(line)
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
    if parts:
        prefix, namespace, local = parts
        if prefix in prefix_map:
            curie = f"{prefix}:{local}"
            href = namespace + local
            return f"<a href='{html.escape(href, quote=True)}'><code>{html.escape(curie)}</code></a>"

    full = str(uri)
    return f"<a href='{html.escape(full, quote=True)}'>{html.escape(full, quote=False)}</a>"


_LATEX_HINTS = (
    "\\cdot",
    "\\frac",
    "\\sqrt",
    "\\mathrm",
    "\\mathbf",
    "\\mathit",
    "\\left",
    "\\right",
    "\\over",
    "\\times",
    "\\pm",
)


def looks_like_latex(s: str) -> bool:
    t = s.strip()
    if not t:
        return False
    if "$" in t:
        return True
    if any(h in t for h in _LATEX_HINTS):
        return True
    if t.startswith("\\(") or t.startswith("\\["):
        return True
    return False


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
                        inner = s[i + 2 : j]
                        out.append("\\[" + inner + "\\]")
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
                    inner = s[i + 1 : j]
                    out.append("\\(" + inner + "\\)")
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


def _is_true_literal(lit: Literal) -> bool:
    if isinstance(lit.value, bool):
        return bool(lit.value)
    s = str(lit).strip().lower()
    return s in {"true", "1", "yes"}


def render_numeric_token(text: str) -> str:
    return f"<span class='lit'>{html.escape(text, quote=False)}</span>"


def render_literal(g: Graph, lit: Literal, prefix_map: Dict[str, str]) -> str:
    raw = str(lit)

    # Safety net: numeric-looking literals render unquoted even if scanner missed them.
    if _NUMERIC_TOKEN_RE.fullmatch(raw.strip()):
        return render_numeric_token(raw.strip())

    if lit.datatype and URIRef(lit.datatype) == XSD.anyURI:
        href = html.escape(raw, quote=True)
        text = html.escape(raw, quote=False)
        return f"<a href='{href}' class='prewrap'>{text}</a>"

    if is_qudt_latex_string(g, lit, prefix_map) or looks_like_latex(raw):
        converted = convert_dollar_math_to_mathjax(raw)
        converted_esc = html.escape(converted, quote=False)
        content = f"<span class='lit prewrap'>{converted_esc}</span>"
    else:
        txt = html.escape(raw, quote=False)
        content = f"<span class='lit prewrap'>“{txt}”</span>"

    if lit.language:
        content += f"<span class='small'>@{html.escape(lit.language)}</span>"

    return content


def iter_subjects(g: Graph) -> Iterable[URIRef]:
    seen: set[URIRef] = set()
    for s in g.subjects():
        if isinstance(s, URIRef) and s not in seen:
            seen.add(s)
            yield s


def subject_token_variants(g: Graph, s: URIRef, prefix_map: Dict[str, str]) -> Tuple[str, str]:
    qname = ""
    parts = try_curie_parts(g, s, prefix_map)
    if parts:
        qname = f"{parts[0]}:{parts[2]}"
    iri = f"<{str(s)}>"
    return qname, iri


def predicate_token_variants(g: Graph, p: URIRef, prefix_map: Dict[str, str]) -> Tuple[str, str]:
    qname = ""
    parts = try_curie_parts(g, p, prefix_map)
    if parts:
        qname = f"{parts[0]}:{parts[2]}"
    iri = f"<{str(p)}>"
    return qname, iri


@dataclass(frozen=True)
class BNodeRecord:
    key: str
    parent_pred: str
    triples_fp: Tuple[Tuple[str, str], ...]
    numerics: Dict[str, str]


def _lexical_literal_token(lit: Literal, g: Graph, prefix_map: Dict[str, str]) -> str:
    s = str(lit)
    if lit.language:
        return f"\"{s}\"@{lit.language}"
    if lit.datatype:
        dt = URIRef(lit.datatype)
        parts = try_curie_parts(g, dt, prefix_map)
        dt_tok = f"{parts[0]}:{parts[2]}" if parts else f"<{str(dt)}>"
        return f"\"{s}\"^^{dt_tok}"
    return f"\"{s}\""


def _uri_token(uri: URIRef, g: Graph, prefix_map: Dict[str, str]) -> str:
    parts = try_curie_parts(g, uri, prefix_map)
    if parts:
        return f"{parts[0]}:{parts[2]}"
    return f"<{str(uri)}>"


def _obj_token(term: Any, g: Graph, prefix_map: Dict[str, str]) -> str:
    if isinstance(term, URIRef):
        return _uri_token(term, g, prefix_map)
    if isinstance(term, Literal):
        txt = str(term).strip()
        if _NUMERIC_TOKEN_RE.fullmatch(txt):
            return txt
        return _lexical_literal_token(term, g, prefix_map)
    if isinstance(term, BNode):
        return "_:bnode"
    return str(term).strip()


class MultilineState:
    """
    Tracks whether we're inside a Turtle long string.
    Turtle allows two long-string delimiters:
      - triple double quote
      - triple single quote
    """

    def __init__(self) -> None:
        self.delim: Optional[str] = None  # will hold one of: '"""' or "'''"

    def update(self, line: str) -> None:
        i = 0
        while i < len(line):
            nxt = None
            nxt_pos = None
            for d in ('"""', "'''"):
                pos = line.find(d, i)
                if pos != -1 and (nxt_pos is None or pos < nxt_pos):
                    nxt = d
                    nxt_pos = pos
            if nxt is None or nxt_pos is None:
                break

            if self.delim is None:
                self.delim = nxt
            elif self.delim == nxt:
                self.delim = None

            i = nxt_pos + 3

    @property
    def in_multiline(self) -> bool:
        return self.delim is not None


def scan_authoritative_numeric_literals_and_bnodes(
    ttl_text: str,
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, List[BNodeRecord]]]:
    auth_nums: Dict[str, Dict[str, str]] = {}
    bnode_records_by_subject: Dict[str, List[BNodeRecord]] = {}

    pred_re = r"(?P<pred>(?:[A-Za-z_][\w.-]*:[\w.-]+)|(?:<[^>]+>))"
    num_re = r"(?P<num>[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?)"
    num_pat = re.compile(rf"\b{pred_re}\b[ \t]+{num_re}\s*(?=[;,.])")

    open_pat = re.compile(rf"^\s*{pred_re}\s*\[\s*$")
    open_inline_pat = re.compile(rf"\b{pred_re}\b\s*\[\s*$")
    po_pat = re.compile(rf"^\s*{pred_re}\s+(?P<obj>.+?)\s*(?P<end>[;.\]])\s*$")

    ms = MultilineState()
    outer_subject: Optional[str] = None
    current_key: Optional[str] = None
    bnode_stack: List[Dict[str, Any]] = []
    bnode_counter = 0

    def push_bnode(parent_pred_token: str) -> None:
        nonlocal bnode_counter, current_key
        if not outer_subject:
            return
        bnode_counter += 1
        key = f"{outer_subject}::bn{bnode_counter}"
        bnode_stack.append(
            {"key": key, "parent_pred": parent_pred_token, "triples": [], "numerics": {}, "depth": 1}
        )
        current_key = key

    def pop_bnode() -> None:
        nonlocal current_key
        if not outer_subject or not bnode_stack:
            current_key = outer_subject
            return
        ctx = bnode_stack.pop()
        triples = tuple(sorted((p, o.strip()) for p, o in ctx["triples"]))
        rec = BNodeRecord(
            key=ctx["key"],
            parent_pred=ctx["parent_pred"],
            triples_fp=triples,
            numerics=dict(ctx["numerics"]),
        )
        bnode_records_by_subject.setdefault(outer_subject, []).append(rec)
        current_key = bnode_stack[-1]["key"] if bnode_stack else outer_subject

    for raw_line in ttl_text.splitlines():
        line = raw_line.rstrip("\n")

        ms.update(line)
        in_multiline = ms.in_multiline

        if not in_multiline and not bnode_stack:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("@"):
                if not line[:1].isspace():
                    parts = line.split()
                    if parts:
                        outer_subject = parts[0]
                        current_key = outer_subject
                        bnode_counter = 0

        if not in_multiline and outer_subject:
            m_open = open_pat.match(line) or open_inline_pat.search(line)
            if m_open:
                push_bnode(m_open.group("pred"))

        if not in_multiline and bnode_stack:
            bnode_stack[-1]["depth"] += line.count("[") - line.count("]")

            for m in num_pat.finditer(line):
                pred = m.group("pred")
                num = m.group("num")
                auth_nums.setdefault(current_key or outer_subject, {})[pred] = num
                bnode_stack[-1]["numerics"][pred] = num

            m_po = po_pat.match(line)
            if m_po:
                pred = m_po.group("pred")
                obj = m_po.group("obj").strip()
                obj_tok = "_:bnode" if obj == "[" else obj
                bnode_stack[-1]["triples"].append((pred, obj_tok))

            if bnode_stack and bnode_stack[-1]["depth"] <= 0:
                pop_bnode()

        elif not in_multiline and current_key:
            for m in num_pat.finditer(line):
                pred = m.group("pred")
                num = m.group("num")
                auth_nums.setdefault(current_key, {})[pred] = num

    while bnode_stack:
        pop_bnode()

    return auth_nums, bnode_records_by_subject


def lookup_authoritative_numeric(
    auth_nums: Dict[str, Dict[str, str]],
    subj_key: str,
    pred_keys: Tuple[str, str],
) -> Optional[str]:
    if subj_key in auth_nums:
        for pk in pred_keys:
            if pk and pk in auth_nums[subj_key]:
                return auth_nums[subj_key][pk]
    return None


def render_object_value(
    g: Graph,
    subject_key: str,
    prefix_map: Dict[str, str],
    p: URIRef,
    o: Any,
    auth_nums: Dict[str, Dict[str, str]],
) -> str:
    if isinstance(o, Literal):
        pred_qname, pred_iri = predicate_token_variants(g, p, prefix_map)
        token = lookup_authoritative_numeric(auth_nums, subject_key, (pred_qname, pred_iri))
        if token is not None:
            return render_numeric_token(token)
        return render_literal(g, o, prefix_map)

    if isinstance(o, URIRef):
        return render_uri(g, o, prefix_map)

    if isinstance(o, BNode):
        return f"<span class='bnode'>_:{html.escape(str(o))}</span>"

    return html.escape(str(o))


def build_bnode_key_map_for_subject(
    g: Graph,
    subject: URIRef,
    bnode_records: List[BNodeRecord],
    prefix_map: Dict[str, str],
) -> Dict[BNode, str]:
    by_parent_pred: Dict[str, List[BNodeRecord]] = {}
    for rec in bnode_records:
        by_parent_pred.setdefault(rec.parent_pred, []).append(rec)

    mapping: Dict[BNode, str] = {}

    for p_uri in set(g.predicates(subject=subject)):
        if not isinstance(p_uri, URIRef):
            continue

        p_tok_qname, p_tok_iri = predicate_token_variants(g, p_uri, prefix_map)
        parent_tok = p_tok_qname or p_tok_iri
        recs = by_parent_pred.get(parent_tok, [])
        if not recs:
            continue

        candidates: List[BNode] = [o for o in g.objects(subject, p_uri) if isinstance(o, BNode)]
        if not candidates:
            continue

        cand_fp: Dict[BNode, Tuple[Tuple[str, str], ...]] = {}
        for bn in candidates:
            triples = []
            for p2, o2 in g.predicate_objects(bn):
                if not isinstance(p2, URIRef):
                    continue
                pt = _uri_token(p2, g, prefix_map)
                ot = _obj_token(o2, g, prefix_map)
                triples.append((pt, ot))
            cand_fp[bn] = tuple(sorted(triples))

        unused_bnodes = set(candidates)
        unmatched_recs: List[BNodeRecord] = []

        fp_to_bnodes: Dict[Tuple[Tuple[str, str], ...], List[BNode]] = {}
        for bn, fp in cand_fp.items():
            fp_to_bnodes.setdefault(fp, []).append(bn)

        for rec in recs:
            bns = fp_to_bnodes.get(rec.triples_fp, [])
            picked = None
            for bn in bns:
                if bn in unused_bnodes:
                    picked = bn
                    break
            if picked is None:
                unmatched_recs.append(rec)
                continue
            mapping[picked] = rec.key
            unused_bnodes.remove(picked)

        if unmatched_recs and unused_bnodes:
            leftover_bnodes = sorted(unused_bnodes, key=lambda x: str(x))
            for rec, bn in zip(unmatched_recs, leftover_bnodes):
                mapping[bn] = rec.key

    return mapping


def expand_bnode_one_level(
    g: Graph,
    bnode: BNode,
    bnode_subject_key: str,
    prefix_map: Dict[str, str],
    auth_nums: Dict[str, Dict[str, str]],
) -> list[Tuple[str, str]]:
    rows: list[Tuple[str, str]] = []
    for p2, o2 in g.predicate_objects(bnode):
        if not isinstance(p2, URIRef):
            continue
        p2_disp = render_uri(g, p2, prefix_map)
        o2_disp = render_object_value(g, bnode_subject_key, prefix_map, p2, o2, auth_nums)
        rows.append((f"↳ {p2_disp}", o2_disp))
    return rows


def subject_rows_with_double_hop(
    g: Graph,
    subject: URIRef,
    prefix_map: Dict[str, str],
    auth_nums: Dict[str, Dict[str, str]],
    bnode_records_by_subject: Dict[str, List[BNodeRecord]],
) -> list[Tuple[str, str]]:
    rows: list[Tuple[str, str]] = []

    subj_qname, subj_iri = subject_token_variants(g, subject, prefix_map)
    subj_key = subj_qname or subj_iri

    scanned_recs = bnode_records_by_subject.get(subj_key, [])
    bnode_key_map = build_bnode_key_map_for_subject(g, subject, scanned_recs, prefix_map) if scanned_recs else {}

    for p, o in g.predicate_objects(subject):
        if not isinstance(p, URIRef):
            continue

        p_disp = render_uri(g, p, prefix_map)

        if isinstance(o, BNode):
            rows.append((p_disp, ""))
            bnode_key = bnode_key_map.get(o, subj_key)
            rows.extend(expand_bnode_one_level(g, o, bnode_key, prefix_map, auth_nums))
        else:
            rows.append((p_disp, render_object_value(g, subj_key, prefix_map, p, o, auth_nums)))

    return rows


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
        if isinstance(o, Literal) and _is_true_literal(o):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate per-resource static HTML pages from Turtle RDF.")
    ap.add_argument("input", help="Input Turtle RDF file")
    ap.add_argument("--format", default=None, help="Optional RDFLib parser format (default: autodetect)")
    ap.add_argument("--out", default="site", help="Output directory for static HTML")
    ap.add_argument("--title", default="RDF Index", help="Title for the index page")
    args = ap.parse_args()

    inp = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ttl_text = inp.read_text(encoding="utf-8")
    prefix_map = parse_prefix_map_from_turtle(ttl_text)

    auth_nums, bnode_records_by_subject = scan_authoritative_numeric_literals_and_bnodes(ttl_text)

    g = Graph()
    g.parse(str(inp), format=args.format)
    bind_prefix_map(g, prefix_map)

    env = Environment(loader=BaseLoader(), autoescape=select_autoescape(enabled_extensions=("html", "xml")))
    page_t = env.from_string(PAGE_TMPL)
    index_t = env.from_string(INDEX_TMPL)

    subjects = list(iter_subjects(g))

    for s in subjects:
        triples = subject_rows_with_double_hop(g, s, prefix_map, auth_nums, bnode_records_by_subject)

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


if __name__ == "__main__":
    raise SystemExit(main())