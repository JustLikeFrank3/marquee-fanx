# Build the Marquee image in ACR and roll out via Terraform. Rerun for every redeploy.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

# Feed secrets from .env to Terraform without printing them.
$secretMap = @{ 'SEATGEEK_CLIENT_ID'='seatgeek_client_id'; 'SEATGEEK_CLIENT_SECRET'='seatgeek_client_secret'
                'AZURE_MAPS_KEY'='azure_maps_key'; 'LASTFM_API_KEY'='lastfm_api_key' }
foreach ($line in Get-Content (Join-Path $root '.env')) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $name, $value = ($line -split '=', 2)
    if ($secretMap.ContainsKey($name.Trim())) {
        # dotenv strips surrounding quotes locally; do the same before seeding cloud secrets.
        $clean = $value.Trim() -replace '^["'']|["'']$', ''
        Set-Item -Path ("env:TF_VAR_" + $secretMap[$name.Trim()]) -Value $clean
    }
}
foreach ($required in $secretMap.Values) {
    if (-not (Get-Item "env:TF_VAR_$required" -ErrorAction SilentlyContinue)) {
        throw "Missing .env entry for $required"
    }
}

$tf = Join-Path $root 'infra\terraform'

# One-time idempotent bootstrap: resource providers and Entra-authenticated remote state.
foreach ($rp in 'Microsoft.App','Microsoft.OperationalInsights','Microsoft.ContainerRegistry','Microsoft.ManagedIdentity') {
    az provider register --namespace $rp --wait
}
az storage account create -n marqueetfstate -g marquee-rg -l eastus2 --sku Standard_LRS --kind StorageV2 `
    --allow-blob-public-access false --allow-shared-key-access false --min-tls-version TLS1_2 -o none
$me = az ad signed-in-user show --query id -o tsv
$stateId = az storage account show -n marqueetfstate -g marquee-rg --query id -o tsv
az role assignment create --assignee $me --role 'Storage Blob Data Contributor' --scope $stateId -o none 2>$null
# Role propagation can lag; retry container creation briefly.
for ($i = 0; $i -lt 6; $i++) {
    az storage container create --account-name marqueetfstate -n tfstate --auth-mode login -o none 2>$null
    if (-not $LASTEXITCODE) { break }
    Start-Sleep -Seconds 10
}
if ($LASTEXITCODE) { throw 'Could not create the terraform state container.' }

Push-Location $tf
try {
    terraform init -input=false -reconfigure | Out-Null
    # The registry must exist before the image can be built into it.
    terraform apply -input=false -auto-approve "-target=azurerm_container_registry.main" "-var=image_tag=bootstrap"
    if ($LASTEXITCODE) { throw 'Terraform registry apply failed.' }
    $acr = terraform output -raw acr_login_server 2>$null
    if (-not $acr) { $acr = 'marqueefrankacr.azurecr.io' }

    $tag = Get-Date -Format 'yyyyMMdd-HHmmss'
    # Stage only the build inputs; some local cache dirs have broken ACLs that fail the tar upload.
    $stage = Join-Path $env:TEMP "marquee-build-$tag"
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        Copy-Item (Join-Path $root 'Dockerfile'), (Join-Path $root 'requirements.lock.txt'), (Join-Path $root 'requirements.txt'), (Join-Path $root '.dockerignore') $stage
        robocopy (Join-Path $root 'server') (Join-Path $stage 'server') /E /XD __pycache__ .pytest_cache | Out-Null
        robocopy (Join-Path $root 'web') (Join-Path $stage 'web') /E /XD node_modules dist | Out-Null
        az acr build --registry ($acr -split '\.')[0] --image "marquee:$tag" $stage
        if ($LASTEXITCODE) { throw 'ACR image build failed.' }
    }
    finally { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue }

    terraform apply -input=false -auto-approve "-var=image_tag=$tag"
    if ($LASTEXITCODE) { throw 'Terraform apply failed.' }
    # Terraform ignores image changes after creation; roll the tag out directly.
    az containerapp update -n marquee -g marquee-rg --image "$acr/marquee:$tag" -o none
    if ($LASTEXITCODE) { throw 'Image rollout failed.' }
    Write-Host "Deployed marquee:$tag"
    Write-Host "App URL: $(terraform output -raw app_url)"
}
finally { Pop-Location }
