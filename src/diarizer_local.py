"""HuggingFace 인증 불필요한 로컬 화자 분리.

speechbrain의 ECAPA-TDNN 화자 임베딩 + scikit-learn AgglomerativeClustering.

- 모델 `speechbrain/spkrec-ecapa-voxceleb`은 HF에서 자동 다운로드되지만
  read-only public 모델이라 토큰/약관 동의 불필요
- CPU 동작
- 정확도는 pyannote보다 낮지만 명확한 화자 구분(서로 다른 사람의 음성)에는 충분
"""
from __future__ import annotations

import gc
from pathlib import Path
from typing import Optional

import numpy as np


class LocalDiarizeError(RuntimeError):
    pass


_ENCODER_CACHE = {}


def clear_encoder_cache() -> None:
    """speechbrain encoder singleton cache를 비워 다음 LLM 단계 메모리를 확보."""
    _ENCODER_CACHE.clear()
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
    except Exception:
        pass


def _get_encoder(savedir: str = "./data/models/spkrec-ecapa-voxceleb", device: str = "cpu"):
    """speechbrain ECAPA-TDNN 임베더 로드 (디바이스별 싱글톤 캐시)."""
    cache_key = f"enc_{device}"
    if cache_key in _ENCODER_CACHE:
        return _ENCODER_CACHE[cache_key]
    try:
        # speechbrain 1.x
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError:
        try:
            # speechbrain 0.5.x fallback
            from speechbrain.pretrained import EncoderClassifier
        except ImportError as e:
            raise LocalDiarizeError(
                "speechbrain이 설치되지 않았습니다: pip install speechbrain"
            ) from e

    # Windows에서 symlink 권한 부족 회피 — COPY 전략 사용
    kwargs = {}
    try:
        from speechbrain.utils.fetching import LocalStrategy
        kwargs["local_strategy"] = LocalStrategy.COPY
    except ImportError:
        pass  # 구버전 speechbrain은 옵션 없음

    Path(savedir).mkdir(parents=True, exist_ok=True)
    enc = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=savedir,
        run_opts={"device": device},
        **kwargs,
    )
    _ENCODER_CACHE[cache_key] = enc
    return enc


def _load_audio_16k_mono(wav_path: str) -> tuple[np.ndarray, int]:
    """16kHz mono float32 ndarray 로드."""
    try:
        import soundfile as sf
    except ImportError as e:
        raise LocalDiarizeError("soundfile 필요: pip install soundfile") from e

    data, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        try:
            import librosa
            data = librosa.resample(data, orig_sr=sr, target_sr=16000)
            sr = 16000
        except ImportError as e:
            raise LocalDiarizeError(
                f"입력 wav가 16kHz가 아닙니다 (현재 {sr}Hz). "
                f"audio.normalize()로 사전 변환하거나 librosa를 설치하세요."
            ) from e
    return data.astype(np.float32, copy=False), sr


def _embed_chunk(encoder, audio_chunk: np.ndarray, device: str = "cpu") -> np.ndarray:
    """ECAPA-TDNN 임베딩 추출. 반환: shape (192,) float32"""
    import torch
    with torch.no_grad():
        tensor = torch.from_numpy(audio_chunk).unsqueeze(0)  # (1, T)
        if device == "cuda":
            tensor = tensor.cuda()
        emb = encoder.encode_batch(tensor)  # (1, 1, 192) or (1, 192)
        emb = emb.squeeze().cpu().numpy().astype(np.float32)
        # L2 정규화 (cosine distance를 위해)
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb


def _estimate_num_speakers(
    embeddings: np.ndarray, *, min_k: int = 1, max_k: int = 8
) -> int:
    """silhouette score로 화자 수 추정."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    n = len(embeddings)
    if n < 2:
        return 1
    max_k = min(max_k, n - 1)
    if max_k < 2:
        return 1

    best_k, best_score = 1, -1.0
    for k in range(max(2, min_k), max_k + 1):
        try:
            labels = AgglomerativeClustering(
                n_clusters=k, metric="cosine", linkage="average"
            ).fit_predict(embeddings)
            if len(set(labels)) < 2:
                continue
            score = silhouette_score(embeddings, labels, metric="cosine")
            if score > best_score:
                best_score, best_k = score, k
        except Exception:
            continue
    # silhouette < 0.1 → 사실상 단일 화자
    return best_k if best_score >= 0.1 else 1


def diarize_local(
    wav_path: str,
    segments: list[dict],
    *,
    num_speakers: Optional[int] = None,
    min_seg_sec: float = 0.5,
    savedir: str = "./data/models/spkrec-ecapa-voxceleb",
    enrollment_db: Optional[str] = None,
    enrollment_threshold: float = 0.75,
    device: str = "cpu",
) -> list[dict]:
    """화자 라벨을 segments에 부여한다.

    Args:
        wav_path: 16kHz mono wav (audio.normalize() 결과 권장)
        segments: WhisperX 발화 [{start, end, text, ...}, ...]
        num_speakers: None이면 silhouette으로 자동 추정
        min_seg_sec: 이보다 짧으면 임베딩 생략 → 직전 화자로 추정
        savedir: 모델 다운로드 저장 위치

    Returns:
        speaker 라벨이 채워진 segments
    """
    if not segments:
        return []

    encoder = _get_encoder(savedir, device=device)
    audio, sr = _load_audio_16k_mono(wav_path)

    embeddings: list[np.ndarray] = []
    emb_idx_per_seg: list[Optional[int]] = []

    for seg in segments:
        start = int(float(seg.get("start", 0.0)) * sr)
        end = int(float(seg.get("end", 0.0)) * sr)
        chunk = audio[start:end]
        if len(chunk) < int(min_seg_sec * sr):
            emb_idx_per_seg.append(None)
            continue
        try:
            emb = _embed_chunk(encoder, chunk, device=device)
            embeddings.append(emb)
            emb_idx_per_seg.append(len(embeddings) - 1)
        except Exception:
            emb_idx_per_seg.append(None)

    if not embeddings:
        return [{**s, "speaker": "SPEAKER_00"} for s in segments]

    emb_matrix = np.stack(embeddings)
    if num_speakers is None:
        num_speakers = _estimate_num_speakers(emb_matrix)
    num_speakers = max(1, min(int(num_speakers), len(emb_matrix)))

    if num_speakers == 1:
        labels = np.zeros(len(emb_matrix), dtype=int)
    else:
        from sklearn.cluster import AgglomerativeClustering
        labels = AgglomerativeClustering(
            n_clusters=num_speakers, metric="cosine", linkage="average"
        ).fit_predict(emb_matrix)

    # Enrollment 매칭 (옵션) — 클러스터 중심을 등록 화자와 비교
    cluster_to_name: dict[int, str] = {}
    if enrollment_db:
        try:
            from src.speaker_registry import SpeakerRegistry
            reg = SpeakerRegistry(enrollment_db)
            if reg.list_all():
                # 클러스터별 중심 임베딩
                centroids: dict[int, np.ndarray] = {}
                for cid in set(labels.tolist()):
                    mask = labels == cid
                    centroid = emb_matrix[mask].mean(axis=0)
                    centroid = centroid / max(np.linalg.norm(centroid), 1e-8)
                    centroids[int(cid)] = centroid.astype(np.float32)
                cluster_to_name = reg.match_clusters(centroids, threshold=enrollment_threshold)
                if cluster_to_name:
                    print(f"[info] 등록 화자 매칭: {cluster_to_name}")
        except Exception as e:
            print(f"[warn] enrollment 매칭 실패: {e}")

    out = []
    last_known = "SPEAKER_00"
    for seg, emb_idx in zip(segments, emb_idx_per_seg):
        if emb_idx is None:
            speaker = last_known
        else:
            cid = int(labels[emb_idx])
            speaker = cluster_to_name.get(cid) or f"SPEAKER_{cid:02d}"
            last_known = speaker
        out.append({**seg, "speaker": speaker})
    return out


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 3:
        print('usage: python -m src.diarizer_local <wav_path> <segments.json> [num_speakers]')
        sys.exit(1)

    with open(sys.argv[2], encoding="utf-8") as f:
        segs = json.load(f)
    n_spk = int(sys.argv[3]) if len(sys.argv) > 3 else None
    result = diarize_local(sys.argv[1], segs, num_speakers=n_spk)
    print(json.dumps(result, ensure_ascii=False, indent=2))
