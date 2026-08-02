#!/usr/bin/env python3
"""Compatibility wrapper: query documents via enterprise-rag CLI."""

from __future__ import annotations

import sys

from enterprise_rag.cli.main import app


def main() -> None:
    sys.argv = [sys.argv[0], "query", *sys.argv[1:]]
    app()


if __name__ == "__main__":
    main()
