// Event Hubs Namespace with hubs for trade and order book streaming
@description('Azure region for deployment')
param location string

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Project name prefix')
param projectName string

@description('Resource tags')
param tags object

var namespaceName = '${projectName}-ehns-${environmentName}'

resource eventHubNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  }
  properties: {
    isAutoInflateEnabled: true
    maximumThroughputUnits: 4
  }
}

resource tradesHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubNamespace
  name: 'trades-stream'
  properties: {
    messageRetentionInDays: 1
    partitionCount: 2
  }
}

resource orderbookHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubNamespace
  name: 'orderbook-stream'
  properties: {
    messageRetentionInDays: 1
    partitionCount: 2
  }
}

// Consumer groups for each surveillance agent
var agentConsumerGroups = [
  'pattern-detection'
  'anomaly-detection'
  'cross-market'
  'evidence-collection'
  'intervention'
]

resource tradesConsumerGroups 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = [
  for agent in agentConsumerGroups: {
    parent: tradesHub
    name: agent
    properties: {}
  }
]

resource orderbookConsumerGroups 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = [
  for agent in agentConsumerGroups: {
    parent: orderbookHub
    name: agent
    properties: {}
  }
]

// Authorization rule for sending and listening
resource sendListenRule 'Microsoft.EventHub/namespaces/authorizationRules@2024-01-01' = {
  parent: eventHubNamespace
  name: 'surveillance-app'
  properties: {
    rights: [
      'Send'
      'Listen'
    ]
  }
}

@description('Event Hubs namespace name')
output namespaceName string = eventHubNamespace.name

@description('Event Hubs namespace ID')
output namespaceId string = eventHubNamespace.id

@description('Trades hub name')
output tradesHubName string = tradesHub.name

@description('Order book hub name')
output orderbookHubName string = orderbookHub.name
