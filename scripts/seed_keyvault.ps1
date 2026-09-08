# One-time: create the Marquee Key Vault and seed app secrets from .env.
# Terraform reads these at plan/apply time; GitHub never stores a real credential.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$vault = 'marquee-kv-frank'

az keyvault create -n $vault -g marquee-rg -l eastus2 --enable-rbac-authorization true -o none 2>$null
$vaultId = az keyvault show -n $vault -g marquee-rg --query id -o tsv
$me = az ad signed-in-user show --query id -o tsv
az role assignment create --assignee $me --role 'Key Vault Administrator' --scope $vaultId -o none 2>$null

# Secret names mirror the terraform data sources.
$map = @{ 'SEATGEEK_CLIENT_ID'='seatgeek-client-id'; 'SEATGEEK_CLIENT_SECRET'='seatgeek-client-secret'
          'AZURE_MAPS_KEY'='azure-maps-key'; 'LASTFM_API_KEY'='lastfm-api-key'
          'TAILSCALE_AUTHKEY'='tailscale-auth-key' }
$seeded = 0
foreach ($line in Get-Content (Join-Path $root '.env')) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $name, $value = ($line -split '=', 2)
    if ($map.ContainsKey($name.Trim())) {
        $clean = $value.Trim() -replace '^["'']|["'']$', ''
        if ($clean) {
            az keyvault secret set --vault-name $vault --name $map[$name.Trim()] --value $clean -o none
            $seeded++
        }
    }
}
Write-Host "Seeded $seeded secrets into $vault."
