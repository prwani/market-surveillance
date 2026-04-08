// Streaming agent worker — continuously processes events from Fabric Eventhouse
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

@description('Fabric Eventhouse KQL URI')
param kqlUri string

@description('KQL database name')
param kqlDb string = 'surveillance'

@description('Poll interval in seconds')
param pollInterval string = '10'

var appName = '${projectName}-worker-${environmentName}'

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
      // No ingress — worker is not a web server
    }
    template: {
      containers: [
        {
          name: 'surveillance-worker'
          image: '${acrLoginServer}/market-surveillance-worker:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'KQL_URI'
              value: kqlUri
            }
            {
              name: 'KQL_DB'
              value: kqlDb
            }
            {
              name: 'POLL_INTERVAL'
              value: pollInterval
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
