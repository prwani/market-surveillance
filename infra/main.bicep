// Main Bicep template for Market Surveillance System
// Deploys Fabric Capacity, Key Vault, Container Apps, Storage
// NOTE: KQL database lives in Fabric Eventhouse (created via Fabric REST API),
//       not a standalone Azure Data Explorer cluster.
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
// Container Registry — dashboard image
// ──────────────────────────────────────────────
var acrName = replace('${projectName}acr', '-', '')
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// ──────────────────────────────────────────────
// Container App — surveillance dashboard
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
    acrLoginServer: acr.properties.loginServer
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
// Streaming Workers — per-exchange partitioned
// ──────────────────────────────────────────────
var exchangeWorkers = ['SGX', 'HKEX', 'NSE', 'cross-market']

module workerApps 'modules/worker-app.bicep' = [for exchange in exchangeWorkers: {
  name: 'workerDeploy-${exchange}'
  params: {
    location: location
    environmentName: environmentName
    projectName: projectName
    tags: tags
    containerAppEnvId: containerApp.outputs.environmentId
    acrLoginServer: acr.properties.loginServer
    kqlUri: '' // Set post-deployment once Fabric workspace is created
    exchangeFilter: exchange
  }
}]

// ──────────────────────────────────────────────
// Outputs
// ──────────────────────────────────────────────
@description('Fabric capacity name')
output fabricCapacityName string = fabricCapacity.outputs.capacityName

@description('Fabric capacity ID')
output fabricCapacityId string = fabricCapacity.outputs.capacityId

@description('Fabric capacity SKU')
output fabricCapacitySku string = fabricCapacity.outputs.capacitySku

@description('Key Vault name')
output keyVaultName string = keyVault.name

@description('Container App Environment name')
output containerAppEnvironment string = containerApp.outputs.environmentName

@description('Container App name')
output containerAppName string = containerApp.outputs.appName

@description('Worker App names (per-exchange)')
output workerAppNames array = [for (exchange, i) in exchangeWorkers: workerApps[i].outputs.appName]

@description('Dashboard URL')
output dashboardUrl string = 'https://${containerApp.outputs.appFqdn}'

@description('Container Registry login server')
output acrLoginServer string = acr.properties.loginServer

@description('Storage Account name')
output storageAccountName string = storageAccount.name

@description('Log Analytics Workspace name')
output logAnalyticsWorkspace string = logAnalytics.name
