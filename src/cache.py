"""Cache path helpers for transcript artifacts."""
from __future__ import annotations

import hashlib
from pathlib import Path


def _fingerprint(path: Path) -> str:
    resolved = path.resolve()
    try:
        st = resolved.stat()
        raw = f"{resolved}|{st.st_size}|{st.st_mtime_ns}"
    except OSError:
        raw = str(resolved)
    return hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]


def segments_cache_path(source_path: str | Path, work_dir: str | Path) -> Path:
    """Return a stable, collision-resistant cache path for STT segments."""
    source = Path(source_path)
    return Path(work_dir) / f"{source.stem}.{_fingerprint(source)}.segments.json"
