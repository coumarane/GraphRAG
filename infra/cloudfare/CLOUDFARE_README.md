# Cloudflare DNS

This folder contains the DNS payload and automation script used to manage Cloudflare DNS records for `chatwithdocs.org`.

## Files

- `dns_records.json`: source of truth for the DNS records to apply.
- `apply_dns_records.py`: Python script that creates or updates records in Cloudflare.
- `set_cloudflare_github_token.py`: Python script that creates or updates the GitHub Actions secret `CLOUDFLARE_API_TOKEN`.

## Managed zone

- Zone: `chatwithdocs.org`
- TTL: `Auto` (`ttl=1` in the JSON payload)

## DNS records

| Name                            | Type  | Content           | Proxy    |
| ------------------------------- | ----- | ----------------- | -------- |
| `chatwithdocs.org`            | `A` | `51.38.19.54`   | Proxied  |
| `www.chatwithdocs.org`        | `A` | `51.38.19.54`   | Proxied  |
| `api.chatwithdocs.org`        | `A` | `51.38.19.54`   | Proxied  |
| `argocd.chatwithdocs.org`     | `A` | `51.38.19.54`   | Proxied  |
| `prometheus.chatwithdocs.org` | `A` | `51.38.19.54`   | Proxied  |
| `database.chatwithdocs.org`   | `A` | `167.86.88.114` | DNS only |
| `harbor.chatwithdocs.org`     | `A` | `62.84.180.181` | DNS only |

## Prerequisites

- Python 3 available locally.
- A Cloudflare API token with `Zone DNS Write` permission for `chatwithdocs.org`.
- The target zone already exists in Cloudflare.
- `gh` authenticated locally if you want to push the token into GitHub Actions secrets.

## Run the script

From the repository root:

```bash
export CLOUDFLARE_API_TOKEN="your-token-here"
python3 infra/cloudfare/apply_dns_records.py --list
python3 infra/cloudfare/apply_dns_records.py --dry-run
python3 infra/cloudfare/apply_dns_records.py
```

## Create the GitHub Actions secret

The Kubernetes add-ons workflow expects `CLOUDFLARE_API_TOKEN` as a GitHub Actions environment secret on environment `dev`.

Using the local environment variable:

```bash
export CLOUDFLARE_API_TOKEN="your-token-here"
python3 infra/cloudfare/set_cloudflare_github_token.py
```

Using a file:

```bash
python3 infra/cloudfare/set_cloudflare_github_token.py \
  --token-file ~/.config/cloudflare/chatwithdocs.token
```

Preview only:

```bash
export CLOUDFLARE_API_TOKEN="your-token-here"
python3 infra/cloudfare/set_cloudflare_github_token.py --dry-run
```

Show help:

```bash
python3 infra/cloudfare/set_cloudflare_github_token.py --help
```

Defaults:

- repository: `coumarane/GraphRAG`
- environment: `dev`
- secret name: `CLOUDFLARE_API_TOKEN`

## Script behavior

- Resolves the Cloudflare zone ID from `zone_name`.
- Lists current DNS records with `--list`.
- Lists existing DNS records in the zone.
- Creates missing records.
- Updates existing records when content, TTL, or proxy status changed.
- Skips records that already match the JSON payload.

## Optional arguments

Use a different JSON file:

```bash
python3 infra/cloudfare/apply_dns_records.py --input /path/to/dns_records.json --dry-run
```

Use a different environment variable for the token:

```bash
export MY_CF_TOKEN="your-token-here"
python3 infra/cloudfare/apply_dns_records.py --token-env MY_CF_TOKEN --dry-run
```

Override the zone name from the command line:

```bash
python3 infra/cloudfare/apply_dns_records.py --zone-name chatwithdocs.org --dry-run
```

List the current DNS records in Cloudflare:

```bash
python3 infra/cloudfare/apply_dns_records.py --list
```

## Expected output

```text
CREATE: A api.chatwithdocs.org -> 51.38.19.54 (ttl=1, proxied=True)
UPDATE: A www.chatwithdocs.org -> 51.38.19.54 (ttl=1, proxied=True)
SKIP: A chatwithdocs.org -> 51.38.19.54 (ttl=1, proxied=True)
```

## Notes

- `--dry-run` shows the planned changes without writing to Cloudflare.
- `--list` reads the current records from Cloudflare and does not modify anything.
- The script performs upserts; it does not delete records that are not present in `dns_records.json`.
