variable "azure_subscription_id" {
  description = "Azure subscription that contains the remote state storage account."
  type        = string
  default     = "a555786b-b00c-4cea-946c-5c435d5e7100"
}

variable "azure_tenant_id" {
  description = "Azure tenant used for provider authentication."
  type        = string
  default     = "f387bed5-f1ed-4801-9df7-837a8905a354"
}

variable "azure_resource_group_name" {
  description = "Azure resource group that contains the existing storage account."
  type        = string
  default     = "rg-safranysAI-Dev"
}

variable "azure_storage_account_name" {
  description = "Existing Azure Storage Account used for Terraform remote state."
  type        = string
  default     = "terraformstate240775"
}

variable "state_container_name" {
  description = "Blob container name used for the OVH Terraform state."
  type        = string
  default     = "tfstate-ovh-dedicated-reinstall"
}

variable "state_blob_key" {
  description = "Blob name used by the OVH reinstall Terraform state."
  type        = string
  default     = "ovh-dedicated-reinstall.tfstate"
}
