azure_resource_group_name   = "rg-safranysAI-Dev"
environment                 = "dev"
storage_account_name_prefix = "graphragdocs"
account_replication_type    = "ZRS"

storage_containers = [
  "documents",
  "artifacts",
]

blob_data_contributor_principal_ids = []
