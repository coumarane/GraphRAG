"""Metadata for a verified DEV PostgreSQL backup.

The file records where the dump was stored and how it was checked. It must
not contain passwords, connection strings, or row contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 1
WORKFLOW = "backup-dev-database.yml"
BLOB_PREFIX = "postgres-backups/dev/"
APP_ROLE = "chatwithdocs_dev_user"
DUMP_ARGS = ["--format=custom", "--no-owner", "--no-acl"]
MAX_FUTURE_SKEW = timedelta(minutes=10)


class BackupMetadataError(Exception):
    """The backup evidence is missing or does not match this database."""


def parse_counts(text: str) -> dict[str, str]:
    counts: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        name, separator, value = line.partition("\t")
        if separator != "\t" or not name or not value.strip().isdigit():
            raise BackupMetadataError(f"Unreadable table count line for {name or 'a public table'}.")
        counts[name] = value.strip()
    if not counts:
        raise BackupMetadataError("The backup verification did not record any public table counts.")
    return counts


def counts_match(before: str, after: str) -> None:
    source = parse_counts(before)
    restored = parse_counts(after)
    if source.keys() != restored.keys():
        raise BackupMetadataError("The restored database does not have the same public tables.")
    mismatched = [name for name in sorted(source) if source[name] != restored[name]]
    if mismatched:
        raise BackupMetadataError(
            "Restored row counts differ for: " + ", ".join(mismatched)
        )


def expired_blob_names(
    blobs: list[dict[str, str]],
    *,
    now: datetime,
    retention_days: int,
    keep: str,
    prefix: str = BLOB_PREFIX,
) -> list[str]:
    if retention_days < 1:
        raise BackupMetadataError("retention_days must be at least 1.")
    if not prefix.startswith("postgres-backups/"):
        raise BackupMetadataError("Cleanup is limited to the postgres-backups prefix.")
    cutoff = now - timedelta(days=retention_days)
    expired: list[str] = []
    for blob in blobs:
        name = str(blob.get("name", ""))
        if not name.startswith(prefix):
            raise BackupMetadataError(f"Refusing to clean a blob outside {prefix}.")
        if name == keep:
            continue
        modified = datetime.fromisoformat(str(blob["modified"]).replace("Z", "+00:00"))
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=timezone.utc)
        if modified.astimezone(timezone.utc) < cutoff:
            expired.append(name)
    return expired


def build_metadata(
    *,
    host: str,
    port: int,
    database: str,
    admin_role: str,
    admin_privilege: str,
    postgres_version: str,
    alembic_revision: str,
    sha256: str,
    content_md5: str,
    size_bytes: int,
    account: str,
    container: str,
    blob: str,
    retention_days: int,
    completed_at: datetime,
) -> dict[str, object]:
    if admin_role == APP_ROLE:
        raise BackupMetadataError("Refusing to record a backup taken as the application role.")
    if admin_privilege not in {"superuser", "bypassrls"}:
        raise BackupMetadataError("The backup role cannot bypass row level security.")
    if not blob.startswith(BLOB_PREFIX):
        raise BackupMetadataError(f"Backup blob must be stored under {BLOB_PREFIX}.")
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise BackupMetadataError("sha256 must be 64 hexadecimal characters.")
    if not content_md5 or not postgres_version or not alembic_revision:
        raise BackupMetadataError("Backup metadata is missing the checksum, version, or revision.")
    completed = completed_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": SCHEMA_VERSION,
        "workflow": WORKFLOW,
        "host": host,
        "port": port,
        "database": database,
        "admin_role": admin_role,
        "admin_privilege": admin_privilege,
        "postgres_version": postgres_version,
        "alembic_revision": alembic_revision,
        "dump_format": "custom",
        "pg_dump_args": DUMP_ARGS,
        "row_security": "off",
        "sha256": sha256,
        "content_md5": content_md5,
        "bytes": size_bytes,
        "storage": {
            "account": account,
            "container": container,
            "blob": blob,
            "access": "private",
        },
        "verification": {
            "pg_restore_list": "passed",
            "restore_database": "passed",
            "row_counts_match": True,
        },
        "completed_at": completed,
        "retention_days": retention_days,
    }


def validate_metadata(
    metadata: dict[str, object],
    *,
    host: str,
    database: str,
    account: str,
    container: str,
    now: datetime,
    max_age: timedelta,
) -> None:
    if metadata.get("schema_version") != SCHEMA_VERSION or metadata.get("workflow") != WORKFLOW:
        raise BackupMetadataError("Backup metadata is not from Backup DEV database.")
    if metadata.get("host") != host or metadata.get("database") != database:
        raise BackupMetadataError("The verified backup is for a different database.")
    if metadata.get("admin_role") == APP_ROLE:
        raise BackupMetadataError("The backup was taken as the application role.")
    if metadata.get("admin_privilege") not in {"superuser", "bypassrls"}:
        raise BackupMetadataError("The backup role cannot bypass row level security.")
    if metadata.get("row_security") != "off":
        raise BackupMetadataError("The backup did not bypass row level security.")
    if metadata.get("pg_dump_args") != DUMP_ARGS:
        raise BackupMetadataError("The backup was not taken with the required pg_dump arguments.")
    verification = metadata.get("verification")
    if not isinstance(verification, dict):
        raise BackupMetadataError("Backup verification is missing.")
    if verification.get("pg_restore_list") != "passed" or verification.get("restore_database") != "passed":
        raise BackupMetadataError("The backup archive was not restored successfully.")
    if verification.get("row_counts_match") is not True:
        raise BackupMetadataError("The restored row counts did not match the source database.")
    storage = metadata.get("storage")
    if not isinstance(storage, dict):
        raise BackupMetadataError("Backup storage location is missing.")
    if storage.get("account") != account or storage.get("container") != container:
        raise BackupMetadataError("The backup is not in the private DEV artifacts container.")
    if storage.get("access") != "private":
        raise BackupMetadataError("The backup container was not private.")
    blob = storage.get("blob")
    if not isinstance(blob, str) or not blob.startswith(BLOB_PREFIX):
        raise BackupMetadataError(f"Backup blob must be stored under {BLOB_PREFIX}.")
    sha256 = metadata.get("sha256")
    content_md5 = metadata.get("content_md5")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise BackupMetadataError("Backup sha256 is missing.")
    if not isinstance(content_md5, str) or not content_md5:
        raise BackupMetadataError("Backup content MD5 is missing.")
    completed_raw = metadata.get("completed_at")
    if not isinstance(completed_raw, str):
        raise BackupMetadataError("Backup completion time is missing.")
    completed = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    age = now.astimezone(timezone.utc) - completed.astimezone(timezone.utc)
    if age < -MAX_FUTURE_SKEW or age > max_age:
        raise BackupMetadataError(
            "The verified backup is outside the allowed freshness window. Dispatch Backup DEV database again."
        )


def file_checksums(path: Path) -> tuple[str, str, int]:
    digest = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            md5.update(block)
            size += len(block)
    return digest.hexdigest(), _b64(md5.digest()), size


def _b64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode("ascii")


def _read_metadata(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BackupMetadataError("Backup metadata must be a JSON object.")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or write DEV backup metadata.")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check-counts")
    check.add_argument("--before", type=Path, required=True)
    check.add_argument("--after", type=Path, required=True)

    checksum = commands.add_parser("checksum")
    checksum.add_argument("--file", type=Path, required=True)

    expired = commands.add_parser("expired-blobs")
    expired.add_argument("--blobs", type=Path, required=True)
    expired.add_argument("--keep", required=True)
    expired.add_argument("--retention-days", type=int, required=True)

    write = commands.add_parser("write")
    write.add_argument("--output", type=Path, required=True)
    write.add_argument("--host", required=True)
    write.add_argument("--port", type=int, required=True)
    write.add_argument("--database", required=True)
    write.add_argument("--admin-role", required=True)
    write.add_argument("--admin-privilege", required=True)
    write.add_argument("--postgres-version", required=True)
    write.add_argument("--alembic-revision", required=True)
    write.add_argument("--sha256", required=True)
    write.add_argument("--content-md5", required=True)
    write.add_argument("--bytes", type=int, required=True)
    write.add_argument("--account", required=True)
    write.add_argument("--container", required=True)
    write.add_argument("--blob", required=True)
    write.add_argument("--retention-days", type=int, required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--metadata", type=Path, required=True)
    validate.add_argument("--host", required=True)
    validate.add_argument("--database", required=True)
    validate.add_argument("--account", required=True)
    validate.add_argument("--container", required=True)
    validate.add_argument("--max-age-hours", type=int, default=24)

    args = parser.parse_args(argv)
    try:
        if args.command == "check-counts":
            counts_match(args.before.read_text(encoding="utf-8"), args.after.read_text(encoding="utf-8"))
            print("row_counts_match=true")
        elif args.command == "checksum":
            sha256, content_md5, size_bytes = file_checksums(args.file)
            print(sha256)
            print(content_md5)
            print(size_bytes)
        elif args.command == "expired-blobs":
            blobs = json.loads(args.blobs.read_text(encoding="utf-8"))
            names = expired_blob_names(
                blobs,
                now=datetime.now(timezone.utc),
                retention_days=args.retention_days,
                keep=args.keep,
            )
            for name in names:
                print(name)
        elif args.command == "write":
            metadata = build_metadata(
                host=args.host,
                port=args.port,
                database=args.database,
                admin_role=args.admin_role,
                admin_privilege=args.admin_privilege,
                postgres_version=args.postgres_version,
                alembic_revision=args.alembic_revision,
                sha256=args.sha256,
                content_md5=args.content_md5,
                size_bytes=args.bytes,
                account=args.account,
                container=args.container,
                blob=args.blob,
                retention_days=args.retention_days,
                completed_at=datetime.now(timezone.utc),
            )
            args.output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {args.output}")
        elif args.command == "validate":
            validate_metadata(
                _read_metadata(args.metadata),
                host=args.host,
                database=args.database,
                account=args.account,
                container=args.container,
                now=datetime.now(timezone.utc),
                max_age=timedelta(hours=args.max_age_hours),
            )
            print("backup_metadata=valid")
    except (BackupMetadataError, json.JSONDecodeError, OSError, KeyError, ValueError) as exc:
        print(f"Backup evidence rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
