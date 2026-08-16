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
- Azure Key Vault env sync tooling created for application configuration secrets
- Azure RBAC helper created to grant `Key Vault Secrets Officer` on app Key Vaults
- Azure env sync documentation added for API and web app secret management
- Azure Terraform stack created and executed for application object storage
- dedicated Azure Storage account deployed successfully for application document storage
- Azure Key Vault CSI-based secret mount pattern added for Kubernetes API and web deployments
- Kubernetes add-ons workflow extended to install Secrets Store CSI Driver + Azure Key Vault provider
- API and web deploy workflows extended to provision namespace-level CSI auth secret for Key Vault access
- API runtime extended to support Azure Blob as an object-store backend while preserving MinIO for local development
- Kubernetes API secret mount updated to project Azure Blob configuration from Key Vault
- API and web deploy workflows hardened to prefer committed image digests and block unsafe `latest` overrides
- Harbor image build path adjusted so Azure SDK dependencies are installed in runtime images despite the current `uv.lock` resolver conflict
- Dedicated PostgreSQL host deployment path moved back to `database.safranys.com` on `167.86.88.114`
- PostgreSQL GitHub workflow updated to support destructive rebuild from scratch
- PostgreSQL Ansible role refactored for rebuild support, lint-safe variable naming, and explicit restart handling
- PostgreSQL bootstrap path migrated to direct `psql` commands for app database and role setup
- Database migrations workflow fixed to target `database.safranys.com` by default
- Database migrations executed successfully against the dedicated PostgreSQL host
- Kubernetes add-ons workflow extended to install in-cluster data services for application dependencies:
  - Redis
  - Qdrant
  - Neo4j
- MinIO is intentionally deferred pending the final storage decision between Azure Storage and S3-compatible object storage
- local-path provisioner added and validated for PVC-backed in-cluster services
- Browser login path validated successfully through `https://chatwithdocs.org` with the bootstrap admin account

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
  - `redis`
  - `qdrant`
  - `neo4j`

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
- `database.safranys.com` -> `167.86.88.114` DNS only
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
- API deployment rollout is healthy after successful schema migration
- web deployment rollout is healthy after loading mounted runtime env before Next.js startup
- API Kubernetes health probes were corrected to the mounted FastAPI paths:
  - `/api/v1/health/live`
  - `/api/v1/health/ready`
- authentication bootstrap is configured and validated
- bootstrap admin login validated with:
  - `AUTH_BOOTSTRAP_EMAIL=admin@chatwithdocs.com`
  - `AUTH_BOOTSTRAP_PASSWORD` from synced production secrets
- API and web redeploy are now intended to target the dedicated PostgreSQL host instead of any in-cluster database path
- in-cluster dependency services are now deployed before the next API/web redeploy:
  - Redis for cache/session-style needs
  - Qdrant for vector search
  - Neo4j for graph storage
- these three services are deployed as internal-only `ClusterIP` services
- public DNS names for those backends should not be exposed unless there is a later explicit operational need
- current internal service endpoints prepared for the API env:
  - Redis: `redis://redis-master.redis.svc.cluster.local:6379/0`
  - Qdrant: `http://qdrant.qdrant.svc.cluster.local:6333`
  - Neo4j: `bolt://neo4j.neo4j.svc.cluster.local:7687`

Dedicated PostgreSQL state:

- dedicated PostgreSQL host target: `database.safranys.com`
- resolved server IP: `167.86.88.114`
- PostgreSQL is intentionally kept outside the OVH Kubernetes cluster
- workflow `.github/workflows/run-postgresql-deploy.yml` now supports:
  - `target_host=database.safranys.com`
  - `postgres_version=18`
  - `postgres_rebuild=true` for destructive reinstall
- pgAdmin is now disabled by default and must be explicitly enabled with credentials
- PostgreSQL stabilization fixes applied on Saturday, August 15, 2026:
  - destructive rebuild option
  - default target host switch to `database.safranys.com`
  - database migrations workflow host switch to `database.safranys.com`
  - role variable prefix cleanup for ansible-lint
  - missing PostgreSQL restart handler
  - explicit `psql` bootstrap path using `argv`
- current status:
  - host connectivity and package installation are working
  - schema migration path is validated through `.github/workflows/run-database-migrations.yml`
  - API startup now succeeds against the migrated database schema

Azure application secrets state:

- dedicated Key Vault created for API app secrets:
  - `graphrag-kv-api`
- dedicated Key Vault created for web app secrets:
  - `graphrag-kv-web`
- production env source files prepared locally:
  - `.env.production`
  - `frontend/.env.production`
- generic dotenv-to-Key Vault sync script is ready:
  - `infra/azure/manage_keyvault_app_env.py`
- Key Vault RBAC assignment helper is ready:
  - `infra/azure/assign_keyvault_role.py`
- Azure application object storage state:
  - dedicated Storage account deployed for GraphRAG documents
  - current deployed account name: `graphragdocsdevbmo9`
  - current intended primary container for the API: `documents`
  - object-store backend split is now:
    - local development -> MinIO
    - OVH cluster production -> Azure Blob Storage
- local env sync path is now working once the operator has the required Key Vault RBAC
- Kubernetes runtime secret consumption design is now prepared:
  - Azure Key Vault secrets mounted into pods through Secrets Store CSI Driver
  - `initContainer` generates `/app/.env` into a shared `emptyDir`
  - main container starts only after `.env` exists
- current operational note:
  - Azure Blob runtime rollout required API image rebuild and redeploy because the original image did not include the Azure SDK
  - the build/deploy workflow path is now corrected to avoid digest drift during redeploys

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
- the web server-side auth proxy now explicitly sources `/app/.env` before starting Next.js so `RAG_API_URL` is honored at runtime
- stateful in-cluster application dependencies now use:
  - Rancher `local-path-provisioner`
  - explicit `local-path` PVC binding in Redis, Qdrant, and Neo4j Helm values
- application runtime secrets are no longer intended to be modeled through hardcoded per-app JSON examples
- application secrets source of truth is now the local production dotenv files synced to Azure Key Vault
- PostgreSQL remains a dedicated-host service for this environment:
  - easier lifecycle separation from the Kubernetes cluster
  - simpler future host migration via DNS update
  - avoids treating PostgreSQL as a temporary in-cluster workload
- Azure Key Vault env sync supports:
  - sync from any dotenv file to any Key Vault
  - optional scoped cleanup of managed secrets with `--delete-missing`
  - explicit RBAC assignment helper for `Key Vault Secrets Officer`
- application object storage strategy is now intentionally split by environment:
  - local development keeps MinIO for fast iterative work
  - OVH cluster production targets Azure Blob Storage
- Azure Blob support was added in application runtime code instead of trying to force MinIO semantics into production infrastructure
- Harbor/Kubernetes deploy workflows now protect the GitOps path by requiring committed digests when no manual tag is provided and by refusing `latest`
- Kubernetes app runtime secret delivery now targets:
  - Secrets Store CSI Driver
  - Azure Key Vault provider
  - `SecretProviderClass` per namespace
  - `initContainer`-rendered `.env` files instead of ConfigMap-based app config

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
- [.github/workflows/run-postgresql-deploy.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-postgresql-deploy.yml)
- [infra/cloudfare/CLOUDFARE_README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/cloudfare/CLOUDFARE_README.md)
- [infra/cloudfare/dns_records.json](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/cloudfare/dns_records.json)
- [infra/azure/README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/azure/README.md)
- [infra/azure/manage_keyvault_app_env.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/azure/manage_keyvault_app_env.py)
- [infra/azure/assign_keyvault_role.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/azure/assign_keyvault_role.py)
- [infra/k8s/api/secretproviderclass.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/api/secretproviderclass.yaml)
- [infra/k8s/web/secretproviderclass.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/web/secretproviderclass.yaml)
- [infra/ansible/harbor/playbook.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/harbor/playbook.yml)
- [infra/ansible/kubernetes/public_ingress_playbook.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/ansible/kubernetes/public_ingress_playbook.yml)
- [infra/k8s/gateway/envoyproxy-public-gateway.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/gateway/envoyproxy-public-gateway.yaml)
- [infra/k8s/smoke-web/kustomization.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/smoke-web/kustomization.yaml)
- [infra/k8s/api/deployment.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/api/deployment.yaml)
- [infra/k8s/web/deployment.yaml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/k8s/web/deployment.yaml)
- [.github/workflows/run-k8s-addons-bootstrap.yml](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/workflows/run-k8s-addons-bootstrap.yml)

## Next step

Prepare the next application services and operational capabilities on top of the now-working platform baseline:
- worker deployment and background processing validation
- remaining app infrastructure dependencies such as object storage decision
- Argo CD application management for non-smoke workloads
