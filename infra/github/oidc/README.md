# GitHub OIDC App Registration

This folder contains automation to create, update, or delete an Azure App Registration and GitHub Actions OIDC federated credentials for a repository.

The script is intended for GitHub Actions identities such as the OVH Terraform workflow in this repository.

## Files

- [create_github_oidc_app_registration.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/create_github_oidc_app_registration.py)
- [assign_azure_roles.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/assign_azure_roles.py)
- [examples/coumarane-GraphRAG.ovh-terraform.dev.example.json](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/examples/coumarane-GraphRAG.ovh-terraform.dev.example.json)

## What it creates

- Azure App Registration
- Azure service principal for that app registration
- One or more federated credentials with issuer `https://token.actions.githubusercontent.com`

It is idempotent for:

- app creation by exact display name
- service principal creation by app client ID
- federated credential create or update by credential name

## Prerequisites

- Azure CLI installed
- Azure CLI logged in:

```bash
az login
az account set --subscription a555786b-b00c-4cea-946c-5c435d5e7100
```

- Permission to create:
  - App registrations
  - Service principals
  - Federated credentials

## Config format

Example:

```json
{
  "display_name": "github-actions-coumarane-graphrag-ovh-terraform-dev",
  "repo": "coumarane/GraphRAG",
  "tenant_id": "f387bed5-f1ed-4801-9df7-837a8905a354",
  "subscription_id": "a555786b-b00c-4cea-946c-5c435d5e7100",
  "create_service_principal": true,
  "federated_credentials": [
    {
      "name": "github-environment-dev",
      "subject": "repo:coumarane@9210984/GraphRAG@1319645493:environment:dev",
      "description": "Allows GitHub Actions jobs in the dev environment to exchange the GitHub OIDC token for Azure access."
    }
  ]
}
```

Important subject formats:

- environment-scoped job: `repo:OWNER/REPO:environment:ENVIRONMENT`
- branch-scoped job: `repo:OWNER/REPO:ref:refs/heads/BRANCH`
- pull request job: `repo:OWNER/REPO:pull_request`

The current OVH Terraform workflow uses a GitHub environment, and for this repository GitHub is currently presenting the immutable environment subject:

- `repo:coumarane@9210984/GraphRAG@1319645493:environment:dev`

Use the exact subject shown in the GitHub Actions `azure/login` log if it differs from the classic `repo:OWNER/REPO:environment:ENVIRONMENT` form.

## Dry run

```bash
python3 infra/github/oidc/create_github_oidc_app_registration.py \
  --config infra/github/oidc/examples/coumarane-GraphRAG.ovh-terraform.dev.example.json \
  --dry-run
```

## Apply

```bash
python3 infra/github/oidc/create_github_oidc_app_registration.py \
  --config infra/github/oidc/examples/coumarane-GraphRAG.ovh-terraform.dev.example.json
```

## Delete

Delete the app registration resolved by `display_name` in the config:

```bash
python3 infra/github/oidc/create_github_oidc_app_registration.py \
  --config infra/github/oidc/examples/coumarane-GraphRAG.ovh-terraform.dev.json \
  --action delete
```

Dry run delete:

```bash
python3 infra/github/oidc/create_github_oidc_app_registration.py \
  --config infra/github/oidc/examples/coumarane-GraphRAG.ovh-terraform.dev.json \
  --action delete \
  --dry-run
```

## JSON output

```bash
python3 infra/github/oidc/create_github_oidc_app_registration.py \
  --config infra/github/oidc/examples/coumarane-GraphRAG.ovh-terraform.dev.example.json \
  --output json
```

The output includes the Azure client ID you must store in GitHub Actions as:

- secret `AZURE_CLIENT_ID`

For the OVH Terraform workflow, the rest of the required GitHub settings are documented in [infra/terraform/ovh-dedicated-reinstall/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/README.md).

## Assign Azure RBAC roles

After creating the app registration, grant the Azure roles required by the workflow:

```bash
python3 infra/github/oidc/assign_azure_roles.py \
  --client-id <azure-client-id>
```

Dry run:

```bash
python3 infra/github/oidc/assign_azure_roles.py \
  --client-id <azure-client-id> \
  --dry-run
```

List only:

```bash
python3 infra/github/oidc/assign_azure_roles.py \
  --client-id <azure-client-id> \
  --action list
```

Delete the same workflow-specific assignments:

```bash
python3 infra/github/oidc/assign_azure_roles.py \
  --client-id <azure-client-id> \
  --action delete
```

## Notes

- `create_github_oidc_app_registration.py` does not assign Azure RBAC roles.
- `assign_azure_roles.py` manages the Azure RBAC roles needed by this OVH workflow.
- For this OVH workflow, the minimum practical role set is:
  - `Reader` on resource group `rg-safranysAI-Dev`
  - `Storage Blob Data Contributor` on storage account `terraformstate240775`
  - `Key Vault Secrets Officer` on Key Vault `safranys-kv-shared`
- `--action delete` deletes the Azure App Registration identified by the config `display_name`.
- If multiple app registrations already share the same display name, the script stops and asks for a unique display name.
- Use `--delete-extra-federated-credentials` only when you want the config file to be the full source of truth.
