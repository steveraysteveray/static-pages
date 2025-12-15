# static-pages
Experiment to generate static html pages from arbitrary RDF files

Run it as follows:
```
python3 -m venv .venv
source .venv/bin/activate
pip install rdflib jinja2

python rdf_static_site.py VOCAB_QUDT-UNITS-ALL.ttl --format turtle --out site
open site/index.html
```
