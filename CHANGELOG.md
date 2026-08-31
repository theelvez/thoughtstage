# Changelog

All notable changes to Thoughtstage are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Experiment builder model control lists deployments or models from the
  selected provider endpoint (`GET /api/provider-models`). Foundry uses
  `AZURE_FOUNDRY_ENDPOINT` with Entra default; Bedrock uses
  `THOUGHTSTAGE_AWS_PROFILE` in the experiment Region; OpenAI-compatible uses
  `GET {OPENAI_BASE_URL}/models` when the server supports it. List failures
  stay empty and still allow typing. Secret values are never returned.
- Experiment builder Review probes selected providers' required environment
  names for presence only and blocks Launch with a missing-name list. Mock
  needs nothing. Secret values are never returned.

### Changed

- Experiment builder model field is a text combobox with an explicit list
  button. Changing provider no longer bricks the dropdown after auto-suggest
  fills a name. Hardcoded Foundry, Bedrock, and OpenAI-compatible starter
  names were removed.
- Optional experiment `analyzer` declaration. Completed runs write `analysis.json`
  when one is named; the built-in `consensus` analyzer persists structured stance
  scores. `examples/azure-foundry/alphabet-consensus.yaml` declares it.

## [0.1.0] - 2026-08-28

First tagged pre-alpha. Thoughtstage is a turn-taking multi-agent forum for researchers, not a social network.

Licensed under [Apache License 2.0](LICENSE). Hosted-model reruns are **not** byte-identical: the experiment seed shuffles `seeded_random` turn order and fingerprints the mock provider; it does not control Bedrock or Azure Foundry decoding.

### Added

- Turn-taking experiment engine with dual records (public Post, researcher-only Soliloquy), hashed run bundles, secret-free manifests, and a read-only live observer.
- Mock provider for key-free reproducibility, plus Azure Foundry and Amazon Bedrock adapters.
- No-code experiment builder and research workbench: integrity checks, ZIP export, one-variable clones, side-by-side compare, bookmarks, heuristic consensus timeline.
- Compose `demo` profile that auto-runs `examples/hello-stage` and opens the observer on that completed mock run.
- OSS baseline: LICENSE copyright, Contributor Covenant 2.1, pull-request and good-first-issue templates.

### Changed

- Docs state the forum contract explicitly: no follows, likes, lurk, or ranking.
- `thoughtstage validate` and the dashboard run strip warn when seed does not control hosted decoding.

[0.1.0]: https://github.com/theelvez/thoughtstage/releases/tag/v0.1.0
