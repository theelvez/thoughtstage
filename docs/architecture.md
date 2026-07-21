# Architecture

Thoughtstage treats information boundaries as part of the research instrument,
not merely a user-interface concern.

## Core components

1. **Manifest loader** validates a versioned YAML experiment definition.
2. **Experiment engine** constructs the eligible context for each turn and
   schedules agents using explicit simultaneous or sequential semantics.
3. **Provider adapters** translate an `AgentTurnContext` into a Post and a
   Soliloquy. Provider/model configuration stays outside the context object.
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

The type contains no field for another agent's soliloquy, provider, model, or
credential. Provider metadata is used by the adapter itself and written only to
the researcher manifest.

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

Only the deterministic `mock` provider ships in the initial foundation. Real
provider adapters will be added behind the same contract with key-free contract
tests.

## Interpreting a soliloquy

A Soliloquy is a second, researcher-private model output elicited for the
experiment. It may be useful for comparing private self-presentation with public
behavior, but it is not guaranteed to expose a model provider's native or hidden
reasoning process. Research claims must preserve that distinction.
