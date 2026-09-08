variable "subscription_id" {
  type    = string
  default = "a8d74766-7daf-4bb2-85b4-4b95fa2687e0"
}

variable "resource_group_name" {
  type    = string
  default = "marquee-rg"
}

variable "acr_name" {
  type    = string
  default = "marqueefrankacr"
}

variable "foundry_account_name" {
  type    = string
  default = "marquee-frank-foundry"
}

variable "foundry_project_endpoint" {
  type    = string
  default = "https://marquee-frank-foundry.services.ai.azure.com/api/projects/marquee"
}

variable "foundry_agent_name" {
  type    = string
  default = "marquee-planner"
}

variable "image_tag" {
  type        = string
  description = "Tag of the marquee image in ACR, set by scripts/deploy.ps1."
}

variable "seatgeek_client_id" {
  type      = string
  sensitive = true
}

variable "seatgeek_client_secret" {
  type      = string
  sensitive = true
}

variable "azure_maps_key" {
  type      = string
  sensitive = true
}

variable "lastfm_api_key" {
  type      = string
  sensitive = true
}
