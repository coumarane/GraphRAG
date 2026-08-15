# Chatwithdocs web deployment (Kubernetes)

Minimal Kubernetes manifests to run the web container that is built and pushed to Harbor by `.github/workflows/build-and-push-web-image.yml`.

## Prerequisites
- cert-manager + `letsencrypt-prod` ClusterIssuer installed (see `infra/helm/cert-manager`).
- Envoy Gateway present with the shared `public-gateway` Gateway installed by the bootstrap workflow.
- Harbor image already pushed, e.g. `harbor.safranys.com/chatwithdocs/web:<tag>`.
- Harbor pull credentials available.

## Configure
1) By default the build workflow commits the image digest into `infra/k8s/web/kustomization.yaml`.
2) If you want to override that manually for a one-off deploy, set `newTag` for the Harbor image or use `.github/workflows/run-web-kubernetes-deploy.yml` with `image_tag`.
3) Adjust the route host in `infra/k8s/web/httproute.yaml` (`chatwithdocs.org`) to your domain.
4) If you need a different API URL at build time, set the appropriate frontend environment values before building the image.

## Deploy
```bash
# 1) Create namespace (needed before the pull secret)
kubectl apply -f infra/k8s/web/namespace.yaml

# 2) Create/refresh Harbor imagePullSecret (fills harbor-regcred referenced by the Deployment)
kubectl -n chatwithdocs-web create secret docker-registry harbor-regcred \
  --docker-server=harbor.safranys.com \
  --docker-username=$HARBOR_USERNAME \
  --docker-password=$HARBOR_PASSWORD \
  --docker-email=devnull@example.com \
  --dry-run=client -o yaml | kubectl apply -f -

# 3) Deploy the app
kubectl apply -k infra/k8s/web

# 4) Wait for rollout and check route/TLS
kubectl -n chatwithdocs-web rollout status deploy/web --timeout=180s
kubectl -n chatwithdocs-web get httproute
```
