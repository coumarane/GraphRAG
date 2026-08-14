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
- Kubernetes cluster installed successfully on the three OVH servers with Ansible
- Cilium CNI installed and cluster node health validated
- Kubernetes add-ons bootstrap completed successfully:
  - MetalLB
  - cert-manager
  - Envoy Gateway
  - Prometheus + Grafana
  - Argo CD core
- Argo CD app bootstrap separated from cluster add-ons bootstrap into its own workflow
- Cloudflare DNS records for `chatwithdocs.org` and related subdomains prepared and aligned with `infra/cloudfare/dns_records.json`

## Current infrastructure state

OVH servers targeted by the reinstall workflow:

- `rag-master` -> `193.70.35.121` -> `ns3063017.ip-193-70-35.eu`
- `rag-worker-1` -> `193.70.35.122` -> `ns3063022.ip-193-70-35.eu`
- `rag-worker-2` -> `145.239.68.200` -> `ns3086111.ip-145-239-68.eu`

Shared SSH key:

- private key secret in Key Vault: `ovh-rag-reinstall-ssh-private-key`
- public key secret in Key Vault: `ovh-rag-reinstall-ssh-public-key`
- local restore path used on Mac: `~/.ssh/ovh-rag-reinstall-ed25519`

Kubernetes cluster:

- control plane: `rag-master`
- workers:
  - `rag-worker-1`
  - `rag-worker-2`
- kubeconfig restored locally on Mac and cluster access validated

Platform ingress and TLS:

- Envoy Gateway is the intended ingress layer
- cert-manager uses Cloudflare DNS-01 for `chatwithdocs.org`
- shared Gateway listeners are prepared for:
  - `chatwithdocs.org`
  - `api.chatwithdocs.org`
  - `argocd.chatwithdocs.org`
  - `prometheus.chatwithdocs.org`

Cloudflare DNS state:

- `chatwithdocs.org` -> `51.38.19.54` proxied
- `www.chatwithdocs.org` -> `51.38.19.54` proxied
- `api.chatwithdocs.org` -> `51.38.19.54` proxied
- `argocd.chatwithdocs.org` -> `51.38.19.54` proxied
- `prometheus.chatwithdocs.org` -> `51.38.19.54` proxied
- `database.chatwithdocs.org` -> `167.86.88.114` DNS only
- `harbor.chatwithdocs.org` -> `62.84.180.181` DNS only

## Important implementation decisions

- GitHub workflow uses tracked file `infra/terraform/ovh-dedicated-reinstall/terraform.dev.tfvars`
- local-only Terraform overrides use ignored file `infra/terraform/ovh-dedicated-reinstall/terraform.local.tfvars`
- OVH reinstall template name is `ubuntu2604-server_64`
- OVH template does not accept the `language` customization for this OS, so that field was removed
- ingress-nginx was removed from the repository and replaced with Envoy Gateway + Gateway API resources
- Grafana bootstrap no longer requires OIDC and defaults to login form + admin password
- Argo CD bootstrap no longer requires OIDC and uses core install separately from application registration
- Argo CD `Application` objects are now deployed through dedicated workflow `.github/workflows/run-argocd-apps-bootstrap.yml`

## Relevant files

- [infra/github/README_OVH.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/README_OVH.md)
- [infra/github/oidc/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/README.md)
- [infra/github/manage_github_actions_config.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/manage_github_actions_config.py)
- [infra/github/oidc/create_github_oidc_app_registration.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/create_github_oidc_app_registration.py)
- [infra/github/oidc/assign_azure_roles.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/github/oidc/assign_azure_roles.py)
- [infra/terraform/ovh-dedicated-reinstall/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/README.md)
- [.github/workflows/run-ovh-terraform-reinstall.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-ovh-terraform-reinstall.yml)
- [.github/workflows/reusable-ovh-terraform-reinstall.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/reusable-ovh-terraform-reinstall.yml)
- [infra/ansible/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/README.md)
- [.github/workflows/run-kubernetes-cluster-deploy.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-kubernetes-cluster-deploy.yml)
- [.github/workflows/run-k8s-addons-bootstrap.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-k8s-addons-bootstrap.yml)
- [.github/workflows/run-argocd-apps-bootstrap.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-argocd-apps-bootstrap.yml)
- [infra/cloudfare/CLOUDFARE_README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/cloudfare/CLOUDFARE_README.md)
- [infra/cloudfare/dns_records.json](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/cloudfare/dns_records.json)

## Next step

Deploy a small test application on the OVH Kubernetes cluster, expose it through Envoy Gateway on `chatwithdocs.org`, and validate end-to-end DNS, TLS, routing, and external access using the Cloudflare records already prepared in `infra/cloudfare`.
