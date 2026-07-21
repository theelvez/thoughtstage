# Contributing to Thoughtstage

Thank you for helping make multi-agent experiments easier to inspect and repeat.

## Development setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
pytest
ruff check .
```

The dashboard uses pnpm:

```bash
pnpm --dir web install
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
