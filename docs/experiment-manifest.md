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
| `rounds` | Number of rounds |
| `schedule` | `simultaneous` or `sequential` |
| `turn_order` | `declared` or `seeded_random` |
| `private_memory` | `none` or `own_history`; defaults to `none` |
| `seed` | Recorded scheduling/provider seed |
| `files_dir` | Optional directory relative to the manifest |
| `agents` | One or more independently configured participants |

## Agent fields

Every agent has an `id`, `display_name`, `persona_prompt`, `provider`, and `model`.
`credential_env` refers to an environment-variable *name*, never a secret value.
`temperature` and `parameters` capture provider inference controls.

Provider/model configuration is available to the engine, adapter, researcher,
and reproducibility manifest. It is not placed in any participating agent's
context.

## Shared-prompt guarantee

There is no per-agent `system_prompt` field. The schema represents the shared
system prompt once at the experiment level, removing an entire class of accidental
prompt drift.

The complete JSON Schema is also available from `GET /api/schema/experiment`.
