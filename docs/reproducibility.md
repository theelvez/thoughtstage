# Reproducibility contract

Thoughtstage distinguishes **replayability** from **rerun reproducibility**.

## Replayability

A completed run bundle contains the exact public and private event streams plus
the experiment and input-file hashes. Analysis code can therefore replay the
observed run without calling a model provider again.

## Rerun reproducibility

The bundle records:

- Thoughtstage version and source revision;
- original experiment bytes and SHA-256 hash;
- input-file paths, sizes, and SHA-256 hashes;
- schedule, turn order, private-memory policy, round count, and seed;
- provider and model identifiers;
- inference parameters and credential environment-variable names; and
- Python and platform versions.

Container digests and dependency lock files should be retained alongside released
experiments. Secrets are intentionally excluded.

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
