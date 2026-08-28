# Changelog

All notable changes to Thoughtstage are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
