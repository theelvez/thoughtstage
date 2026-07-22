# Amazon Bedrock provider

The `bedrock` provider calls text models through Amazon Bedrock's unified
Converse API. It uses an explicit two-call protocol for every turn:

1. elicit a researcher-private soliloquy; and
2. give only that agent's current soliloquy back to the same model while asking
   for the public post.

The adapter records the two calls separately as `private` and `public` usage.
It never inserts the AWS profile, Region, provider name, model ID, credentials,
or another agent's soliloquy into model-visible context.

## Authenticate

Use short-lived IAM Identity Center credentials and the least-privilege role
created by the [AWS infrastructure scaffold](../../infra/aws/README.md):

```powershell
aws sso login --profile thoughtstage-source
$env:THOUGHTSTAGE_AWS_PROFILE = "thoughtstage-bedrock"
```

```bash
aws sso login --profile thoughtstage-source
export THOUGHTSTAGE_AWS_PROFILE=thoughtstage-bedrock
```

The environment variable contains an AWS profile name, not a secret. A manifest
references that variable through `credential_env`:

```yaml
provider: bedrock
model: us.amazon.nova-2-lite-v1:0
credential_env: THOUGHTSTAGE_AWS_PROFILE
temperature: 0.6
parameters:
  region: us-east-2
  private_max_output_tokens: 260
  public_max_output_tokens: 360
  max_attempts: 5
```

If `credential_env` is omitted, boto3 uses its normal default credential chain.
Never place access keys, session tokens, or credential values in a manifest.

## Provider parameters

The Bedrock adapter rejects unknown parameters instead of silently guessing.

| Parameter | Default | Meaning |
|---|---:|---|
| `region` | `us-east-2` | Bedrock Runtime source Region |
| `private_max_output_tokens` | `400` | Hard output-token limit for the soliloquy call |
| `public_max_output_tokens` | `400` | Hard output-token limit for the public-post call |
| `connect_timeout_seconds` | `10` | SDK connection timeout |
| `timeout_seconds` | `120` | SDK read timeout |
| `max_attempts` | `5` | Adaptive retry attempt limit |
| `send_temperature` | `true` | Whether to send the agent's `temperature` |
| `top_p` | omitted | Optional nucleus-sampling value |
| `service_tier` | omitted | Optional `default`, `flex`, or `priority` tier |

Both Converse calls always set `maxTokens` explicitly. This bounds spend and
avoids reserving a model's maximum output quota for short social posts.

## Model IDs and geographic routing

Use live catalog discovery rather than copying model IDs from old results:

```powershell
aws bedrock list-foundation-models `
  --region us-east-2 `
  --profile thoughtstage-bedrock

aws bedrock list-inference-profiles `
  --region us-east-2 `
  --profile thoughtstage-bedrock
```

Newer models often require an inference-profile ID. The bundled examples prefer
`us.` profiles so cross-Region routing remains within the United States. Model
availability, access terms, and pricing can change independently of Thoughtstage.

## Run the smoke panel

```powershell
$env:THOUGHTSTAGE_AWS_PROFILE = "thoughtstage-bedrock"
thoughtstage validate examples/bedrock/model-panel-smoke.yaml
thoughtstage run examples/bedrock/model-panel-smoke.yaml
```

Successful token counts are stored only in
`private/model_usage.jsonl`. AWS billing data remains authoritative for spend.
