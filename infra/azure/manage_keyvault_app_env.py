#!/usr/bin/env python3
"""Sync any dotenv file to Azure Key Vault."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Any


ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def run_az(args: list[str], *, capture_json: bool = False, dry_run: bool = False) -> Any:
    cmd = ["az", *args]
    if dry_run:
        print("DRY-RUN:", " ".join(cmd))
        return [] if capture_json else ""

    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(f"Azure CLI failed: {' '.join(cmd)}\n{stderr}")
    if capture_json:
        import json

        stdout = completed.stdout.strip()
        return json.loads(stdout) if stdout else []
    return completed.stdout


def env_to_secret_name(env_name: str) -> str:
    return env_name.lower().replace("_", "-")


def load_dotenv_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"Env file not found: {path}")

    result: dict[str, str] = {}
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, sep, value = line.partition("=")
        if not sep:
            raise SystemExit(f"Invalid dotenv line in {path}:{lineno}: {raw_line}")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        result[key] = value
    return result


def parse_set(items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"Invalid --set value: {item}. Expected KEY=VALUE.")
        parsed[key.strip()] = value
    return parsed


def normalize_value(value: str) -> str:
    return value.strip() if value is not None else ""


def validate_env_names(env_vars: dict[str, str]) -> None:
    for key in env_vars:
        if not ENV_NAME_RE.match(key):
            raise SystemExit(f"Invalid env var name: {key}")


def get_existing_secret_index(vault_name: str) -> dict[str, dict[str, Any]]:
    items = run_az(
        [
            "keyvault",
            "secret",
            "list",
            "--vault-name",
            vault_name,
            "--query",
            "[].{name:name,tags:tags}",
            "-o",
            "json",
        ],
        capture_json=True,
    )
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        env_name = (item.get("tags") or {}).get("env_name")
        if env_name:
            index[env_name] = item
    return index


def infer_app_name(app: str | None, env_file: Path, vault_name: str) -> str:
    if app:
        return app
    if env_file.name.startswith(".env.") and env_file.parent == Path("."):
        return env_file.name.removeprefix(".env.")
    return vault_name


def apply_env(
    *,
    app: str,
    env_file: Path,
    vault_name: str,
    env_vars: dict[str, str],
    dry_run: bool,
) -> None:
    for key, value in sorted(env_vars.items()):
        if value == "":
            continue
        secret_name = env_to_secret_name(key)
        tags = [
            f"app={app}",
            f"env_name={key}",
            f"env_file={env_file}",
            "managed_by=manage_keyvault_app_env.py",
        ]
        run_az(
            [
                "keyvault",
                "secret",
                "set",
                "--vault-name",
                vault_name,
                "--name",
                secret_name,
                "--value",
                value,
                "--content-type",
                f"dotenv/{app}",
                "--tags",
                *tags,
                "-o",
                "none",
            ],
            dry_run=dry_run,
        )
        print(f"SET {vault_name}:{secret_name} <- {key}")


def delete_missing_env(
    *,
    app: str,
    env_file: Path,
    vault_name: str,
    desired_keys: set[str],
    existing_index: dict[str, dict[str, Any]],
    dry_run: bool,
) -> None:
    env_file_tag = str(env_file)
    for env_name, item in sorted(existing_index.items()):
        tags = item.get("tags") or {}
        managed_by = tags.get("managed_by")
        if managed_by != "manage_keyvault_app_env.py":
            continue

        same_scope = False
        if app:
            same_scope = tags.get("app") == app
        if not same_scope:
            same_scope = tags.get("env_file") == env_file_tag
        if not same_scope:
            continue

        if env_name in desired_keys:
            continue

        secret_name = item["name"]
        run_az(
            [
                "keyvault",
                "secret",
                "delete",
                "--vault-name",
                vault_name,
                "--name",
                secret_name,
                "-o",
                "none",
            ],
            dry_run=dry_run,
        )
        print(f"DELETE-MISSING {vault_name}:{secret_name} ({env_name})")


def delete_env(*, vault_name: str, keys: list[str], dry_run: bool) -> None:
    for key in keys:
        secret_name = env_to_secret_name(key)
        run_az(
            [
                "keyvault",
                "secret",
                "delete",
                "--vault-name",
                vault_name,
                "--name",
                secret_name,
                "-o",
                "none",
            ],
            dry_run=dry_run,
        )
        print(f"DELETE {vault_name}:{secret_name} ({key})")


def list_env(*, vault_name: str) -> None:
    items = run_az(
        [
            "keyvault",
            "secret",
            "list",
            "--vault-name",
            vault_name,
            "--query",
            "[].{name:name,contentType:contentType,tags:tags}",
            "-o",
            "json",
        ],
        capture_json=True,
    )
    for item in sorted(items, key=lambda x: x["name"]):
        tags = item.get("tags") or {}
        env_name = tags.get("env_name", "-")
        app = tags.get("app", "-")
        env_file = tags.get("env_file", "-")
        print(f"{item['name']}  env={env_name}  app={app}  env_file={env_file}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync any dotenv file to Azure Key Vault.")
    parser.add_argument("--env-file", type=Path, help="Path to the dotenv file to sync.")
    parser.add_argument("--vault-name", required=True, help="Azure Key Vault name.")
    parser.add_argument("--app", help="Logical app label stored in secret tags.")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Inline env var override. Can be used multiple times.",
    )
    parser.add_argument("--list", action="store_true", help="List Key Vault secrets managed as env vars.")
    parser.add_argument(
        "--delete",
        action="append",
        default=[],
        metavar="ENV_NAME",
        help="Delete one env var secret by env var name. Can be repeated.",
    )
    parser.add_argument(
        "--delete-missing",
        action="store_true",
        help="Delete managed secrets in the same app/env-file scope that are not present in the current env file.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show Azure CLI operations without applying them.")
    args = parser.parse_args()

    if args.list:
        list_env(vault_name=args.vault_name)
        return 0

    if args.delete:
        delete_env(vault_name=args.vault_name, keys=args.delete, dry_run=args.dry_run)
        return 0

    if not args.env_file:
        raise SystemExit("--env-file is required unless you use --list or --delete.")

    desired = load_dotenv_file(args.env_file)
    desired.update(parse_set(args.set))
    desired = {key: normalize_value(value) for key, value in desired.items()}

    if not desired:
        raise SystemExit(f"Nothing to apply from {args.env_file}.")

    desired_non_empty = {key for key, value in desired.items() if value != ""}
    validate_env_names(desired)
    app = infer_app_name(args.app, args.env_file, args.vault_name)
    apply_env(
        app=app,
        env_file=args.env_file,
        vault_name=args.vault_name,
        env_vars=desired,
        dry_run=args.dry_run,
    )
    if args.delete_missing:
        existing_index = get_existing_secret_index(args.vault_name)
        delete_missing_env(
            app=app,
            env_file=args.env_file,
            vault_name=args.vault_name,
            desired_keys=desired_non_empty,
            existing_index=existing_index,
            dry_run=args.dry_run,
        )
    print(f"Completed sync for env_file={args.env_file} vault={args.vault_name} app={app}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
