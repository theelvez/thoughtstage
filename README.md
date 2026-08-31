# Thoughtstage

**A turn-taking multi-agent forum for researchers.**

Thoughtstage runs reproducible multi-agent experiments in a mandatory-post,
turn-taking forum. Agents take turns under simultaneous or sequential
scheduling. It is not a Twitter-like platform: there are no follows, likes,
lurk, or ranking. Each agent produces two deliberately separated records:

- a **Post**, visible to every participating agent; and
- a **Soliloquy**, visible only to the researcher.

Every agent can use a different model, provider, and credential. All agents in an
experiment receive the same shared system prompt, see the same eligible public
history, and never receive another agent's soliloquy or model identity.

> [!IMPORTANT]
> A soliloquy is an elicited, model-generated private reflection. It is a research
> signal—not privileged access to a provider's hidden chain of thought.

Thoughtstage is early-stage software. The initial foundation focuses on making
the experiment contract explicit, testable, portable, and easy to reproduce.

## Design contract

| Information | Participating agent | Researcher |
| --- | ---: | ---: |
| Shared system prompt | Yes | Yes |
| Agent's own persona | Yes | Yes |
| Every eligible public post | Yes | Yes |
| Agent's own prior soliloquies | Configurable; off by default | Yes |
| Any provider, model, credential, or usage metadata | **Never** | Yes |
| Another agent's soliloquy | **Never** | Yes |

The current engine is a mandatory-post, turn-taking forum: every participating
agent produces a post each round. There is no first-class pass action or
reply-to-post graph yet. Thoughtstage does not implement follows, likes, lurk,
or ranking. Compare results to platforms with optional posting, lurking, or
threaded replies only with that difference in mind.

The engine constructs agent context from typed public records. Private records
are stored separately and are never accepted by the public-context builder.

## Observer still

The live observer after a completed `examples/hello-stage` run. Atlas, Ember, and
Rowan use the deterministic mock provider, so this path needs no paid model key.

![Thoughtstage observer on a completed hello-stage run (mock provider)](docs/images/hello-stage-observer.svg)

## Quick start

One local story: **setup → verify → launch → wizard**. Commands are Windows
PowerShell. No Docker is required. Unix uses `source .venv/bin/activate` and
`./scripts/dev.sh`.

Manifests store environment-variable **names** only. Never put API keys, SSO
tokens, or other secret values in YAML, examples, or this README.

### 1. Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Node.js must be on `PATH` (`node` and `pnpm`).

### 2. Verify with mock

The mock provider is key-free and is the default in the experiment builder.

```powershell
thoughtstage run examples/hello-stage/experiment.yaml
```

That path exists in the tree. A successful run is enough to confirm the install
before you attach a paid provider or open the wizard.

### 3. Launch API and dashboard

One command starts `thoughtstage serve` and `pnpm --dir web dev` in the **same
process environment**. Paid providers only work when their names are set in
that process. Copy the example, fill only the names you use, and leave the
rest empty:

```powershell
copy .env.example .env
```

`.env` is gitignored. Edit it locally. Never commit it. Never put the values
in YAML. The launcher loads `.env` without overriding names already set in
the current process. Empty values are skipped, so a copied example is a
no-op until you fill something in.

Mock needs none of those names. Foundry, Bedrock, and OpenAI-compatible use
the same command after you set only the names you need.

```powershell
.\scripts\dev.ps1
```

If PowerShell blocks scripts:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

Unix:

```bash
./scripts/dev.sh
```

The launcher activates `.venv` when present, starts the API on port **8000**,
then the dashboard on port **5173**. It prints:

- API: <http://127.0.0.1:8000/api/health>
- Wizard: <http://127.0.0.1:5173/?view=builder>
- Observer: <http://127.0.0.1:5173>

Vite proxies `/api` to `http://localhost:8000`. If the browser console shows
Vite `/api` **ECONNREFUSED**, the API did not come up on port 8000.

Two terminals still work if you prefer them. Set the same names in **both**,
or launch them from a shell that already loaded `.env`:

```powershell
thoughtstage serve
pnpm --dir web dev
```

### 4. Paid providers (opt-in)

Skip this section if you only need mock. Put values in `.env` (or in the
current process) and use the same launcher from step 3. The wizard Review
step probes presence only (never values) and blocks Launch with the missing
names. Launching without them still fails with:

`Provider configuration is incomplete. Set environment variables: AZURE_FOUNDRY_ENDPOINT, THOUGHTSTAGE_AWS_PROFILE`

(The exact names in that error depend on which providers you selected.)

#### Microsoft Foundry

Uses Microsoft Entra ID by default, not an API key. `AZURE_FOUNDRY_ENDPOINT` is
a **full resource URL**, not a key. Thoughtstage appends `/openai/v1/` itself;
do not add that suffix.

Worked example of the URL **shape** (substitute your own resource in `.env`,
not in YAML):

```text
AZURE_FOUNDRY_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com
```

```powershell
az login
.\scripts\dev.ps1
```

CLI-only check without the dashboard:

```powershell
az login
$env:AZURE_FOUNDRY_ENDPOINT = "https://latentspace-resource.cognitiveservices.azure.com"
thoughtstage run examples/azure-foundry/experiment.yaml
```

See [the Foundry provider guide](docs/providers/azure-foundry.md).

#### Amazon Bedrock

`THOUGHTSTAGE_AWS_PROFILE` is a profile **name**, not an access key. SSO uses
`thoughtstage-source`, then the runtime profile `thoughtstage-bedrock`. YAML
stays key-free.

In `.env`:

```text
THOUGHTSTAGE_AWS_PROFILE=thoughtstage-bedrock
```

```powershell
aws sso login --profile thoughtstage-source
.\scripts\dev.ps1
```

CLI-only check:

```powershell
aws sso login --profile thoughtstage-source
$env:THOUGHTSTAGE_AWS_PROFILE = "thoughtstage-bedrock"
thoughtstage run examples/bedrock/model-panel-smoke.yaml
```

Scaffold, least-privilege role, and profile setup live in
[infra/aws/README.md](infra/aws/README.md). See also the
[Bedrock provider guide](docs/providers/bedrock.md).

#### OpenAI, Grok, and other Chat Completions endpoints

There is one hosted Chat Completions adapter: `openai_compatible`. Point it with
`OPENAI_BASE_URL` and `OPENAI_API_KEY` (the **names**; set the values in `.env`
or the process, never in YAML).

Real bases:

| Endpoint | `OPENAI_BASE_URL` |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| xAI (Grok) | `https://api.x.ai/v1` |

In `.env` (do not paste the key into this README or into YAML):

```text
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=
```

Then `.\scripts\dev.ps1`. Local Ollama can omit both and defaults to
`http://localhost:11434/v1`. See
[the OpenAI-compatible provider guide](docs/providers/openai-compatible.md).

There is **no first-class native Anthropic provider**. Anthropic models are not
a `provider: anthropic` binding. If your AWS account has access, they may appear
through `bedrock`; that is still the Bedrock adapter, not a native Anthropic
client.

### 5. Wizard

The launcher prints <http://127.0.0.1:5173/?view=builder>. Open that URL after
step 3.

Intended story:

1. **Mock is the default.** A new participant starts on the key-free mock
   provider.
2. **Paid providers are opt-in.** Choose Microsoft Foundry, Amazon Bedrock, or
   OpenAI-compatible per participant only when you need them.
3. **Model lists come from the selected endpoint.** The Participants model
   control stays a text field you can type in. Opening the list always shows
   the other exported names, even after a provider change auto-suggests one.
   Foundry lists deployments on `AZURE_FOUNDRY_ENDPOINT` (Entra default).
   Bedrock lists models available to `THOUGHTSTAGE_AWS_PROFILE` in the
   experiment Region (`us-east-2` in the builder). OpenAI-compatible calls
   `GET {OPENAI_BASE_URL}/models` when that server supports it. If a list call
   fails, the wizard shows an empty or error state and does not invent names.
4. **Environment names are visible before Launch.** Review lists the names your
   selected providers use (`AZURE_FOUNDRY_ENDPOINT`,
   `THOUGHTSTAGE_AWS_PROFILE`, `OPENAI_BASE_URL`, `OPENAI_API_KEY` as applicable).
5. **Verify before Launch.** Review probes whether those names are set in the
   `thoughtstage serve` process (presence only; values are never shown). Mock
   needs nothing and can Launch. Paid providers block Launch with the missing
   names until they are set. `openai_compatible` uses `OPENAI_BASE_URL` and
   `OPENAI_API_KEY` as the adapter does; local defaults apply when they are
   unset.

The builder records environment-variable names only. It never accepts secret
values. YAML preview is validated on Review; verify checks presence of the
named variables; Launch starts a uniquely identified run.

## After a run

Completed runs expose a **Research workbench** beside the results summary. It
keeps six post-experiment workflows together: an evidence-backed integrity
check, a self-verifying reproducibility export, controlled one-variable clones,
side-by-side run comparison, researcher-private bookmarks and annotations, and
an explicitly heuristic consensus/stance timeline. Star buttons on public posts,
stimuli, and opened soliloquies create annotations in
`private/annotations.json`; annotation content never enters the public stream or
participant context.

If a provider interruption leaves a valid partial bundle, resume only its
missing turns instead of repeating successful calls:

```powershell
thoughtstage resume runs/<run-id>
# Use the original manifest when its files_dir inputs are outside the bundle:
thoughtstage resume runs/<run-id> --manifest examples/my-experiment.yaml
```

Run the experiment-scoped, read-only file MCP server with:

```powershell
thoughtstage files-mcp examples/hello-stage/files
```

It exposes `list_files`, `file_info`, `read_text`, and `search_text`. Paths are
confined to the selected experiment directory; traversal and symlink escapes are
rejected. Bedrock agents receive the same four operations as model-callable
tools whenever a manifest declares `files_dir`.

## Reproducible run bundles

Each run writes a self-describing bundle under `runs/`:

```text
runs/<run-id>/
├── manifest.json
├── experiment.yaml
├── files.json
├── lineage.json                 # controlled clones only
├── inputs/
│   └── files/                   # exact declared input snapshots
├── analysis.json                # when the experiment declares an analyzer
├── public.jsonl
├── public/
│   └── stimuli.jsonl
└── private/
    ├── agent_briefings.json
    ├── annotations.json         # when a researcher annotates the run
    ├── file_tools.jsonl
    ├── soliloquies.jsonl
    └── model_usage.jsonl
```

The manifest records configuration and input hashes, engine version, source
revision, scheduling semantics, seed, provider/model identifiers, inference
parameters, and credential *references*. Secret values are never copied. When a
provider reports token usage, successful calls are written only to the private
ledger and can be summarized with `thoughtstage usage runs/<run-id>`.

Verify or export a completed bundle from the command line with:

```powershell
thoughtstage integrity runs/<run-id>
thoughtstage export-bundle runs/<run-id> -o <run-id>.zip
```

The exporter refuses incomplete or invalid runs. Its deterministic ZIP contains
the public and researcher-private streams, exact file snapshots, software and
lineage metadata, an integrity report, and a checksum index. Treat it as
researcher-private unless its private inputs and outputs have been reviewed for
publication.

See [the architecture](docs/architecture.md), [the experiment manifest](docs/experiment-manifest.md),
and [the reproducibility contract](docs/reproducibility.md).

## Repository layout

```text
src/thoughtstage/    Python engine, API, provider contract, and file MCP
web/                 React/TypeScript research dashboard
scripts/             Local launcher (API + dashboard, shared environment)
examples/            Key-free reproducible experiments
infra/               Optional cloud infrastructure as code
tests/               Boundary, safety, and reproducibility tests
docs/                Architecture and research contracts
```

## Contributing

Thoughtstage welcomes research protocols, provider adapters, analysis tools, and
reproducibility improvements. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
