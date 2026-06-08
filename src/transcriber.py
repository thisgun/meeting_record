"""faster-whisper 기반 STT + 화자 분리.

이전에는 WhisperX를 사용했으나, WhisperX가 `ctranslate2==4.4.0`을 고정(pin)해
Python 3.13/3.14용 wheel이 없어 설치가 실패했다. faster-whisper를 직접 사용하면
ctranslate2 4.8+(3.9~3.14 wheel 제공)를 쓸 수 있어 최신 파이썬까지 지원된다.

- 단어 타임스탬프: faster-whisper의 `word_timestamps=True` (WhisperX의 wav2vec2
  정렬 대체. 정밀도는 약간 낮지만 별도 정렬 모델/의존성이 필요 없다).
- 배치 추론: faster-whisper `BatchedInferencePipeline` (실패 시 순차 처리로 폴백).

화자 분리 방식 2가지:
- pyannote (HuggingFace 토큰 + 모델 약관 동의 필요, 정확도 ↑) — 선택 설치
- 로컬 (speechbrain ECAPA-TDNN + clustering, 인증 불필요, 정확도 중간)

`hf_token`이 비어있거나 pyannote 미설치/실패 시 자동으로 로컬 fallback. CPU + int8 기준.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np

from src.runtime_memory import release_torch_memory


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


def _load_faster_whisper():
    try:
        import faster_whisper
        return faster_whisper
    except ImportError as e:
        raise TranscribeError(
            "faster-whisper가 설치되지 않았습니다. 'pip install faster-whisper'를 실행하세요."
        ) from e


def _materialize_segments(seg_iter) -> list[dict]:
    """faster-whisper Segment 제너레이터 → 정규화된 dict 리스트.

    제너레이터를 즉시 소비하므로, 호출자는 try 안에서 호출해 배치 실패를
    잡고 순차 처리로 재시도할 수 있다.
    """
    out: list[dict] = []
    for s in seg_iter:
        words = []
        for w in (getattr(s, "words", None) or []):
            words.append({"start": w.start, "end": w.end, "word": w.word})
        item = {
            "start": s.start,
            "end": s.end,
            "text": s.text,
            "words": words,
        }
        for key in ("avg_logprob", "no_speech_prob", "compression_ratio"):
            value = getattr(s, key, None)
            if value is not None:
                item[key] = value
        out.append(item)
    return out


def _transcribe_segments(model, audio, batch_size: int, transcribe_kwargs: dict):
    """배치 추론 우선, 실패 시 순차 처리로 폴백. (segments, language) 반환."""
    if batch_size and batch_size > 1:
        try:
            from faster_whisper import BatchedInferencePipeline
            engine = BatchedInferencePipeline(model=model)
            seg_iter, info = engine.transcribe(
                audio, batch_size=batch_size, **transcribe_kwargs
            )
            return _materialize_segments(seg_iter), info.language
        except Exception as e:
            # 배치 미지원 버전이거나 처리 중 오류 → 순차 처리로 재시도
            print(f"[warn] 배치 추론 실패 → 순차 처리로 재시도: {e}")
    seg_iter, info = model.transcribe(audio, **transcribe_kwargs)
    return _materialize_segments(seg_iter), info.language


def _segments_stats(segments: list[dict]) -> tuple[int, float, int]:
    speech_sec = 0.0
    chars = 0
    for seg in segments:
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", start) or start)
        speech_sec += max(0.0, end - start)
        chars += len((seg.get("text") or "").strip())
    return len(segments), speech_sec, chars


def _should_retry_without_vad(segments: list[dict], audio_duration_sec: float) -> bool:
    """VAD가 말소리를 과하게 버렸을 가능성이 크면 재시도."""
    if audio_duration_sec < 60:
        return False
    count, speech_sec, chars = _segments_stats(segments)
    if count == 0 or chars < 100:
        return True
    minutes = max(audio_duration_sec / 60.0, 1e-6)
    segment_density = count / minutes
    speech_ratio = speech_sec / max(audio_duration_sec, 1e-6)
    if audio_duration_sec >= 180 and segment_density < 2.0:
        return True
    if audio_duration_sec >= 120 and speech_ratio < 0.12:
        return True
    return False


def _prefer_vad_retry(
    original: list[dict],
    retry: list[dict],
    audio_duration_sec: float,
) -> bool:
    orig_count, orig_speech, orig_chars = _segments_stats(original)
    retry_count, retry_speech, retry_chars = _segments_stats(retry)
    if retry_count == 0 or retry_chars == 0:
        return False
    if retry_chars < max(50, int(orig_chars * 0.8)):
        return False
    if retry_chars >= max(orig_chars + 100, int(orig_chars * 1.2)) and retry_count >= orig_count:
        return True
    if retry_count >= max(orig_count + 3, int(orig_count * 1.5)) and retry_chars >= int(orig_chars * 0.9):
        return True
    if retry_speech >= orig_speech + max(15.0, audio_duration_sec * 0.1) and retry_chars >= orig_chars:
        return True
    return False


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
    """STT(+단어 타임스탬프)만 수행. 화자 분리는 호출자가 별도 처리.

    Args:
        cpu_threads: 0이면 ctranslate2 기본 (보통 모든 코어). 양수면 명시 지정.
        batch_size: 배치 추론 크기 (>1이면 BatchedInferencePipeline 사용).
        vad_filter: faster-whisper의 VAD 사전 필터 (무음 구간 스킵).

    Returns:
        (audio_array, result_dict) — result는 {"segments": [...], "language": ...}
        각 segment: {"start", "end", "text", "words": [{"start","end","word"}, ...]}
    """
    # 16kHz mono float32 디코딩은 faster-whisper(PyAV)가 처리하지만,
    # 상류 단계(pydub 등)가 PATH의 ffmpeg를 쓰므로 보장해 둔다.
    from src.audio import ensure_ffmpeg_on_path
    ensure_ffmpeg_on_path()

    fw = _load_faster_whisper()
    from faster_whisper import WhisperModel
    try:
        decode_audio = fw.decode_audio  # 최신 버전: 패키지 최상위 노출
    except AttributeError:
        from faster_whisper.audio import decode_audio  # 구버전 호환

    # PyAV 기반 디코딩 (16kHz mono float32). pyannote 경로에서 재사용.
    audio = decode_audio(wav_path, sampling_rate=16000)

    resolved = _resolve_whisper_model(model_name)
    if resolved != model_name:
        print(f"[info] Whisper 모델 로컬 사용: {resolved}")

    model_kwargs = {"device": device, "compute_type": compute_type}
    if cpu_threads > 0:
        model_kwargs["cpu_threads"] = cpu_threads

    print(f"[info] Whisper 설정: batch={batch_size}, threads={cpu_threads or 'auto'}, vad={vad_filter}")
    model = WhisperModel(resolved, **model_kwargs)

    transcribe_kwargs = {
        "language": language,
        "beam_size": 5,
        "vad_filter": vad_filter,
        "vad_parameters": {"min_silence_duration_ms": 500},
        # WhisperX의 wav2vec2 정렬 대체: 모델 내장 단어 타임스탬프
        "word_timestamps": True,
    }
    if initial_prompt:
        transcribe_kwargs["initial_prompt"] = initial_prompt
        print(f"[info] Whisper initial_prompt: {initial_prompt[:80]}...")

    try:
        segments, _lang = _transcribe_segments(model, audio, batch_size, transcribe_kwargs)
        audio_duration_sec = float(len(audio)) / 16000.0 if hasattr(audio, "__len__") else 0.0
        if vad_filter and _should_retry_without_vad(segments, audio_duration_sec):
            count, speech_sec, chars = _segments_stats(segments)
            print(
                "[warn] VAD 적용 결과가 너무 적어 보입니다 "
                f"(발화 {count}건, 음성 {speech_sec:.1f}/{audio_duration_sec:.1f}s, 글자 {chars}자). "
                "VAD를 끄고 STT를 한 번 더 시도합니다."
            )
            retry_kwargs = dict(transcribe_kwargs)
            retry_kwargs["vad_filter"] = False
            retry_segments, _retry_lang = _transcribe_segments(
                model, audio, batch_size, retry_kwargs
            )
            if _prefer_vad_retry(segments, retry_segments, audio_duration_sec):
                r_count, r_speech, r_chars = _segments_stats(retry_segments)
                print(
                    "[info] VAD off 재시도 결과 채택 "
                    f"(발화 {r_count}건, 음성 {r_speech:.1f}s, 글자 {r_chars}자)"
                )
                segments = retry_segments
            else:
                print("[info] VAD off 재시도 결과가 더 낫지 않아 기존 STT 결과를 사용합니다.")
        result = {"segments": segments, "language": language}
    finally:
        del model
        release_torch_memory("Whisper 모델 해제", verbose=False)

    return audio, result


def _assign_speakers_by_overlap(turns: list[tuple], result: dict) -> dict:
    """화자 turn(start, end, speaker) 목록을 시간 겹침 기준으로 발화에 할당.

    WhisperX의 assign_word_speakers 대체. 각 segment(및 word)에 대해 가장 많이
    겹치는 화자를 부여한다.
    """
    def pick(start: float, end: float):
        best, best_ov = None, 0.0
        for ts, te, spk in turns:
            ov = min(end, te) - max(start, ts)
            if ov > best_ov:
                best_ov, best = ov, spk
        return best

    for seg in result.get("segments", []):
        s0 = float(seg.get("start", 0.0))
        s1 = float(seg.get("end", 0.0))
        spk = pick(s0, s1)
        if spk is not None:
            seg["speaker"] = spk
        for w in (seg.get("words") or []):
            wspk = pick(float(w.get("start", s0)), float(w.get("end", s1)))
            if wspk is not None:
                w["speaker"] = wspk
    return result


def _diarize_pyannote(
    audio,
    result: dict,
    hf_token: str,
    *,
    device: str = "cpu",
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> dict:
    """pyannote.audio 직접 호출 → 시간 겹침 기반 화자 할당.

    pyannote.audio는 선택 의존성(최신 Python에서는 미설치일 수 있음). 미설치/실패
    시 예외를 던지면 호출자가 로컬 diarizer로 fallback 한다.
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise TranscribeError(
            "pyannote.audio가 설치되지 않았습니다 (선택 의존성). "
            "고정밀 화자 분리를 쓰려면 'pip install pyannote.audio' 후 HF 토큰을 설정하세요."
        ) from e

    import torch

    pipeline = None
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
        )
        if pipeline is None:
            raise TranscribeError(
                "pyannote 모델 로드 실패 — HF 토큰 또는 모델 약관 동의를 확인하세요."
            )
        try:
            pipeline.to(torch.device(device))
        except Exception:
            pass  # device 이동 실패해도 CPU로 동작

        # (channel, time) 형태 waveform 텐서로 전달 (파일 재디코딩 회피)
        waveform = torch.from_numpy(np.ascontiguousarray(audio)).unsqueeze(0)
        diar_input = {"waveform": waveform, "sample_rate": 16000}
        kwargs = {}
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers

        diarization = pipeline(diar_input, **kwargs)
        turns = [
            (float(seg.start), float(seg.end), spk)
            for seg, _track, spk in diarization.itertracks(yield_label=True)
        ]
        return _assign_speakers_by_overlap(turns, result)
    finally:
        del pipeline
        release_torch_memory("pyannote 모델 해제", verbose=False)


def _segments_from_result(result: dict) -> list[dict]:
    """result → 정규화된 segment list (speaker 미할당 가능)."""
    out = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        item = {
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0)),
            "speaker": seg.get("speaker") or "SPEAKER_00",
            "text": text,
        }
        for key in ("avg_logprob", "no_speech_prob", "compression_ratio"):
            if key in seg and seg.get(key) is not None:
                item[key] = seg.get(key)
        out.append(item)
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
    audio = None
    result = None
    try:
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
            # pyannote 경로 (선택 의존성, 실패 시 아래 로컬 fallback)
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

        # 로컬 fallback (HF 토큰 없거나 pyannote 실패/미설치)
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
    finally:
        del audio
        del result
        release_torch_memory("STT/화자 분리 반환 전", verbose=False)


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
            for key in ("no_speech_prob", "compression_ratio"):
                if seg.get(key) is not None:
                    last[key] = max(float(last.get(key, 0.0) or 0.0), float(seg[key]))
            if seg.get("avg_logprob") is not None:
                last["avg_logprob"] = min(
                    float(last.get("avg_logprob", seg["avg_logprob"]) or seg["avg_logprob"]),
                    float(seg["avg_logprob"]),
                )
        else:
            merged.append(dict(seg))
    return merged


if __name__ == "__main__":
    import json
    import sys

    from config import load_config

    if len(sys.argv) < 2:
        print("usage: python -m src.transcriber <wav_path> [num_speakers]")
        sys.exit(1)

    cfg = load_config()
    n_spk = int(sys.argv[2]) if len(sys.argv) > 2 else None
    segs = transcribe_and_diarize(
        sys.argv[1],
        hf_token=cfg.huggingface_token,
        model_name=cfg.whisper_model,
        num_speakers=n_spk,
    )
    segs = merge_consecutive(remap_speakers(segs))
    print(json.dumps(segs, ensure_ascii=False, indent=2))
