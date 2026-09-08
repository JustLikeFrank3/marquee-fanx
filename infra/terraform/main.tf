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
  role_definition_name = "Azure AI User"
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
    value = var.seatgeek_client_id
  }
  secret {
    name  = "seatgeek-client-secret"
    value = var.seatgeek_client_secret
  }
  secret {
    name  = "azure-maps-key"
    value = var.azure_maps_key
  }
  secret {
    name  = "lastfm-api-key"
    value = var.lastfm_api_key
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
        value = "azure_foundry"
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
  }
}
