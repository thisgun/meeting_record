"""WhisperX 기반 STT + 화자 분리.

화자 분리 방식 2가지:
- pyannote (HuggingFace 토큰 + 모델 약관 동의 필요, 정확도 ↑)
- 로컬 (speechbrain ECAPA-TDNN + clustering, 인증 불필요, 정확도 중간)

`hf_token`이 비어있으면 자동으로 로컬 fallback. CPU + int8 환경 기준.
"""
from __future__ import annotations

import gc
import os
from pathlib import Path
from typing import Optional


class TranscribeError(RuntimeError):
    pass


# 프로젝트 내 사전 다운로드한 모델 경로 (Windows symlink 권한 회피용)
_MODELS_DIR = Path(__file__).resolve().parent.parent / "data" / "models"


def _resolve_whisper_model(name: str) -> str:
    """model_name이 단순 이름이면 로컬 폴더 우선 확인, 없으면 그대로 반환."""
    # 사용자가 경로 자체를 지정했으면 그대로 사용
    if os.sep in name or "/" in name:
        return name
    local = _MODELS_DIR / f"faster-whisper-{name}"
    if local.exists() and (local / "model.bin").exists():
        return str(local)
    return name  # HF에서 다운로드 시도


def _load_whisperx():
    try:
        import whisperx
        return whisperx
    except ImportError as e:
        raise TranscribeError(
            "whisperx가 설치되지 않았습니다. 'pip install whisperx'를 실행하세요."
        ) from e


def transcribe_only(
    wav_path: str,
    *,
    model_name: str = "medium",
    language: str = "ko",
    compute_type: str = "int8",
    device: str = "cpu",
    cpu_threads: int = 0,
    batch_size: int = 8,
    vad_filter: bool = True,
    initial_prompt: str = "",
):
    """STT + word align만 수행. 화자 분리는 호출자가 별도 처리.

    Args:
        cpu_threads: 0이면 ctranslate2 기본 (보통 모든 코어). 양수면 명시 지정.
        batch_size: WhisperX transcribe batch (메모리/속도 trade-off).
        vad_filter: faster-whisper의 VAD 사전 필터 (무음 구간 스킵).

    Returns:
        (audio_array, segments_list) — whisperx 내부 형식 그대로
    """
    # whisperx는 bare 'ffmpeg'를 subprocess로 직접 호출하므로 PATH에 보장해 둔다.
    from src.audio import ensure_ffmpeg_on_path
    ensure_ffmpeg_on_path()

    whisperx = _load_whisperx()
    audio = whisperx.load_audio(wav_path)

    resolved = _resolve_whisper_model(model_name)
    if resolved != model_name:
        print(f"[info] Whisper 모델 로컬 사용: {resolved}")

    # WhisperX load_model은 일부 옵션을 ctranslate2 WhisperModel로 전달
    model_kwargs = {"device": device, "compute_type": compute_type, "language": language}
    if cpu_threads > 0:
        # WhisperX → faster_whisper → ctranslate2 WhisperModel(cpu_threads=N)
        model_kwargs["threads"] = cpu_threads
    if vad_filter:
        # WhisperX 자체 VAD를 사용 (기본 활성). vad_options 지정 가능.
        model_kwargs["vad_options"] = {"min_silence_duration_ms": 500}

    if initial_prompt:
        # WhisperX는 asr_options에 initial_prompt 전달
        existing = model_kwargs.get("asr_options", {})
        existing["initial_prompt"] = initial_prompt
        model_kwargs["asr_options"] = existing
        print(f"[info] Whisper initial_prompt: {initial_prompt[:80]}...")

    print(f"[info] Whisper 설정: batch={batch_size}, threads={cpu_threads or 'auto'}, vad={vad_filter}")
    model = whisperx.load_model(resolved, **model_kwargs)
    result = model.transcribe(audio, batch_size=batch_size, language=language)
    del model
    gc.collect()

    try:
        # 한국어 align 모델 로컬 경로 우선
        align_kwargs = {"language_code": language, "device": device}
        local_align = _MODELS_DIR / "wav2vec2-korean"
        if language == "ko" and local_align.exists() and any(local_align.iterdir()):
            align_kwargs["model_name"] = str(local_align)
            print(f"[info] Align 모델 로컬 사용: {local_align}")
        align_model, metadata = whisperx.load_align_model(**align_kwargs)
        result = whisperx.align(
            result["segments"], align_model, metadata, audio, device,
            return_char_alignments=False,
        )
        del align_model
        gc.collect()
    except Exception as e:
        print(f"[warn] align 실패, segment 단위로 진행: {e}")

    return audio, result


def _diarize_pyannote(
    audio,
    result: dict,
    hf_token: str,
    *,
    device: str = "cpu",
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> dict:
    """pyannote diarization → whisperx assign_word_speakers."""
    whisperx = _load_whisperx()
    try:
        from whisperx.diarize import DiarizationPipeline
    except ImportError:
        from whisperx import DiarizationPipeline  # 구버전 호환

    pipeline = DiarizationPipeline(use_auth_token=hf_token, device=device)
    kwargs = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers
    diarize_segments = pipeline(audio, **kwargs)
    return whisperx.assign_word_speakers(diarize_segments, result)


def _segments_from_result(result: dict) -> list[dict]:
    """whisperx result → 정규화된 segment list (speaker 미할당 가능)."""
    out = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0)),
            "speaker": seg.get("speaker") or "SPEAKER_00",
            "text": text,
        })
    return out


def transcribe_and_diarize(
    wav_path: str,
    hf_token: str = "",
    *,
    model_name: str = "medium",
    language: str = "ko",
    compute_type: str = "int8",
    device: str = "cpu",
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    enrollment_db: Optional[str] = None,
    enrollment_threshold: float = 0.75,
    cpu_threads: int = 0,
    batch_size: int = 8,
    vad_filter: bool = True,
    initial_prompt: str = "",
) -> list[dict]:
    """STT + 화자 분리 통합. hf_token이 비어있으면 로컬 (speechbrain) fallback.

    Args:
        hf_token: HuggingFace 토큰. 비어있으면 로컬 diarizer 사용.
        num_speakers: 로컬 diarizer에 전달 (pyannote는 min/max_speakers 사용).
        min_speakers/max_speakers: pyannote에만 적용.

    Returns:
        [{"start": float, "end": float, "speaker": str, "text": str}, ...]
    """
    audio, result = transcribe_only(
        wav_path,
        model_name=model_name,
        language=language,
        compute_type=compute_type,
        device=device,
        cpu_threads=cpu_threads,
        batch_size=batch_size,
        vad_filter=vad_filter,
        initial_prompt=initial_prompt,
    )

    if hf_token:
        # pyannote 경로
        try:
            result = _diarize_pyannote(
                audio, result, hf_token,
                device=device,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )
            return _segments_from_result(result)
        except Exception as e:
            print(f"[warn] pyannote diarization 실패 → 로컬 fallback: {e}")

    # 로컬 fallback (HF 토큰 없거나 pyannote 실패)
    print("[info] 로컬 화자 분리 사용 (speechbrain ECAPA-TDNN)")
    segments = _segments_from_result(result)
    try:
        from src.diarizer_local import diarize_local
    except ImportError:
        from diarizer_local import diarize_local  # 모듈 단독 실행 호환
    return diarize_local(
        wav_path, segments,
        num_speakers=num_speakers,
        enrollment_db=enrollment_db,
        enrollment_threshold=enrollment_threshold,
        device=device,
    )


def remap_speakers(segments: list[dict], prefix: str = "사용자") -> list[dict]:
    """SPEAKER_XX 등장 순서대로 '사용자1', '사용자2', ... 재매핑."""
    mapping: dict[str, str] = {}
    next_idx = 1
    out = []
    for seg in segments:
        raw = seg.get("speaker", "UNKNOWN")
        if raw not in mapping:
            if raw == "UNKNOWN":
                mapping[raw] = "미식별"
            else:
                mapping[raw] = f"{prefix}{next_idx}"
                next_idx += 1
        out.append({**seg, "speaker": mapping[raw]})
    return out


def merge_consecutive(segments: list[dict], gap_sec: float = 1.0) -> list[dict]:
    """같은 화자의 연속 발화를 합친다."""
    if not segments:
        return []
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        last = merged[-1]
        if seg["speaker"] == last["speaker"] and seg["start"] - last["end"] <= gap_sec:
            last["end"] = seg["end"]
            last["text"] = f"{last['text']} {seg['text']}".strip()
        else:
            merged.append(dict(seg))
    return merged


if __name__ == "__main__":
    import json
    import os
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) < 2:
        print("usage: python -m src.transcriber <wav_path> [num_speakers]")
        sys.exit(1)

    n_spk = int(sys.argv[2]) if len(sys.argv) > 2 else None
    segs = transcribe_and_diarize(
        sys.argv[1],
        hf_token=os.getenv("HUGGINGFACE_TOKEN", ""),
        model_name=os.getenv("WHISPER_MODEL", "medium"),
        num_speakers=n_spk,
    )
    segs = merge_consecutive(remap_speakers(segs))
    print(json.dumps(segs, ensure_ascii=False, indent=2))
