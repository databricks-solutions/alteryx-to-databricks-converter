"""Materialize uploaded Alteryx files into a working directory.

Wraps the framework-agnostic :mod:`a2d.packaging` extractor, translating its
:class:`~a2d.packaging.PackageError` into HTTP errors and handling plain
(non-package) uploads. A ``.yxzp`` package is extracted so its ``.yxmc`` macros
land beside the workflow, which lets macro expansion resolve them.

Macros can also arrive as their own files (a project's ``.yxmc`` uploads).
:func:`write_macro_library` puts those in one shared folder that every workflow
in the run searches, so a workflow finds a macro by its file name wherever the
reference pointed on the author's machine.
"""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from a2d.packaging import PackageError, PackageTooLargeError, extract_primary_workflow, is_package
from server.settings import settings
from server.utils.validation import sanitize_filename

logger = logging.getLogger("a2d.server.utils.package")


MACRO_SUFFIX = ".yxmc"


def is_macro(filename: str) -> bool:
    """True for an Alteryx macro file (``.yxmc``)."""
    return filename.lower().endswith(MACRO_SUFFIX)


def macro_files(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """The macros among ``files``."""
    return [(name, content) for name, content in files if is_macro(name)]


def _library_name(filename: str) -> str | None:
    """The name a macro is stored under in the shared folder.

    Its own file name, not :func:`sanitize_filename`'s rewrite: workflows refer to
    macros by name (``Standard Cleanse.yxmc``), so the name has to survive. Only
    the last path component is kept and control characters are refused, so a
    name can't place a file outside the folder.
    """
    name = PurePosixPath(filename.replace("\\", "/")).name
    if name in ("", ".", "..") or any(ord(ch) < 32 for ch in name) or len(name.encode()) > 255:
        return None
    return name


def write_macro_library(macros: list[tuple[str, bytes]], base_dir: Path) -> list[Path]:
    """Write ``macros`` into one folder under ``base_dir`` and return it as a
    one-item list of macro search paths (empty when there are no macros)."""
    if not macros:
        return []
    library = base_dir / "_macros"
    library.mkdir(parents=True, exist_ok=True)
    for filename, content in macros:
        name = _library_name(filename)
        if name is None:
            logger.warning("Skipping macro with an unusable file name: %r", filename)
            continue
        (library / name).write_bytes(content)
    return [library]


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
        except PackageTooLargeError as exc:
            # Size-guard breach is a payload problem, not a malformed request.
            raise HTTPException(status_code=413, detail=f"{filename}: {exc}") from exc
        except PackageError as exc:
            raise HTTPException(status_code=400, detail=f"{filename}: {exc}") from exc
        return workflow_path, True

    path = dest_dir / sanitize_filename(filename)
    path.write_bytes(content)
    return path, False


def materialize_uploads(
    files: list[tuple[str, bytes]],
    base_dir: Path,
    skipped: list[str] | None = None,
) -> list[Path]:
    """Materialize many uploads, each into its own subdirectory of ``base_dir``.

    Per-file subdirectories keep distinct uploads from colliding after
    ``sanitize_filename`` (which is lossy) and give each extracted package its
    own macro namespace. Returns the resolved workflow path for each upload.

    A ``.yxzp`` that cannot be extracted is skipped (and logged), not fatal: the
    batch analyzers this feeds don't isolate a per-file parse error, so one bad
    package would otherwise abort the whole multi-file analyze/portfolio request.
    Pass ``skipped`` to receive the names of any dropped files so the caller can
    surface them (silently omitting files makes estate totals look complete when
    they are not).
    """
    paths: list[Path] = []
    for index, (filename, content) in enumerate(files):
        sub = base_dir / f"upload_{index}"
        sub.mkdir(parents=True, exist_ok=True)
        try:
            workflow_path, _ = materialize_upload(content, filename, sub)
        except HTTPException as exc:
            logger.warning("Skipping unreadable package %s: %s", filename, exc.detail)
            if skipped is not None:
                skipped.append(filename)
            continue
        paths.append(workflow_path)
    return paths


def upload_name_for(file_path: str | Path, base_dir: Path, files: list[tuple[str, bytes]]) -> str:
    """Map a path produced by :func:`materialize_uploads` back to the uploaded
    file's name.

    Upload *i* is written under ``base_dir/upload_<i>/`` (a package's primary
    workflow may sit deeper), so the first path component identifies it. This is
    how an analysis row for a ``.yxzp`` finds the package it came from.
    """
    try:
        first = Path(file_path).resolve().relative_to(base_dir.resolve()).parts[0]
        return files[int(first.removeprefix("upload_"))][0]
    except (ValueError, IndexError):
        return Path(file_path).name


def analyze_each(analyzer, paths: list[Path], base_dir: Path, files: list[tuple[str, bytes]], skipped: list[str]):
    """Run ``analyzer.analyze_files`` one path at a time, so one unreadable
    workflow is reported in ``skipped`` instead of failing the whole estate."""
    analyses: list = []
    for path in paths:
        before = len(analyses)
        try:
            analyses.extend(analyzer.analyze_files([path]))
        except Exception:
            logger.warning("Skipping workflow that could not be analyzed: %s", path, exc_info=True)
        if len(analyses) == before:
            skipped.append(upload_name_for(path, base_dir, files))
    return analyses
