// Container App Environment and surveillance dashboard
@description('Azure region for deployment')
param location string

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Project name prefix')
param projectName string

@description('Resource tags')
param tags object

@description('Log Analytics workspace ID')
param logAnalyticsWorkspaceId string

@description('Log Analytics shared key')
@secure()
param logAnalyticsSharedKey string

@description('Key Vault name for secret references')
param keyVaultName string

@description('ACR login server (e.g. myacr.azurecr.io)')
param acrLoginServer string

@description('Fabric Eventhouse KQL URI')
param kqlUri string = ''

var envName = '${projectName}-cae-${environmentName}'
var appName = '${projectName}-agent-${environmentName}'

resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspaceId
        sharedKey: logAnalyticsSharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: 'surveillance-dashboard'
          image: '${acrLoginServer}/market-surveillance:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'ENVIRONMENT'
              value: environmentName
            }
            {
              name: 'KQL_URI'
              value: kqlUri
            }
            {
              name: 'KQL_DB'
              value: 'surveillance'
            }
            {
              name: 'KEY_VAULT_NAME'
              value: keyVaultName
            }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/healthz'
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8080
              }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/ready'
                port: 8080
              }
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

@description('Container App Environment name')
output environmentName string = containerAppEnv.name

@description('Container App Environment ID')
output environmentId string = containerAppEnv.id

@description('Container App name')
output appName string = containerApp.name

@description('Container App FQDN')
output appFqdn string = containerApp.properties.configuration.ingress.fqdn

@description('Container App principal ID')
output appPrincipalId string = containerApp.identity.principalId
