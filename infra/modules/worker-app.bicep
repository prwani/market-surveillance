// Streaming agent worker — continuously processes events from Fabric Eventhouse
// Can be deployed multiple times with different exchangeFilter values for
// per-exchange partitioning.
@description('Azure region for deployment')
param location string

@description('Environment name')
param environmentName string

@description('Project name prefix')
param projectName string

@description('Resource tags')
param tags object

@description('Container App Environment ID')
param containerAppEnvId string

@description('ACR login server')
param acrLoginServer string

@description('ACR admin username')
@secure()
param acrUsername string

@description('ACR admin password')
@secure()
param acrPassword string

@description('Worker container image (set by azd deploy)')
param workerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('KQL database name')
param kqlDb string = 'surveillance'

@description('Poll interval in seconds')
param pollInterval string = '10'

@description('Exchange partition filter (SGX, HKEX, NSE, cross-market, or empty for all)')
param exchangeFilter string = ''

@description('Minutes of history to back-fill on cold start')
param warmupMinutes string = '60'

var suffix = exchangeFilter == 'cross-market' ? 'crossmkt' : exchangeFilter != '' ? toLower(exchangeFilter) : 'all'
var appName = '${projectName}-wk-${suffix}-${environmentName}'

resource workerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnvId
    configuration: {
      registries: [
        {
          server: acrLoginServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'surveillance-worker'
          image: workerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'KQL_DB'
              value: kqlDb
            }
            {
              name: 'POLL_INTERVAL'
              value: pollInterval
            }
            {
              name: 'EXCHANGE_FILTER'
              value: exchangeFilter
            }
            {
              name: 'WARMUP_MINUTES'
              value: warmupMinutes
            }
            {
              name: 'ENVIRONMENT'
              value: environmentName
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

@description('Worker Container App name')
output appName string = workerApp.name

@description('Worker principal ID')
output appPrincipalId string = workerApp.identity.principalId
