output "reinstall_tasks" {
  description = "Reinstall task ids and targets returned by OVH."
  value = {
    for name, task in ovh_dedicated_server_reinstall_task.cluster : name => {
      id           = task.id
      service_name = task.service_name
      os           = task.os
    }
  }
}

output "ssh_private_key_path" {
  description = "Local path of the SSH private key used for the OVH reinstall, when auto-generation is enabled."
  value       = var.auto_generate_ssh_key && var.ssh_public_key == null ? pathexpand(var.ssh_private_key_path) : null
}

output "ssh_private_key_secret_id" {
  description = "Azure Key Vault secret id that stores the SSH private key."
  value       = try(one(azurerm_key_vault_secret.ssh_private_key[*].id), null)
}

output "ssh_public_key_secret_id" {
  description = "Azure Key Vault secret id that stores the SSH public key."
  value       = try(one(azurerm_key_vault_secret.ssh_public_key[*].id), null)
}
