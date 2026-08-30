"""Monitor a real, live website: books.toscrape.com.

Registers http://books.toscrape.com (a public scraping sandbox) as a Reweave
source with five golden records, then runs one full pipeline cycle against
the live site.

Run from the repo root:

    python examples/real_source.py

What to notice:

* golden records use the FULL book titles — on the live page the visible link
  text is truncated ("A Light in the ..."), so the seed spec reads the link's
  ``title`` attribute instead. When this site "redesigns", the Surgeon can
  re-anchor on these same facts.
* prices are in £ — ``parse_price`` doesn't care about the currency symbol.
* with ``BRIGHTDATA_API_KEY`` set, the fetch routes through Web Unlocker and
  the event log will show ``brightdata:<zone>`` provenance instead of
  ``direct``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import reweave  # noqa: F401  (installed via `pip install -e .`)
except ModuleNotFoundError:  # allow running straight from a clone
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reweave import registry
from reweave.models import ExtractionSpec, FieldSpec
from reweave.pipeline import run_source

GOLDEN = [
    {"title": "A Light in the Attic", "price": 51.77, "url": "a-light-in-the-attic_1000/index.html"},
    {"title": "Tipping the Velvet", "price": 53.74, "url": "tipping-the-velvet_999/index.html"},
    {"title": "Soumission", "price": 50.10, "url": "soumission_998/index.html"},
    {"title": "Sharp Objects", "price": 47.82, "url": "sharp-objects_997/index.html"},
    {"title": "Sapiens: A Brief History of Humankind", "price": 54.23, "url": "sapiens-a-brief-history-of-humankind_996/index.html"},
]

SPEC = ExtractionSpec(
    item_selector="article.product_pod",
    fields=[
        FieldSpec("title", "h3 > a", attr="title", kind="text"),
        FieldSpec("price", "p.price_color", kind="price"),
        FieldSpec("url", "h3 > a", attr="href", kind="url"),
    ],
    version=1,
    origin="seed",
)


def main() -> None:
    registry.upsert_source(
        "books", "books.toscrape.com · demo catalog", "http://books.toscrape.com/", GOLDEN, SPEC
    )
    result = run_source("books")
    report = result["report"]

    print(f"provenance : {result['provenance']}")
    print(f"spec       : v{result['spec_version']}")
    print(f"rows       : {report['row_count']} (golden: {report['expected_rows']})")
    print(f"healthy    : {report['healthy']}  confidence: {report['confidence']:.0%}")
    for f in report["fields"]:
        print(
            f"  field {f['name']:<6} null_rate={f['null_rate']:.0%} "
            f"golden_match={f['golden_match_rate']:.0%}"
        )
    print("\nfirst row  :", json.dumps(result["rows"][0], indent=2))


if __name__ == "__main__":
    main()
