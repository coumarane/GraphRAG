variable "azure_subscription_id" {
  description = "Azure subscription ID."
  type        = string
  default     = "a555786b-b00c-4cea-946c-5c435d5e7100"
}

variable "azure_tenant_id" {
  description = "Azure tenant ID."
  type        = string
  default     = "f387bed5-f1ed-4801-9df7-837a8905a354"
}

variable "azure_resource_group_name" {
  description = "Existing Azure resource group that hosts the Terraform state storage account."
  type        = string
  default     = "rg-safranysAI-Dev"
}

variable "azure_storage_account_name" {
  description = "Existing Azure Storage account used for Terraform state."
  type        = string
  default     = "terraformstate240775"
}

variable "state_container_name" {
  description = "Blob container name used for the Azure Terraform stack state."
  type        = string
  default     = "tfstate-azure"
}

variable "state_blob_key" {
  description = "Terraform state blob key that will be used in backend.hcl."
  type        = string
  default     = "azure-rag-storage.tfstate"
}
