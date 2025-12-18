#!/usr/bin/env python3
"""List instances of an RDF class from a local Turtle file.

This replaces the TopBraid servlet call:

  qudt:listAllInstancesOfClass

Behavior:
  * Parses a Turtle input file.
  * Computes the rdfs:subClassOf transitive closure for the given class IRI.
  * Returns all non-bnode subjects that have rdf:type any class in that closure.
  * Prints one instance IRI per line, sorted.

CLI:
  qudt_list_instances.py --input <file.ttl> --class <class-iri>

Exit codes:
  0 on success
  2 on bad args / missing file
  3 on parse failure
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Set

try:
    from rdflib import Graph, URIRef
    from rdflib.namespace import RDF, RDFS
except Exception as e:  # pragma: no cover
    print(f"ERROR: rdflib is required: {e}", file=sys.stderr)
    sys.exit(2)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="List instances of a class (including subclasses) from a Turtle file."
    )
    p.add_argument(
        "--input",
        required=True,
        help="Path to a Turtle file to parse.",
    )
    p.add_argument(
        "--class",
        dest="class_iri",
        required=True,
        help="Class IRI whose instances you want (includes subclasses).",
    )
    return p.parse_args(argv)


def _subclass_closure(g: Graph, root: URIRef) -> Set[URIRef]:
    """Return {root} ∪ {all subclasses of root via rdfs:subClassOf*}."""
    closure: Set[URIRef] = {root}
    frontier: list[URIRef] = [root]
    while frontier:
        current = frontier.pop()
        for sub in g.subjects(RDFS.subClassOf, current):
            if isinstance(sub, URIRef) and sub not in closure:
                closure.add(sub)
                frontier.append(sub)
    return closure


def iter_instances(g: Graph, class_iri: URIRef) -> Iterable[URIRef]:
    classes = _subclass_closure(g, class_iri)
    seen: Set[URIRef] = set()
    for c in classes:
        for s in g.subjects(RDF.type, c):
            if isinstance(s, URIRef) and s not in seen:
                seen.add(s)
                yield s


def main(argv: list[str]) -> int:
    ns = _parse_args(argv)
    in_path = ns.input
    if not os.path.exists(in_path):
        print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
        return 2

    g = Graph()
    try:
        g.parse(in_path, format="turtle")
    except Exception as e:
        print(f"ERROR: failed to parse Turtle file {in_path}: {e}", file=sys.stderr)
        return 3

    class_iri = URIRef(ns.class_iri)
    instances = sorted(str(u) for u in iter_instances(g, class_iri))
    sys.stdout.write("\n".join(instances))
    if instances:
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
