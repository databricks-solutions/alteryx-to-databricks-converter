"""HTTP header helpers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import quote


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    """A ``Content-Disposition`` value that is safe for any file name.

    Workflow names come from customers and can hold quotes, non-ASCII letters
    (``売上.yxmd``) or control characters. Starlette encodes headers as latin-1,
    so a raw non-ASCII name raises and the response becomes a 500. This sends an
    ASCII-only ``filename`` fallback plus the real name as RFC 5987
    ``filename*``, which browsers prefer.
    """
    name = PurePosixPath(str(filename).replace("\\", "/")).name or "download"
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._") or "download"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"
