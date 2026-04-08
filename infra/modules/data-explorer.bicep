// Azure Data Explorer (Kusto) cluster and surveillance database
@description('Azure region for deployment')
param location string

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Project name prefix')
param projectName string

@description('Resource tags')
param tags object

var clusterName = '${replace(projectName, '-', '')}adx${environmentName}'
var databaseName = 'surveillance'

resource adxCluster 'Microsoft.Kusto/clusters@2023-08-15' = {
  name: clusterName
  location: location
  tags: tags
  sku: {
    name: 'Dev(No SLA)_Standard_D11_v2'
    tier: 'Basic'
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    enableStreamingIngest: true
    enableAutoStop: true
  }
}

resource database 'Microsoft.Kusto/clusters/databases@2023-08-15' = {
  parent: adxCluster
  name: databaseName
  location: location
  kind: 'ReadWrite'
  properties: {
    hotCachePeriod: 'P7D'
    softDeletePeriod: 'P365D'
  }
}

@description('ADX cluster name')
output clusterName string = adxCluster.name

@description('ADX cluster ID')
output clusterId string = adxCluster.id

@description('ADX cluster URI')
output clusterUri string = adxCluster.properties.uri

@description('ADX data ingestion URI')
output dataIngestionUri string = adxCluster.properties.dataIngestionUri

@description('Database name')
output databaseName string = database.name
