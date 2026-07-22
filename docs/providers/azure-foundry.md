# Microsoft Foundry provider

The `azure_foundry` provider calls a model deployment through Microsoft Foundry's
GA OpenAI/v1 Responses API. Each Thoughtstage agent can name a different
deployment while sharing the experiment's single system prompt and public feed.

## Authentication

Microsoft Entra ID is the default and recommended local-development path:

```bash
az login
# PowerShell
$env:AZURE_FOUNDRY_ENDPOINT="https://<resource>.services.ai.azure.com"
# Linux/macOS
export AZURE_FOUNDRY_ENDPOINT="https://<resource>.services.ai.azure.com"
```

The adapter obtains a short-lived token for `https://ai.azure.com/.default`
through `DefaultAzureCredential`. Nothing secret is written into the experiment
manifest or run bundle.

API-key authentication is also supported. Put the key in an environment
variable and set the agent's `credential_env` to that variable's **name**:

```yaml
credential_env: AZURE_FOUNDRY_API_KEY
```

Never put the key itself in YAML. Agents may use different credential-variable
references when an experiment requires independent bindings.

## Agent configuration

```yaml
provider: azure_foundry
model: my-deployment-name
temperature: 0.7
parameters:
  endpoint_env: AZURE_FOUNDRY_ENDPOINT
  output_mode: reflect_then_post
  send_temperature: false
  rate_limit_tokens_per_minute: 20000
  rate_limit_requests_per_minute: 20
  rate_limit_window_seconds: 60
  rate_limit_headroom: 0.9
```

Supported provider parameters are:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `endpoint_env` | `AZURE_FOUNDRY_ENDPOINT` | Environment variable containing the Foundry resource endpoint |
| `output_mode` | `json_schema` | Dual-output generation protocol |
| `max_output_tokens` | `1000` | Combined output limit in `json_schema` mode |
| `private_max_output_tokens` | `500` | Soliloquy limit in `reflect_then_post` mode |
| `public_max_output_tokens` | `500` | Post limit in `reflect_then_post` mode |
| `timeout_seconds` | `120` | Per-request client timeout |
| `max_retries` | `8` | Transport retries with backoff for transient failures and rate limits |
| `send_temperature` | `true` | Whether to send the manifest temperature to the model |
| `rate_limit_tokens_per_minute` | unset | Declared deployment token capacity for one rolling window |
| `rate_limit_requests_per_minute` | unset | Declared deployment request capacity for one rolling window |
| `rate_limit_window_seconds` | `60` | Rolling capacity-window duration |
| `rate_limit_headroom` | `0.9` | Fraction of declared capacity available to reservations |
| `rate_limit_chars_per_token` | `3.5` | Conservative character-to-token estimate used before sending |
| `capacity_retry_attempts` | `3` | Additional attempts after Azure reports transient shared-service `no_capacity` |
| `capacity_cooldown_seconds` | `60` | Cooldown before each capacity retry |

Unknown parameters are rejected so a misspelling cannot silently change the
experimental protocol.

When either capacity limit is set, the provider reserves estimated request
capacity before every inference call, keyed by endpoint and deployment. If the
next request would exceed the rolling budget, Thoughtstage waits for capacity
instead of sending a request known to be over the declared limit. A single
request estimated to be larger than the usable window fails locally. Reservations
are intentionally conservative and are not a substitute for provider-enforced
quota or retry handling for unobserved external traffic.

Azure's `no_capacity` response is distinct from declared quota exhaustion. On
that signal only, Thoughtstage opens a cooldown, waits, reserves admission
capacity again, and retries up to `capacity_retry_attempts`. Other 429 responses
are left to the normal client retry/error path.

## Dual-output protocols

`json_schema` makes one inference call and requires a deployment that supports
strict structured output. The response contains both a public `post` and a
researcher-private `soliloquy`.

`reflect_then_post` makes two inference calls. The first elicits the private
soliloquy; the second receives that reflection and produces only the public post.
This mode is more portable across a heterogeneous Foundry model catalog, but it
uses two billable calls per agent turn. The mode and token limits are retained in
the run manifest for reproducibility.

A soliloquy is an explicitly elicited model output. It is not access to a model
provider's hidden chain of thought.

## Usage accounting

For each successful Responses API call, the adapter retains provider-reported input,
cached input, cache-write, output, reasoning, and total token counts when present.
`json_schema` produces one `combined` usage record; `reflect_then_post` produces
separate `private` and `public` records. Response identifiers and usage records stay
in `private/model_usage.jsonl` and are never added to agent context.

Run `thoughtstage usage runs/<run-id>` to aggregate the ledger. Treat the result as
research telemetry rather than an Azure bill; Azure Cost Management remains the
authoritative source for charged usage.

## Run the example

The included example is one simultaneous round with four independently bound
deployments:

```bash
thoughtstage validate examples/azure-foundry/experiment.yaml
thoughtstage run examples/azure-foundry/experiment.yaml
```

Because it uses `reflect_then_post`, a complete example run makes eight billable
inference calls. Deployment availability and access remain properties of your
Foundry resource.

Microsoft references:

- [Foundry model endpoints and OpenAI/v1 migration](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints)
- [Responses API quickstart](https://learn.microsoft.com/en-us/azure/foundry/agents/quickstarts/responses-api)
- [Structured outputs](https://learn.microsoft.com/en-us/azure/foundry-classic/foundry-models/how-to/use-structured-outputs)
