targetScope = 'resourceGroup'

@description('Azure region for the Foundry resource and project.')
param location string

@description('Globally unique Foundry resource name.')
param accountName string

@description('Foundry project name.')
param projectName string

@description('Resource ownership and cost-attribution tags.')
param tags object

@description('Create the configured model deployments.')
param deployModels bool

@description('Model deployment definitions.')
param modelDeployments array

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  tags: tags
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    dynamicThrottlingEnabled: false
    publicNetworkAccess: 'Enabled'
    restrictOutboundNetworkAccess: false
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Thoughtstage'
    description: 'Reproducible multi-agent social experiments'
  }
}

resource deployments 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [for deployment in modelDeployments: if (deployModels) {
  parent: account
  name: deployment.deploymentName
  sku: {
    name: deployment.skuName
    capacity: deployment.capacity
  }
  properties: {
    model: {
      format: deployment.format
      name: deployment.modelName
      version: deployment.version
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
  dependsOn: [
    project
  ]
}]

output accountName string = account.name
output projectName string = project.name
output endpoint string = 'https://${account.name}.services.ai.azure.com'
output deploymentNames array = [for deployment in modelDeployments: deployment.deploymentName]
