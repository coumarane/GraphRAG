"""Helpers for validating domain payloads against ``contracts/*.schema.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"


@lru_cache(maxsize=16)
def load_contract_schema(name: str) -> dict[str, Any]:
    """Load a YAML JSON Schema contract by file stem."""
    path = CONTRACTS_DIR / f"{name}.schema.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"Contract schema root must be a mapping: {path}"
        raise TypeError(msg)
    return raw


def assert_matches_contract(name: str, payload: dict[str, Any]) -> None:
    """Raise ``jsonschema.ValidationError`` when payload violates the contract."""
    schema = load_contract_schema(name)
    Draft202012Validator(schema).validate(payload)
