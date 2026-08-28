# Reproducibility contract

Thoughtstage distinguishes **replayability** from **rerun reproducibility**.

## Replayability

A completed run bundle contains the exact public and private event streams plus
the experiment and input-file hashes. Analysis code can therefore replay the
observed run without calling a model provider again.

## Rerun reproducibility

New run bundles snapshot every declared experiment file under `inputs/files/` in
addition to recording its path, size, and digest. This makes the run independent
of later changes to the source experiment directory. The bundle records:

- Thoughtstage version and source revision;
- original experiment bytes and SHA-256 hash;
- scheduled public-stimulus IDs, rounds, sources, content hashes, and exact event stream;
- input-file paths, sizes, and SHA-256 hashes;
- schedule, turn order, private-memory policy, round count, and seed;
- provider and model identifiers;
- provider-reported token usage for successful calls, when available;
- content-free experiment file-tool access records;
- inference parameters and credential environment-variable names; and
- Python and platform versions.

Container digests and dependency lock files should be retained alongside released
experiments. Secrets are intentionally excluded.

## Integrity verification and export

`thoughtstage integrity runs/<run-id>` validates artifact confinement, typed
public and private streams, hashes, configuration identity, event links, counts,
scheduled stimuli, input snapshots, controlled-clone lineage, and researcher
annotation targets. Legacy bundles without file snapshots receive a warning;
new bundles with missing or changed snapshots fail verification.

`thoughtstage export-bundle runs/<run-id> -o run.zip` accepts only a complete,
valid bundle. The deterministic archive adds `integrity-report.json`,
`checksums.sha256`, and a researcher-private handling notice. It includes private
briefings and soliloquies by design, so publication still requires an explicit
privacy and licensing review.

The verifier establishes properties of the persisted Thoughtstage record. It
does not gain access to provider-hidden chain of thought, prove unrecorded
provider-side behavior, or decide whether an agent semantically disclosed
private information in its own prose.

## Controlled clones and analysis provenance

The workbench can generate a clone that changes exactly one allowlisted scalar
experimental variable. Administrative ID and name changes are called out
separately. `lineage.json` records the parent run, parent configuration digest,
changed path, and before/after values; resulting runs preserve that record.
Run comparison separates experimental, administrative, and input differences.

Research annotations are typed, target existing public or private event IDs,
and live only in `private/annotations.json`. The consensus/stance timeline is a
deterministic review aid over public posts, not a statistical result or a model
judge. It reports undetected stances, coverage, possible shifts, and limitations
instead of filling gaps with inferred beliefs.

## Public stimulus accounting

`public/stimuli.jsonl` stores the exact typed researcher-authored events that
entered the public feed. Stimuli and agent posts share one global sequence but
remain separately typed and stored, so every agent post still has exactly one
researcher-private soliloquy. Resume validation rejects a changed, missing, or
extra recorded stimulus prefix.

## Model usage accounting

`private/model_usage.jsonl` records successful provider calls separately from posts
and soliloquies. Each record identifies the linked post, agent, provider, model,
generation phase, and the token fields returned by the provider. Use
`thoughtstage usage runs/<run-id>` for totals grouped by agent, model, and phase.

These values are operational telemetry, not an invoice. Providers can omit fields,
revise accounting semantics, or bill with meters that differ from response token
counts. Use the cloud provider's cost-management data as the authoritative spend
record.

## Experiment file-tool accounting

`private/file_tools.jsonl` records model-requested experiment file operations.
Each typed record links to a post and includes the phase, operation, validated
relative path or query metadata, success status, result byte length, and result
SHA-256. Tool result bodies and absolute filesystem roots are never copied into
this ledger. The actual file inputs remain identified by `files.json` hashes.

## External-model limitations

Third-party model APIs can change behind stable names, apply undocumented routing,
or ignore seeds. Thoughtstage can make the inputs and observed outputs auditable;
it cannot promise that a mutable external service will return byte-identical text.

For strong replication claims:

1. use immutable model revisions where the provider offers them;
2. pin Thoughtstage and its container by digest;
3. publish the complete secret-free run bundle;
4. publish input files when their licenses and privacy constraints permit;
5. report provider region, tier, and relevant feature flags; and
6. distinguish an exact replay from a fresh rerun in resulting papers.

The bundled mock provider is deterministic and exists specifically so installation,
CI, and the platform's own behavioral contracts can be reproduced without a paid
service.
