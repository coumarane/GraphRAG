#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


ScopeType = Literal["repo-secret", "repo-var", "env-secret", "env-var"]


@dataclass(frozen=True)
class ConfigEntry:
    name: str
    scope: ScopeType
    environment: str | None
    description: str
    required_by: tuple[str, ...]


WORKFLOW_ENTRIES: tuple[ConfigEntry, ...] = (
    ConfigEntry(
        name="HARBOR_REGISTRY_USERNAME",
        scope="env-secret",
        environment="dev",
        description="Harbor registry username for API/Web image build and deploy workflows.",
        required_by=(
            "build-and-push-api-image.yml",
            "build-and-push-web-image.yml",
            "run-api-kubernetes-deploy.yml",
            "run-web-kubernetes-deploy.yml",
        ),
    ),
    ConfigEntry(
        name="HARBOR_REGISTRY_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="Harbor registry password for API/Web image build and deploy workflows.",
        required_by=(
            "build-and-push-api-image.yml",
            "build-and-push-web-image.yml",
            "run-api-kubernetes-deploy.yml",
            "run-web-kubernetes-deploy.yml",
        ),
    ),
    ConfigEntry(
        name="CLOUDFLARE_API_TOKEN",
        scope="env-secret",
        environment="dev",
        description="Cloudflare API token used by cert-manager bootstrap.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="GRAFANA_ADMIN_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="Grafana admin password for Prometheus stack bootstrap.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET",
        scope="env-secret",
        environment="dev",
        description="Optional Grafana OIDC client secret if Grafana generic OAuth is enabled later.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="ARGOCD_ADMIN_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="Argo CD admin password.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="ARGOCD_GITHUB_APP_ID",
        scope="env-secret",
        environment="dev",
        description="Argo CD GitHub App ID.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="ARGOCD_GITHUB_APP_INSTALLATION_ID",
        scope="env-secret",
        environment="dev",
        description="Argo CD GitHub App installation ID.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="ARGOCD_GITHUB_APP_PRIVATE_KEY",
        scope="env-secret",
        environment="dev",
        description="Argo CD GitHub App private key.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="ARGOCD_OIDC_CLIENT_SECRET",
        scope="env-secret",
        environment="dev",
        description="Optional Argo CD OIDC client secret if external OIDC login is enabled later.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="REDIS_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="Redis password for the in-cluster Redis Helm deployment.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="QDRANT_API_KEY",
        scope="env-secret",
        environment="dev",
        description="Qdrant API key for the in-cluster Qdrant Helm deployment.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="NEO4J_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="Neo4j initial password for the in-cluster Neo4j Helm deployment.",
        required_by=("run-k8s-addons-bootstrap.yml",),
    ),
    ConfigEntry(
        name="CONTABO_ROOT_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="Harbor target root password for Ansible password-based SSH.",
        required_by=("run-harbor-deploy.yml",),
    ),
    ConfigEntry(
        name="HARBOR_ADMIN_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="Harbor admin password for the Harbor Ansible playbook.",
        required_by=("run-harbor-deploy.yml",),
    ),
    ConfigEntry(
        name="HARBOR_DB_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="Harbor database password for the Harbor Ansible playbook.",
        required_by=("run-harbor-deploy.yml",),
    ),
    ConfigEntry(
        name="CONTABO_VM2_ROOT_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="PostgreSQL target root password for Ansible password-based SSH.",
        required_by=("run-postgresql-deploy.yml",),
    ),
    ConfigEntry(
        name="POSTGRES_ADMIN_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="PostgreSQL admin password used by deploy and migration workflows.",
        required_by=("run-postgresql-deploy.yml", "run-database-migrations.yml"),
    ),
    ConfigEntry(
        name="POSTGRES_APP_DB",
        scope="env-secret",
        environment="dev",
        description="PostgreSQL application database name.",
        required_by=("run-postgresql-deploy.yml", "run-database-migrations.yml"),
    ),
    ConfigEntry(
        name="POSTGRES_APP_USER",
        scope="env-secret",
        environment="dev",
        description="PostgreSQL application user.",
        required_by=("run-postgresql-deploy.yml", "run-database-migrations.yml"),
    ),
    ConfigEntry(
        name="POSTGRES_APP_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="PostgreSQL application user password.",
        required_by=("run-postgresql-deploy.yml", "run-database-migrations.yml"),
    ),
    ConfigEntry(
        name="PGADMIN_EMAIL",
        scope="env-secret",
        environment="dev",
        description="pgAdmin bootstrap email.",
        required_by=("run-postgresql-deploy.yml",),
    ),
    ConfigEntry(
        name="PGADMIN_PASSWORD",
        scope="env-secret",
        environment="dev",
        description="pgAdmin bootstrap password.",
        required_by=("run-postgresql-deploy.yml",),
    ),
    ConfigEntry(
        name="AZURE_CLIENT_ID",
        scope="env-secret",
        environment="dev",
        description="Azure workload identity application client ID used by the OVH Terraform workflow.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="OVH_APPLICATION_KEY",
        scope="env-secret",
        environment="dev",
        description="OVH application key used by the OVH Terraform workflow.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="OVH_APPLICATION_SECRET",
        scope="env-secret",
        environment="dev",
        description="OVH application secret used by the OVH Terraform workflow.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="OVH_CONSUMER_KEY",
        scope="env-secret",
        environment="dev",
        description="OVH consumer key used by the OVH Terraform workflow.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="AZURE_SUBSCRIPTION_ID",
        scope="env-var",
        environment="dev",
        description="Azure subscription ID used by the OVH Terraform workflow backend and provider.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="AZURE_TENANT_ID",
        scope="env-var",
        environment="dev",
        description="Azure tenant ID used by the OVH Terraform workflow backend and provider.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="AZURE_RESOURCE_GROUP_NAME",
        scope="env-var",
        environment="dev",
        description="Azure resource group that contains the OVH Terraform state storage account.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="AZURE_STORAGE_ACCOUNT_NAME",
        scope="env-var",
        environment="dev",
        description="Azure storage account that contains the OVH Terraform state container.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="AZURE_TERRAFORM_STATE_CONTAINER_NAME",
        scope="env-var",
        environment="dev",
        description="Azure blob container used by the OVH Terraform remote state backend.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="AZURE_KEY_VAULT_NAME",
        scope="env-var",
        environment="dev",
        description="Azure Key Vault name used by the OVH Terraform workflow for SSH key persistence.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="OVH_TERRAFORM_STATE_KEY",
        scope="env-var",
        environment="dev",
        description="Optional Azure blob name for the OVH Terraform remote state file.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="OVH_SSH_PRIVATE_KEY_SECRET_NAME",
        scope="env-var",
        environment="dev",
        description="Optional Key Vault secret name that stores the OVH Terraform SSH private key.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
    ConfigEntry(
        name="OVH_SSH_PRIVATE_KEY_PATH",
        scope="env-var",
        environment="dev",
        description="Optional local runner path used by the OVH Terraform workflow for the SSH private key.",
        required_by=("run-ovh-terraform-reinstall.yml",),
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create, update, delete, or list GitHub Actions secrets and variables used by this repository."
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="Repository in OWNER/REPO format. Defaults to GITHUB_REPOSITORY.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="Print the built-in catalog used by infra workflows.")
    catalog.add_argument("--format", choices=("table", "json"), default="table")

    template = subparsers.add_parser("template", help="Print a JSON template for batch apply.")
    template.add_argument("--environment", default="dev")

    list_parser = subparsers.add_parser("list", help="List repository or environment secrets/variables.")
    list_parser.add_argument("--scope", required=True, choices=("repo-secret", "repo-var", "env-secret", "env-var"))
    list_parser.add_argument("--environment")
    list_parser.add_argument("--json", action="store_true")

    set_parser = subparsers.add_parser("set", help="Create or update one secret or variable.")
    add_scope_args(set_parser)
    set_parser.add_argument("--name", required=True)
    value_group = set_parser.add_mutually_exclusive_group(required=True)
    value_group.add_argument("--value")
    value_group.add_argument("--value-file", type=Path)

    delete_parser = subparsers.add_parser("delete", help="Delete one secret or variable.")
    add_scope_args(delete_parser)
    delete_parser.add_argument("--name", required=True)

    apply_parser = subparsers.add_parser("apply", help="Create or update entries from a JSON file.")
    apply_parser.add_argument("--file", required=True, type=Path)

    return parser


def add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scope", required=True, choices=("repo-secret", "repo-var", "env-secret", "env-var"))
    parser.add_argument("--environment")


def ensure_repo(repo: str | None) -> str:
    if not repo:
        raise SystemExit("Missing repository. Pass --repo OWNER/REPO or set GITHUB_REPOSITORY.")
    return repo


def ensure_gh() -> None:
    try:
        subprocess.run(["gh", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit("GitHub CLI 'gh' is required. Install it and run 'gh auth login'.") from exc


def run_gh(args: list[str], *, stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        input=stdin_text,
        text=True,
        check=True,
        capture_output=True,
    )


def list_entries(repo: str, scope: ScopeType, environment: str | None, as_json: bool) -> None:
    args = ["secret", "list"] if "secret" in scope else ["variable", "list"]
    args.extend(["--repo", repo])
    if "env" in scope:
        if not environment:
            raise SystemExit("--environment is required for env-secret and env-var.")
        args.extend(["--env", environment])
    if as_json:
        args.extend(["--json", "name,updatedAt,numSelectedRepos,visibility,value"])
    result = run_gh(args)
    sys.stdout.write(result.stdout)


def set_entry(repo: str, scope: ScopeType, environment: str | None, name: str, value: str) -> None:
    if "secret" in scope:
        args = ["secret", "set", name, "--repo", repo]
        if "env" in scope:
            if not environment:
                raise SystemExit("--environment is required for env-secret.")
            args.extend(["--env", environment])
        run_gh(args, stdin_text=value)
        print(f"Set {scope} {name}")
        return

    args = ["variable", "set", name, "--repo", repo, "--body", value]
    if "env" in scope:
        if not environment:
            raise SystemExit("--environment is required for env-var.")
        args.extend(["--env", environment])
    run_gh(args)
    print(f"Set {scope} {name}")


def delete_entry(repo: str, scope: ScopeType, environment: str | None, name: str) -> None:
    if "secret" in scope:
        args = ["secret", "delete", name, "--repo", repo, "--yes"]
        if "env" in scope:
            if not environment:
                raise SystemExit("--environment is required for env-secret.")
            args.extend(["--env", environment])
        run_gh(args)
        print(f"Deleted {scope} {name}")
        return

    args = ["variable", "delete", name, "--repo", repo, "--yes"]
    if "env" in scope:
        if not environment:
            raise SystemExit("--environment is required for env-var.")
        args.extend(["--env", environment])
    run_gh(args)
    print(f"Deleted {scope} {name}")


def print_catalog(output_format: str) -> None:
    payload = [
        {
            "name": entry.name,
            "scope": entry.scope,
            "environment": entry.environment,
            "description": entry.description,
            "required_by": list(entry.required_by),
        }
        for entry in WORKFLOW_ENTRIES
    ]
    if output_format == "json":
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    print("NAME\tSCOPE\tENVIRONMENT\tWORKFLOWS")
    for entry in WORKFLOW_ENTRIES:
        workflows = ",".join(entry.required_by)
        environment = entry.environment or "-"
        print(f"{entry.name}\t{entry.scope}\t{environment}\t{workflows}")


def print_template(environment: str) -> None:
    entries: list[dict[str, Any]] = []
    for entry in WORKFLOW_ENTRIES:
        entry_environment = environment if entry.environment == "dev" else entry.environment
        entries.append(
            {
                "name": entry.name,
                "scope": entry.scope,
                "environment": entry_environment,
                "value": "",
                "description": entry.description,
            }
        )
    json.dump({"entries": entries}, sys.stdout, indent=2)
    sys.stdout.write("\n")


def load_value(value: str | None, value_file: Path | None) -> str:
    if value is not None:
        return value
    if value_file is None:
        raise SystemExit("Missing value. Use --value or --value-file.")
    return value_file.read_text(encoding="utf-8")


def apply_file(repo: str, file_path: Path) -> None:
    data = json.loads(file_path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise SystemExit("JSON file must contain an 'entries' list.")

    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise SystemExit(f"entries[{index}] must be an object.")
        name = str(item.get("name", "")).strip()
        scope = str(item.get("scope", "")).strip()
        environment = item.get("environment")
        value = item.get("value")
        delete = bool(item.get("delete", False))
        if not name or scope not in {"repo-secret", "repo-var", "env-secret", "env-var"}:
            raise SystemExit(f"entries[{index}] must define valid 'name' and 'scope'.")
        if delete:
            delete_entry(repo, scope, environment, name)
            continue
        if not isinstance(value, str):
            raise SystemExit(f"entries[{index}] must define string 'value' unless delete=true.")
        set_entry(repo, scope, environment, name, value)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    ensure_gh()

    if args.command in {"catalog", "template"}:
        if args.command == "catalog":
            print_catalog(args.format)
        else:
            print_template(args.environment)
        return 0

    repo = ensure_repo(args.repo)

    if args.command == "list":
        list_entries(repo, args.scope, args.environment, args.json)
        return 0

    if args.command == "set":
        value = load_value(args.value, args.value_file)
        set_entry(repo, args.scope, args.environment, args.name, value)
        return 0

    if args.command == "delete":
        delete_entry(repo, args.scope, args.environment, args.name)
        return 0

    if args.command == "apply":
        apply_file(repo, args.file)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
