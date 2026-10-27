# No separate staging environment

Feature 001 uses the existing DEV pipeline. The proposed namespace `chatwithdocs-staging`, the hosts `staging.chatwithdocs.org` and `staging-api.chatwithdocs.org`, and a separate database or bucket are not part of the deployment.

The OVH cluster already serves the DEV web origin `https://chatwithdocs.org` and the API origin `https://api.chatwithdocs.org`. Argo CD applications `chatwithdocs-api`, `chatwithdocs-worker`, and `chatwithdocs-web` track branch `dev`. The deploy order, image digests, migration `0013`, and CORS step are in [rollout.md](rollout.md).

Browser CORS for that web origin is prepared in `infra/dev/minio-cors.dev.json` and `infra/dev/azure-blob-cors.dev.json`. Apply the file that matches the DEV `OBJECT_STORE_BACKEND` secret. Do not create a second storage account or bucket for this feature.
