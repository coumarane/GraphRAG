#!/usr/bin/env python3
"""Compatibility wrapper: upload/ingest a document via enterprise-rag CLI."""

from __future__ import annotations

import sys

from enterprise_rag.cli.main import app


def main() -> None:
    # Rewrite to `enterprise-rag ingest ...` while preserving argv tail.
    sys.argv = [sys.argv[0], "ingest", *sys.argv[1:]]
    app()


if __name__ == "__main__":
    main()
