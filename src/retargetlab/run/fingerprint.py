"""Stable hashes for recipes and other pydantic payloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from retargetlab.contracts import Recipe


def canonical_json_bytes(value: BaseModel | dict[str, Any]) -> bytes:
    """Serialize a payload independent of key insertion order or whitespace."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    """Hash one canonical byte sequence."""

    return hashlib.sha256(payload).hexdigest()


def recipe_sha256(recipe: Recipe) -> str:
    """Return the recipe hash recorded beside every run recipe."""

    return sha256_bytes(canonical_json_bytes(recipe))
