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

variable "key_vault_name" {
  type    = string
  default = "marquee-kv-frank"
}

variable "local_llm_base_url" {
  type    = string
  default = "http://100.88.74.98:8081/v1"
}

variable "local_llm_model" {
  type    = string
  default = "qwen3.8-27b"
}
