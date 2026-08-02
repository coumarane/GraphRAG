# 17 — Coding Standards

## Python

- strict type annotations;
- Python 3.13 or verified newer compatible version;
- Pydantic v2;
- SQLAlchemy 2 typed mappings;
- `asyncio` or AnyIO-compatible async I/O;
- UTC-aware datetimes;
- enums for controlled vocabulary;
- dataclasses or Pydantic models for stable contracts.

## Design

- dependency inversion;
- cohesive modules;
- explicit service and repository interfaces;
- no infrastructure imports in domain code;
- no hidden I/O in property access;
- explicit transactions;
- context managers for resources;
- typed domain exceptions.

## Error handling

- never use bare `except`;
- classify transient and permanent errors;
- include safe machine-readable error codes;
- retry only idempotent operations or operations protected by idempotency keys;
- preserve original exception chaining.

## Quality tools

- Ruff format and lint;
- mypy strict for domain/application;
- pytest and pytest-asyncio;
- test coverage with meaningful thresholds;
- dependency vulnerability scanning;
- container scanning.

## Documentation

Public protocols and application use cases require docstrings. Complex architectural choices require ADRs under `docs/adr/`.
