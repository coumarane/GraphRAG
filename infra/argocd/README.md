# Argo CD Application Delivery

## Target model

API and web are now intended to be delivered through Argo CD, not through the SSH-based Kubernetes deploy workflows.

Normal deploy path:

1. `Build And Push API Image` or `Build And Push Web Image`
2. the build workflow commits the new immutable image digest into:
   - `infra/k8s/api/kustomization.yaml`
   - `infra/k8s/web/kustomization.yaml`
3. Argo CD detects the Git change on branch `dev`
4. Argo CD syncs the updated manifests into the OVH cluster

## One-time bootstrap

Before Argo CD can reconcile the applications, the target namespaces and bootstrap secrets must already exist.

Run these workflows in order:

1. `Run K8s Add-ons Bootstrap`
   This must already have installed:
   - Argo CD
   - Secrets Store CSI Driver
   - Azure Key Vault provider

2. `Run App Namespaces And Secrets Bootstrap`
   This creates:
   - namespace `chatwithdocs-api`
   - namespace `chatwithdocs-web`
   - secret `harbor-regcred` in both namespaces
   - secret `secrets-store-creds` in both namespaces

3. `Run Argo CD Apps Bootstrap`
   This applies the `Application` objects from `infra/argocd/apps`.

## Managed applications

- `chatwithdocs-api` -> `infra/k8s/api`
- `chatwithdocs-web` -> `infra/k8s/web`

The repository tracked by Argo CD is:

- `https://github.com/coumarane/GraphRAG.git`
- branch `dev`

## Emergency manual deploy workflows

These workflows still exist, but they are no longer the normal path:

- `Run API Kubernetes Deploy`
- `Run Web Kubernetes Deploy`

They now require explicit acknowledgement that Argo CD is being bypassed and should only be used for emergency/manual recovery.
