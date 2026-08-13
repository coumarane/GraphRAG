#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_BASE_URL = "https://api.cloudflare.com/client/v4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create, update, or list Cloudflare DNS records from a JSON payload."
        ,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 infra/cloudfare/apply_dns_records.py --list\n"
            "  python3 infra/cloudfare/apply_dns_records.py --dry-run\n"
            "  python3 infra/cloudfare/apply_dns_records.py\n"
            "  python3 infra/cloudfare/apply_dns_records.py --input /path/to/dns_records.json --dry-run\n"
            "  python3 infra/cloudfare/apply_dns_records.py --zone-name chatwithdocs.org --list\n"
            "  python3 infra/cloudfare/apply_dns_records.py --token-env MY_CF_TOKEN --list"
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).with_name("dns_records.json"),
        help="Path to the DNS records JSON file.",
    )
    parser.add_argument(
        "--zone-name",
        help="Override the zone name from the JSON file.",
    )
    parser.add_argument(
        "--token-env",
        default="CLOUDFLARE_API_TOKEN",
        help="Environment variable that stores the Cloudflare API token.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without calling the write APIs.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List DNS records currently present in the Cloudflare zone.",
    )
    return parser.parse_args()


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if "zone_name" not in payload:
        raise ValueError("Payload must include 'zone_name'.")
    if not isinstance(payload.get("records"), list):
        raise ValueError("Payload must include a 'records' list.")
    return payload


def api_request(
    method: str,
    path: str,
    token: str,
    *,
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{API_BASE_URL}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Cloudflare API error ({exc.code}) for {method} {url}: {message}") from exc

    if not payload.get("success", False):
        errors = payload.get("errors", [])
        raise RuntimeError(f"Cloudflare API rejected {method} {url}: {errors}")

    return payload


def get_zone_id(zone_name: str, token: str) -> str:
    response = api_request("GET", "/zones", token, query={"name": zone_name})
    results = response.get("result", [])
    if not results:
        raise RuntimeError(f"Zone '{zone_name}' was not found in Cloudflare.")
    if len(results) > 1:
        raise RuntimeError(f"Expected one zone for '{zone_name}', got {len(results)}.")
    zone_id = results[0].get("id")
    if not isinstance(zone_id, str) or not zone_id:
        raise RuntimeError(f"Cloudflare returned an invalid zone id for '{zone_name}'.")
    return zone_id


def list_dns_records(zone_id: str, token: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        response = api_request(
            "GET",
            f"/zones/{zone_id}/dns_records",
            token,
            query={"page": str(page), "per_page": "1000"},
        )
        batch = response.get("result", [])
        if not isinstance(batch, list):
            raise RuntimeError("Cloudflare returned an invalid DNS records response.")
        records.extend(batch)

        result_info = response.get("result_info", {})
        total_pages = result_info.get("total_pages", page)
        if not isinstance(total_pages, int) or page >= total_pages:
            break
        page += 1

    return records


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "type": record["type"],
        "name": record["name"],
        "content": record["content"],
        "ttl": record.get("ttl", 1),
    }
    if record["type"] in {"A", "AAAA", "CNAME"}:
        normalized["proxied"] = bool(record.get("proxied", False))
    return normalized


def print_change(action: str, record: dict[str, Any]) -> None:
    proxied = record.get("proxied")
    proxied_text = "" if proxied is None else f", proxied={proxied}"
    print(
        f"{action}: {record['type']} {record['name']} -> {record['content']} "
        f"(ttl={record['ttl']}{proxied_text})"
    )


def format_proxied(record: dict[str, Any]) -> str:
    proxied = record.get("proxied")
    if proxied is None:
        return "n/a"
    return "true" if proxied else "false"


def print_records(records: list[dict[str, Any]]) -> None:
    sorted_records = sorted(
        records,
        key=lambda record: (
            str(record.get("name", "")),
            str(record.get("type", "")),
            str(record.get("content", "")),
        ),
    )
    print("TYPE\tNAME\tCONTENT\tPROXIED\tTTL")
    for record in sorted_records:
        print(
            f"{record.get('type', '')}\t"
            f"{record.get('name', '')}\t"
            f"{record.get('content', '')}\t"
            f"{format_proxied(record)}\t"
            f"{record.get('ttl', '')}"
        )


def upsert_records(
    zone_id: str,
    token: str,
    records: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> None:
    existing_records = list_dns_records(zone_id, token)
    indexed_existing = {
        (record.get("type"), record.get("name")): record for record in existing_records
    }

    for record in records:
        normalized = normalize_record(record)
        key = (normalized["type"], normalized["name"])
        existing = indexed_existing.get(key)

        if existing is None:
            print_change("CREATE", normalized)
            if dry_run:
                continue
            api_request("POST", f"/zones/{zone_id}/dns_records", token, body=normalized)
            continue

        existing_normalized = normalize_record(existing)
        if existing_normalized == normalized:
            print_change("SKIP", normalized)
            continue

        record_id = existing.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError(f"Existing record {key} is missing an id.")

        print_change("UPDATE", normalized)
        if dry_run:
            continue
        api_request(
            "PATCH",
            f"/zones/{zone_id}/dns_records/{record_id}",
            token,
            body=normalized,
        )


def main() -> int:
    args = parse_args()
    token = os.environ.get(args.token_env)
    if not token:
        print(
            f"Missing Cloudflare token. Set the {args.token_env} environment variable.",
            file=sys.stderr,
        )
        return 1

    try:
        payload = load_payload(args.input)
        zone_name = args.zone_name or payload["zone_name"]
        zone_id = get_zone_id(zone_name, token)
        if args.list:
            print_records(list_dns_records(zone_id, token))
            return 0

        records = payload["records"]
        upsert_records(zone_id, token, records, dry_run=args.dry_run)
    except (RuntimeError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
