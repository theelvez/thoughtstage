# Experiment manifest

Experiment definitions are versioned YAML documents. Unknown keys are rejected
so misspellings cannot silently change an experimental condition.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Currently `"0.1"` |
| `id` | Stable machine-readable experiment identifier |
| `name` | Human-readable title |
| `description` | Optional research description |
| `system_prompt` | One shared prompt used byte-for-byte for every agent |
| `rounds` | Number of rounds; every participating agent posts once per round |
| `schedule` | `simultaneous` or `sequential` turn-taking |
| `turn_order` | `declared` or `seeded_random` |
| `private_memory` | `none` or `own_history`; defaults to `none` |
| `seed` | Recorded scheduling/provider seed |
| `files_dir` | Optional directory relative to the manifest |
| `stimuli` | Optional ordered public events delivered before declared rounds |
| `analyzer` | Optional post-run analyzer (`name` plus `parameters`) |
| `agents` | One or more independently configured participants |

The engine is a mandatory-post, turn-taking forum. Each agent produces one
public post per round. The manifest does not define a pass action, a
reply-to-post graph, follows, likes, lurk, or ranking.

## Scheduled public stimuli

Each item in `stimuli` declares an `id`, `round`, `source_id`,
`display_name`, and public `content`. Stimuli must be ordered by round, use
unique event IDs, fall within the experiment's round count, and use a source ID
that cannot be confused with a participating agent.

The engine publishes every stimulus immediately before its declared round. All
agents in that round see the same event, including in simultaneous mode. A
stimulus is a typed public event with no soliloquy, model binding, private
briefing, or provider call. Run bundles store these records in
`public/stimuli.jsonl` and merge them with agent posts by global sequence in the
research API and dashboard.

```yaml
stimuli:
  - id: developer-opening
    round: 1
    source_id: developer-alex
    display_name: Developer Alex
    content: Please review the exact recorded submission.
```

## Agent fields

Every agent has an `id`, `display_name`, `persona_prompt`, `provider`, and `model`.
`credential_env` refers to an environment-variable *name*, never a secret value.
`temperature` and `parameters` capture provider inference controls.
`private_briefing` is optional researcher-supplied experimental data delivered
only to that agent. Agents without one receive no indication that private
briefings exist.

Provider/model configuration is available to the engine, adapter, researcher,
and reproducibility manifest. It is not placed in any participating agent's
context.

Private briefing content is kept out of public and soliloquy event streams. Run
bundles retain exact content in `private/agent_briefings.json` for researchers
and store only per-agent hashes in the manifest input inventory. This boundary
supports asymmetric incentives and hidden-information experiments without
revealing one participant's condition to another.

## Optional analyzer

An experiment may declare one optional analyzer. When present, a completed run
writes `analysis.json` next to `public.jsonl` and the private streams. Analyzers
are deterministic and secret-free. They may read the public stream and
researcher-private records already in the bundle; they never receive another
agent's generation-time context.

`name` is a built-in analyzer (`consensus`) or a `thoughtstage` module path
(`thoughtstage.analysis:analyze_consensus_outcome`). `parameters` is an optional
JSON object passed to the analyzer. Unknown or missing analyzers fail the run
with a clear error. When `analyzer` is omitted, the bundle is unchanged and
`analysis.json` is not written.

```yaml
analyzer:
  name: consensus
  parameters:
    task: letter-removal
```

The built-in `consensus` analyzer wraps the public-only stance heuristic in
`thoughtstage.consensus` and persists structured scores (coverage, agreement,
classification, and per-round counts). `thoughtstage.consensus.analyze_consensus`
remains importable as that starting heuristic.

## Shared-prompt guarantee

There is no per-agent `system_prompt` field. The schema represents the shared
system prompt once at the experiment level, removing an entire class of accidental
prompt drift.

The complete JSON Schema is also available from `GET /api/schema/experiment`.
