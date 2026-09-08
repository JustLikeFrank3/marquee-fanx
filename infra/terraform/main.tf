terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
  backend "azurerm" {
    resource_group_name  = "marquee-rg"
    storage_account_name = "marqueetfstate"
    container_name       = "tfstate"
    key                  = "marquee.tfstate"
    use_azuread_auth     = true
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  # Providers are registered once in scripts/deploy.ps1; auto-registration hangs applies.
  resource_provider_registrations = "none"
}

data "azurerm_resource_group" "marquee" {
  name = var.resource_group_name
}

# Secrets live in Key Vault (seeded by scripts/seed_keyvault.ps1); Terraform only reads them.
data "azurerm_key_vault" "main" {
  name                = var.key_vault_name
  resource_group_name = var.resource_group_name
}

data "azurerm_key_vault_secret" "app" {
  for_each     = toset(["seatgeek-client-id", "seatgeek-client-secret", "azure-maps-key", "lastfm-api-key", "tailscale-auth-key"])
  name         = each.key
  key_vault_id = data.azurerm_key_vault.main.id
}

locals {
  kv                 = { for name, secret in data.azurerm_key_vault_secret.app : name => secret.value }
  tailscale_auth_key = local.kv["tailscale-auth-key"]
}

resource "azurerm_container_registry" "main" {
  name                = var.acr_name
  resource_group_name = data.azurerm_resource_group.marquee.name
  location            = data.azurerm_resource_group.marquee.location
  sku                 = "Basic"
  admin_enabled       = false
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "marquee-logs"
  resource_group_name = data.azurerm_resource_group.marquee.name
  location            = data.azurerm_resource_group.marquee.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_app_environment" "main" {
  name                       = "marquee-env"
  resource_group_name        = data.azurerm_resource_group.marquee.name
  location                   = data.azurerm_resource_group.marquee.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "marquee-app-identity"
  resource_group_name = data.azurerm_resource_group.marquee.name
  location            = data.azurerm_resource_group.marquee.location
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Lets the app call the existing Foundry project agent via managed identity.
resource "azurerm_role_assignment" "foundry_user" {
  scope                = "${data.azurerm_resource_group.marquee.id}/providers/Microsoft.CognitiveServices/accounts/${var.foundry_account_name}"
  role_definition_name = "Azure AI Developer"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Azure AI Developer lacks AIServices/* data actions, which the Foundry agents API requires.
resource "azurerm_role_assignment" "foundry_data" {
  scope                = "${data.azurerm_resource_group.marquee.id}/providers/Microsoft.CognitiveServices/accounts/${var.foundry_account_name}"
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_container_app" "main" {
  name                         = "marquee"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = data.azurerm_resource_group.marquee.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name  = "seatgeek-client-id"
    value = local.kv["seatgeek-client-id"]
  }
  secret {
    name  = "seatgeek-client-secret"
    value = local.kv["seatgeek-client-secret"]
  }
  secret {
    name  = "azure-maps-key"
    value = local.kv["azure-maps-key"]
  }
  secret {
    name  = "lastfm-api-key"
    value = local.kv["lastfm-api-key"]
  }
  dynamic "secret" {
    for_each = local.tailscale_auth_key == "" ? [] : [1]
    content {
      name  = "tailscale-auth-key"
      value = local.tailscale_auth_key
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # In-memory session evidence requires exactly one replica.
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "marquee"
      image  = "${azurerm_container_registry.main.login_server}/marquee:${var.image_tag}"
      cpu    = 0.25
      memory = "0.5Gi"
      env {
        name  = "MARQUEE_DATA_MODE"
        value = "live"
      }
      env {
        name  = "MARQUEE_AI_PROVIDER"
        value = local.tailscale_auth_key == "" ? "azure_foundry" : "local_first"
      }
      dynamic "env" {
        for_each = local.tailscale_auth_key == "" ? {} : {
          LOCAL_LLM_BASE_URL = var.local_llm_base_url
          LOCAL_LLM_MODEL    = var.local_llm_model
          LOCAL_LLM_PROXY    = "socks5://localhost:1055"
        }
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name  = "FOUNDRY_PROJECT_ENDPOINT"
        value = var.foundry_project_endpoint
      }
      env {
        name  = "FOUNDRY_AGENT_NAME"
        value = var.foundry_agent_name
      }
      env {
        name  = "FOUNDRY_AUTH"
        value = "managed_identity"
      }
      env {
        name  = "TRUST_FORWARDED_FOR"
        value = "1"
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app.client_id
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = "https://marquee.${azurerm_container_app_environment.main.default_domain}"
      }
      env {
        name        = "SEATGEEK_CLIENT_ID"
        secret_name = "seatgeek-client-id"
      }
      env {
        name        = "SEATGEEK_CLIENT_SECRET"
        secret_name = "seatgeek-client-secret"
      }
      env {
        name        = "AZURE_MAPS_KEY"
        secret_name = "azure-maps-key"
      }
      env {
        name        = "LASTFM_API_KEY"
        secret_name = "lastfm-api-key"
      }
    }

    # Userspace Tailscale sidecar: exposes the tailnet to the app via a pod-local SOCKS proxy.
    dynamic "container" {
      for_each = local.tailscale_auth_key == "" ? [] : [1]
      content {
        name   = "tailscale"
        image  = "docker.io/tailscale/tailscale:stable"
        cpu    = 0.25
        memory = "0.5Gi"
        env {
          name        = "TS_AUTHKEY"
          secret_name = "tailscale-auth-key"
        }
        env {
          name  = "TS_USERSPACE"
          value = "true"
        }
        env {
          name  = "TS_SOCKS5_SERVER"
          value = "localhost:1055"
        }
        env {
          name  = "TS_STATE_DIR"
          value = "mem:"
        }
        env {
          # ACA leaks KUBERNETES_SERVICE_HOST; stop containerboot from trying kube state storage.
          name  = "TS_KUBE_SECRET"
          value = ""
        }
        env {
          name  = "TS_HOSTNAME"
          value = "marquee-cloud"
        }
      }
    }
  }

  # Image tags roll out via CI (az containerapp update); Terraform manages everything else.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}
