"""Shared test fixtures for binance-shioaji-sdk."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest


def _make_response(status_code: int, body: Any) -> MagicMock:
    """Construct a mock httpx.Response with given status / body."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)
    resp.headers = {"content-type": "application/json"}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def make_response():
    """Fixture wrapper for `_make_response` (httpx.Response stub)."""
    return _make_response
