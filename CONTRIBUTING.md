# Contributing to Thoughtstage

Thank you for helping make multi-agent experiments easier to inspect and repeat.

## Development setup

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=thoughtstage --cov-report=term-missing --cov-fail-under=85
```

These locked-dependency commands match CI. The editable virtual-environment path
in the README is convenient for exploration, but pull requests should be checked
with the commands above before submission.

The dashboard uses pnpm:

```bash
pnpm --dir web install --frozen-lockfile
pnpm --dir web test
pnpm --dir web build
```

## Non-negotiable boundaries

Changes must preserve these invariants:

1. Other agents' soliloquies never enter an agent context.
2. Other agents' model, provider, and credential metadata stay researcher-only.
3. The shared system prompt is byte-identical for every agent in a run.
4. Credential values never enter configuration snapshots or run bundles.
5. Experiment files remain read-only and confined to their declared root.

Add or update tests whenever a change touches one of these boundaries.

## Pull requests

Keep changes focused, describe their research impact, and include the commands
used to validate them. New provider adapters should include a deterministic fake
or recorded contract test that requires no paid API key.
