targetScope = 'subscription'

metadata name = 'Thoughtstage research infrastructure'
metadata description = 'A cost-isolated Microsoft Foundry resource, project, model set, and optional monthly budget.'

@description('Azure region for the resource group and Foundry resource.')
param location string = 'westus'

@description('Dedicated resource group used to isolate Thoughtstage research costs.')
param resourceGroupName string = 'rg-thoughtstage-research'

@description('Globally unique Foundry resource name.')
param foundryAccountName string = 'thoughtstage-models-${uniqueString(subscription().subscriptionId)}'

@description('Foundry project name.')
param projectName string = 'thoughtstage'

@description('Create the configured model deployments. Disable for base-infrastructure preflight when quota is unavailable.')
param deployModels bool = true

@description('Additional tags applied alongside the required Thoughtstage ownership tags.')
param additionalTags object = {}

@description('Create a subscription budget filtered to the Thoughtstage resource group.')
param enableBudget bool = false

@minValue(1)
@description('Monthly budget amount in the subscription billing currency.')
param monthlyBudgetAmount int = 100

@description('Email recipients for budget notifications. Required when enableBudget is true.')
param budgetContactEmails array = []

@description('First day of the budget period in UTC. Override when deploying a saved parameter file later.')
param budgetStartDate string = utcNow('yyyy-MM-01T00:00:00Z')

@description('Pinned model deployments. Capacity controls throughput quota for Standard SKUs, not prepaid capacity.')
param modelDeployments array = [
  {
    deploymentName: 'gpt-4o'
    format: 'OpenAI'
    modelName: 'gpt-4o'
    version: '2024-11-20'
    skuName: 'GlobalStandard'
    capacity: 100
  }
  {
    deploymentName: 'Llama-3.3-70B-Instruct'
    format: 'Meta'
    modelName: 'Llama-3.3-70B-Instruct'
    version: '9'
    skuName: 'GlobalStandard'
    capacity: 20
  }
  {
    deploymentName: 'grok-4-1-fast-reasoning'
    format: 'xAI'
    modelName: 'grok-4-1-fast-reasoning'
    version: '1'
    skuName: 'GlobalStandard'
    capacity: 50
  }
  {
    deploymentName: 'DeepSeek-V3.2'
    format: 'DeepSeek'
    modelName: 'DeepSeek-V3.2'
    version: '1'
    skuName: 'GlobalStandard'
    capacity: 20
  }
]


var requiredTags = {
  project: 'thoughtstage'
  environment: 'research'
  owner: 'jonathan'
  'managed-by': 'bicep'
}
var tags = union(requiredTags, additionalTags)

resource researchResourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module foundry './modules/foundry.bicep' = {
  name: 'thoughtstage-foundry'
  scope: researchResourceGroup
  params: {
    location: location
    accountName: foundryAccountName
    projectName: projectName
    deployModels: deployModels
    tags: tags
    modelDeployments: modelDeployments
  }
}

module budget './modules/budget.bicep' = if (enableBudget) {
  name: 'thoughtstage-budget'
  params: {
    budgetName: '${resourceGroupName}-monthly'
    resourceGroupName: resourceGroupName
    amount: monthlyBudgetAmount
    contactEmails: budgetContactEmails
    startDate: budgetStartDate
  }
  dependsOn: [
    researchResourceGroup
  ]
}

output resourceGroupName string = researchResourceGroup.name
output foundryAccountName string = foundry.outputs.accountName
output foundryProjectName string = foundry.outputs.projectName
output foundryEndpoint string = foundry.outputs.endpoint
output deploymentNames array = foundry.outputs.deploymentNames
