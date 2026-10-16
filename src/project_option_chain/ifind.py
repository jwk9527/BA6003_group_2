"""Shared iFinD HTTP API helpers (token is always passed in, never stored)."""

from __future__ import annotations

BASE_URL = "https://quantapi.51ifind.com/api/v1"


def headers(token: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "access_token": token}
