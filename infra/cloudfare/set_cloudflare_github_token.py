#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_REPO = "coumarane/GraphRAG"
DEFAULT_ENVIRONMENT = "dev"
DEFAULT_SECRET_NAME = "CLOUDFLARE_API_TOKEN"
DEFAULT_TOKEN_ENV = "CLOUDFLARE_API_TOKEN"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or update the GitHub Actions environment secret "
            "CLOUDFLARE_API_TOKEN for this repository."
        )
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"GitHub repository in owner/name format. Default: {DEFAULT_REPO}",
    )
    parser.add_argument(
        "--environment",
        default=DEFAULT_ENVIRONMENT,
        help=f"GitHub Actions environment name. Default: {DEFAULT_ENVIRONMENT}",
    )
    parser.add_argument(
        "--secret-name",
        default=DEFAULT_SECRET_NAME,
        help=f"GitHub Actions secret name. Default: {DEFAULT_SECRET_NAME}",
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help=(
            "Environment variable that contains the Cloudflare API token value. "
            f"Default: {DEFAULT_TOKEN_ENV}"
        ),
    )
    parser.add_argument(
        "--token-file",
        help="Read the Cloudflare API token value from a file instead of an environment variable.",
    )
    parser.add_argument(
        "--token-value",
        help="Pass the Cloudflare API token value directly on the command line.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the GitHub update command without executing it.",
    )
    return parser.parse_args()


def resolve_token(args: argparse.Namespace) -> str:
    provided = [bool(args.token_value), bool(args.token_file), bool(os.getenv(args.token_env))]
    if sum(provided) != 1:
        raise SystemExit(
            "Provide exactly one token source: "
            "--token-value, --token-file, or the environment variable "
            f"{args.token_env}."
        )

    if args.token_value:
        token = args.token_value.strip()
    elif args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
    else:
        token = os.environ[args.token_env].strip()

    if not token:
        raise SystemExit("Cloudflare API token is empty.")
    return token


def main() -> int:
    args = parse_args()
    token = resolve_token(args)

    repo_root = Path(__file__).resolve().parents[2]
    manager_script = repo_root / "infra" / "github" / "manage_github_actions_config.py"
    if not manager_script.exists():
        raise SystemExit(f"Missing GitHub config helper: {manager_script}")

    command = [
        sys.executable,
        str(manager_script),
        "--repo",
        args.repo,
        "set",
        "--scope",
        "env-secret",
        "--environment",
        args.environment,
        "--name",
        args.secret_name,
        "--value",
        token,
    ]

    if args.dry_run:
        print("Dry run. Command to execute:")
        print(" ".join(command[:-1] + ["***REDACTED***"]))
        return 0

    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise SystemExit(
            "Failed to run the GitHub config helper. Ensure Python 3 is available."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc

    print(
        f"Secret {args.secret_name} updated for repo {args.repo} "
        f"environment {args.environment}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
