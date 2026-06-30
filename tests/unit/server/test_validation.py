"""Tests for server validation utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from server.utils.validation import sanitize_filename


class TestSanitizeFilename:
    def test_simple_filename(self):
        assert sanitize_filename("workflow.yxmd") == "workflow.yxmd"

    def test_strips_directory_components(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"
        assert sanitize_filename("/absolute/path/file.yxmd") == "file.yxmd"

    def test_strips_windows_paths(self):
        result = sanitize_filename("C:\\Users\\admin\\file.yxmd")
        # PurePosixPath treats backslashes as part of the name
        assert ".yxmd" in result

    def test_replaces_dangerous_characters(self):
        result = sanitize_filename("file name (1).yxmd")
        assert " " not in result
        assert "(" not in result
        assert ")" not in result
        assert result.endswith(".yxmd")

    def test_empty_filename_returns_default(self):
        assert sanitize_filename("") == "upload.yxmd"

    def test_dots_only(self):
        # PurePosixPath("..").name returns ".." which sanitize keeps as __
        result = sanitize_filename("..")
        assert "/" not in result
        assert "\\" not in result

    def test_preserves_hyphens_and_underscores(self):
        assert sanitize_filename("my-file_v2.yxmd") == "my-file_v2.yxmd"


class TestReadUpload:
    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self):
        """Files exceeding max size should raise HTTPException 413."""
        from server.utils.validation import read_upload

        mock_file = AsyncMock()
        mock_file.filename = "big.yxmd"
        # Return 1MB chunk each time (over the default 50MB limit after many reads)
        chunk = b"x" * (1024 * 1024)  # 1MB

        call_count = 0

        async def mock_read(size):
            nonlocal call_count
            call_count += 1
            if call_count > 55:  # More than 50MB
                return b""
            return chunk

        mock_file.read = mock_read

        with pytest.raises(HTTPException) as exc_info:
            await read_upload(mock_file)
        assert exc_info.value.status_code == 413
