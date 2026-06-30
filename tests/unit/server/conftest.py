"""Shared fixtures for server tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from server.main import app


@pytest.fixture()
def client():
    """Synchronous test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture()
def simple_yxmd() -> bytes:
    """Read the simple_filter fixture as bytes."""
    path = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "simple_filter.yxmd"
    return path.read_bytes()
