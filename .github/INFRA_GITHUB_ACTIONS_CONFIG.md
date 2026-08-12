# Infra GitHub Actions Config Management

This folder contains automation for managing the GitHub Actions configuration used by the infrastructure and deployment workflows.

## Script

- [manage_github_actions_config.py](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/manage_github_actions_config.py): create, update, delete, list, or batch-apply GitHub Actions secrets and variables.

The script manages:

- Environment secrets
- Repository secrets
- Environment variables
- Repository variables

It is designed around the current infrastructure workflows in `.github/workflows/` and `infra/ansible/`.

## Prerequisites

- GitHub CLI installed: `gh`
- Authenticated GitHub CLI session:

```bash
gh auth login
```

- Repository access to the target repo

The script uses the GitHub CLI for writes, so it does not require a separate API token if `gh` is already authenticated.

## Repository selection

By default, the script reads the repository from `GITHUB_REPOSITORY`.

You can also pass it explicitly:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo catalog
```

## Show the built-in catalog

The catalog reflects the entries currently used by the Ansible and deployment workflows.

Table output:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo catalog
```

JSON output:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo catalog --format json
```

## Generate a JSON template

Generate a batch-apply template for an environment such as `dev`:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo template --environment dev > .github/actions-config.dev.json
```

A committed example template for `dev` is also available:

- [actions-config.dev.example.json](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/.github/actions-config.dev.example.json)

## List existing entries

List environment secrets:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo list --scope env-secret --environment dev
```

List environment variables:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo list --scope env-var --environment dev
```

List repository secrets:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo list --scope repo-secret
```

List repository variables:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo list --scope repo-var
```

## Create or update one entry

Set an environment secret from a literal value:

```bash
python3 .github/manage_github_actions_config.py \
  --repo owner/repo \
  set \
  --scope env-secret \
  --environment dev \
  --name HARBOR_REGISTRY_USERNAME \
  --value my-user
```

Set an environment secret from a file:

```bash
python3 .github/manage_github_actions_config.py \
  --repo owner/repo \
  set \
  --scope env-secret \
  --environment dev \
  --name K8S_MASTER_SSH_PRIVATE_KEY \
  --value-file ~/.ssh/id_ed25519
```

Set an environment variable:

```bash
python3 .github/manage_github_actions_config.py \
  --repo owner/repo \
  set \
  --scope env-var \
  --environment dev \
  --name REGISTRY_HOST \
  --value harbor.chatwithdocs.org
```

Set a repository variable:

```bash
python3 .github/manage_github_actions_config.py \
  --repo owner/repo \
  set \
  --scope repo-var \
  --name DEFAULT_ENVIRONMENT \
  --value dev
```

## Delete one entry

Delete an environment secret:

```bash
python3 .github/manage_github_actions_config.py \
  --repo owner/repo \
  delete \
  --scope env-secret \
  --environment dev \
  --name K8S_WORKER_SSH_PRIVATE_KEY
```

Delete a repository variable:

```bash
python3 .github/manage_github_actions_config.py \
  --repo owner/repo \
  delete \
  --scope repo-var \
  --name DEFAULT_ENVIRONMENT
```

## Batch apply from JSON

Create a template:

```bash
python3 .github/manage_github_actions_config.py --repo owner/repo template --environment dev > .github/actions-config.dev.json
```

Fill the `value` fields, then apply:

```bash
python3 .github/manage_github_actions_config.py \
  --repo owner/repo \
  apply \
  --file .github/actions-config.dev.json
```

To delete an entry during batch apply, set:

```json
{
  "name": "DEFAULT_ENVIRONMENT",
  "scope": "repo-var",
  "environment": null,
  "delete": true
}
```

## JSON file format

```json
{
  "entries": [
    {
      "name": "HARBOR_REGISTRY_USERNAME",
      "scope": "env-secret",
      "environment": "dev",
      "value": "my-user"
    },
    {
      "name": "DEFAULT_ENVIRONMENT",
      "scope": "repo-var",
      "environment": null,
      "value": "dev"
    }
  ]
}
```

Supported scopes:

- `env-secret`
- `repo-secret`
- `env-var`
- `repo-var`

## Notes

- The script does not guess values. It only manages entries.
- The built-in catalog is derived from the current Ansible and deployment workflows as of August 12, 2026.
- Repository and environment names are passed directly to the GitHub CLI.
