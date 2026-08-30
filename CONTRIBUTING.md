# Contributing to reweave

Thanks for pulling on a thread. 🧵

## Setup

```bash
git clone https://github.com/vnmoorthy/reweave && cd reweave
pip install -e ".[dev]"
python -m pytest        # the full suite must pass before and after your change
```

## Ground rules

- **The extractor stays dumb.** Heuristics belong in the Surgeon; execution
  stays deterministic. If your change makes `extractor.py` smarter, it's in
  the wrong file.
- **Nothing deploys itself.** Any code path that activates a spec version
  must go through `ApprovalGate` with an accountable actor. No exceptions,
  including tests of convenience.
- **Evidence over vibes.** New synthesis strategies (LLM prompts, embeddings,
  visual diffing…) are welcome — behind the same golden-record validation
  every candidate faces today.
- **Every state transition is auditable.** If you add a transition, log it.

## Pull requests

1. One logical change per PR; include tests that fail without your change.
2. Update `docs/architecture.md` if you touched a boundary between
   subsystems.
3. CI (pytest on 3.10–3.12) must be green.

## Adding a real source

A source needs: a URL, an `ExtractionSpec`, and 5+ golden records. See
`reweave/server.py::seed()` for the shape; a `reweave add-source` CLI is on
the roadmap and is a great first contribution.
