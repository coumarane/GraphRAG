# OVH Dedicated Server Reinstall

Terraform stack to reinstall the existing OVH dedicated servers for the cluster from the OVHcloud OS template:

- template type: `os basic`
- template name: `ubuntu2604-server`
- OS label: `Ubuntu Server 26.04 "Resolute Raccoon" LTS`

The server inventory and disk layout come from [infra/ovh/CLUSTER_README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ovh/CLUSTER_README.md).

## What this stack does

- uses `ovh_dedicated_server_reinstall_task`
- reinstalls the three existing dedicated servers
- stores Terraform state in Azure Blob Storage
- generates an SSH key automatically on your Mac when needed
- stores the generated private SSH key in Azure Key Vault
- injects the paired public key into the OVH reinstall task

Target servers:

- `ns3063017.ip-193-70-35.eu`
- `ns3063022.ip-193-70-35.eu`
- `ns3086111.ip-145-239-68.eu`

## Azure resources used

This stack is preconfigured for:

- subscription: `a555786b-b00c-4cea-946c-5c435d5e7100`
- tenant: `f387bed5-f1ed-4801-9df7-837a8905a354`
- resource group: `rg-safranysAI-Dev`
- storage account: `terraformstate240775`
- key vault: `safranys-kv-shared`

The Azure Blob container is created by the bootstrap stack in [bootstrap-azure-state](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/bootstrap-azure-state).

## Files

- [providers.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/providers.tf): Terraform requirements, Azure backend, providers
- [variables.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/variables.tf): user inputs
- [main.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/main.tf): OVH reinstall task, Key Vault secret publishing, SSH key generation
- [outputs.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/outputs.tf): task and secret outputs
- [terraform.dev.tfvars](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/terraform.dev.tfvars): tracked GitHub Actions inputs for the dev environment
- `infra/terraform/ovh-dedicated-reinstall/terraform.local.tfvars`: ignored local-only overrides
- [backend.hcl.example](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/backend.hcl.example): backend init settings

## Prerequisites

- Terraform `>= 1.12`
- Azure CLI
- `ssh-keygen`
- Python 3
- OVH API credentials exported in your shell
- Azure access that can:
  - create a blob container in `terraformstate240775`
  - read and write secrets in `safranys-kv-shared`

OVH environment variables:

```bash
export OVH_ENDPOINT=ovh-eu
export OVH_APPLICATION_KEY=replace-me
export OVH_APPLICATION_SECRET=replace-me
export OVH_CONSUMER_KEY=replace-me
```

Azure login for local use:

```bash
az login
az account set --subscription a555786b-b00c-4cea-946c-5c435d5e7100
```

## Step 1: Create the Azure Blob container

Run the bootstrap stack once:

```bash
cd infra/terraform/ovh-dedicated-reinstall/bootstrap-azure-state
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
```

This creates the container `tfstate-ovh-dedicated-reinstall` in the existing storage account `terraformstate240775`.

## Step 2: Configure the main stack

Use the tracked dev variable file:

```bash
cat infra/terraform/ovh-dedicated-reinstall/terraform.dev.tfvars
```

Default behavior:

- generates `~/.ssh/ovh-rag-reinstall-ed25519` if it does not exist
- stores the private key in Key Vault secret `ovh-rag-reinstall-ssh-private-key`
- stores the public key in Key Vault secret `ovh-rag-reinstall-ssh-public-key`
- uses that public key for the OVH reinstall

Override this only if needed:

- use `infra/terraform/ovh-dedicated-reinstall/terraform.local.tfvars` for local-only changes you do not want to commit
- set `ssh_public_key` if you want to supply your own public key
- set `auto_generate_ssh_key = false` if the key is managed outside Terraform
- increment `ssh_private_key_secret_version` if you intentionally rotate the private key and want Terraform to publish a new Key Vault secret version

To base64-encode a post-install script:

```bash
base64 -w0 post_install.sh
```

## Step 3: Initialize the Azure backend

Copy the backend example:

```bash
cp infra/terraform/ovh-dedicated-reinstall/backend.hcl.example \
  infra/terraform/ovh-dedicated-reinstall/backend.hcl
```

Initialize the main stack against Azure Blob Storage:

```bash
cd infra/terraform/ovh-dedicated-reinstall
terraform init -reconfigure -backend-config=backend.hcl
```

The backend uses Azure CLI authentication with Microsoft Entra ID.

## Step 4: Plan and apply

```bash
cd infra/terraform/ovh-dedicated-reinstall
terraform plan
terraform apply
```

## GitHub Actions

Manual workflow:

- [run-ovh-terraform-reinstall.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-ovh-terraform-reinstall.yml)

Reusable workflow:

- [reusable-ovh-terraform-reinstall.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/reusable-ovh-terraform-reinstall.yml)

The manual workflow supports:

- `plan`
- `apply`

Required GitHub repository or environment secrets:

- `AZURE_CLIENT_ID`
- `OVH_APPLICATION_KEY`
- `OVH_APPLICATION_SECRET`
- `OVH_CONSUMER_KEY`

Required GitHub repository or environment variables:

- `AZURE_SUBSCRIPTION_ID`
- `AZURE_TENANT_ID`
- `AZURE_RESOURCE_GROUP_NAME`
- `AZURE_STORAGE_ACCOUNT_NAME`
- `AZURE_TERRAFORM_STATE_CONTAINER_NAME`
- `AZURE_KEY_VAULT_NAME`

Optional GitHub repository or environment variables:

- `OVH_TERRAFORM_STATE_KEY`
- `OVH_SSH_PRIVATE_KEY_SECRET_NAME`
- `OVH_SSH_PRIVATE_KEY_PATH`

Workflow behavior:

- logs into Azure using OIDC through `AZURE_CLIENT_ID`
- restores the SSH private key from Key Vault when the secret already exists
- generates `backend.hcl` on the runner
- uses `infra/terraform/ovh-dedicated-reinstall/terraform.dev.tfvars` by default in GitHub Actions
- falls back to that tracked dev file when a custom `tfvars_file` input does not exist in the repository checkout
- runs `terraform init`, `terraform validate`, then `terraform plan`
- runs `terraform apply` only when you dispatch the workflow with `operation=apply`

## SSH key behavior

On the first run, Terraform generates the SSH key locally on your Mac before planning the OVH reinstall task.

Local key path:

- `~/.ssh/ovh-rag-reinstall-ed25519`
- `~/.ssh/ovh-rag-reinstall-ed25519.pub`

If you need to restore the private key from Key Vault onto another Mac:

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

Then connect with:

```bash
ssh -i ~/.ssh/ovh-rag-reinstall-ed25519 ubuntu@193.70.35.121
```

## Important behavior

- This is destructive. It reinstalls the operating system on the existing OVH dedicated servers.
- It does not create new servers.
- The OVH resource is task-based. A change to the task arguments can produce a new reinstall task.
- The private key is not written into Terraform state because it is pushed to Key Vault through a write-only argument.

## Partitioning

The partition layout follows the cluster README intent:

- `/boot`: `1 GB`
- `/`: `35 GB`
- `/var`: `20 GB`
- `swap`: `4 GB`
- `/data`: remaining space

`/boot/efi` is still not modeled explicitly in this stack. If OVH requires a dedicated EFI partition for this template on your hardware, adjust the partition layout after validating the accepted mount points and filesystem values for the reinstall task.

## Sources

- OVH cluster inventory and disk layout: [infra/ovh/CLUSTER_README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ovh/CLUSTER_README.md)
- OVH provider resource docs: `ovh_dedicated_server_reinstall_task`
- OVH provider dedicated server docs: `ovh_dedicated_server`
