targetScope = 'subscription'

@minLength(1)
@maxLength(40)
param environmentName string

@description('Region checked for Flex Consumption and model availability before deployment.')
@metadata({
  azd: {
    type: 'location'
  }
})
param location string

@description('Capacity units of the pay-per-token GlobalStandard deployment; not reserved throughput.')
@minValue(1)
param modelCapacity int = 10

var tags = {
  'azd-env-name': environmentName
  project: 'poliamor-netcoreconf'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources './resources.bicep' = {
  name: 'poliamor-resources'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: uniqueString(subscription().subscriptionId, environmentName, location)
    modelCapacity: modelCapacity
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_AI_ACCOUNT_NAME string = resources.outputs.foundryAccountName
output AZURE_AI_PROJECT_NAME string = resources.outputs.foundryProjectName
output AZURE_AI_PROJECT_ENDPOINT string = resources.outputs.projectEndpoint
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = resources.outputs.modelDeploymentName
output APPLICATIONINSIGHTS_NAME string = resources.outputs.applicationInsightsName
output SERVICE_RESTAURANTES_NAME string = resources.outputs.functionNames[0]
output SERVICE_RESTAURANTES_URI string = resources.outputs.functionUrls[0]
output SERVICE_ORQUESTADOR_NAME string = resources.outputs.functionNames[1]
output SERVICE_ORQUESTADOR_URI string = resources.outputs.functionUrls[1]
output SERVICE_PRESUPUESTO_NAME string = resources.outputs.functionNames[2]
output SERVICE_PRESUPUESTO_URI string = resources.outputs.functionUrls[2]
