# Azure Key Vault Env Sync

This folder contains two helpers:

- [assign_keyvault_role.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/azure/assign_keyvault_role.py)
  Grants, removes, or lists an Azure RBAC role on a Key Vault.
- [manage_keyvault_app_env.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/azure/manage_keyvault_app_env.py)
  Syncs any dotenv file to Azure Key Vault.

## Scope

Current Key Vaults:

- API: `graphrag-kv-api`
- Web: `graphrag-kv-web`
- Resource group: `rg-safranysAI-Dev`
- Subscription: `a555786b-b00c-4cea-946c-5c435d5e7100`

## Quick Start

1. Login to Azure CLI.
2. Grant the right Key Vault RBAC role.
3. Verify you can write a test secret.
4. Sync the env file.

## 1. Azure Login

```bash
az login
az account set --subscription a555786b-b00c-4cea-946c-5c435d5e7100
```

## 2. Grant RBAC

Operator access for syncing `.env` into Key Vault:

Grant `Key Vault Secrets Officer` to your current signed-in Azure user on the API Key Vault:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-api \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets Officer"
```

Grant `Key Vault Secrets Officer` to your current signed-in Azure user on the web Key Vault:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-web \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets Officer"
```

CSI runtime access for Kubernetes pods:

Grant `Key Vault Secrets User` to the service principal used by the CSI provider on the API Key Vault:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-api \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets User" \
  --assignee "$AZURE_CLIENT_ID" \
  --principal-type ServicePrincipal
```

Grant `Key Vault Secrets User` to the service principal used by the CSI provider on the web Key Vault:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-web \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets User" \
  --assignee "$AZURE_CLIENT_ID" \
  --principal-type ServicePrincipal
```

Useful variants:

- Preview only:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-api \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets Officer" \
  --dry-run
```

- Check current assignment:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-api \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets Officer" \
  --action list
```

- Remove the assignment:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-api \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets Officer" \
  --action delete
```

- Grant to a specific user:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-api \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets Officer" \
  --assignee your.user@company.com \
  --principal-type User
```

- Grant to a service principal:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-api \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets User" \
  --assignee 00000000-0000-0000-0000-000000000000 \
  --principal-type ServicePrincipal
```

## 3. Verify Access

After RBAC assignment, wait a few minutes for propagation, then test:

```bash
az keyvault secret set \
  --vault-name graphrag-kv-api \
  --name test-secret \
  --value test
```

If this fails with `Forbidden`, RBAC has not propagated yet or the assignment is missing.

Note:

- the write test above is for operator access using `Key Vault Secrets Officer`
- for CSI runtime access, the correct least-privilege role is `Key Vault Secrets User`
- `Key Vault Secrets User` is enough for Kubernetes runtime reads, but not for syncing `.env` into the vault

## 4. Sync Env File To Key Vault

Sync API env:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --env-file .env.production \
  --vault-name graphrag-kv-api \
  --app api
```

Sync web env:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --env-file frontend/.env.production \
  --vault-name graphrag-kv-web \
  --app web
```

Sync any other env file:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --env-file path/to/.env.production \
  --vault-name some-keyvault-name \
  --app some-app
```

Inline override:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --env-file .env.production \
  --vault-name graphrag-kv-api \
  --app api \
  --set AUTH_BOOTSTRAP_EMAIL=admin@safranys.com
```

Dry run:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --env-file .env.production \
  --vault-name graphrag-kv-api \
  --app api \
  --dry-run
```

## 5. List, Delete, And Reconcile

List secrets:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --vault-name graphrag-kv-api \
  --list
```

Delete one secret:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --vault-name graphrag-kv-api \
  --delete AUTH_BOOTSTRAP_PASSWORD
```

Delete several:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --vault-name graphrag-kv-api \
  --delete AUTH_BOOTSTRAP_PASSWORD \
  --delete AUTH_BOOTSTRAP_EMAIL
```

Make Key Vault match the env file by deleting missing managed secrets:

```bash
python3 infra/azure/manage_keyvault_app_env.py \
  --env-file .env.production \
  --vault-name graphrag-kv-api \
  --app api \
  --delete-missing
```

`--delete-missing` only deletes secrets previously managed by this script in the same scope:

- if `--app` is set, it matches the same `app` tag
- otherwise it matches the same `env_file` tag

## Permissions

Recommended role:

- `Key Vault Secrets Officer`

Runtime read-only role for Kubernetes CSI:

- `Key Vault Secrets User`

Broader alternative:

- `Key Vault Administrator`

Permission split by command:

- normal sync needs secret create or update permission
- `--list` needs secret metadata read permission
- `--delete` needs secret delete permission
- `--delete-missing` needs both list and delete permission

## Secret Naming

Azure Key Vault secret names cannot use `_`, so env names are mapped like this:

- `AUTH_JWT_SECRET` -> `auth-jwt-secret`
- `NEXT_PUBLIC_API_URL` -> `next-public-api-url`

The original env name is preserved in tags as `env_name`.

## Tags Added By The Sync Script

Each managed secret gets these tags:

- `app`
- `env_name`
- `env_file`
- `managed_by`
