"""``reweave`` command line interface."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reweave",
        description="Self-healing web data pipelines with human-gated repairs.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="run the control-plane API + dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8321)
    serve.add_argument(
        "--no-autopilot", action="store_true", help="disable continuous background monitoring"
    )

    run = sub.add_parser("run", help="run one pipeline cycle for a source")
    run.add_argument("source_id")

    add = sub.add_parser(
        "add", help="onboard a new source from golden examples (no selectors needed)"
    )
    add.add_argument("url")
    add.add_argument("--golden", required=True, help="path to a JSON list of golden example records")
    add.add_argument("--name", default="")

    export = sub.add_parser("export", help="export a source's latest rows")
    export.add_argument("source_id")
    export.add_argument("--csv", action="store_true", help="CSV instead of JSON")

    sub.add_parser("chaos", help="break the demo site (ship a redesign)")
    sub.add_parser("reset", help="reset demo state")
    sub.add_parser("mcp", help="serve Reweave as an MCP server on stdio (for TrueForge)")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import os

        import uvicorn

        os.environ.setdefault("REWEAVE_AUTOPILOT", "0" if args.no_autopilot else "1")

        from .server import app

        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.cmd == "add":
        from pathlib import Path

        from . import registry, server
        from .fetch import fetch
        from .pipeline import run_source
        from .surgeon import bootstrap_spec

        server.seed()
        golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
        html, provenance = fetch(args.url)
        proposal = bootstrap_spec(html, golden, "bootstrap", base_url=args.url)
        if proposal is None:
            print("could not anchor the golden examples on that page", file=sys.stderr)
            return 1
        source_id = server._slugify(args.name or args.url.split("//")[-1].split("/")[0])
        registry.upsert_source(source_id, args.name or args.url, args.url, golden, proposal.new_spec)
        out = run_source(source_id)
        print(
            f"onboarded '{source_id}' via {provenance}: spec v1 with "
            f"{len(proposal.new_spec.fields)} fields, first run "
            f"{out['report']['row_count']} rows, "
            f"confidence {out['report']['confidence']:.0%}"
        )
        return 0

    if args.cmd == "export":
        from . import registry, server

        server.seed()
        run_rec = registry.latest_run(args.source_id)
        if run_rec is None:
            print(f"no runs recorded for {args.source_id}", file=sys.stderr)
            return 1
        if args.csv:
            import csv

            writer = csv.DictWriter(
                sys.stdout, fieldnames=list(run_rec["rows"][0].keys()) if run_rec["rows"] else []
            )
            writer.writeheader()
            writer.writerows(run_rec["rows"])
        else:
            json.dump(run_rec["rows"], sys.stdout, indent=2)
            print()
        return 0

    if args.cmd == "run":
        from . import server

        server.seed()
        from .pipeline import run_source

        out = run_source(args.source_id)
        json.dump(out["report"], sys.stdout, indent=2)
        print()
        return 0 if out["report"]["healthy"] else 1

    if args.cmd == "chaos":
        from . import demo

        print(f"demo site is now structural era {demo.break_site()}")
        return 0

    if args.cmd == "reset":
        from . import demo, registry, server

        registry.reset()
        demo.reset()
        server.seed()
        print("demo state reset")
        return 0

    if args.cmd == "mcp":
        from .harness.mcp_server import serve_stdio

        serve_stdio()
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
