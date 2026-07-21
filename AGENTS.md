# Thoughtstage agent guide

## Project purpose

Thoughtstage is an open, reproducible social laboratory for multi-agent AI
experiments. Each participating agent produces a public `Post` and a
researcher-private `Soliloquy`. A soliloquy is an elicited model output, not a
provider's hidden chain of thought.

Keep the platform provider-neutral: every agent may have an independent model,
provider, credential reference, and inference configuration.

## Non-negotiable research boundaries

Preserve these invariants in code, tests, examples, documentation, and UI:

1. Every agent in an experiment receives the same experiment-level system prompt.
2. Agents may see all public posts eligible under the declared schedule.
3. An agent never receives another agent's soliloquy.
4. Provider, model, and credential metadata never enter participating-agent context.
5. Credential values never enter manifests, logs, run bundles, fixtures, or commits.
6. Experiment files are read-only and confined to the declared experiment root.
7. Public and private event streams remain separately typed and separately stored.

Any change touching an information boundary must add or update a regression test.

## Repository map

- `src/thoughtstage/`: engine, typed contracts, providers, API, CLI, and file MCP
- `tests/`: boundary, safety, scheduling, CLI, and reproducibility tests
- `examples/`: deterministic, key-free experiments
- `docs/`: architecture and research contracts
- `web/`: React/TypeScript researcher dashboard
- `runs/`: generated local run bundles; ignored by Git

## Canonical development commands

Use the locked dependencies and the same commands as CI:

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=thoughtstage --cov-report=term-missing --cov-fail-under=85
```

For the dashboard:

```bash
pnpm --dir web install --frozen-lockfile
pnpm --dir web test
pnpm --dir web build
```

For the portable container path:

```bash
docker compose build
docker compose run --rm api thoughtstage validate examples/hello-stage/experiment.yaml
docker compose run --rm api thoughtstage run examples/hello-stage/experiment.yaml
```

## Experiment workflow

Validate a manifest before running it. Prefer deterministic mock providers for
tests and public examples so no paid key is required. A normal key-free smoke run
is:

```bash
uv run thoughtstage validate examples/hello-stage/experiment.yaml
uv run thoughtstage run examples/hello-stage/experiment.yaml --run-id hello-stage-smoke
```

Inspect both `public.jsonl` and `private/soliloquies.jsonl`, and verify private
content does not appear in the public stream. Treat generated run bundles as
local artifacts unless a specific reproducibility bundle is intentionally being
published.

## Change discipline

- Keep changes focused and make experimental semantics explicit rather than implicit.
- Prefer typed records over catch-all message dictionaries at trust boundaries.
- Reject invalid or ambiguous configuration instead of silently guessing.
- Keep provider-specific behavior behind the provider contract.
- Support Windows and Linux paths and container execution.
- Update user-facing documentation when commands, manifests, or semantics change.
- Do not weaken a boundary merely to simplify an adapter or UI feature.

Before considering work complete, run the relevant Python and dashboard checks,
exercise the affected CLI or API path, and report exactly what was verified.
