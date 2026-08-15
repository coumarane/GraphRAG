#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


DEFAULT_DISPLAY_NAME = "graphrag-kv-csi-dev"
DEFAULT_SIGN_IN_AUDIENCE = "AzureADMyOrg"
DEFAULT_SECRET_DISPLAY_NAME = "graphrag-kv-csi-client-secret"
DEFAULT_YEARS = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create, list, or delete the Azure App Registration and Service Principal "
            "used by Kubernetes Secrets Store CSI to read Azure Key Vault."
        )
    )
    parser.add_argument(
        "--display-name",
        default=DEFAULT_DISPLAY_NAME,
        help=f"Azure App Registration display name. Default: {DEFAULT_DISPLAY_NAME}",
    )
    parser.add_argument(
        "--action",
        choices=("apply", "list", "delete"),
        default="apply",
        help="Whether to create/update resources, list them, or delete the app registration.",
    )
    parser.add_argument(
        "--create-client-secret",
        action="store_true",
        help="Create a new client secret and print it in the output.",
    )
    parser.add_argument(
        "--secret-display-name",
        default=DEFAULT_SECRET_DISPLAY_NAME,
        help=f"Display name for the generated client secret. Default: {DEFAULT_SECRET_DISPLAY_NAME}",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=DEFAULT_YEARS,
        help=f"Client secret validity in years when --create-client-secret is used. Default: {DEFAULT_YEARS}",
    )
    parser.add_argument(
        "--sign-in-audience",
        default=DEFAULT_SIGN_IN_AUDIENCE,
        help=f"App registration sign-in audience. Default: {DEFAULT_SIGN_IN_AUDIENCE}",
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


def get_current_account() -> dict[str, Any]:
    return run_az(["account", "show", "--output", "json"]) or {}


def find_app_by_display_name(display_name: str) -> dict[str, Any] | None:
    apps = run_az(["ad", "app", "list", "--display-name", display_name, "--output", "json"]) or []
    exact = [app for app in apps if app.get("displayName") == display_name]
    if len(exact) > 1:
        raise SystemExit(
            f"Multiple App Registrations found with display name '{display_name}'. "
            "Use a unique display name."
        )
    return exact[0] if exact else None


def ensure_app(display_name: str, sign_in_audience: str, *, dry_run: bool) -> tuple[dict[str, Any], bool]:
    existing = find_app_by_display_name(display_name)
    if existing:
        return existing, False

    created = run_az(
        [
            "ad",
            "app",
            "create",
            "--display-name",
            display_name,
            "--sign-in-audience",
            sign_in_audience,
            "--output",
            "json",
        ],
        dry_run=dry_run,
    )
    if dry_run:
        return {
            "displayName": display_name,
            "appId": "<planned>",
            "id": "<planned>",
        }, True
    return created, True


def ensure_service_principal(app_id: str, *, dry_run: bool) -> tuple[dict[str, Any], bool]:
    if dry_run:
        return {"id": "<planned>", "appId": app_id}, True

    try:
        existing = run_az(["ad", "sp", "show", "--id", app_id, "--output", "json"])
        return existing, False
    except subprocess.CalledProcessError:
        created = run_az(["ad", "sp", "create", "--id", app_id, "--output", "json"])
        return created, True


def create_client_secret(
    *,
    app_identifier: str,
    secret_display_name: str,
    years: int,
    dry_run: bool,
) -> dict[str, Any]:
    if years <= 0:
        raise SystemExit("--years must be greater than 0.")
    result = run_az(
        [
            "ad",
            "app",
            "credential",
            "reset",
            "--id",
            app_identifier,
            "--append",
            "--display-name",
            secret_display_name,
            "--years",
            str(years),
            "--output",
            "json",
        ],
        dry_run=dry_run,
    )
    if dry_run:
        return {
            "appId": "<planned>",
            "password": "<planned>",
            "tenant": "<planned>",
        }
    return result or {}


def delete_app(display_name: str, *, dry_run: bool) -> dict[str, Any]:
    existing = find_app_by_display_name(display_name)
    if not existing:
        return {
            "display_name": display_name,
            "deleted": False,
            "app_id": None,
        }

    run_az(["ad", "app", "delete", "--id", existing["id"]], expect_json=False, dry_run=dry_run)
    return {
        "display_name": display_name,
        "deleted": True,
        "app_id": existing.get("appId"),
    }


def print_table(output: dict[str, Any]) -> None:
    print(f"Display name: {output['display_name']}")
    print(f"Tenant ID: {output['tenant_id']}")
    print(f"App ID / Client ID: {output['app_id']}")
    print(f"Application object ID: {output['application_object_id']}")
    print(f"Service principal object ID: {output['service_principal_object_id']}")
    print(f"App created: {'yes' if output['app_created'] else 'no'}")
    print(f"Service principal created: {'yes' if output['service_principal_created'] else 'no'}")
    print(f"Client secret created: {'yes' if output['client_secret_created'] else 'no'}")
    if output.get("client_secret"):
        print("")
        print("Save these values now:")
        print(f"- AZURE_KEYVAULT_CSI_CLIENT_ID={output['app_id']}")
        print(f"- AZURE_KEYVAULT_CSI_CLIENT_SECRET={output['client_secret']}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ensure_az_login()
    account = get_current_account()
    tenant_id = str(account.get("tenantId") or "")

    if args.action == "delete":
        result = delete_app(args.display_name, dry_run=args.dry_run)
        if args.output == "json":
            print(json.dumps(result, indent=2))
            return 0
        print(f"Display name: {result['display_name']}")
        print(f"Deleted: {'yes' if result['deleted'] else 'no'}")
        if result.get("app_id"):
            print(f"App ID / Client ID: {result['app_id']}")
        return 0

    app, app_created = ensure_app(args.display_name, args.sign_in_audience, dry_run=args.dry_run)
    sp, sp_created = ensure_service_principal(str(app["appId"]), dry_run=args.dry_run)

    client_secret = ""
    if args.create_client_secret:
        credential = create_client_secret(
            app_identifier=str(app["id"]),
            secret_display_name=args.secret_display_name,
            years=args.years,
            dry_run=args.dry_run,
        )
        client_secret = str(credential.get("password") or "")

    output = {
        "display_name": args.display_name,
        "tenant_id": tenant_id if not args.dry_run else "<planned>",
        "app_id": str(app["appId"]),
        "application_object_id": str(app["id"]),
        "service_principal_object_id": str(sp["id"]),
        "app_created": app_created,
        "service_principal_created": sp_created,
        "client_secret_created": bool(args.create_client_secret),
        "client_secret": client_secret,
    }

    if args.output == "json":
        print(json.dumps(output, indent=2))
        return 0

    print_table(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
