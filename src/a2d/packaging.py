"""Alteryx ``.yxzp`` package handling.

A ``.yxzp`` is a plain ZIP archive that bundles an analytic app (``.yxwz``) or a
workflow (``.yxmd``) together with its supporting macros (``.yxmc``) and, often,
sample data. This module extracts such a package safely and locates the primary
workflow to convert, leaving the macros co-located beside it so macro expansion
(``config.expand_macros``) can resolve them by their original relative paths.

Pure standard library and framework-agnostic: the CLI and the FastAPI server
both build on it. Callers translate :class:`PackageError` into their own error
surface (a CLI message or an HTTP 400/413).
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path, PurePosixPath

PACKAGE_SUFFIX = ".yxzp"

# Extensions that can act as the primary workflow inside a package. Macros
# (``.yxmc``) are supporting files, not the entry point, so they are excluded.
PRIMARY_WORKFLOW_SUFFIXES: tuple[str, ...] = (".yxmd", ".yxwz")

# Guards against hostile archives (zip bombs / oversized packages). Generous
# enough for a real analytic-app package, small enough to bound memory and disk.
MAX_MEMBERS = 1024
MAX_TOTAL_EXTRACTED_BYTES = 200 * 1024 * 1024  # 200 MB uncompressed


class PackageError(Exception):
    """Raised when a ``.yxzp`` package cannot be safely extracted or resolved."""


def is_package(name: str | os.PathLike[str]) -> bool:
    """Return True if ``name`` has the ``.yxzp`` package suffix."""
    return PurePosixPath(str(name)).suffix.lower() == PACKAGE_SUFFIX


def extract_package(
    source: bytes | str | os.PathLike[str],
    dest_dir: Path,
    *,
    max_members: int = MAX_MEMBERS,
    max_total_bytes: int = MAX_TOTAL_EXTRACTED_BYTES,
) -> list[Path]:
    """Safely extract a ``.yxzp`` archive into ``dest_dir``.

    ``source`` may be the raw archive bytes or a path to a ``.yxzp`` on disk.
    Returns the extracted file paths (directory entries omitted).

    Guards, all raising :class:`PackageError`:

    * **zip-slip** — an entry that resolves outside ``dest_dir`` is rejected;
    * **zip-bomb** — extraction stops once ``max_total_bytes`` of decompressed
      output is exceeded (counted on the bytes actually written, not the header);
    * **member count** — an archive with more than ``max_members`` entries is
      rejected before any extraction.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()

    try:
        opener = io.BytesIO(source) if isinstance(source, bytes) else os.fspath(source)
        archive = zipfile.ZipFile(opener)
    except zipfile.BadZipFile as exc:
        raise PackageError("not a valid .yxzp package (bad ZIP archive)") from exc

    extracted: list[Path] = []
    with archive as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > max_members:
            raise PackageError(f"package has too many entries (max {max_members})")
        total = 0
        for info in infos:
            target = (dest_dir / info.filename).resolve()
            if target != dest_root and not str(target).startswith(str(dest_root) + os.sep):
                raise PackageError(f"unsafe path in package: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(65_536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_total_bytes:
                        raise PackageError(
                            f"package expands beyond the {max_total_bytes // (1024 * 1024)} MB limit"
                        )
                    out.write(chunk)
            extracted.append(target)
    return extracted


def find_primary_workflow(paths: list[Path], root: Path) -> Path:
    """Pick the primary workflow among extracted ``paths``.

    Prefers a single ``.yxmd``/``.yxwz``; when several exist, prefers the one
    closest to the package root. Raises :class:`PackageError` when there is no
    workflow or the choice is ambiguous.
    """
    candidates = [p for p in paths if p.suffix.lower() in PRIMARY_WORKFLOW_SUFFIXES]
    if not candidates:
        raise PackageError("package contains no .yxmd or .yxwz workflow")
    if len(candidates) == 1:
        return candidates[0]

    root_resolved = root.resolve()

    def depth(p: Path) -> int:
        return len(p.resolve().relative_to(root_resolved).parts)

    min_depth = min(depth(p) for p in candidates)
    shallowest = [p for p in candidates if depth(p) == min_depth]
    if len(shallowest) == 1:
        return shallowest[0]
    names = ", ".join(sorted(p.name for p in shallowest))
    raise PackageError(
        "package has multiple candidate workflows; unclear which is primary "
        f"({names}) — unzip it and convert the intended workflow directly"
    )


def extract_primary_workflow(
    source: bytes | str | os.PathLike[str],
    dest_dir: Path,
    *,
    max_members: int = MAX_MEMBERS,
    max_total_bytes: int = MAX_TOTAL_EXTRACTED_BYTES,
) -> Path:
    """Extract a package and return its primary workflow path (macros co-located)."""
    extracted = extract_package(
        source, dest_dir, max_members=max_members, max_total_bytes=max_total_bytes
    )
    return find_primary_workflow(extracted, dest_dir)
