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

    run = sub.add_parser("run", help="run one pipeline cycle for a source")
    run.add_argument("source_id")

    sub.add_parser("chaos", help="break the demo site (ship a redesign)")
    sub.add_parser("reset", help="reset demo state")
    sub.add_parser("mcp", help="serve Reweave as an MCP server on stdio (for TrueForge)")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        from .server import app

        uvicorn.run(app, host=args.host, port=args.port)
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
