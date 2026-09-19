// PayNexus V2/V2.1 — core hosting resources as Infrastructure-as-Code.
//
// Scope, deliberately narrow: the App Service Plan, the backend Web App
// (container-based), and the Static Web App frontend -- the pieces that
// were provisioned by hand via one-off `az` CLI commands during the
// original build (see the PayNexus Atlas doc / paynexus-v2-pending-items
// memory for that history) and are cheap and safe to describe declaratively.
//
// Deliberately OUT of scope, not because it's harder but because it would
// be actively risky to manage this way right now:
//   - `paynexus-db-ramya` (Postgres Flexible Server) — SHARED with V1's
//     live production database on the same server. Describing it here
//     would risk a `what-if`/deploy accidentally treating manual changes
//     made outside this file (backups, firewall rules added ad hoc, V1's
//     own database) as drift to "correct" -- too easy to get a destructive
//     surprise on a server holding real user data for a different app.
//   - The Azure AI Foundry project + its capability-host stack (Cosmos DB,
//     AI Search, Storage) -- provisioned via a hand-written ARM template
//     during the original migration for reasons specific to that one-time
//     setup (see paynexus-v2.1-foundry-migration memory); not revisited
//     here since it isn't the everyday redeploy path this file targets.
//
// This file is deliberately never applied automatically by CI -- deploying
// it is a manual, explicit `az deployment group create` a human runs when
// they mean to, not something a push triggers. Validate without deploying:
//   az bicep build --file infra/v2-core.bicep
// Preview what a real deploy would change, without changing anything:
//   az deployment group what-if --resource-group paynexus-rg \
//     --template-file infra/v2-core.bicep --parameters dockerImageTag=v2-latest

@description('Azure region for all resources in this file.')
param location string = resourceGroup().location

@description('App Service Plan name. Existing plan is F1 (free tier) -- see the 2026-09-13 cost decision in paynexus-v2-pending-items memory for why.')
param appServicePlanName string = 'paynexus-plan'

@description('Backend Web App name.')
param webAppName string = 'paynexus-api-v2'

@description('Static Web App name (frontend).')
param staticWebAppName string = 'paynexus-web-v2'

@description('Docker Hub repo the backend container image lives in.')
param dockerHubRepo string = 'ramya192/paynexus-backend'

@description('Image tag to deploy -- matches deploy-v2.yml\'s build output.')
param dockerImageTag string = 'v2-latest'

@description('Full Postgres connection string. Passed at deploy time (az deployment group create --parameters databaseUrl=...), never committed to this file or to git.')
@secure()
param databaseUrl string

@description('Azure AI Foundry project endpoint the backend calls.')
param foundryProjectEndpoint string

@description('CORS-allowed origin for the deployed frontend.')
param corsOrigin string = 'https://ambitious-pebble-083cdaf10.7.azurestaticapps.net'

@description('Application Insights resource name. Workspace-based (points at a Log Analytics workspace) rather than classic -- classic App Insights is retired for new resources. Both this and the workspace below are free at this app\'s traffic (Application Insights\' free 5GB/month ingestion grant), same "cheap and safe to describe declaratively" reasoning as the resources above.')
param appInsightsName string = 'paynexus-insights-v2'

@description('Log Analytics workspace backing Application Insights above.')
param logAnalyticsWorkspaceName string = 'paynexus-logs-v2'

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' existing = {
  name: appServicePlanName
}

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    // 30 days is the free-tier retention ceiling for the first 5GB/month --
    // no reason to pay for longer retention on a portfolio project's traffic.
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
  }
}

resource backendApp 'Microsoft.Web/sites@2023-12-01' = {
  name: webAppName
  location: location
  properties: {
    serverFarmId: appServicePlan.id
    siteConfig: {
      linuxFxVersion: 'DOCKER|index.docker.io/${dockerHubRepo}:${dockerImageTag}'
      appSettings: [
        {
          name: 'DATABASE_URL'
          value: databaseUrl
        }
        {
          name: 'FOUNDRY_PROJECT_ENDPOINT'
          value: foundryProjectEndpoint
        }
        {
          name: 'CORS_ORIGINS'
          value: corsOrigin
        }
        {
          name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE'
          value: 'false'
        }
        {
          // Sole wiring point -- api/main.py's configure_azure_monitor() call
          // is a no-op everywhere this app setting isn't present (local dev,
          // CI, tests), see backend/config.py. Setting this here is what
          // turns APM on for the deployed instance only.
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
      ]
    }
    httpsOnly: true
  }
}

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    // Deploys go through deploy-v2.yml's token-based `Azure/static-web-apps-deploy`
    // action, not this resource's own repositoryUrl/branch integration --
    // see the PayNexus Atlas doc's note on why the "branch" field on this
    // resource is informational, not the real deploy trigger.
    buildProperties: {
      skipGithubActionWorkflowGeneration: true
    }
  }
}

output backendUrl string = 'https://${backendApp.properties.defaultHostName}'
output frontendUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output appInsightsName string = appInsights.name
