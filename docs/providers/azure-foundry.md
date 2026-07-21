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

Unknown parameters are rejected so a misspelling cannot silently change the
experimental protocol.

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
