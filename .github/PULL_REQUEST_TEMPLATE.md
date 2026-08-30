## What & why

<!-- One paragraph. Link the issue if there is one. -->

## Invariants check

- [ ] The extractor stays deterministic (no heuristics added to `extractor.py`)
- [ ] Nothing deploys without `ApprovalGate` + an accountable actor
- [ ] Any new synthesis candidate source passes golden-record validation
- [ ] New state transitions are logged to the audit trail
- [ ] `python -m pytest` green; new behavior has a test that fails without this PR
- [ ] `docs/architecture.md` updated if a subsystem boundary moved
