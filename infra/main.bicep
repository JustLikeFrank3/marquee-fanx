@description('Azure Container Registry or other image URL for the built Marquee container.')
param image string
@description('Globally distinct application name.')
param appName string = 'marquee'
param location string = resourceGroup().location
@secure()
param seatGeekClientId string
@secure()
param seatGeekClientSecret string = ''
@description('Container registry hostname, or empty for a public image.')
param registryServer string = ''
param registryUsername string = ''
@secure()
param registryPassword string = ''

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${appName}-environment'
  location: location
  properties: {}
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      secrets: concat([
        { name: 'seatgeek-id', value: seatGeekClientId }
      ], empty(seatGeekClientSecret) ? [] : [
        { name: 'seatgeek-secret', value: seatGeekClientSecret }
      ], empty(registryServer) ? [] : [
        { name: 'registry-password', value: registryPassword }
      ])
      registries: empty(registryServer) ? [] : [
        { server: registryServer, username: registryUsername, passwordSecretRef: 'registry-password' }
      ]
    }
    template: {
      containers: [
        {
          name: 'marquee'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat([
            { name: 'MARQUEE_DATA_MODE', value: 'live' }
            { name: 'SEATGEEK_CLIENT_ID', secretRef: 'seatgeek-id' }
            { name: 'ALLOWED_ORIGINS', value: 'https://${appName}.${environment.properties.defaultDomain}' }
          ], empty(seatGeekClientSecret) ? [] : [
            { name: 'SEATGEEK_CLIENT_SECRET', secretRef: 'seatgeek-secret' }
          ])
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
