output "resource_group_name" {
  description = "Azure resource group hosting the storage account."
  value       = data.azurerm_resource_group.shared.name
}

output "storage_account_name" {
  description = "Generated Azure Storage account name for GraphRAG document storage."
  value       = azurerm_storage_account.rag.name
}

output "storage_account_id" {
  description = "Azure Storage account resource ID."
  value       = azurerm_storage_account.rag.id
}

output "primary_blob_endpoint" {
  description = "Primary Blob endpoint."
  value       = azurerm_storage_account.rag.primary_blob_endpoint
}

output "container_names" {
  description = "Created blob containers."
  value       = sort(keys(azurerm_storage_container.rag))
}

output "container_ids" {
  description = "Created blob container IDs."
  value = {
    for name, container in azurerm_storage_container.rag : name => container.id
  }
}
