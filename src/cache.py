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
    vad_filter: bool | None = None,
    condition_on_previous_text: bool | None = None,
    prompt: str = "",
) -> Path:
    """STT 발화 캐시 경로.

    캐시 키(fingerprint)에 **STT 결과를 바꾸는 모든 설정**을 포함한다:
    모델/언어뿐 아니라 VAD 필터, condition_on_previous_text, Whisper
    initial_prompt(사전/파일명 힌트)까지. 따라서 이 중 하나라도 바꾸면 캐시가
    자동으로 분리되어 같은 음원도 다시 전사한다. (인자를 안 주면 그 항목은 키에서
    빠져 과거와 동일 — 하위호환)
    """
    source = Path(source_path)
    parts: list[str] = [p for p in (model, language) if p]
    if vad_filter is not None:
        parts.append(f"vad={int(bool(vad_filter))}")
    if condition_on_previous_text is not None:
        parts.append(f"cond={int(bool(condition_on_previous_text))}")
    if prompt:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8", errors="surrogatepass")).hexdigest()[:8]
        parts.append(f"p={prompt_hash}")
    variant = "|".join(parts)
    return Path(work_dir) / f"{source.stem}.{_fingerprint(source, variant=variant)}.segments.json"
