targetScope = 'resourceGroup'

param location string
param tags object
param resourceToken string
param modelCapacity int

var services = [
  'restaurantes'
  'orquestador'
  'presupuesto'
]
var agentServices = [
  1
  2
]
var modelName = 'gpt-4.1-mini'
var projectName = 'cena'
var projectUrl = 'https://${foundry.name}.services.ai.azure.com/api/projects/${projectName}'
var blobOwnerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')
var monitoringPublisherRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
// Previously named Azure AI User; the role ID remains unchanged.
var foundryUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stpol${resourceToken}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource deploymentContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for service in services: {
  parent: blobService
  name: 'deployment-${service}'
  properties: {
    publicAccess: 'None'
  }
}]

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-poliamor-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-poliamor-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: true
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'ai-poliamor-${resourceToken}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: 'ai-poliamor-${resourceToken}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Cena de ponentes'
    description: 'Demos MCP, agents as tools y A2A de NetCoreConf.'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: modelName
  dependsOn: [
    project
  ]
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: '2025-04-14'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

@batchSize(1)
resource plans 'Microsoft.Web/serverfarms@2024-04-01' = [for service in services: {
  name: 'plan-${service}-${resourceToken}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}]

resource apps 'Microsoft.Web/sites@2024-04-01' = [for (service, i) in services: {
  name: 'func-${service}-${resourceToken}'
  location: location
  tags: union(tags, {
    'azd-service-name': service
  })
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plans[i].id
    httpsOnly: true
    functionAppConfig: {
      runtime: {
        name: 'python'
        version: '3.12'
      }
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentContainers[i].name}'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        instanceMemoryMB: 2048
        maximumInstanceCount: service == 'presupuesto' ? 1 : 10
        triggers: {
          http: {
            perInstanceConcurrency: 1
          }
        }
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        {
          name: 'FUNCTIONS_WORKER_PROCESS_COUNT'
          value: '1'
        }
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storage.name
        }
        {
          name: 'AzureWebJobsStorage__credential'
          value: 'managedidentity'
        }
        {
          name: 'AzureFunctionsWebHost__hostid'
          value: '${service}-${resourceToken}'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: insights.properties.ConnectionString
        }
        {
          name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING'
          value: 'Authorization=AAD'
        }
        {
          name: 'AZURE_AI_PROJECT_ENDPOINT'
          value: projectUrl
        }
        {
          name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME'
          value: model.name
        }
      ]
    }
  }
}]

resource storageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (service, i) in services: {
  name: guid(storage.id, apps[i].name, blobOwnerRole)
  scope: storage
  properties: {
    roleDefinitionId: blobOwnerRole
    principalId: apps[i].identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource telemetryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (service, i) in services: {
  name: guid(insights.id, apps[i].name, monitoringPublisherRole)
  scope: insights
  properties: {
    roleDefinitionId: monitoringPublisherRole
    principalId: apps[i].identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource modelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in agentServices: {
  name: guid(project.id, apps[i].name, foundryUserRole)
  scope: project
  properties: {
    roleDefinitionId: foundryUserRole
    principalId: apps[i].identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

output functionNames array = [for (service, i) in services: apps[i].name]
output functionUrls array = [for (service, i) in services: 'https://${apps[i].properties.defaultHostName}']
output foundryAccountName string = foundry.name
output foundryProjectName string = project.name
output projectEndpoint string = projectUrl
output modelDeploymentName string = model.name
output applicationInsightsName string = insights.name
