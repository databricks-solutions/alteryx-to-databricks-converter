"""Materialize uploaded Alteryx files into a working directory.

Wraps the framework-agnostic :mod:`a2d.packaging` extractor, translating its
:class:`~a2d.packaging.PackageError` into HTTP errors and handling plain
(non-package) uploads. A ``.yxzp`` package is extracted so its ``.yxmc`` macros
land beside the workflow, which lets macro expansion resolve them.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

from a2d.packaging import PackageError, extract_primary_workflow, is_package
from server.settings import settings
from server.utils.validation import sanitize_filename

logger = logging.getLogger("a2d.server.utils.package")


def materialize_upload(content: bytes, filename: str, dest_dir: Path) -> tuple[Path, bool]:
    """Write one upload into ``dest_dir`` and return ``(workflow_path, was_package)``.

    For a ``.yxzp`` the archive is extracted into ``dest_dir`` and the primary
    workflow path is returned with its macros co-located. For any other file the
    bytes are written verbatim under a sanitized name.
    """
    if is_package(filename):
        try:
            workflow_path = extract_primary_workflow(
                content,
                dest_dir,
                max_members=settings.max_package_members,
                max_total_bytes=settings.max_package_extracted_bytes,
            )
        except PackageError as exc:
            raise HTTPException(status_code=400, detail=f"{filename}: {exc}") from exc
        return workflow_path, True

    path = dest_dir / sanitize_filename(filename)
    path.write_bytes(content)
    return path, False


def materialize_uploads(files: list[tuple[str, bytes]], base_dir: Path) -> list[Path]:
    """Materialize many uploads, each into its own subdirectory of ``base_dir``.

    Per-file subdirectories keep distinct uploads from colliding after
    ``sanitize_filename`` (which is lossy) and give each extracted package its
    own macro namespace. Returns the resolved workflow path for each upload.

    A ``.yxzp`` that cannot be extracted is skipped (and logged), not fatal: the
    batch analyzers this feeds don't isolate a per-file parse error, so one bad
    package would otherwise abort the whole multi-file analyze/portfolio request.
    """
    paths: list[Path] = []
    for index, (filename, content) in enumerate(files):
        sub = base_dir / f"upload_{index}"
        sub.mkdir(parents=True, exist_ok=True)
        try:
            workflow_path, _ = materialize_upload(content, filename, sub)
        except HTTPException as exc:
            logger.warning("Skipping unreadable package %s: %s", filename, exc.detail)
            continue
        paths.append(workflow_path)
    return paths
