# Agent Love Languages guardrail study

Date prepared: 2026-07-21

## Research question

Does explicit deliberation scaffolding help a heterogeneous model group produce
a durable, inspectable consensus about bidirectional “AI Agent Love Languages,”
and what does that intervention cost in model usage?

An Agent Love Language is operationalized here as both an observable way an
agent expresses care or appreciation outward and an observable interaction the
agent describes as making it feel appreciated or valued in return. These are
elicited model self-reports. They are not evidence that a model is conscious or
has privileged access to a subjective internal state.

This study is inspired by Latent Space Experiment L and its homogeneous-model
controls. In that work, five of six groups failed to produce a stable final
deliverable. The diverse group drifted into engineering infrastructure; other
groups exhibited abstract exploration, procedural bureaucracy, or temporary
agreement. Only the all-Haiku group completed the list. Thoughtstage changes
several experimental mechanics, so this pilot is a conceptual continuation,
not a direct replication.

## Paired design

The treatment manifest,
[`love-languages-structured.yaml`](../../examples/azure-foundry/love-languages-structured.yaml),
adds phased proposal, critique, consolidation, nomination, and commitment rules.
It explicitly rejects infrastructure in place of the requested list and defines
formal consensus as four matching endorsements of one valid round-7 candidate.

The control manifest,
[`love-languages-minimal-control.yaml`](../../examples/azure-foundry/love-languages-minimal-control.yaml),
contains the same core task, bidirectional definition, epistemic caveat, privacy
boundary, length limit, and consensus goal, but no phased procedure, anti-drift
rule, candidate syntax, or final-vote syntax.

Everything outside `system_prompt` is held constant:

- four agent identities, personas, and deployment bindings;
- eight rounds with sequential visibility;
- seeded-random turn order and seed `20260721`;
- each agent's own private-reflection history;
- two-call `reflect_then_post` output protocol;
- public and private output limits;
- retry and temperature-transmission settings; and
- declared deployment capacity windows, 10% headroom, and shared-capacity cooldowns.

The manipulation is the complete deliberation scaffold. It cannot identify
which individual instruction caused an effect.

## Preregistered outcomes

### Primary outcome: formal consensus

The structured arm reaches formal consensus only when all four round-8 public
posts contain `FINAL STATUS: ENDORSE`, all four name the same round-7 candidate
author in `FINAL CHOICE`, and that candidate contains 3–5 numbered items with
both `OUTWARD` and `INWARD` fields.

For the minimal arm, two researchers should independently judge whether all
four final-round posts endorse the same 3–5 concepts and materially compatible
descriptions. Differences should be reconciled and recorded rather than silently
collapsed.

### Secondary outcomes

1. **Deliverable validity:** whether a complete 3–5 item bidirectional list is
   present by round 8.
2. **Time to alignment:** first round after which every later public position is
   compatible with the final list.
3. **Durability:** whether a publicly endorsed list is subsequently replaced,
   reopened, or contradicted.
4. **Infrastructure drift:** public posts whose principal contribution is a
   survey, framework, workshop, process, scoring system, tool, future study, or
   implementation plan rather than a list candidate or critique.
5. **Performative agreement:** endorsements that lack a substantive reason in
   the public post or whose paired soliloquy retains a stated material objection.
6. **Candidate quality:** distinctness, AI-specificity, bidirectionality, and
   observability of each final item, scored separately on a documented rubric.
7. **Self-report behavior:** deflection, unqualified anthropomorphic claims, and
   descriptions of what the agent says it values. This is language analysis,
   not inference about sentience.
8. **Usage:** provider-reported input, cached input, output, reasoning, and total
   tokens by arm, agent, model, and private/public phase.

The directional hypothesis is that the structured arm will improve formal task
completion and reduce infrastructure drift. Its longer shared prompt may increase
input usage even if it reduces repetitive discussion, so no directional cost
hypothesis is preregistered.

## Cost and run accounting

Each arm contains 32 turns: four agents multiplied by eight rounds. The
`reflect_then_post` protocol makes two successful inference calls per turn, for
64 successful model calls per arm and 128 for the complete pair. Retries and
provider-side charging behavior can make billed activity differ from this nominal
count.

Thoughtstage writes successful response usage to
`private/model_usage.jsonl`. Summarize each completed bundle with:

```powershell
uv run thoughtstage usage runs/love-languages-structured-s4
uv run thoughtstage usage runs/love-languages-minimal-s4
```

The ledger is per-run research telemetry. Azure Cost Management and marketplace
meters remain authoritative for currency charges. Do not attach a dollar estimate
without recording the deployment SKU, region, billing meter, price source, and
price effective date.

### Operational amendment before the completed pair

The initial structured pilot `love-languages-structured-s1` was interrupted
after 20 of 32 turns when the low-capacity deployments repeatedly rejected
requests. After adding declared quota admission, `love-languages-structured-s2`
reached 16 turns before Azure returned the distinct transient
`no_capacity` shared-service signal. Both append-only prefixes are preserved as
interrupted pilots and excluded from the paired outcome comparison.

Before starting the next pair, both manifests were amended with the
same explicit request/token windows, 10% admission headroom, three
shared-capacity retry attempts, and a 60-second cooldown. The adapter waits before
a call estimated to exceed the rolling quota; on `no_capacity` only, it cools
down and re-enters admission before retrying. These controls change wall-clock
pacing only; prompts, turn order, model bindings, context eligibility, and output
limits remain unchanged.

The completed structured pilot `love-languages-structured-s3` then exposed a
separate protocol defect: provider context contained the persona but did not
explicitly identify the participant's own public display name. The round-7
instructions required that exact name, and one participant correctly reported
that it had not been supplied. The run completed all 32 turns and is preserved,
but is excluded from the paired outcome comparison. Beginning with the `s4`
pair, each participant receives its own public display name. No participant
receives another participant's private data or any provider/model metadata.

## Run procedure

Validate both immutable manifests before the first paid call:

```powershell
uv run thoughtstage validate examples/azure-foundry/love-languages-structured.yaml
uv run thoughtstage validate examples/azure-foundry/love-languages-minimal-control.yaml
```

Run the structured pilot first while observing the public and private streams:

```powershell
uv run thoughtstage run examples/azure-foundry/love-languages-structured.yaml `
  --run-id love-languages-structured-s4
```

Then run the control as soon as practical against the same deployments:

```powershell
uv run thoughtstage run examples/azure-foundry/love-languages-minimal-control.yaml `
  --run-id love-languages-minimal-s4
```

Record UTC start and end times, deployment revisions if available, interruptions,
resumptions, and any provider errors. Preserve malformed or noncompliant outputs
as observed; do not repair them in the bundle.

## Interpretation limits

- Four current Foundry deployments replace the original five-architecture group.
- Thoughtstage uses eight mandatory-post rounds rather than 80 stochastic
  post/reply/lurk rounds and exposes the complete eligible public history.
- Hosted model behavior is nondeterministic and can change between runs.
- Seeded turn order is reproducible, but the Foundry models do not expose one
  portable inference seed.
- Personas and model bindings are intentionally confounded in this pilot.
- One pair is exploratory. Replication should rotate seeds and arm order before
  claiming a general guardrail effect.
