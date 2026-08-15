# Azure Key Vault Env Sync

This folder contains two helpers:

- [assign_keyvault_role.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/azure/assign_keyvault_role.py)
  Grants, removes, or lists an Azure RBAC role on a Key Vault.
- [manage_keyvault_app_env.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/azure/manage_keyvault_app_env.py)
  Syncs any dotenv file to Azure Key Vault.
- [create_keyvault_csi_app.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/azure/create_keyvault_csi_app.py)
  Creates the Azure App Registration, Service Principal, and optional client secret for Kubernetes Key Vault CSI runtime access.

## Scope

Current Key Vaults:

- API: `graphrag-kv-api`
- Web: `graphrag-kv-web`
- Resource group: `rg-safranysAI-Dev`
- Subscription: `a555786b-b00c-4cea-946c-5c435d5e7100`

## Quick Start

1. Login to Azure CLI.
2. Create the CSI runtime app if you do not have one yet.
3. Grant the right Key Vault RBAC role.
4. Verify you can write a test secret.
5. Sync the env file.

## 1. Azure Login

```bash
az login
az account set --subscription a555786b-b00c-4cea-946c-5c435d5e7100
```

## 2. Create The CSI Runtime App

Create the dedicated App Registration and Service Principal for Kubernetes CSI runtime:

```bash
python3 infra/azure/create_keyvault_csi_app.py \
  --display-name graphrag-kv-csi-dev \
  --create-client-secret
```

Important:

- copy the printed client secret immediately
- use the output to fill these GitHub secrets:
  - `AZURE_KEYVAULT_CSI_CLIENT_ID`
  - `AZURE_KEYVAULT_CSI_CLIENT_SECRET`

Useful variants:

- Dry run:

```bash
python3 infra/azure/create_keyvault_csi_app.py \
  --display-name graphrag-kv-csi-dev \
  --create-client-secret \
  --dry-run
```

- List existing app:

```bash
python3 infra/azure/create_keyvault_csi_app.py \
  --display-name graphrag-kv-csi-dev \
  --action list
```

- Delete app:

```bash
python3 infra/azure/create_keyvault_csi_app.py \
  --display-name graphrag-kv-csi-dev \
  --action delete
```

## 3. Grant RBAC

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

## CSI Runtime Identity

The Kubernetes pods do not use GitHub OIDC directly at runtime.

For Azure Key Vault CSI access, the cluster uses a client ID and client secret for an Azure App Registration / Service Principal.

Recommended model:

- GitHub workflows:
  - keep using OIDC with `AZURE_CLIENT_ID`
- Kubernetes CSI runtime:
  - use a dedicated App Registration
  - grant it `Key Vault Secrets User`
  - store its credentials in GitHub secrets

### Where `AZURE_KEYVAULT_CSI_CLIENT_SECRET` Comes From

`AZURE_KEYVAULT_CSI_CLIENT_SECRET` is the client secret of the Azure App Registration used by the Secrets Store CSI Azure provider.

Create it in Azure Portal:

1. Open `Microsoft Entra ID`
2. Open `App registrations`
3. Open the app you want to use for Kubernetes CSI runtime
4. Go to `Certificates & secrets`
5. Select `New client secret`
6. Give it a name such as `graphrag-kv-csi`
7. Choose the expiry period
8. Create the secret
9. Copy the secret value immediately

Important:

- Azure only shows the secret value once
- the secret `Value` is what you store in GitHub
- do not confuse it with the secret `ID`

### Recommended GitHub Secrets

Recommended dedicated CSI secrets:

- `AZURE_KEYVAULT_CSI_CLIENT_ID`
- `AZURE_KEYVAULT_CSI_CLIENT_SECRET`

The deploy workflows also support fallback to:

- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`

But for least privilege and cleaner separation, it is better to use dedicated CSI credentials instead of reusing the workflow identity.

### GitHub Secret Setup Example

If you create a dedicated App Registration for CSI:

- `AZURE_KEYVAULT_CSI_CLIENT_ID`
  - value: the application (client) ID of that App Registration
- `AZURE_KEYVAULT_CSI_CLIENT_SECRET`
  - value: the client secret value created under `Certificates & secrets`

### Required RBAC For The CSI Identity

Grant this role to the CSI App Registration / Service Principal:

- `Key Vault Secrets User`

Grant it on:

- `graphrag-kv-api`
- `graphrag-kv-web`

Example:

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-api \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets User" \
  --assignee "$AZURE_KEYVAULT_CSI_CLIENT_ID" \
  --principal-type ServicePrincipal
```

```bash
python3 infra/azure/assign_keyvault_role.py \
  --vault-name graphrag-kv-web \
  --resource-group rg-safranysAI-Dev \
  --role-name "Key Vault Secrets User" \
  --assignee "$AZURE_KEYVAULT_CSI_CLIENT_ID" \
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

## 4. Verify Access

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

## 5. Sync Env File To Key Vault

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
