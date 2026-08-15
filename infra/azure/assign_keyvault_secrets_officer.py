#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


ROLE_NAME = "Key Vault Secrets Officer"
DEFAULT_SUBSCRIPTION_ID = "a555786b-b00c-4cea-946c-5c435d5e7100"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create, delete, or list the Azure RBAC assignment for "
            "'Key Vault Secrets Officer' on a target Key Vault."
        )
    )
    parser.add_argument(
        "--vault-name",
        required=True,
        help="Azure Key Vault name.",
    )
    parser.add_argument(
        "--resource-group",
        required=True,
        help="Azure resource group containing the Key Vault.",
    )
    parser.add_argument(
        "--subscription-id",
        default=DEFAULT_SUBSCRIPTION_ID,
        help=f"Azure subscription ID. Default: {DEFAULT_SUBSCRIPTION_ID}",
    )
    parser.add_argument(
        "--action",
        choices=("apply", "delete", "list"),
        default="apply",
        help="Whether to create the assignment, delete it, or list current state.",
    )
    parser.add_argument(
        "--assignee",
        help=(
            "Azure assignee identifier. Can be a user principal name, object ID, "
            "client ID, or service principal app ID. If omitted, the signed-in user is used."
        ),
    )
    parser.add_argument(
        "--principal-type",
        choices=("User", "ServicePrincipal"),
        help="Principal type for creation. Defaults to User for the signed-in user, otherwise auto-detected.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show Azure CLI commands without applying changes.",
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


def get_signed_in_user() -> dict[str, str]:
    data = run_az(["ad", "signed-in-user", "show", "--output", "json"])
    object_id = data.get("id")
    user_principal_name = data.get("userPrincipalName") or data.get("mail") or ""
    if not object_id:
        raise SystemExit("Could not resolve the signed-in user object ID from Azure CLI.")
    return {
        "assignee": str(user_principal_name or object_id),
        "object_id": str(object_id),
        "principal_type": "User",
    }


def get_service_principal_by_app_id(app_id: str) -> dict[str, str]:
    data = run_az(["ad", "sp", "show", "--id", app_id, "--output", "json"])
    object_id = data.get("id")
    if not object_id:
        raise SystemExit(f"Could not resolve service principal object ID for {app_id}.")
    return {
        "assignee": app_id,
        "object_id": str(object_id),
        "principal_type": "ServicePrincipal",
    }


def infer_principal(args: argparse.Namespace) -> dict[str, str]:
    if not args.assignee:
        return get_signed_in_user()

    if args.principal_type == "ServicePrincipal":
        return get_service_principal_by_app_id(args.assignee)

    if args.principal_type == "User":
        return {
            "assignee": args.assignee,
            "object_id": "",
            "principal_type": "User",
        }

    if "@" in args.assignee:
        return {
            "assignee": args.assignee,
            "object_id": "",
            "principal_type": "User",
        }

    try:
        return get_service_principal_by_app_id(args.assignee)
    except subprocess.CalledProcessError:
        return {
            "assignee": args.assignee,
            "object_id": "",
            "principal_type": "User",
        }


def build_scope(*, subscription_id: str, resource_group: str, vault_name: str) -> str:
    return (
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.KeyVault/vaults/{vault_name}"
    )


def list_assignments(*, assignee: str, scope: str) -> list[dict[str, Any]]:
    data = run_az(
        [
            "role",
            "assignment",
            "list",
            "--assignee",
            assignee,
            "--scope",
            scope,
            "--output",
            "json",
        ]
    )
    return data or []


def find_existing_assignment(*, assignee: str, scope: str) -> dict[str, Any] | None:
    assignments = list_assignments(assignee=assignee, scope=scope)
    for assignment in assignments:
        if assignment.get("roleDefinitionName") == ROLE_NAME:
            return assignment
    return None


def apply_assignment(*, principal: dict[str, str], scope: str, dry_run: bool) -> dict[str, list[str]]:
    label = f"{ROLE_NAME} :: {scope}"
    existing = find_existing_assignment(assignee=principal["assignee"], scope=scope)
    if existing:
        return {"created": [], "unchanged": [label]}

    cmd = [
        "role",
        "assignment",
        "create",
        "--role",
        ROLE_NAME,
        "--scope",
        scope,
        "--output",
        "json",
    ]
    if principal["object_id"]:
        cmd.extend(
            [
                "--assignee-object-id",
                principal["object_id"],
                "--assignee-principal-type",
                principal["principal_type"],
            ]
        )
    else:
        cmd.extend(["--assignee", principal["assignee"]])

    run_az(cmd, dry_run=dry_run)
    return {"created": [label], "unchanged": []}


def delete_assignment(*, principal: dict[str, str], scope: str, dry_run: bool) -> dict[str, list[str]]:
    label = f"{ROLE_NAME} :: {scope}"
    existing = find_existing_assignment(assignee=principal["assignee"], scope=scope)
    if not existing:
        return {"deleted": [], "missing": [label]}

    run_az(
        [
            "role",
            "assignment",
            "delete",
            "--assignee",
            principal["assignee"],
            "--role",
            ROLE_NAME,
            "--scope",
            scope,
        ],
        expect_json=False,
        dry_run=dry_run,
    )
    return {"deleted": [label], "missing": []}


def print_table(title: str, values: list[str]) -> None:
    if not values:
        return
    print(title)
    for value in values:
        print(f"- {value}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ensure_az_login()
    principal = infer_principal(args)
    scope = build_scope(
        subscription_id=args.subscription_id,
        resource_group=args.resource_group,
        vault_name=args.vault_name,
    )

    if args.action == "apply":
        result = apply_assignment(principal=principal, scope=scope, dry_run=args.dry_run)
    elif args.action == "delete":
        result = delete_assignment(principal=principal, scope=scope, dry_run=args.dry_run)
    else:
        result = {}

    existing = find_existing_assignment(assignee=principal["assignee"], scope=scope)
    summary = {
        "role": ROLE_NAME,
        "scope": scope,
        "status": "present" if existing else "missing",
    }

    output = {
        "assignee": principal["assignee"],
        "principal_type": principal["principal_type"],
        "scope": scope,
        "action": args.action,
        "dry_run": args.dry_run,
        "changes": result,
        "summary": summary,
    }

    if args.output == "json":
        print(json.dumps(output, indent=2))
        return 0

    print(f"Assignee: {principal['assignee']}")
    print(f"Principal type: {principal['principal_type']}")
    print(f"Action: {args.action}")
    print(f"Dry run: {'yes' if args.dry_run else 'no'}")
    print("")
    print_table("Created", result.get("created", []))
    print_table("Unchanged", result.get("unchanged", []))
    print_table("Deleted", result.get("deleted", []))
    print_table("Missing", result.get("missing", []))
    if result:
        print("")
    print(f"ROLE: {ROLE_NAME}")
    print(f"STATUS: {summary['status']}")
    print(f"SCOPE: {scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
