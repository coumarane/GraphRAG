data "azurerm_resource_group" "shared" {
  name = var.azure_resource_group_name
}

data "azurerm_storage_account" "state" {
  name                = var.azure_storage_account_name
  resource_group_name = data.azurerm_resource_group.shared.name
}

resource "azurerm_storage_container" "azure_state" {
  name                  = var.state_container_name
  storage_account_id    = data.azurerm_storage_account.state.id
  container_access_type = "private"
}
