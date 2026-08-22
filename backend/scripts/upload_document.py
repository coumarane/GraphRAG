#!/usr/bin/env python3
"""Compatibility wrapper: upload/ingest a document via graph-rag CLI."""

from __future__ import annotations

import sys

from graph_rag.cli.main import app


def main() -> None:
    # Rewrite to `graph-rag ingest ...` while preserving argv tail.
    sys.argv = [sys.argv[0], "ingest", *sys.argv[1:]]
    app()


if __name__ == "__main__":
    main()
