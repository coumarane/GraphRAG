output "backend_config" {
  description = "Backend configuration values to pass to terraform init for the OVH reinstall stack."
  value = {
    resource_group_name  = data.azurerm_resource_group.shared.name
    storage_account_name = data.azurerm_storage_account.state.name
    container_name       = azurerm_storage_container.ovh_state.name
    key                  = var.state_blob_key
    tenant_id            = var.azure_tenant_id
    subscription_id      = var.azure_subscription_id
    use_azuread_auth     = true
    use_cli              = true
  }
}
