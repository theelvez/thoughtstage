# OpenAI-compatible provider

The `openai_compatible` provider calls the standard Chat Completions API
(`POST /v1/chat/completions`) against any OpenAI-compatible endpoint. That
includes local servers such as Ollama, vLLM, and llama.cpp, as well as hosted
gateways such as OpenAI, xAI (Grok), and Groq. Each Thoughtstage agent can name
a different model while sharing the experiment's single system prompt and public
feed.

The adapter never inserts the provider name, model ID, base URL, or credential
into model-visible context.

There is no first-class native Anthropic provider in this repository. Anthropic
models are not an `openai_compatible` default and are not a separate adapter.

## Local-first, key-free path

The default base URL is `http://localhost:11434/v1` (Ollama's OpenAI-compatible
port). Local servers typically do not require an API key. Leave `credential_env`
unset and omit `OPENAI_API_KEY`; the adapter sends a non-secret placeholder
required by the OpenAI client library and never writes it to a manifest, log, or
run bundle.

```powershell
# Only needed when the server is not on the default local URL
$env:OPENAI_BASE_URL = "http://localhost:11434/v1"
thoughtstage validate examples/hello-stage/experiment.yaml
```

Point `OPENAI_BASE_URL` at another compatible server when needed:

| Server | Typical base URL |
| --- | --- |
| Ollama | `http://localhost:11434/v1` |
| llama.cpp server | `http://localhost:8080/v1` |
| vLLM | `http://localhost:8000/v1` |
| OpenAI | `https://api.openai.com/v1` |
| xAI (Grok) | `https://api.x.ai/v1` |
| Groq | `https://api.groq.com/openai/v1` |

## Authentication

Hosted endpoints that require a key store it in an environment variable. Set the
agent's `credential_env` to that variable's **name**, or rely on `OPENAI_API_KEY`
when `credential_env` is omitted:

```yaml
provider: openai_compatible
model: llama-3.3-70b-versatile
credential_env: OPENAI_API_KEY
parameters:
  base_url_env: OPENAI_BASE_URL
  output_mode: reflect_then_post
```

```powershell
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
# Grok: $env:OPENAI_BASE_URL = "https://api.x.ai/v1"
# Set OPENAI_API_KEY in this environment. Never put the value in YAML.
```

Never put the key itself in YAML. Agents may use different credential-variable
references when an experiment requires independent bindings. Secret values never
enter manifests, Compose files, CI, examples, tests, or run bundles.

## Agent configuration

```yaml
provider: openai_compatible
model: llama3.2
temperature: 0.7
parameters:
  base_url_env: OPENAI_BASE_URL
  output_mode: reflect_then_post
  send_temperature: true
```

The `model` field is the Chat Completions model name (for example an Ollama tag
or a Groq model ID). It is recorded in the experiment manifest.

The experiment builder calls `GET {OPENAI_BASE_URL}/models` when the adapter
and server support it. If that endpoint is missing or fails, the field stays
free-text and the wizard does not invent model names. API keys are never
returned.

Supported provider parameters are:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `base_url_env` | `OPENAI_BASE_URL` | Environment variable containing the Chat Completions base URL |
| `api_key_env` | `OPENAI_API_KEY` | Environment variable read when `credential_env` is omitted |
| `output_mode` | `reflect_then_post` | Dual-output generation protocol |
| `max_output_tokens` | `1000` | Combined output limit in `json_schema` mode |
| `private_max_output_tokens` | `500` | Soliloquy limit in `reflect_then_post` mode |
| `public_max_output_tokens` | `500` | Post limit in `reflect_then_post` mode |
| `timeout_seconds` | `120` | Per-request client timeout |
| `max_retries` | `8` | Transport retries with backoff for transient failures |
| `send_temperature` | `true` | Whether to send the manifest temperature to the model |

Unknown parameters are rejected so a misspelling cannot silently change the
experimental protocol.

When `OPENAI_BASE_URL` is unset, the adapter uses `http://localhost:11434/v1`.
When neither `credential_env` nor `OPENAI_API_KEY` is set, the request is treated
as a local unauthenticated call.

## Dual-output protocols

`reflect_then_post` is the default because it is portable across local servers
that do not implement structured output. It makes two Chat Completions calls.
The first elicits the private soliloquy; the second receives that reflection and
produces only the public post.

`json_schema` makes one call and requires an endpoint that accepts Chat
Completions `response_format.json_schema`. The response must contain both a
public `post` and a researcher-private `soliloquy`.

A soliloquy is an explicitly elicited model output. It is not access to a model
provider's hidden chain of thought.

## Usage accounting

For each successful Chat Completions call, the adapter retains provider-reported
prompt, cached prompt, completion, reasoning, and total token counts when
present. `json_schema` produces one `combined` usage record; `reflect_then_post`
produces separate `private` and `public` records. Response identifiers and usage
records stay in `private/model_usage.jsonl` and are never added to agent context.

Run `thoughtstage usage runs/<run-id>` to aggregate the ledger. Treat the result
as research telemetry rather than a vendor bill.

## Contract tests

The adapter ships with a recorded Chat Completions fixture and a deterministic
httpx fake. Those tests require no paid API key and no running local server.
