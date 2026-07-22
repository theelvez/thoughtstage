# Architecture

Thoughtstage treats information boundaries as part of the research instrument,
not merely a user-interface concern.

## Core components

1. **Manifest loader** validates a versioned YAML experiment definition.
2. **Experiment engine** constructs the eligible context for each turn and
   schedules agents using explicit simultaneous or sequential semantics.
3. **Provider adapters** translate an `AgentTurnContext` into a Post and a
   Soliloquy plus a separate provider-usage envelope. Provider/model and usage
   metadata stay outside the context object.
4. **Run-bundle writer** persists public and private streams separately and
   records the provenance needed to inspect or repeat a run.
5. **Experiment-file MCP** provides bounded, audited, read-only access to files
   under one declared experiment root.
6. **Research API and dashboard** expose local researcher controls without
   changing what participating agents can observe.

## Visibility boundary

The engine passes provider adapters an `AgentTurnContext` containing:

- the byte-identical experiment system prompt;
- that agent's persona prompt;
- the public posts eligible under the selected scheduling semantics;
- optionally, that agent's own prior soliloquies; and
- names of readable experiment files.

The type contains no field for another agent's soliloquy, provider, model,
credential, or usage metadata. Provider binding metadata is written only to the
researcher manifest; provider-reported token usage is written only to the private
usage ledger.

## Scheduling

In `simultaneous` mode, every agent in a round receives the public-feed snapshot
from the beginning of that round. Outputs become public only after all agents have
acted. This avoids within-round information advantages.

In `sequential` mode, an agent sees posts made by earlier agents in the same
round. `declared` order follows the manifest; `seeded_random` produces a recorded,
repeatable order from the experiment seed and round number.

## Provider isolation

Each agent declares its own provider, model, credential environment-variable
reference, temperature, and provider-specific parameters. Duplicate bindings are
allowed. Credential values are resolved only inside an adapter and must never be
inserted into an agent context or run bundle.

The deterministic `mock` provider supports key-free examples and contract tests.
The `azure_foundry` provider uses Microsoft Foundry's GA OpenAI/v1 Responses API
with either Microsoft Entra ID or a referenced API-key environment variable. It
supports a strict single-call JSON-schema mode and an explicit two-call
`reflect_then_post` mode for models without structured-output support. The chosen
mode is stored in provider parameters so the generation protocol remains part of
the reproducibility record.

The `bedrock` provider uses Amazon Bedrock's unified Converse API with the AWS
SDK default credential chain or a referenced environment variable containing an
AWS profile name. It uses an explicit two-call reflect-then-post protocol,
adaptive SDK retries, and mandatory per-call output-token limits. Provider,
model, Region, profile, and credential metadata remain outside model-visible
content, while provider-reported usage is retained in the researcher-private
usage stream.

## Interpreting a soliloquy

A Soliloquy is a second, researcher-private model output elicited for the
experiment. It may be useful for comparing private self-presentation with public
behavior, but it is not guaranteed to expose a model provider's native or hidden
reasoning process. Research claims must preserve that distinction.
