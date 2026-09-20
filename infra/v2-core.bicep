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
// Preview what a real deploy would change, without changing anything -- the
// four secure params have no default and must be supplied every time (pull
// databaseUrl/foundryProjectEndpoint from backend/.env; openaiApiKey/
// jwtSecretKey from the live app's own settings if not also in .env --
// `az webapp config appsettings list --name paynexus-api-v2 --resource-group
// paynexus-rg`, never echoed to a log):
//   az deployment group what-if --resource-group paynexus-rg \
//     --template-file infra/v2-core.bicep --parameters \
//     databaseUrl=... foundryProjectEndpoint=... openaiApiKey=... jwtSecretKey=...

@description('Azure region for all resources in this file.')
param location string = resourceGroup().location

@description('Region for Application Insights + its Log Analytics workspace specifically. Separate from `location` above because `Microsoft.OperationalInsights/workspaces` is not available in indiasouthcentral (the resource group\'s own region, where everything else already lives) -- discovered live, 2026-09-19, via a real failed deployment attempt (LocationNotAvailableForResourceType), not assumed. centralindia is the nearest region that supports it.')
param observabilityLocation string = 'centralindia'

@description('Region the existing Static Web App actually lives in -- `Microsoft.Web/staticSites` has never been available in indiasouthcentral at all (a much shorter region list than regular App Service), and this resource is confirmed live in Central US (`az staticwebapp show`), also discovered via a real failed deployment attempt, not assumed.')
param staticWebAppLocation string = 'centralus'

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

@description('OpenAI API key -- still used by extraction/categorization helpers outside the 7 Foundry-routed agents. Passed at deploy time, never committed.')
@secure()
param openaiApiKey string

@description('JWT signing secret. Passed at deploy time, never committed -- rotating this invalidates every existing session, so the deployed value must match what is already live unless a rotation is genuinely intended.')
@secure()
param jwtSecretKey string

// The remaining app settings below are non-secret and match the live app's
// current values exactly (verified via `az webapp config appsettings list`
// before this file's first real deploy, 2026-09-19) -- appSettings is a full
// REPLACE when deployed via ARM/Bicep, not a merge, so every setting the
// live app actually needs has to be listed here or it silently disappears
// on deploy. Five of the fifteen live settings above already have their own
// named params (databaseUrl, foundryProjectEndpoint, corsOrigin, plus the
// two secrets just above); these nine cover the rest.
@description('JWT signing algorithm.')
param jwtAlgorithm string = 'HS256'

@description('JWT expiry, in minutes.')
param jwtExpireMinutes string = '60'

@description('Enables Level 1/2 context compression (§6 of the README).')
param enableContextCompression string = 'True'

@description('Whether hybrid-tier agents fall back to a local Ollama SLM instead of a cloud model.')
param useLocalSlm string = 'False'

@description('Oryx build-on-deploy flag -- left matching the live app even though this container-based app does not actually use an Oryx build.')
param scmDoBuildDuringDeployment string = 'true'

@description('Python stdout/stderr buffering -- unbuffered so logs show up in App Service log streaming immediately.')
param pythonUnbuffered string = '1'

@description('Python module search path inside the container.')
param pythonPath string = '/home/site/wwwroot'

@description('Port the container listens on -- must match the Dockerfile/uvicorn bind port.')
param websitesPort string = '8000'

@description('Enables the Docker Hub webhook-triggered Continuous Deployment pull.')
param dockerEnableCi string = 'true'

@description('Application Insights resource name. Workspace-based (points at a Log Analytics workspace) rather than classic -- classic App Insights is retired for new resources. Both this and the workspace below are free at this app\'s traffic (Application Insights\' free 5GB/month ingestion grant), same "cheap and safe to describe declaratively" reasoning as the resources above.')
param appInsightsName string = 'paynexus-insights-v2'

@description('Log Analytics workspace backing Application Insights above.')
param logAnalyticsWorkspaceName string = 'paynexus-logs-v2'

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' existing = {
  name: appServicePlanName
}

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: observabilityLocation
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
  location: observabilityLocation
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
        {
          name: 'OPENAI_API_KEY'
          value: openaiApiKey
        }
        {
          name: 'JWT_SECRET_KEY'
          value: jwtSecretKey
        }
        {
          name: 'JWT_ALGORITHM'
          value: jwtAlgorithm
        }
        {
          name: 'JWT_EXPIRE_MINUTES'
          value: jwtExpireMinutes
        }
        {
          name: 'ENABLE_CONTEXT_COMPRESSION'
          value: enableContextCompression
        }
        {
          name: 'USE_LOCAL_SLM'
          value: useLocalSlm
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: scmDoBuildDuringDeployment
        }
        {
          name: 'PYTHONUNBUFFERED'
          value: pythonUnbuffered
        }
        {
          name: 'PYTHONPATH'
          value: pythonPath
        }
        {
          name: 'WEBSITES_PORT'
          value: websitesPort
        }
        {
          name: 'DOCKER_ENABLE_CI'
          value: dockerEnableCi
        }
      ]
    }
    httpsOnly: true
  }
}

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticWebAppName
  location: staticWebAppLocation
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    // Deploys go through deploy-v2.yml's token-based `Azure/static-web-apps-deploy`
    // action, not this resource's own repositoryUrl/branch integration --
    // see the PayNexus Atlas doc's note on why the "branch" field on this
    // resource is informational, not the real deploy trigger.
    //
    // Pinned explicitly to match the live resource (verified 2026-09-19,
    // before this file's first real deploy) rather than left unset.
    // `deploymentAuthPolicy` (what makes the existing
    // AZURE_STATIC_WEB_APPS_API_TOKEN_V2 GitHub secret valid) was tried here
    // too but Bicep rejects it -- BCP037, not a settable property on
    // StaticSite in this API version at all. That's actually reassuring:
    // if this template structurally can't touch it, it can't reset it
    // either, so `what-if` flagging it for removal earlier was noise, not a
    // real risk (matches this tool's own documented false-positive caveat).
    repositoryUrl: 'https://github.com/Ramya192/pay-nexus'
    branch: 'foundry-v2'
    provider: 'GitHub'
    buildProperties: {
      skipGithubActionWorkflowGeneration: true
    }
  }
}

output backendUrl string = 'https://${backendApp.properties.defaultHostName}'
output frontendUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output appInsightsName string = appInsights.name
