# Harbor Setup

This folder documents the Harbor registry used by the OVH Kubernetes platform.

Current live registry:

- URL: `https://harbor.safranys.com`
- Harbor UI: `https://harbor.safranys.com/harbor/projects`
- Current server IP: `62.84.180.181`

## DNS

Harbor currently uses direct DNS resolution through Cloudflare with proxy disabled.

- record: `harbor.safranys.com`
- type: `A`
- target: `62.84.180.181`
- proxy mode: `DNS only`

Reference screenshot:

- [cloudfare_harbor_dns_records.png](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/harbor/assets/cloudfare_harbor_dns_records.png)

## Project

Create a Harbor project for the application images:

- project name: `chatwithdocs`
- visibility: `private`

Expected image paths:

- `harbor.safranys.com/chatwithdocs/api:<tag>`
- `harbor.safranys.com/chatwithdocs/web:<tag>`
- `harbor.safranys.com/chatwithdocs/worker:<tag>`

## Robot Account

Use a robot account dedicated to GitHub Actions image push and pull.

Recommended values:

- name: `github-actions-chatwithdocs`
- description: `CI robot for chatwithdocs image push/pull`
- expiration: `Never`

Important:

- use the exact Harbor-generated robot username when logging in
- do not use only the short display name
- Harbor typically generates a username such as `robot$github-actions-chatwithdocs`

Robot account creation screenshots:

- [robot_account_basic_infos.png](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/harbor/assets/robot_account_basic_infos.png)
- [robot_account_basic_sys_permissions.png](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/harbor/assets/robot_account_basic_sys_permissions.png)
- [robot_account_project_permission.png](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/harbor/assets/robot_account_project_permission.png)
- [robot_account_creation_result.png](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/harbor/assets/robot_account_creation_result.png)

### System permissions

For this CI use case, leave system permissions empty.

### Project permissions

For project `chatwithdocs`, grant only the minimum required permissions:

- `Project` -> `Read`
- `Repository` -> `Pull`, `Push`
- `Artifact` -> `Read`
- `Tag` -> `List`

Do not grant:

- any `Delete`
- `Project Member`
- `Robot Account`
- `Quota`
- `Tag Retention`
- `Immutable Tag`
- `Scanner`
- `Scan`
- `Notification Policy`
- `Preheat Policy`

If a workflow later needs more access, extend permissions incrementally instead of making the robot broadly privileged.

## GitHub Secrets

After creating the robot account, copy the generated credentials immediately and store them as repository or environment secrets:

- `HARBOR_REGISTRY_USERNAME`
- `HARBOR_REGISTRY_PASSWORD`

Use the exact Harbor-generated robot username for `HARBOR_REGISTRY_USERNAME`.

## Local Login Test

Validate the credentials from your Mac:

```bash
docker login harbor.safranys.com
```

Then enter:

- username: exact Harbor-generated robot username, for example `robot$github-actions-chatwithdocs`
- password: the generated robot secret

If login succeeds, Docker prints:

```text
Login Succeeded
```

## Security Notes

- the generated robot secret is shown only once by Harbor
- if you lose the secret, create a new robot secret or recreate the robot account
- do not commit exported robot credential files to Git
- `infra/harbor/robot$github-actions-chatwithdocs.json` is a sensitive local file and should remain untracked

## Next Step

Once Harbor credentials are validated:

1. store `HARBOR_REGISTRY_USERNAME` and `HARBOR_REGISTRY_PASSWORD` in GitHub
2. review the image build workflows to push `api`, `web`, and later `worker` images to `harbor.safranys.com/chatwithdocs`
3. configure Kubernetes image pull access for the same Harbor project
