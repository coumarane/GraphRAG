# Infra Progress: OVH Cluster Bootstrap

Last updated: 2026-08-14

## Scope completed

- Azure GitHub Actions OIDC app registration created for repository `coumarane/GraphRAG`
- GitHub Actions federated credential aligned with the repository's immutable OIDC subject format
- Azure RBAC model documented for:
  - GitHub workflow access
  - human access to Key Vault secrets with `Key Vault Secrets User`
- OVH API token created for the Terraform workflow
- GitHub Actions secrets and variables prepared from `infra/github/actions-config.dev.json`
- OVH Terraform workflow created and executed from GitHub Actions
- Azure Blob backend used for Terraform state
- shared SSH private key generated and stored in Azure Key Vault
- SSH connectivity validated from local Mac to all three OVH servers with the shared key

## Current infrastructure state

OVH servers targeted by the reinstall workflow:

- `rag-master` -> `193.70.35.121` -> `ns3063017.ip-193-70-35.eu`
- `rag-worker-1` -> `193.70.35.122` -> `ns3063022.ip-193-70-35.eu`
- `rag-worker-2` -> `145.239.68.200` -> `ns3086111.ip-145-239-68.eu`

Shared SSH key:

- private key secret in Key Vault: `ovh-rag-reinstall-ssh-private-key`
- public key secret in Key Vault: `ovh-rag-reinstall-ssh-public-key`
- local restore path used on Mac: `~/.ssh/ovh-rag-reinstall-ed25519`

## Important implementation decisions

- GitHub workflow uses tracked file `infra/terraform/ovh-dedicated-reinstall/terraform.dev.tfvars`
- local-only Terraform overrides use ignored file `infra/terraform/ovh-dedicated-reinstall/terraform.local.tfvars`
- OVH reinstall template name is `ubuntu2604-server_64`
- OVH template does not accept the `language` customization for this OS, so that field was removed

## Relevant files

- [infra/github/README_OVH.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/README_OVH.md)
- [infra/github/oidc/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/README.md)
- [infra/github/manage_github_actions_config.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/manage_github_actions_config.py)
- [infra/github/oidc/create_github_oidc_app_registration.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/create_github_oidc_app_registration.py)
- [infra/github/oidc/assign_azure_roles.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/assign_azure_roles.py)
- [infra/terraform/ovh-dedicated-reinstall/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/README.md)
- [.github/workflows/run-ovh-terraform-reinstall.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-ovh-terraform-reinstall.yml)
- [.github/workflows/reusable-ovh-terraform-reinstall.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/reusable-ovh-terraform-reinstall.yml)

## Next step

Proceed with the next infrastructure bootstrap phase on the three provisioned OVH servers, using the shared SSH key from Azure Key Vault and the Ansible/GitHub workflow setup already prepared in this repository.
