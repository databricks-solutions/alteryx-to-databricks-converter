"""Shared fixtures for server tests."""

from __future__ import annotations

import io
import zipfile
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


@pytest.fixture()
def simple_yxzp(simple_yxmd) -> bytes:
    """A .yxzp package wrapping the simple_filter workflow (as a .yxwz)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("simple_filter.yxwz", simple_yxmd)
    return buf.getvalue()
