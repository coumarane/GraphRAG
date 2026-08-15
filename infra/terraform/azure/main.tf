data "azurerm_resource_group" "shared" {
  name = var.azure_resource_group_name
}

resource "random_string" "storage_suffix" {
  length  = 4
  upper   = false
  special = false
  numeric = true
  lower   = true
}

locals {
  storage_account_name = substr(
    regexreplace(
      lower("${var.storage_account_name_prefix}${var.environment}${random_string.storage_suffix.result}"),
      "[^a-z0-9]",
      ""
    ),
    0,
    24
  )

  common_tags = merge(
    {
      project     = "GraphRAG"
      environment = var.environment
      managed_by  = "terraform"
      stack       = "azure"
    },
    var.tags
  )
}

resource "azurerm_storage_account" "rag" {
  name                            = local.storage_account_name
  resource_group_name             = data.azurerm_resource_group.shared.name
  location                        = data.azurerm_resource_group.shared.location
  account_tier                    = var.account_tier
  account_replication_type        = var.account_replication_type
  account_kind                    = "StorageV2"
  access_tier                     = var.access_tier
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = true

  blob_properties {
    versioning_enabled       = true
    change_feed_enabled      = true
    last_access_time_enabled = true

    delete_retention_policy {
      days = var.blob_delete_retention_days
    }

    container_delete_retention_policy {
      days = var.container_delete_retention_days
    }
  }

  tags = local.common_tags
}

resource "azurerm_storage_container" "rag" {
  for_each = toset(var.storage_containers)

  name                  = each.value
  storage_account_id    = azurerm_storage_account.rag.id
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "rag" {
  count = var.enable_lifecycle_management ? 1 : 0

  storage_account_id = azurerm_storage_account.rag.id

  dynamic "rule" {
    for_each = toset(var.storage_containers)

    content {
      name    = replace("lifecycle-${rule.value}", "-", "")
      enabled = true

      filters {
        blob_types   = ["blockBlob"]
        prefix_match = ["${rule.value}/"]
      }

      actions {
        base_blob {
          tier_to_cool_after_days_since_modification_greater_than = var.tier_to_cool_after_days
          delete_after_days_since_modification_greater_than       = var.delete_after_days
        }

        version {
          delete_after_days_since_creation = var.delete_after_days
        }
      }
    }
  }
}

resource "azurerm_role_assignment" "blob_data_contributor" {
  for_each = toset(var.blob_data_contributor_principal_ids)

  scope                = azurerm_storage_account.rag.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}
