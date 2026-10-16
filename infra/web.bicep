targetScope = 'resourceGroup'

param location string
param environmentName string
param resourceToken string
param entraClientId string
param allowedUserId string
@secure()
param entraClientSecret string
param foundryAccountName string
param foundryProjectName string = 'cena'
param modelDeploymentName string = 'gpt-4.1-mini'
param restaurantsAppName string

var tags = {
  'azd-env-name': environmentName
  project: 'poliamor-netcoreconf'
}
var foundryRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundry
  name: foundryProjectName
}
resource restaurants 'Microsoft.Web/sites@2024-04-01' existing = {
  name: restaurantsAppName
}
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-web-${resourceToken}'
  location: location
  tags: tags
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
    capacity: 1
  }
  properties: {
    reserved: true
  }
}
resource web 'Microsoft.Web/sites@2024-04-01' = {
  name: 'web-poliamor-${resourceToken}'
  location: location
  kind: 'app,linux'
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      healthCheckPath: '/health'
      appCommandLine: 'gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 8 --timeout 180 --graceful-timeout 120 demo_web.wsgi:app'
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'AZURE_TOKEN_CREDENTIALS', value: 'ManagedIdentityCredential' }
        { name: 'AZURE_AI_PROJECT_ENDPOINT', value: 'https://${foundry.name}.services.ai.azure.com/api/projects/${project.name}' }
        { name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME', value: modelDeploymentName }
        { name: 'RESTAURANTES_MCP_URL', value: 'https://${restaurants.properties.defaultHostName}/runtime/webhooks/mcp' }
        { name: 'RESTAURANTES_MCP_KEY', value: listKeys('${restaurants.id}/host/default', '2024-04-01').systemKeys.mcp_extension }
        { name: 'WEB_AUTH_CLIENT_SECRET', value: entraClientSecret }
        { name: 'WEB_ALLOWED_USER_ID', value: allowedUserId }
      ]
    }
  }
}
resource auth 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: web
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: [ '/health' ]
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: 'WEB_AUTH_CLIENT_SECRET'
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [ entraClientId ]
          defaultAuthorizationPolicy: {
            allowedPrincipals: {
              identities: [ allowedUserId ]
            }
          }
        }
      }
    }
    login: {
      tokenStore: { enabled: false }
    }
    httpSettings: {
      requireHttps: true
    }
  }
}
resource modelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, web.name, foundryRole)
  scope: project
  properties: {
    roleDefinitionId: foundryRole
    principalId: web.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output SERVICE_WEB_NAME string = web.name
output SERVICE_WEB_URI string = 'https://${web.properties.defaultHostName}'
