output "backend_config" {
  description = "Values to copy into backend.hcl for the Azure Terraform stack."
  value = {
    resource_group_name  = data.azurerm_resource_group.shared.name
    storage_account_name = data.azurerm_storage_account.state.name
    container_name       = azurerm_storage_container.azure_state.name
    key                  = var.state_blob_key
  }
}
