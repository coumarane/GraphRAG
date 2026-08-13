#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
DEFAULT_AUDIENCE = "api://AzureADTokenExchange"


@dataclass(frozen=True)
class FederatedCredential:
    name: str
    subject: str
    description: str
    issuer: str
    audiences: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FederatedCredential":
        return cls(
            name=str(data["name"]),
            subject=str(data["subject"]),
            description=str(data.get("description", "")),
            issuer=str(data.get("issuer", GITHUB_OIDC_ISSUER)),
            audiences=tuple(data.get("audiences", [DEFAULT_AUDIENCE])),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "issuer": self.issuer,
            "subject": self.subject,
            "description": self.description,
            "audiences": list(self.audiences),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create, update, or delete an Azure App Registration and GitHub Actions OIDC federated credentials."
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to the JSON configuration file.",
    )
    parser.add_argument(
        "--action",
        choices=("apply", "delete"),
        default="apply",
        help="Whether to create/update resources or delete the app registration.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without modifying Azure resources.",
    )
    parser.add_argument(
        "--delete-extra-federated-credentials",
        action="store_true",
        help="Delete existing federated credentials on the app that are not present in the config file.",
    )
    parser.add_argument(
        "--output",
        choices=("json", "table"),
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


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(
            f"Config file not found: {path}. "
            "Use the example in infra/github/oidc/examples/ or create the file first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ("display_name", "repo", "federated_credentials")
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit(f"Missing required config keys in {path}: {', '.join(missing)}")
    if not isinstance(data["federated_credentials"], list) or not data["federated_credentials"]:
        raise SystemExit("Config must include a non-empty 'federated_credentials' array.")
    return data


def get_current_account() -> dict[str, Any]:
    return run_az(["account", "show", "--output", "json"])


def find_app_by_display_name(display_name: str) -> dict[str, Any] | None:
    apps = run_az(["ad", "app", "list", "--display-name", display_name, "--output", "json"]) or []
    exact = [app for app in apps if app.get("displayName") == display_name]
    if len(exact) > 1:
        raise SystemExit(
            f"Multiple App Registrations found with display name '{display_name}'. "
            "Use a unique display name or extend the script to target an explicit app ID."
        )
    return exact[0] if exact else None


def ensure_app(config: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    existing = find_app_by_display_name(config["display_name"])
    if existing:
        return existing

    payload = [
        "ad",
        "app",
        "create",
        "--display-name",
        config["display_name"],
        "--sign-in-audience",
        config.get("sign_in_audience", "AzureADMyOrg"),
        "--output",
        "json",
    ]
    created = run_az(payload, dry_run=dry_run)
    if dry_run:
        return {
            "displayName": config["display_name"],
            "appId": "<planned>",
            "id": "<planned>",
        }
    return created


def delete_app_registration(config: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    existing = find_app_by_display_name(config["display_name"])
    if not existing:
        return {
            "displayName": config["display_name"],
            "appId": None,
            "id": None,
            "deleted": False,
        }

    run_az(
        ["ad", "app", "delete", "--id", existing["id"]],
        expect_json=False,
        dry_run=dry_run,
    )
    return {
        "displayName": existing["displayName"],
        "appId": existing["appId"],
        "id": existing["id"],
        "deleted": True,
    }


def ensure_service_principal(app_id: str, *, dry_run: bool) -> dict[str, Any] | None:
    if dry_run:
        return {"id": "<planned>", "appId": app_id}
    try:
        return run_az(["ad", "sp", "show", "--id", app_id, "--output", "json"], dry_run=dry_run)
    except subprocess.CalledProcessError:
        created = run_az(["ad", "sp", "create", "--id", app_id, "--output", "json"], dry_run=dry_run)
        return created


def list_federated_credentials(app_identifier: str, *, dry_run: bool) -> list[dict[str, Any]]:
    data = run_az(["ad", "app", "federated-credential", "list", "--id", app_identifier, "--output", "json"], dry_run=dry_run)
    return data or []


def write_temp_payload(payload: dict[str, Any]) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
    with handle:
        json.dump(payload, handle)
    return handle.name


def same_federated_credential(existing: dict[str, Any], desired: FederatedCredential) -> bool:
    return (
        existing.get("name") == desired.name
        and existing.get("issuer") == desired.issuer
        and existing.get("subject") == desired.subject
        and tuple(existing.get("audiences", [])) == desired.audiences
        and existing.get("description", "") == desired.description
    )


def apply_federated_credentials(
    app_identifier: str,
    desired_credentials: list[FederatedCredential],
    *,
    dry_run: bool,
    delete_extra: bool,
) -> dict[str, list[str]]:
    existing = {item["name"]: item for item in list_federated_credentials(app_identifier, dry_run=dry_run)}
    changes = {"created": [], "updated": [], "deleted": [], "unchanged": []}

    for desired in desired_credentials:
        payload_path = write_temp_payload(desired.to_payload())
        args = [
            "ad",
            "app",
            "federated-credential",
            "create",
            "--id",
            app_identifier,
            "--parameters",
            payload_path,
            "--output",
            "json",
        ]
        if desired.name in existing:
            if same_federated_credential(existing[desired.name], desired):
                changes["unchanged"].append(desired.name)
                continue
            args = [
                "ad",
                "app",
                "federated-credential",
                "update",
                "--id",
                app_identifier,
                "--federated-credential-id",
                desired.name,
                "--parameters",
                payload_path,
                "--output",
                "json",
            ]
            changes["updated"].append(desired.name)
        else:
            changes["created"].append(desired.name)
        run_az(args, dry_run=dry_run)

    if delete_extra:
        desired_names = {item.name for item in desired_credentials}
        for existing_name in sorted(set(existing) - desired_names):
            run_az(
                [
                    "ad",
                    "app",
                    "federated-credential",
                    "delete",
                    "--id",
                    app_identifier,
                    "--federated-credential-id",
                    existing_name,
                ],
                expect_json=False,
                dry_run=dry_run,
            )
            changes["deleted"].append(existing_name)

    return changes


def format_summary(summary: dict[str, Any], output: str) -> str:
    if output == "json":
        return json.dumps(summary, indent=2)

    if summary["action"] == "delete":
        lines = [
            f"Action: {summary['action']}",
            f"App registration: {summary['display_name']}",
            f"Repository: {summary['repo']}",
            f"Client ID: {summary['client_id']}",
            f"Application object ID: {summary['application_object_id']}",
            f"Deleted: {summary['deleted']}",
            f"Tenant ID: {summary['tenant_id']}",
            f"Subscription ID: {summary['subscription_id']}",
        ]
        return "\n".join(lines)

    lines = [
        f"Action: {summary['action']}",
        f"App registration: {summary['display_name']}",
        f"Repository: {summary['repo']}",
        f"Client ID: {summary['client_id']}",
        f"Application object ID: {summary['application_object_id']}",
        f"Service principal object ID: {summary['service_principal_object_id']}",
        f"Tenant ID: {summary['tenant_id']}",
        f"Subscription ID: {summary['subscription_id']}",
        "Federated credentials:",
    ]
    for name in summary["federated_credentials"]:
        lines.append(f"  - {name}")
    lines.append("Changes:")
    for key in ("created", "updated", "deleted", "unchanged"):
        values = ", ".join(summary["changes"][key]) if summary["changes"][key] else "-"
        lines.append(f"  - {key}: {values}")
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    ensure_az_login()

    account = get_current_account()
    desired_credentials = [FederatedCredential.from_dict(item) for item in config["federated_credentials"]]

    if args.action == "delete":
        deleted_app = delete_app_registration(config, dry_run=args.dry_run)
        summary = {
            "action": args.action,
            "display_name": config["display_name"],
            "repo": config["repo"],
            "client_id": deleted_app["appId"],
            "application_object_id": deleted_app["id"],
            "service_principal_object_id": None,
            "tenant_id": config.get("tenant_id", account.get("tenantId")),
            "subscription_id": config.get("subscription_id", account.get("id")),
            "deleted": deleted_app["deleted"],
        }
        print(format_summary(summary, args.output))
        return 0

    app = ensure_app(config, dry_run=args.dry_run)
    service_principal = None
    if config.get("create_service_principal", True):
        service_principal = ensure_service_principal(app["appId"], dry_run=args.dry_run)

    changes = apply_federated_credentials(
        app["id"],
        desired_credentials,
        dry_run=args.dry_run,
        delete_extra=args.delete_extra_federated_credentials,
    )

    summary = {
        "action": args.action,
        "display_name": config["display_name"],
        "repo": config["repo"],
        "client_id": app["appId"],
        "application_object_id": app["id"],
        "service_principal_object_id": None if service_principal is None else service_principal.get("id"),
        "tenant_id": config.get("tenant_id", account.get("tenantId")),
        "subscription_id": config.get("subscription_id", account.get("id")),
        "federated_credentials": [item.name for item in desired_credentials],
        "changes": changes,
    }
    print(format_summary(summary, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
