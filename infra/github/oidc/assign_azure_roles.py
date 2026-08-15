#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


DEFAULT_SUBSCRIPTION_ID = "a555786b-b00c-4cea-946c-5c435d5e7100"
DEFAULT_RESOURCE_GROUP_NAME = "rg-safranysAI-Dev"
DEFAULT_STORAGE_ACCOUNT_NAME = "terraformstate240775"
DEFAULT_KEY_VAULT_NAME = "safranys-kv-shared"


@dataclass(frozen=True)
class RoleAssignment:
    role_name: str
    scope: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create, delete, or list the Azure RBAC assignments required by the "
            "GitHub OIDC app used by the OVH and Azure Terraform workflows."
        )
    )
    parser.add_argument(
        "--client-id",
        required=True,
        help="Azure App Registration client ID used by GitHub Actions.",
    )
    parser.add_argument(
        "--action",
        choices=("apply", "delete", "list"),
        default="apply",
        help="Whether to create missing assignments, delete them, or list them.",
    )
    parser.add_argument(
        "--subscription-id",
        default=DEFAULT_SUBSCRIPTION_ID,
        help=f"Azure subscription ID. Default: {DEFAULT_SUBSCRIPTION_ID}",
    )
    parser.add_argument(
        "--resource-group-name",
        default=DEFAULT_RESOURCE_GROUP_NAME,
        help=f"Azure resource group name. Default: {DEFAULT_RESOURCE_GROUP_NAME}",
    )
    parser.add_argument(
        "--storage-account-name",
        default=DEFAULT_STORAGE_ACCOUNT_NAME,
        help=f"Azure storage account used for Terraform state. Default: {DEFAULT_STORAGE_ACCOUNT_NAME}",
    )
    parser.add_argument(
        "--key-vault-name",
        default=DEFAULT_KEY_VAULT_NAME,
        help=f"Azure Key Vault used for SSH key persistence. Default: {DEFAULT_KEY_VAULT_NAME}",
    )
    parser.add_argument(
        "--profile",
        choices=("ovh", "azure-terraform", "all"),
        default="all",
        help=(
            "Role set to manage. "
            "'ovh' grants the existing OVH Terraform roles, "
            "'azure-terraform' grants the Azure app Terraform role, "
            "'all' grants both."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the Azure CLI commands without changing role assignments.",
    )
    parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format for the final summary.",
    )
    return parser


def run_az(args: list[str], *, expect_json: bool = True, dry_run: bool = False) -> Any:
    cmd = ["az", *args]
    if dry_run:
        print("+", " ".join(cmd), file=sys.stderr)
        return None

    completed = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
    )
    stdout = completed.stdout.strip()
    if not expect_json:
        return stdout
    if not stdout:
        return None
    return json.loads(stdout)


def ensure_az_login() -> None:
    try:
        run_az(["account", "show", "--output", "json"])
    except subprocess.CalledProcessError as exc:
        raise SystemExit("Azure CLI is not logged in. Run 'az login' first.") from exc
    except FileNotFoundError as exc:
        raise SystemExit("Azure CLI 'az' is required but was not found in PATH.") from exc


def get_service_principal_object_id(client_id: str) -> str:
    data = run_az(["ad", "sp", "show", "--id", client_id, "--output", "json"])
    principal_id = data.get("id")
    if not principal_id:
        raise SystemExit(f"Could not resolve service principal object ID for client ID {client_id}.")
    return str(principal_id)


def build_desired_assignments(
    *,
    subscription_id: str,
    resource_group_name: str,
    storage_account_name: str,
    key_vault_name: str,
    profile: str,
) -> list[RoleAssignment]:
    resource_group_scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
    storage_scope = (
        f"{resource_group_scope}/providers/Microsoft.Storage/storageAccounts/{storage_account_name}"
    )
    key_vault_scope = (
        f"{resource_group_scope}/providers/Microsoft.KeyVault/vaults/{key_vault_name}"
    )
    assignments: list[RoleAssignment] = []

    if profile in ("ovh", "all"):
        assignments.extend(
            [
                RoleAssignment(role_name="Reader", scope=resource_group_scope),
                RoleAssignment(role_name="Storage Blob Data Contributor", scope=storage_scope),
                RoleAssignment(role_name="Key Vault Secrets Officer", scope=key_vault_scope),
            ]
        )

    if profile in ("azure-terraform", "all"):
        assignments.append(RoleAssignment(role_name="Contributor", scope=resource_group_scope))

    return assignments


def list_assignments_for_scope(client_id: str, scope: str) -> list[dict[str, Any]]:
    data = run_az(
        [
            "role",
            "assignment",
            "list",
            "--assignee",
            client_id,
            "--scope",
            scope,
            "--output",
            "json",
        ]
    )
    return data or []


def find_existing_assignment(client_id: str, desired: RoleAssignment) -> dict[str, Any] | None:
    assignments = list_assignments_for_scope(client_id, desired.scope)
    for assignment in assignments:
        if assignment.get("roleDefinitionName") == desired.role_name:
            return assignment
    return None


def apply_assignments(
    *,
    client_id: str,
    principal_id: str,
    desired_assignments: list[RoleAssignment],
    dry_run: bool,
) -> dict[str, list[str]]:
    changes = {"created": [], "unchanged": []}
    for assignment in desired_assignments:
        existing = find_existing_assignment(client_id, assignment)
        label = f"{assignment.role_name} :: {assignment.scope}"
        if existing:
            changes["unchanged"].append(label)
            continue
        run_az(
            [
                "role",
                "assignment",
                "create",
                "--assignee-object-id",
                principal_id,
                "--assignee-principal-type",
                "ServicePrincipal",
                "--role",
                assignment.role_name,
                "--scope",
                assignment.scope,
                "--output",
                "json",
            ],
            dry_run=dry_run,
        )
        changes["created"].append(label)
    return changes


def delete_assignments(
    *,
    client_id: str,
    desired_assignments: list[RoleAssignment],
    dry_run: bool,
) -> dict[str, list[str]]:
    changes = {"deleted": [], "missing": []}
    for assignment in desired_assignments:
        existing = find_existing_assignment(client_id, assignment)
        label = f"{assignment.role_name} :: {assignment.scope}"
        if not existing:
            changes["missing"].append(label)
            continue
        run_az(
            [
                "role",
                "assignment",
                "delete",
                "--assignee",
                client_id,
                "--role",
                assignment.role_name,
                "--scope",
                assignment.scope,
            ],
            expect_json=False,
            dry_run=dry_run,
        )
        changes["deleted"].append(label)
    return changes


def collect_assignment_summary(client_id: str, desired_assignments: list[RoleAssignment]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for assignment in desired_assignments:
        existing = find_existing_assignment(client_id, assignment)
        summary.append(
            {
                "role": assignment.role_name,
                "scope": assignment.scope,
                "status": "present" if existing else "missing",
            }
        )
    return summary


def print_table(title: str, values: list[str]) -> None:
    if not values:
        return
    print(title)
    for value in values:
        print(f"- {value}")


def print_summary_table(summary: list[dict[str, str]]) -> None:
    if not summary:
        return
    role_width = max(len(item["role"]) for item in summary)
    status_width = max(len(item["status"]) for item in summary)
    print(f'{"ROLE".ljust(role_width)}  {"STATUS".ljust(status_width)}  SCOPE')
    for item in summary:
        print(f'{item["role"].ljust(role_width)}  {item["status"].ljust(status_width)}  {item["scope"]}')


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ensure_az_login()
    principal_id = get_service_principal_object_id(args.client_id)
    desired_assignments = build_desired_assignments(
        subscription_id=args.subscription_id,
        resource_group_name=args.resource_group_name,
        storage_account_name=args.storage_account_name,
        key_vault_name=args.key_vault_name,
        profile=args.profile,
    )

    if args.action == "apply":
        result = apply_assignments(
            client_id=args.client_id,
            principal_id=principal_id,
            desired_assignments=desired_assignments,
            dry_run=args.dry_run,
        )
    elif args.action == "delete":
        result = delete_assignments(
            client_id=args.client_id,
            desired_assignments=desired_assignments,
            dry_run=args.dry_run,
        )
    else:
        result = {}

    summary = collect_assignment_summary(args.client_id, desired_assignments)

    output = {
        "client_id": args.client_id,
        "principal_id": principal_id,
        "action": args.action,
        "dry_run": args.dry_run,
        "subscription_id": args.subscription_id,
        "resource_group_name": args.resource_group_name,
        "storage_account_name": args.storage_account_name,
        "key_vault_name": args.key_vault_name,
        "profile": args.profile,
        "changes": result,
        "summary": summary,
    }

    if args.output == "json":
        print(json.dumps(output, indent=2))
        return 0

    print(f"Client ID: {args.client_id}")
    print(f"Principal ID: {principal_id}")
    print(f"Action: {args.action}")
    print(f"Profile: {args.profile}")
    print(f"Dry run: {'yes' if args.dry_run else 'no'}")
    print("")
    print_table("Created", result.get("created", []))
    print_table("Unchanged", result.get("unchanged", []))
    print_table("Deleted", result.get("deleted", []))
    print_table("Missing", result.get("missing", []))
    if result:
        print("")
    print_summary_table(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
