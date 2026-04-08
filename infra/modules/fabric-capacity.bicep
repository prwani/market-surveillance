// Microsoft Fabric capacity for Real-Time Intelligence and FabricIQ
@description('Azure region for deployment')
param location string

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Project name prefix')
param projectName string

@description('Resource tags')
param tags object

@description('Fabric capacity SKU (F2, F4, F8, F16, F32, F64)')
@allowed(['F2', 'F4', 'F8', 'F16', 'F32', 'F64'])
param skuName string = 'F8'

@description('Fabric capacity admin UPN (e.g. admin@contoso.com)')
param adminUpn string

var capacityName = '${replace(projectName, '-', '')}fabric${environmentName}'

resource fabricCapacity 'Microsoft.Fabric/capacities@2023-11-01' = {
  name: capacityName
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: 'Fabric'
  }
  properties: {
    administration: {
      members: [
        adminUpn
      ]
    }
  }
}

@description('Fabric capacity name')
output capacityName string = fabricCapacity.name

@description('Fabric capacity ID')
output capacityId string = fabricCapacity.id

@description('Fabric capacity SKU')
output capacitySku string = fabricCapacity.sku.name

@description('Fabric capacity state')
output capacityState string = fabricCapacity.properties.state
