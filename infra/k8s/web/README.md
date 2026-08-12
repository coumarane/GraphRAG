# Chatwithdocs web deployment (Kubernetes)

Minimal Kubernetes manifests to run the web container that is built and pushed to Harbor by `.github/workflows/build-web-image.yml`.

## Prerequisites
- cert-manager + `letsencrypt-prod` ClusterIssuer installed (see `infra/helm/cert-manager`).
- ingress-nginx present (bootstrap workflow installs it).
- Harbor image already pushed, e.g. `harbor.chatwithdocs.org/chatwithdocs/web:<tag>`.
- Harbor pull credentials available.

## Configure
1) Set the image tag in `infra/k8s/web/kustomization.yaml` (`newTag`) to the Harbor tag you want to deploy (defaults to `latest`).  
2) Adjust the ingress host in `infra/k8s/web/ingress.yaml` (`web.chatwithdocs.org`) to your domain.  
3) If you need a different API URL at build time, set `inputs.image_tag` and the `NEXT_PUBLIC_API_URL` secret/var when running the GitHub Actions build so the baked image has the right URL.

## Deploy
```bash
# 1) Create namespace (needed before the pull secret)
kubectl apply -f infra/k8s/web/namespace.yaml

# 2) Create/refresh Harbor imagePullSecret (fills harbor-regcred referenced by the Deployment)
kubectl -n chatwithdocs-web create secret docker-registry harbor-regcred \
  --docker-server=harbor.chatwithdocs.org \
  --docker-username=$HARBOR_USERNAME \
  --docker-password=$HARBOR_PASSWORD \
  --docker-email=devnull@example.com \
  --dry-run=client -o yaml | kubectl apply -f -

# 3) Deploy the app
kubectl apply -k infra/k8s/web

# 4) Wait for rollout and check ingress/TLS
kubectl -n chatwithdocs-web rollout status deploy/web --timeout=180s
kubectl -n chatwithdocs-web get ingress
```
