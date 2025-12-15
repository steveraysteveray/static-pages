#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Iterable, Tuple, Any, Optional

from rdflib import Graph, URIRef, BNode, Literal, Namespace
from rdflib.namespace import RDF
from jinja2 import Environment, BaseLoader, select_autoescape

QUDT = Namespace("http://qudt.org/schema/qudt/")

# Prefixes that should hyperlink to qudt.org with content negotiation.
# (e.g., unit:M -> https://qudt.org/vocab/unit/M)
QUDT_LINK_PREFIXES = {"unit", "qkdv", "quantitykind", "qudt", "sou"}


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
        // IMPORTANT: do NOT skip table cell tags so math in cells gets processed
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

    /* Preserve line breaks in long literals */
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
    li { margin: 0.25rem 0; }
    .meta { color:#555; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
  </style>
</head>
<body>
<h1>{{ title }}</h1>
<div class="meta">{{ count }} resources</div>

<input id="q" placeholder="Filter…" />

<ul id="list">
{% for item in items %}
  <li data-key="{{ item.key }}"><a href="{{ item.href }}">{{ item.label }}</a></li>
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


def try_curie_parts(g: Graph, uri: URIRef) -> Optional[Tuple[str, str, str]]:
    """Return (prefix, namespace, localname) if graph can compute a QName, else None."""
    try:
        prefix, namespace, local = g.namespace_manager.compute_qname(uri)
        return prefix, str(namespace), local
    except Exception:
        return None


def render_uri(g: Graph, uri: URIRef) -> str:
    """
    Render a URIRef as a <code>curie</code> if possible; if its prefix is in
    QUDT_LINK_PREFIXES, link to the expanded URI (namespace + local) so qudt.org
    content negotiation can serve HTML.
    """
    parts = try_curie_parts(g, uri)
    if parts:
        prefix, namespace, local = parts
        curie = f"{prefix}:{local}"
        curie_esc = html.escape(curie)

        if prefix in QUDT_LINK_PREFIXES:
            href = html.escape(namespace + local)
            return f"<a href='{href}'><code>{curie_esc}</code></a>"

        return f"<code>{curie_esc}</code>"

    return f"<code>{html.escape(str(uri))}</code>"


def render_bnode(bn: BNode) -> str:
    return f"<span class='bnode'>_:{html.escape(str(bn))}</span>"


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


def is_qudt_latex_string(g: Graph, lit: Literal) -> bool:
    """
    True when datatype looks like qudt:LatexString (by QName localname),
    even if the prefix mapping differs.
    """
    if not lit.datatype:
        return False
    try:
        dt_uri = URIRef(lit.datatype)
        parts = try_curie_parts(g, dt_uri)
        if parts and parts[2] == "LatexString":
            return True
        # fallback: URI localname
        return str(dt_uri).rstrip("/#").endswith("LatexString")
    except Exception:
        return False


def convert_dollar_math_to_mathjax(s: str) -> str:
    """
    Convert embedded $...$ and $$...$$ segments inside an arbitrary string into
    MathJax-safe delimiters \\(...\\) and \\[...\\], removing the dollar signs.

    This handles the unit:A style strings where LaTeX is mixed with prose, e.g.:
      "... defined as: $$A = C/s = ...$$ Note that ..."

    Rules:
    - $$...$$ -> \\[...\\]
    - $...$   -> \\(...\\)
    - Backslash-escaped dollars (\\$) are left alone.
    - If a delimiter is unmatched, we leave it as literal '$' text.
    """
    out: list[str] = []
    i = 0
    n = len(s)

    def is_escaped(pos: int) -> bool:
        # count preceding backslashes
        k = pos - 1
        bs = 0
        while k >= 0 and s[k] == "\\":
            bs += 1
            k -= 1
        return (bs % 2) == 1

    while i < n:
        if s[i] == "$" and not is_escaped(i):
            # $$ display?
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
                    # no closing $$ found
                    out.append("$")
                    i += 1
                continue

            # $ inline
            j = i + 1
            while j < n:
                if s[j] == "$" and not is_escaped(j):
                    inner = s[i + 1 : j]
                    out.append("\\(" + inner + "\\)")
                    i = j + 1
                    break
                j += 1
            else:
                # no closing $ found
                out.append("$")
                i += 1
            continue

        out.append(s[i])
        i += 1

    return "".join(out)


def render_literal(g: Graph, lit: Literal) -> str:
    raw = str(lit)

    # If it’s explicitly typed as LatexString (QUDT), treat it as “prose + embedded math”.
    if is_qudt_latex_string(g, lit) or looks_like_latex(raw):
        # Convert embedded $...$ / $$...$$ to MathJax delimiters so the $ never shows.
        converted = convert_dollar_math_to_mathjax(raw)

        # Escape HTML but keep backslashes etc. (html.escape does not touch backslashes)
        converted_esc = html.escape(converted, quote=False)

        # IMPORTANT: don't wrap the whole thing in math mode; leave it as prose
        # containing \\(...\\) and \\[...\\] segments for MathJax to process.
        content = f"<span class='lit prewrap'>{converted_esc}</span>"
    else:
        txt = html.escape(raw, quote=False)
        content = f"<span class='lit prewrap'>“{txt}”</span>"

    extras = ""
    if lit.language:
        extras += f"@{html.escape(lit.language)}"
    if lit.datatype:
        extras += f"^^{render_uri(g, URIRef(lit.datatype))}"

    return content + extras


def render_term(g: Graph, term: Any) -> str:
    if isinstance(term, URIRef):
        return render_uri(g, term)
    if isinstance(term, BNode):
        return render_bnode(term)
    if isinstance(term, Literal):
        return render_literal(g, term)
    return html.escape(str(term))


def link_if_internal_subject(g: Graph, term: Any) -> str:
    """
    For URIRefs that are subjects *in this graph*, link to the local generated
    HTML page. For QUDT-related prefixes we prefer qudt.org external links.
    """
    if isinstance(term, URIRef):
        parts = try_curie_parts(g, term)
        if parts and parts[0] in QUDT_LINK_PREFIXES:
            return render_uri(g, term)

        if (term, None, None) in g:
            href = f"{slugify(str(term))}.html"
            label = render_uri(g, term)
            return f"<a href='{html.escape(href)}'>{label}</a>"
        return render_uri(g, term)

    return render_term(g, term)


def sort_key_term(term: Any) -> str:
    return str(term)


def iter_subjects(g: Graph) -> Iterable[URIRef]:
    """Interpret “instance declarations” as URI subjects that have at least one triple."""
    seen: set[URIRef] = set()
    for s in g.subjects():
        if isinstance(s, URIRef) and s not in seen:
            seen.add(s)
            yield s


def expand_factor_unit_bnode(g: Graph, bnode: BNode) -> list[Tuple[str, str]]:
    """
    One-hop expansion of qudt:hasFactorUnit blank node triples.
    Display these rows with an arrow prefix on the predicate.
    """
    rows: list[Tuple[str, str]] = []
    for p2, o2 in sorted(
        g.predicate_objects(bnode),
        key=lambda t: (sort_key_term(t[0]), sort_key_term(t[1])),
    ):
        p2_disp = f"↳ {render_term(g, p2)}"
        o2_disp = link_if_internal_subject(g, o2)
        rows.append((p2_disp, o2_disp))
    return rows


def subject_rows_with_double_hop(g: Graph, subject: URIRef) -> list[Tuple[str, str]]:
    """
    All triples for subject, plus “double-hop” rows for qudt:hasFactorUnit bnodes.
    For qudt:hasFactorUnit itself, leave the object cell blank (hide bnode id).
    """
    rows: list[Tuple[str, str]] = []

    po_list = sorted(
        g.predicate_objects(subject),
        key=lambda t: (sort_key_term(t[0]), sort_key_term(t[1])),
    )

    for p, o in po_list:
        p_disp = render_term(g, p)

        if p == QUDT.hasFactorUnit and isinstance(o, BNode):
            rows.append((p_disp, ""))  # hide _:bnode
            rows.extend(expand_factor_unit_bnode(g, o))
        else:
            rows.append((p_disp, link_if_internal_subject(g, o)))

    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate per-resource static HTML pages from RDF.")
    ap.add_argument("input", help="Input RDF file (Turtle, RDF/XML, JSON-LD, N-Triples, etc.)")
    ap.add_argument("--format", default=None, help="Optional RDFLib parser format (e.g., turtle, xml, json-ld)")
    ap.add_argument("--out", default="site", help="Output directory for static HTML")
    ap.add_argument("--title", default="RDF Index", help="Title for the index page")
    args = ap.parse_args()

    inp = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    g = Graph()
    g.parse(str(inp), format=args.format)

    env = Environment(
        loader=BaseLoader(),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
    )
    page_t = env.from_string(PAGE_TMPL)
    index_t = env.from_string(INDEX_TMPL)

    subjects = list(iter_subjects(g))

    # Per-subject pages
    for s in subjects:
        triples = subject_rows_with_double_hop(g, s)
        types = [render_term(g, t) for t in g.objects(s, RDF.type)]
        subject_display = render_term(g, s)

        filename = out_dir / f"{slugify(str(s))}.html"
        html_out = page_t.render(
            title=str(s),
            subject_display=subject_display,
            types=types,
            triples=triples,
            index_href="index.html",
        )
        filename.write_text(html_out, encoding="utf-8")

    # Index page (alphabetical)
    items = []
    for s in subjects:
        href = f"{slugify(str(s))}.html"
        parts = try_curie_parts(g, s)
        label = f"{parts[0]}:{parts[2]}" if parts else str(s)
        items.append(
            {
                "href": href,
                "label": html.escape(label),
                "key": html.escape(label.lower()),
            }
        )
    items.sort(key=lambda it: it["key"])

    index_html = index_t.render(title=args.title, count=len(items), items=items)
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")

    print(f"Wrote {len(subjects)} pages + index to: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())