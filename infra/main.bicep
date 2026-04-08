// Main Bicep template for Market Surveillance System
// Deploys Event Hubs, Azure Data Explorer, Key Vault, Container Apps, Storage
targetScope = 'resourceGroup'

@description('Azure region for all resources')
param location string = 'southeastasia'

@description('Environment name (dev, staging, prod)')
@allowed(['dev', 'staging', 'prod'])
param environmentName string

@description('Project name used as prefix for all resources')
@minLength(3)
@maxLength(15)
param projectName string

@description('Fabric capacity SKU (F2, F4, F8, F16, F32, F64)')
@allowed(['F2', 'F4', 'F8', 'F16', 'F32', 'F64'])
param fabricSku string = 'F8'

@description('Fabric capacity admin UPN')
param fabricAdminUpn string

var tags = {
  project: projectName
  environment: environmentName
  managedBy: 'bicep'
  system: 'market-surveillance'
}

// ──────────────────────────────────────────────
// Log Analytics Workspace — central monitoring
// ──────────────────────────────────────────────
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${projectName}-law-${environmentName}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ──────────────────────────────────────────────
// Microsoft Fabric Capacity — RTI + FabricIQ
// ──────────────────────────────────────────────
module fabricCapacity 'modules/fabric-capacity.bicep' = {
  name: 'fabricCapacityDeploy'
  params: {
    location: location
    environmentName: environmentName
    projectName: projectName
    tags: tags
    skuName: fabricSku
    adminUpn: fabricAdminUpn
  }
}

// ──────────────────────────────────────────────
// Event Hubs — trade and order book streaming
// ──────────────────────────────────────────────
module eventHubs 'modules/event-hubs.bicep' = {
  name: 'eventHubsDeploy'
  params: {
    location: location
    environmentName: environmentName
    projectName: projectName
    tags: tags
  }
}

// ──────────────────────────────────────────────
// Azure Data Explorer — KQL time-series queries
// ──────────────────────────────────────────────
module dataExplorer 'modules/data-explorer.bicep' = {
  name: 'dataExplorerDeploy'
  params: {
    location: location
    environmentName: environmentName
    projectName: projectName
    tags: tags
  }
}

// ──────────────────────────────────────────────
// Key Vault — secrets and connection strings
// ──────────────────────────────────────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${projectName}-kv-${environmentName}'
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enabledForTemplateDeployment: true
  }
}

// ──────────────────────────────────────────────
// Storage Account — data output and checkpoints
// ──────────────────────────────────────────────
var storageNameClean = replace('${projectName}st${environmentName}', '-', '')
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageNameClean
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource outputContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobServices
  name: 'surveillance-output'
  properties: {
    publicAccess: 'None'
  }
}

resource checkpointsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobServices
  name: 'eventhub-checkpoints'
  properties: {
    publicAccess: 'None'
  }
}

// ──────────────────────────────────────────────
// Container App — surveillance agent runtime
// ──────────────────────────────────────────────
module containerApp 'modules/container-app.bicep' = {
  name: 'containerAppDeploy'
  params: {
    location: location
    environmentName: environmentName
    projectName: projectName
    tags: tags
    logAnalyticsWorkspaceId: logAnalytics.properties.customerId
    logAnalyticsSharedKey: logAnalytics.listKeys().primarySharedKey
    keyVaultName: keyVault.name
  }
}

// Grant Container App's managed identity "Key Vault Secrets User" on the vault
resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, containerApp.name, '4633458b-17de-408a-b874-0445c86b69e6')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: containerApp.outputs.appPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ──────────────────────────────────────────────
// Outputs
// ──────────────────────────────────────────────
@description('Fabric capacity name')
output fabricCapacityName string = fabricCapacity.outputs.capacityName

@description('Fabric capacity ID')
output fabricCapacityId string = fabricCapacity.outputs.capacityId

@description('Fabric capacity SKU')
output fabricCapacitySku string = fabricCapacity.outputs.capacitySku

@description('Event Hubs namespace name')
output eventHubNamespace string = eventHubs.outputs.namespaceName

@description('Azure Data Explorer cluster URI')
output adxClusterUri string = dataExplorer.outputs.clusterUri

@description('Azure Data Explorer database name')
output adxDatabaseName string = dataExplorer.outputs.databaseName

@description('Key Vault name')
output keyVaultName string = keyVault.name

@description('Container App Environment name')
output containerAppEnvironment string = containerApp.outputs.environmentName

@description('Container App name')
output containerAppName string = containerApp.outputs.appName

@description('Storage Account name')
output storageAccountName string = storageAccount.name

@description('Log Analytics Workspace name')
output logAnalyticsWorkspace string = logAnalytics.name
