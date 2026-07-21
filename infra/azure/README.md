# Thoughtstage Azure research infrastructure

This subscription-scope Bicep scaffold creates one cost-isolated research resource
group containing a Microsoft Foundry resource, a project, and four pinned model
deployments. An optional subscription budget filters costs to that resource group
and sends notifications at 50%, 80%, and 100% actual spend plus 100% forecasted
spend.

Nothing in this directory provisions Azure resources until an operator explicitly
runs an Azure deployment command.

## Why one resource group

Use one stable `rg-thoughtstage-research` resource group for the project rather
than creating a group for every experiment. The resource group and required tags
make Azure Cost Management filtering predictable; Thoughtstage's private model
usage ledger supplies the per-run and per-model attribution that static Azure
resources cannot encode reliably.

The model deployments use `GlobalStandard`, Azure's common pay-as-you-go starting
point. Their `capacity` values are throughput quota settings, not provisioned
throughput reservations. The versions are explicit, and upgrades occur only when
Azure expires the pinned version.

## Included models

| Deployment | Format | Version | Global Standard capacity |
| --- | --- | ---: | ---: |
| `gpt-4o` | OpenAI | `2024-11-20` | 100 |
| `Llama-3.3-70B-Instruct` | Meta | `9` | 20 |
| `grok-4-1-fast-reasoning` | xAI | `1` | 50 |
| `DeepSeek-V3.2` | DeepSeek | `1` | 20 |

These values mirror the deployments already proven by the first Thoughtstage
experiments. Model and SKU availability remains subscription- and region-specific.
Partner models can also require Azure Marketplace permissions or acceptance.

## Validate without provisioning

Compile the templates locally:

```powershell
az bicep build --file infra/azure/main.bicep --outfile "$env:TEMP/thoughtstage-main.json"
az bicep build-params --file infra/azure/main.example.bicepparam --outfile "$env:TEMP/thoughtstage-main.parameters.json"
```

An Azure preflight validation is also non-provisioning. Disable the budget so no
real contact address is needed:

```powershell
az deployment sub validate `
  --name thoughtstage-preflight `
  --location westus `
  --template-file infra/azure/main.bicep `
  --parameters enableBudget=false deployModels=false
```

Before any future deployment, copy `main.example.bicepparam`, replace the budget
email, inspect the change with `az deployment sub what-if`, and confirm the four
models and their requested capacities are available to the subscription in the
selected region. If existing deployments consume the available quota, validate the
base scaffold with `deployModels=false`, then free or raise quota before enabling the
model set. Only then use `az deployment sub create`; that command creates
spend-capable resources.

## Security defaults

Local API-key authentication is disabled. Thoughtstage should authenticate with
Microsoft Entra ID through `DefaultAzureCredential`. Public network access remains
enabled for the initial portable research setup; a later hardened profile can add
private endpoints and network isolation without changing experiment manifests.

References:

- [Create a Foundry resource with Bicep](https://learn.microsoft.com/azure/foundry/how-to/create-resource-template)
- [Deploy Foundry models with Azure CLI and Bicep](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/create-model-deployments)
- [Foundry deployment types](https://learn.microsoft.com/azure/ai-foundry/foundry-models/concepts/deployment-types)
- [Azure Consumption budgets Bicep reference](https://learn.microsoft.com/azure/templates/microsoft.consumption/budgets)
