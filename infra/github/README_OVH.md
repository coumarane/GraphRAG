# OVH GitHub Actions Setup

This document covers the GitHub-side setup for the OVH dedicated server reinstall workflow.

Related files:

- [run-ovh-terraform-reinstall.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-ovh-terraform-reinstall.yml)
- [reusable-ovh-terraform-reinstall.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/reusable-ovh-terraform-reinstall.yml)
- [infra/terraform/ovh-dedicated-reinstall/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/README.md)
- [infra/github/oidc/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/README.md)
- [infra/github/actions-config.dev.json](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/actions-config.dev.json)

## What this workflow does

The OVH GitHub workflow:

- logs into Azure with GitHub OIDC
- reads or restores the SSH private key from Azure Key Vault
- configures the Azure Blob backend for Terraform state
- runs `terraform init`, `terraform validate`, `terraform plan`
- optionally runs `terraform apply`

The Kubernetes and add-on workflows also restore that same SSH private key from Azure Key Vault, so GitHub does not need a separate Kubernetes SSH secret anymore.

## Required GitHub secrets

Set these in the `dev` environment, or at repository scope if that is how you manage them:

- `AZURE_CLIENT_ID`
- `OVH_APPLICATION_KEY`
- `OVH_APPLICATION_SECRET`
- `OVH_CONSUMER_KEY`

## Required GitHub variables

- `AZURE_SUBSCRIPTION_ID`
- `AZURE_TENANT_ID`
- `AZURE_RESOURCE_GROUP_NAME`
- `AZURE_STORAGE_ACCOUNT_NAME`
- `AZURE_TERRAFORM_STATE_CONTAINER_NAME`
- `AZURE_KEY_VAULT_NAME`

## Optional GitHub variables

- `OVH_TERRAFORM_STATE_KEY`
- `OVH_SSH_PRIVATE_KEY_SECRET_NAME`
- `OVH_SSH_PRIVATE_KEY_PATH`

Default optional values used by the workflow:

- `OVH_TERRAFORM_STATE_KEY=ovh-dedicated-reinstall.tfstate`
- `OVH_SSH_PRIVATE_KEY_SECRET_NAME=ovh-rag-reinstall-ssh-private-key`
- `OVH_SSH_PRIVATE_KEY_PATH=~/.ssh/ovh-rag-reinstall-ed25519`

## Where the OVH API credentials come from

The workflow uses the classic OVH API key triplet:

- `OVH_APPLICATION_KEY`
- `OVH_APPLICATION_SECRET`
- `OVH_CONSUMER_KEY`

Create them from OVHcloud:

- EU token page: `https://auth.eu.ovhcloud.com/api/createToken`
- or via OVHcloud Control Panel: `Identity, Security & Operations` -> `API keys`

Use a dedicated API key for this repository and restrict permissions to only the API paths the workflow needs whenever possible.

## What to enter in the OVH "Create API Keys" form

Suggested values:

- `Application name`: `GraphRAG OVH Terraform`
- `Application description`: `OVH dedicated server reinstall for coumarane/GraphRAG`
- `Validity`: `Unlimited`

Minimum rights for the current Terraform workflow:

- `GET` -> `/dedicated/server/*`
- `POST` -> `/dedicated/server/*`
- `GET` -> `/dedicated/installationTemplate/*`

Why these rights are needed:

- `/dedicated/server/*`: read dedicated server details and trigger the reinstall task
- `/dedicated/installationTemplate/*`: read the installation template such as `ubuntu2604-server`

Restricted IPs:

- leave empty if the same credentials will be used by GitHub-hosted runners
- optionally restrict to your public IP only if you use the key locally from your Mac and nowhere else

Do not add broader rights such as `*`, `PUT`, or `DELETE` unless you later confirm the workflow requires them.

After you click `Create`, OVH returns:

- `Application Key` -> `OVH_APPLICATION_KEY`
- `Application Secret` -> `OVH_APPLICATION_SECRET`
- `Consumer Key` -> `OVH_CONSUMER_KEY`

## Where `AZURE_CLIENT_ID` comes from

`AZURE_CLIENT_ID` is the Azure App Registration client ID used by GitHub OIDC.

Create it with:

```bash
python3 infra/github/oidc/create_github_oidc_app_registration.py \
  --config infra/github/oidc/examples/coumarane-GraphRAG.ovh-terraform.dev.json
```

The script output includes the client ID. Put that value into GitHub as secret `AZURE_CLIENT_ID`.

## Applying the GitHub config

Fill the values in:

- [infra/github/actions-config.dev.json](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/actions-config.dev.json)

Then apply them:

```bash
python3 infra/github/manage_github_actions_config.py \
  --repo coumarane/GraphRAG \
  apply \
  --file infra/github/actions-config.dev.json
```

Important:

- the JSON file is not auto-filled by the workflow
- you must set the secret and variable values before applying it
- the shared SSH key secret in Azure Key Vault is created later by the Terraform workflow itself
- Kubernetes-related workflows reuse that same Key Vault SSH secret

## How to connect from your Mac after the first run

You do not need to create the SSH key manually before the first workflow run.

Normal flow:

- the GitHub workflow checks Azure Key Vault for `OVH_SSH_PRIVATE_KEY_SECRET_NAME`
- if the secret exists, it restores and uses that key
- if the secret does not exist, Terraform generates the key pair and stores the private key in Azure Key Vault

After the first successful run, restore the private key onto your Mac:

```bash
az keyvault secret show \
  --vault-name safranys-kv-shared \
  --name ovh-rag-reinstall-ssh-private-key \
  --query value \
  -o tsv > ~/.ssh/ovh-rag-reinstall-ed25519

chmod 600 ~/.ssh/ovh-rag-reinstall-ed25519
ssh-keygen -y -f ~/.ssh/ovh-rag-reinstall-ed25519 > ~/.ssh/ovh-rag-reinstall-ed25519.pub
chmod 644 ~/.ssh/ovh-rag-reinstall-ed25519.pub
```

Then connect:

```bash
ssh -i ~/.ssh/ovh-rag-reinstall-ed25519 ubuntu@193.70.35.121
```

To inspect the derived public key:

```bash
cat ~/.ssh/ovh-rag-reinstall-ed25519.pub
```

If you changed the GitHub variables from their defaults, replace:

- Key Vault secret name `ovh-rag-reinstall-ssh-private-key`
- local key path `~/.ssh/ovh-rag-reinstall-ed25519`

## Suggested setup order

1. Create the Azure OIDC app registration and federated credential.
2. Copy the returned Azure client ID into `infra/github/actions-config.dev.json`.
3. Fill the OVH API key values.
4. Fill the Azure backend and Key Vault variables.
5. Apply the GitHub config JSON.
6. Run the OVH Terraform workflow with `operation=plan`.
7. Run again with `operation=apply` only after reviewing the plan.
8. After the first successful apply, Kubernetes-related workflows can reuse the same SSH key from Key Vault automatically.

## Run the workflow

In GitHub Actions, run:

- `Run OVH Terraform Reinstall`

Inputs:

- `operation=plan` for a safe first run
- `operation=apply` for the actual reinstall
- `environment_name=dev`

## Notes

- This workflow is destructive when run with `operation=apply`.
- It targets existing OVH dedicated servers. It does not order new servers.
- If the Key Vault SSH private key already exists, the workflow restores it before Terraform runs.
