# Thoughtstage AWS research access

This CloudFormation scaffold creates one human-assumable IAM role and
an IAM Identity Center permission set for local Thoughtstage research against
Amazon Bedrock. It creates no models, endpoints, storage, networking,
subscriptions, or other spend-capable resources.

The role can:

- discover foundation models and inference profiles;
- inspect model and inference-profile metadata; and
- invoke models through the Bedrock runtime, including streaming.

The role cannot mutate IAM, accept AWS Marketplace terms, create Bedrock agents
or knowledge bases, configure logging, or access any non-Bedrock service.

The Identity Center permission set grants exactly `sts:AssumeRole` on the
Thoughtstage role and no direct service permissions. The instance ARN and user
ID are deployment parameters so account-specific identity data is never
committed to the repository.

The managed policy intentionally uses `Resource: "*"` only for
`GetFoundationModelAvailability`, `ListFoundationModels`, and
`ListInferenceProfiles`. AWS does not define resource-level permissions for
these catalog operations. Model metadata and invocation permissions remain
scoped to foundation-model and inference-profile ARNs. The AWS Guard Rules
Registry's generic `IAM_POLICYDOCUMENT_NO_WILDCARD_RESOURCE` rule therefore
reports this statement as a known, reviewed exception.

## Region and cross-region inference

Deploy the stack in `us-east-2`. System and application inference-profile ARNs
are scoped to that source Region and this AWS account. Foundation-model ARNs use
all Regions because Bedrock cross-region inference profiles can route a request
to foundation models in several destination Regions.

## Trust model

Root sessions cannot assume IAM roles. Developers sign in through the
organization-level IAM Identity Center permission set, which grants only
`sts:AssumeRole` on this stack's Thoughtstage role. The role still requires STS
session names matching `thoughtstage-*`, and all Bedrock permissions remain on
that target role. This path uses short-lived credentials and creates no access
keys.

## Validate without provisioning

Run local syntax and security checks first:

```powershell
cfn-lint infra/aws/bedrock-access.yaml
cfn-guard validate `
  --data infra/aws/bedrock-access.yaml `
  --rules <approved-rules-file>
```

Then ask CloudFormation to validate the template without creating resources:

```powershell
aws cloudformation validate-template `
  --region us-east-2 `
  --template-body file://infra/aws/bedrock-access.yaml
```

## Preview and deploy

Create and inspect a change set before execution:

```powershell
aws cloudformation create-change-set `
  --region us-east-2 `
  --stack-name thoughtstage-bedrock-access `
  --change-set-name initial `
  --change-set-type CREATE `
  --capabilities CAPABILITY_NAMED_IAM `
  --template-body file://infra/aws/bedrock-access.yaml `
  --parameters `
    ParameterKey=IdentityCenterInstanceArn,ParameterValue=<instance-arn> `
    ParameterKey=IdentityCenterPrincipalId,ParameterValue=<user-id>

aws cloudformation describe-change-set `
  --region us-east-2 `
  --stack-name thoughtstage-bedrock-access `
  --change-set-name initial
```

Execute only after reviewing the role, trust policy, and managed permissions:

```powershell
aws cloudformation execute-change-set `
  --region us-east-2 `
  --stack-name thoughtstage-bedrock-access `
  --change-set-name initial
```

## Configure the local profile

After deployment, read the `RoleArn` stack output and configure an Identity
Center source profile plus the target role profile:

```powershell
aws configure set sso_start_url <access-portal-url> --profile thoughtstage-source
aws configure set sso_region us-east-2 --profile thoughtstage-source
aws configure set sso_account_id <account-id> --profile thoughtstage-source
aws configure set sso_role_name ThoughtstageBedrockEntry --profile thoughtstage-source
aws configure set region us-east-2 --profile thoughtstage-source

aws configure set role_arn <RoleArn> --profile thoughtstage-bedrock
aws configure set source_profile thoughtstage-source --profile thoughtstage-bedrock
aws configure set region us-east-2 --profile thoughtstage-bedrock
aws configure set role_session_name thoughtstage-local --profile thoughtstage-bedrock

aws sso login --profile thoughtstage-source
```

Use `--profile thoughtstage-bedrock` or set `AWS_PROFILE` for local Bedrock
development. No credential values belong in Thoughtstage configuration or run
bundles. Never use a root profile as the role source.
