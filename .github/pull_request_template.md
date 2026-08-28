## Information-boundary rules

These non-negotiable invariants from [CONTRIBUTING.md](../CONTRIBUTING.md) must be preserved. Confirm this pull request does not break them:

- [ ] Other agents' soliloquies never enter an agent context.
- [ ] Other agents' model, provider, and credential metadata stay researcher-only.
- [ ] The shared system prompt is byte-identical for every agent in a run.
- [ ] Credential values never enter configuration snapshots or run bundles.
- [ ] Experiment files remain read-only and confined to their declared root.

## Contributor checklist

- [ ] Change is focused; research impact is described below.
- [ ] Tests added or updated if this change touches a boundary above.
- [ ] Validation commands used are listed below.

## Summary

<!-- What changed and why it matters for research or contributors. -->

## How I validated

<!-- Commands you ran, for example `uv run pytest` or `uv run ruff check .`. -->
