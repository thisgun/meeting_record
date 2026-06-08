"""Cache path helpers for transcript artifacts."""
from __future__ import annotations

import hashlib
from pathlib import Path


def _fingerprint(path: Path, *, variant: str = "") -> str:
    resolved = path.resolve()
    try:
        st = resolved.stat()
        raw = f"{resolved}|{st.st_size}|{st.st_mtime_ns}"
    except OSError:
        raw = str(resolved)
    if variant:
        raw = f"{raw}|{variant}"
    return hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]


def segments_cache_path(
    source_path: str | Path,
    work_dir: str | Path,
    *,
    model: str = "",
    language: str = "",
) -> Path:
    """STT 발화 캐시 경로.

    캐시 키(fingerprint)에 STT 모델/언어를 포함한다. 따라서 `WHISPER_MODEL`을
    바꾸면 캐시가 자동으로 분리되어, 같은 음원도 새 모델로 다시 전사한다.
    (모델/언어를 안 주면 과거와 동일한 키 — 하위호환)
    """
    source = Path(source_path)
    variant = "|".join(p for p in (model, language) if p)
    return Path(work_dir) / f"{source.stem}.{_fingerprint(source, variant=variant)}.segments.json"
