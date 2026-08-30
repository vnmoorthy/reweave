"""Benchmark harness for reweave's hot paths.

Measures, over the bundled demo fixtures (demo/site_v1|v2|v3 + demo/golden.json):

1. extract            — seed spec on site_v1
2. sentinel.assess    — drift assessment on the extracted rows
3. heal v1->v2        — surgeon.propose_heal, seed spec against the v2 redesign
4. heal v2->v3        — surgeon.propose_heal, healed-v2 spec against the v3 redesign
5. bootstrap          — surgeon.bootstrap_spec on site_v1 from 3 golden examples

Stdlib timing only (time.perf_counter). Each stage runs WARMUP untimed
iterations, then N timed iterations; median and p95 are reported in ms.

Run from anywhere:

    python3 benchmarks/bench.py

Writes benchmarks/RESULTS.md with the measured numbers.
"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # package may not be pip-installed

from bs4 import BeautifulSoup  # noqa: E402

from reweave import sentinel, surgeon  # noqa: E402
from reweave.extractor import extract  # noqa: E402
from reweave.models import ExtractionSpec, FieldSpec  # noqa: E402

WARMUP = 3
N = 25


def seed_spec() -> ExtractionSpec:
    """The v1-era spec (same as server.seed / tests/conftest.py)."""
    return ExtractionSpec(
        item_selector="div.product-card",
        fields=[
            FieldSpec("title", "h3.product-name", None, "text"),
            FieldSpec("price", "span.price-tag", None, "price"),
            FieldSpec("url", "a.product-link", "href", "url"),
        ],
        version=1,
    )


def dom_nodes(html: str) -> int:
    return len(BeautifulSoup(html, "lxml").find_all(True))


def bench(fn, warmup: int = WARMUP, n: int = N) -> dict:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "median_ms": statistics.median(samples),
        "p95_ms": percentile(samples, 95.0),
        "min_ms": samples[0],
        "max_ms": samples[-1],
        "n": n,
    }


def percentile(sorted_samples: list[float], pct: float) -> float:
    """Linear-interpolation percentile over pre-sorted samples."""
    k = (len(sorted_samples) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_samples) - 1)
    frac = k - lo
    return sorted_samples[lo] * (1 - frac) + sorted_samples[hi] * frac


def machine_descriptor() -> str:
    desc = platform.platform()
    if sys.platform == "darwin":
        try:
            cpu = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if cpu:
                desc += f", {cpu}"
        except Exception:
            pass
    return desc


def main() -> None:
    html = {
        v: (REPO / "demo" / f"site_{v}" / "index.html").read_text(encoding="utf-8")
        for v in ("v1", "v2", "v3")
    }
    golden = json.loads((REPO / "demo" / "golden.json").read_text(encoding="utf-8"))
    spec_v1 = seed_spec()

    # --- correctness gates: never benchmark a broken pipeline -------------
    rows_v1 = extract(html["v1"], spec_v1)
    assert len(rows_v1) == len(golden), f"extract: {len(rows_v1)} rows != {len(golden)} golden"
    report = sentinel.assess("nimbusmart", rows_v1, spec_v1, golden)
    assert report.healthy, f"sentinel on v1 rows should be healthy: {report.failures}"

    heal_v2 = surgeon.propose_heal(html["v2"], spec_v1, golden, "nimbusmart")
    assert heal_v2 is not None, "heal v1->v2 returned None"
    spec_v2 = heal_v2.new_spec

    heal_v3 = surgeon.propose_heal(html["v3"], spec_v2, golden, "nimbusmart")
    assert heal_v3 is not None, "heal v2->v3 returned None"

    boot = surgeon.bootstrap_spec(html["v1"], golden[:3], "nimbusmart")
    assert boot is not None, "bootstrap on v1 with 3 golden examples returned None"

    # --- fixture context ---------------------------------------------------
    nodes = {v: dom_nodes(html[v]) for v in html}

    # --- timed stages ------------------------------------------------------
    stages = [
        ("extract (seed spec, site_v1)",
         lambda: extract(html["v1"], spec_v1)),
        ("sentinel.assess (v1 rows)",
         lambda: sentinel.assess("nimbusmart", rows_v1, spec_v1, golden)),
        ("propose_heal v1 spec -> site_v2",
         lambda: surgeon.propose_heal(html["v2"], spec_v1, golden, "nimbusmart")),
        ("propose_heal healed-v2 spec -> site_v3",
         lambda: surgeon.propose_heal(html["v3"], spec_v2, golden, "nimbusmart")),
        ("bootstrap_spec (site_v1, 3 golden)",
         lambda: surgeon.bootstrap_spec(html["v1"], golden[:3], "nimbusmart")),
    ]
    results = [(name, bench(fn)) for name, fn in stages]

    # --- report ------------------------------------------------------------
    py = platform.python_version()
    machine = machine_descriptor()
    fixture_line = ", ".join(
        f"site_{v}: {nodes[v]} DOM nodes ({len(html[v])} bytes)" for v in ("v1", "v2", "v3")
    )

    header = f"{'stage':<42} {'median':>10} {'p95':>10} {'min':>10} {'max':>10}"
    rule = "-" * len(header)
    print(f"reweave benchmark  (warmup={WARMUP}, n={N}, times in ms)")
    print(f"python {py} | {machine}")
    print(fixture_line)
    print(f"golden records: {len(golden)}")
    print()
    print(header)
    print(rule)
    for name, r in results:
        print(
            f"{name:<42} {r['median_ms']:>10.2f} {r['p95_ms']:>10.2f}"
            f" {r['min_ms']:>10.2f} {r['max_ms']:>10.2f}"
        )

    # --- RESULTS.md --------------------------------------------------------
    md = [
        "# Benchmark results",
        "",
        "Latency of reweave's hot paths over the bundled demo fixtures. Generated by",
        "`benchmarks/bench.py` — every number below is written by the harness at run",
        "time, never by hand.",
        "",
        "Reproduce:",
        "",
        "```",
        "python3 benchmarks/bench.py",
        "```",
        "",
        f"- Date: {date.today().isoformat()}",
        f"- Python: {py}",
        f"- Machine: {machine}",
        f"- Method: `time.perf_counter`, {WARMUP} warmup iterations, "
        f"{N} timed iterations per stage; p95 by linear interpolation.",
        "",
        "## Fixtures",
        "",
        "| fixture | DOM nodes | bytes |",
        "|---|---:|---:|",
        *[
            f"| demo/site_{v}/index.html | {nodes[v]} | {len(html[v])} |"
            for v in ("v1", "v2", "v3")
        ],
        f"| demo/golden.json | {len(golden)} records | "
        f"{len((REPO / 'demo' / 'golden.json').read_bytes())} |",
        "",
        "## Timings (ms)",
        "",
        "| stage | median | p95 | min | max |",
        "|---|---:|---:|---:|---:|",
        *[
            f"| {name} | {r['median_ms']:.2f} | {r['p95_ms']:.2f} "
            f"| {r['min_ms']:.2f} | {r['max_ms']:.2f} |"
            for name, r in results
        ],
        "",
        "## Stage notes",
        "",
        "- **extract** runs the deterministic engine (BeautifulSoup + lxml parse,",
        "  CSS select, coercion) with the v1 seed spec on site_v1; the correctness",
        f"  gate asserts it yields all {len(golden)} golden rows before timing.",
        "- **sentinel.assess** scores the already-extracted v1 rows against the",
        "  golden set (row volume, null rates, golden agreement) — pure Python,",
        "  no HTML parsing, hence the sub-millisecond range.",
        "- **propose_heal** stages include the full pipeline: parse the redesigned",
        "  page, anchor golden records, generalize an item selector, synthesize and",
        "  validate per-field selectors, then a sandboxed extract + assess self-test.",
        "- **bootstrap_spec** is propose_heal from a stub spec with only 3 golden",
        "  examples on site_v1.",
        "- The v2->v3 heal starts from the spec the v1->v2 heal actually produced",
        "  (computed once before timing), matching the repeat-heal path in",
        "  tests/test_surgeon.py.",
        "",
    ]
    out = REPO / "benchmarks" / "RESULTS.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"\nwrote {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
