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
  description = "Existing Azure resource group that will host the GraphRAG Azure resources."
  type        = string
  default     = "rg-safranysAI-Dev"
}

variable "environment" {
  description = "Short environment name appended to generated names."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9-]{2,10}$", var.environment))
    error_message = "environment must be 2-10 chars of lowercase letters, numbers, or dashes."
  }
}

variable "storage_account_name_prefix" {
  description = "Lowercase prefix for the generated storage account name. A random suffix is appended to ensure global uniqueness."
  type        = string
  default     = "graphragdocs"

  validation {
    condition     = can(regex("^[a-z0-9]{3,15}$", var.storage_account_name_prefix))
    error_message = "storage_account_name_prefix must be 3-15 lowercase alphanumeric characters."
  }
}

variable "account_tier" {
  description = "Azure Storage account tier."
  type        = string
  default     = "Standard"
}

variable "account_replication_type" {
  description = "Azure Storage replication type."
  type        = string
  default     = "LRS"
}

variable "access_tier" {
  description = "Default access tier for the storage account."
  type        = string
  default     = "Hot"
}

variable "storage_containers" {
  description = "Private blob containers created for the RAG platform."
  type        = list(string)
  default = [
    "documents",
    "artifacts",
  ]

  validation {
    condition = alltrue([
      for name in var.storage_containers : can(regex("^[a-z0-9-]{3,63}$", name))
    ])
    error_message = "Every storage container name must be 3-63 chars of lowercase letters, numbers, or dashes."
  }
}

variable "enable_lifecycle_management" {
  description = "Whether to attach a blob lifecycle management policy."
  type        = bool
  default     = true
}

variable "tier_to_cool_after_days" {
  description = "Days before base blobs transition to Cool."
  type        = number
  default     = 30
}

variable "delete_after_days" {
  description = "Days before base blobs are deleted by lifecycle policy."
  type        = number
  default     = 365
}

variable "blob_delete_retention_days" {
  description = "Soft delete retention for blobs."
  type        = number
  default     = 14
}

variable "container_delete_retention_days" {
  description = "Soft delete retention for containers."
  type        = number
  default     = 14
}

variable "blob_data_contributor_principal_ids" {
  description = "Azure principal IDs that should receive Storage Blob Data Contributor on the storage account."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Extra tags applied to the Azure resources."
  type        = map(string)
  default     = {}
}
