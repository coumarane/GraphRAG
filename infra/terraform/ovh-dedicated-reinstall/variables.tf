variable "installation_template_name" {
  description = "OVH installation template to use for the reinstall task."
  type        = string
  default     = "ubuntu2604-server"
}

variable "azure_subscription_id" {
  description = "Azure subscription used for Key Vault lookups and optional supporting resources."
  type        = string
  default     = "a555786b-b00c-4cea-946c-5c435d5e7100"
}

variable "azure_tenant_id" {
  description = "Azure tenant used for Key Vault lookups and backend authentication."
  type        = string
  default     = "f387bed5-f1ed-4801-9df7-837a8905a354"
}

variable "azure_resource_group_name" {
  description = "Azure resource group that contains the shared Key Vault and Terraform state storage account."
  type        = string
  default     = "rg-safranysAI-Dev"
}

variable "azure_key_vault_name" {
  description = "Existing Azure Key Vault used to store the generated SSH key material."
  type        = string
  default     = "safranys-kv-shared"
}

variable "post_installation_script_base64" {
  description = "Optional base64-encoded post-installation script sent to OVH."
  type        = string
  default     = null
  sensitive   = true
}

variable "ssh_public_key" {
  description = "Optional SSH public key injected by OVH during installation. Leave null to use the auto-generated key."
  type        = string
  default     = null
}

variable "auto_generate_ssh_key" {
  description = "Generate an SSH key pair locally on the operator machine when ssh_public_key is not provided."
  type        = bool
  default     = true
}

variable "ssh_private_key_path" {
  description = "Local private key path on the operator machine. The matching public key is expected at <path>.pub."
  type        = string
  default     = "~/.ssh/ovh-rag-reinstall-ed25519"
}

variable "ssh_key_comment" {
  description = "Comment written into the generated SSH public key."
  type        = string
  default     = "ovh-rag-reinstall"
}

variable "manage_ssh_key_in_key_vault" {
  description = "Store the generated SSH key material in the existing Azure Key Vault."
  type        = bool
  default     = true
}

variable "ssh_private_key_secret_name" {
  description = "Key Vault secret name for the generated private SSH key."
  type        = string
  default     = "ovh-rag-reinstall-ssh-private-key"
}

variable "ssh_private_key_secret_version" {
  description = "Increment this integer when you intentionally rotate the private key and want to publish a new Key Vault secret version."
  type        = number
  default     = 1
}

variable "ssh_public_key_secret_name" {
  description = "Key Vault secret name for the generated public SSH key."
  type        = string
  default     = "ovh-rag-reinstall-ssh-public-key"
}

variable "scheme_name" {
  description = "Optional OVH partition scheme name. Leave null to rely on explicit layouts only."
  type        = string
  default     = null
}

variable "servers" {
  description = "Existing OVH dedicated servers to reinstall."
  type = map(object({
    service_name = string
    hostname     = string
    role         = string
    ip           = string
  }))
  default = {
    master = {
      service_name = "ns3063017.ip-193-70-35.eu"
      hostname     = "rag-master"
      role         = "master"
      ip           = "193.70.35.121"
    }
    worker1 = {
      service_name = "ns3063022.ip-193-70-35.eu"
      hostname     = "rag-worker-1"
      role         = "worker"
      ip           = "193.70.35.122"
    }
    worker2 = {
      service_name = "ns3086111.ip-145-239-68.eu"
      hostname     = "rag-worker-2"
      role         = "worker"
      ip           = "145.239.68.200"
    }
  }
}
