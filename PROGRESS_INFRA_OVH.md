# Infra Progress: OVH Cluster Bootstrap

Last updated: 2026-08-15

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
- Smoke test application deployed successfully and validated through `https://chatwithdocs.org`
- Public ingress validation completed successfully using the master public IP `193.70.35.121`
- Dedicated public ingress workflow created for OVH-friendly exposure of Envoy Gateway through HAProxy on `rag-master`
- Harbor deployment workflow stabilized and Harbor access validated through `https://harbor.safranys.com/harbor/projects`
- Harbor-backed smoke image push and Kubernetes pull path validated successfully through `https://chatwithdocs.org`
- Real `chatwithdocs` API and web images built, pushed to Harbor, and deployed on the OVH Kubernetes cluster

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
- application namespaces deployed:
  - `chatwithdocs-api`
  - `chatwithdocs-web`
  - `chatwithdocs-smoke`

Platform ingress and TLS:

- Envoy Gateway is the intended ingress layer
- cert-manager uses Cloudflare DNS-01 for `chatwithdocs.org`
- shared Gateway listeners are prepared for:
  - `chatwithdocs.org`
  - `api.chatwithdocs.org`
  - `argocd.chatwithdocs.org`
  - `prometheus.chatwithdocs.org`
- public HTTPS validation currently uses `193.70.35.121` on `rag-master`
- HAProxy on `rag-master` forwards public `443` to the Envoy Gateway NodePort
- the OVH Additional IP `51.38.19.54` remains a later networking task and is not the active validated ingress path yet
- production hostname `chatwithdocs.org` is now routed to the real web application
- smoke route was moved off the production hostname to avoid `HTTPRoute` conflicts

Cloudflare DNS state:

- `chatwithdocs.org` -> `193.70.35.121` proxied
- `www.chatwithdocs.org` -> `193.70.35.121` proxied
- `api.chatwithdocs.org` -> `193.70.35.121` proxied
- `argocd.chatwithdocs.org` -> `193.70.35.121` proxied
- `prometheus.chatwithdocs.org` -> `193.70.35.121` proxied
- `database.chatwithdocs.org` -> `167.86.88.114` DNS only
- `harbor.safranys.com` -> `62.84.180.181` DNS only

Harbor state:

- Harbor host: `harbor.safranys.com`
- Harbor server IP: `62.84.180.181`
- Harbor is reachable over HTTPS with a valid public certificate
- Harbor deployment is managed through the Ansible workflow `.github/workflows/run-harbor-deploy.yml`
- Harbor robot account credentials are validated for Docker login
- GitHub Actions can push the smoke image to Harbor
- Kubernetes can pull the smoke image from Harbor using namespace secret `harbor-regcred`
- GitHub Actions can also push the real `api` and `web` images to Harbor
- Kubernetes can pull the real `api` and `web` images from Harbor using namespace secret `harbor-regcred`

Application deployment state:

- web application is deployed in namespace `chatwithdocs-web`
- API application is deployed in namespace `chatwithdocs-api`
- API Kubernetes health probes were corrected to the mounted FastAPI paths:
  - `/api/v1/health/live`
  - `/api/v1/health/ready`
- authentication bootstrap is not configured yet, so no initial application admin account exists at this stage

## Important implementation decisions

- GitHub workflow uses tracked file `infra/terraform/ovh-dedicated-reinstall/terraform.dev.tfvars`
- local-only Terraform overrides use ignored file `infra/terraform/ovh-dedicated-reinstall/terraform.local.tfvars`
- OVH reinstall template name is `ubuntu2604-server_64`
- OVH template does not accept the `language` customization for this OS, so that field was removed
- ingress-nginx was removed from the repository and replaced with Envoy Gateway + Gateway API resources
- Grafana bootstrap no longer requires OIDC and defaults to login form + admin password
- Argo CD bootstrap no longer requires OIDC and uses core install separately from application registration
- Argo CD `Application` objects are now deployed through dedicated workflow `.github/workflows/run-argocd-apps-bootstrap.yml`
- the initial MetalLB-based public ingress design was not suitable for the OVH Additional IP `/32` validation path
- the validated public ingress path now uses:
  - Envoy Gateway inside Kubernetes
  - a dedicated `EnvoyProxy` with `NodePort` exposure
  - HAProxy on `rag-master` for public `443`
  - temporary Cloudflare DNS targeting `193.70.35.121`
- Harbor Ansible check mode now exits before installer/certbot operations because the Harbor online installer workflow is not meaningfully dry-runnable
- reusable Ansible GitHub workflows now pass secrets through `secrets:` instead of embedding them in `with.extra_vars`
- Harbor robot usernames can contain `$`, so Harbor login handling and remote deploy secret passing were adjusted to avoid shell expansion issues
- the smoke deployment path is now Harbor-backed and validates:
  - GitHub Actions push to Harbor
  - Kubernetes pull from Harbor
  - public HTTPS routing on `chatwithdocs.org`
- the real application deployment path is now Harbor-backed and validates:
  - GitHub Actions push for `api` and `web`
  - Kubernetes pull for `api` and `web`
  - public routing of `chatwithdocs.org` to the real web service
  - public routing of `api.chatwithdocs.org` to the real API service

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
- [.github/workflows/run-kubernetes-public-ingress-deploy.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-kubernetes-public-ingress-deploy.yml)
- [.github/workflows/run-argocd-apps-bootstrap.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-argocd-apps-bootstrap.yml)
- [.github/workflows/run-harbor-deploy.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-harbor-deploy.yml)
- [.github/workflows/build-and-push-smoke-web-image.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/build-and-push-smoke-web-image.yml)
- [.github/workflows/run-smoke-web-deploy.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-smoke-web-deploy.yml)
- [.github/workflows/build-and-push-api-image.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/build-and-push-api-image.yml)
- [.github/workflows/build-and-push-web-image.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/build-and-push-web-image.yml)
- [.github/workflows/run-api-kubernetes-deploy.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-api-kubernetes-deploy.yml)
- [.github/workflows/run-web-kubernetes-deploy.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-web-kubernetes-deploy.yml)
- [infra/cloudfare/CLOUDFARE_README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/cloudfare/CLOUDFARE_README.md)
- [infra/cloudfare/dns_records.json](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/cloudfare/dns_records.json)
- [infra/ansible/harbor/playbook.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/harbor/playbook.yml)
- [infra/ansible/kubernetes/public_ingress_playbook.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/kubernetes/public_ingress_playbook.yml)
- [infra/k8s/gateway/envoyproxy-public-gateway.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/gateway/envoyproxy-public-gateway.yaml)
- [infra/k8s/smoke-web/kustomization.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/smoke-web/kustomization.yaml)
- [infra/k8s/api/deployment.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/api/deployment.yaml)
- [infra/k8s/web/deployment.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/web/deployment.yaml)

## Next step

Configure authentication bootstrap for the first application admin account, store the related secrets securely, then validate end-user login on the deployed `chatwithdocs` web application.
