# Azure Terraform Stack

Terraform area for Azure resources used by GraphRAG.

This root stack currently provisions:

- one dedicated Azure Storage account for RAG document storage
- private blob containers for application documents and processing artifacts
- lifecycle management, versioning, change feed, and soft delete settings
- optional `Storage Blob Data Contributor` role assignments

It is intended to grow over time as more Azure resources are added under `infra/terraform/azure`.

## Current scope

Current resource target:

- resource group: `rg-safranysAI-Dev`
- subscription: `a555786b-b00c-4cea-946c-5c435d5e7100`
- tenant: `f387bed5-f1ed-4801-9df7-837a8905a354`

## Files

- [providers.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/providers.tf): Terraform requirements, backend, and Azure provider
- [variables.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/variables.tf): user inputs
- [main.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/main.tf): storage account, containers, lifecycle policy, RBAC
- [outputs.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/outputs.tf): endpoints and IDs
- [terraform.dev.tfvars](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/terraform.dev.tfvars): tracked dev defaults
- [backend.hcl.example](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/backend.hcl.example): backend init settings
- [bootstrap-state/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/bootstrap-state/README.md): create the Azure Blob container for Terraform state

## What this stack provisions

- Azure Storage account:
  - `StorageV2`
  - HTTPS only
  - TLS 1.2 minimum
  - blob versioning enabled
  - blob change feed enabled
  - last-access tracking enabled
  - blob soft delete enabled
  - container soft delete enabled
- Private blob containers:
  - `documents`
  - `artifacts`
- Optional lifecycle policy:
  - transition base blobs to Cool after `30` days
  - delete blobs and old versions after `365` days

## Naming

The storage account name is generated from:

- `storage_account_name_prefix`
- `environment`
- a random 4-character suffix

This avoids global-name collisions while keeping the name readable.

Example generated name:

- `graphragdocsdeva1b2`

## Prerequisites

- Terraform `>= 1.12`
- Azure CLI
- Azure access that can:
  - read the existing resource group `rg-safranysAI-Dev`
  - create storage accounts and blob containers in that resource group
  - create role assignments if you set `blob_data_contributor_principal_ids`

Azure login for local use:

```bash
az login
az account set --subscription a555786b-b00c-4cea-946c-5c435d5e7100
```

## Step 1: Create the Terraform state container

Use the bootstrap stack once:

```bash
cd infra/terraform/azure/bootstrap-state
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
```

This creates the container `tfstate-azure` in the existing storage account `terraformstate240775`.

## Step 2: Initialize the main stack backend

```bash
cp infra/terraform/azure/backend.hcl.example \
  infra/terraform/azure/backend.hcl
```

Then initialize:

```bash
cd infra/terraform/azure
terraform init -reconfigure -backend-config=backend.hcl
```

## Step 3: Review the tracked dev config

```bash
cat infra/terraform/azure/terraform.dev.tfvars
```

Key fields:

- `storage_account_name_prefix`
- `storage_containers`
- `account_replication_type`
- `blob_data_contributor_principal_ids`

Use a local override file for machine-specific changes:

- `infra/terraform/azure/terraform.local.tfvars`

## Step 4: Plan and apply

```bash
cd infra/terraform/azure
terraform plan -var-file=terraform.dev.tfvars
terraform apply -var-file=terraform.dev.tfvars
```

## Outputs

Useful outputs:

- `storage_account_name`
- `primary_blob_endpoint`
- `container_names`

Example:

```bash
terraform output storage_account_name
terraform output primary_blob_endpoint
terraform output container_names
```

## Recommended next step

After apply:

1. decide how the OVH-hosted application authenticates to Blob Storage
2. sync the chosen storage settings into Azure Key Vault
3. update API runtime configuration to use Azure Blob instead of MinIO

Likely app env variables to introduce later:

- `OBJECT_STORE_BACKEND=azure_blob`
- `AZURE_BLOB_ACCOUNT_URL=https://<storage-account>.blob.core.windows.net/`
- `AZURE_BLOB_CONTAINER=documents`
- credentials or service principal values depending on the final auth model
