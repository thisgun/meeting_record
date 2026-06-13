"""HuggingFace 인증 불필요한 로컬 화자 분리.

speechbrain의 ECAPA-TDNN 화자 임베딩 + scikit-learn AgglomerativeClustering.

- 모델 `speechbrain/spkrec-ecapa-voxceleb`은 HF에서 자동 다운로드되지만
  read-only public 모델이라 토큰/약관 동의 불필요
- CPU 동작
- 정확도는 pyannote보다 낮지만 명확한 화자 구분(서로 다른 사람의 음성)에는 충분
"""
from __future__ import annotations

from collections import Counter
import gc
from pathlib import Path
from typing import Optional

import numpy as np


class LocalDiarizeError(RuntimeError):
    pass


_ENCODER_CACHE = {}

# 로컬 speechbrain 화자 분리는 짧은 발화/잡음에 과분리되지만,
# 다인원 회의에서는 말수가 적은 참석자를 과하게 병합하는 것도 치명적이다.
# 자동 추정은 1인 과분리 방지와 다인원 보존 사이에서 균형을 잡는다.
_AUTO_MIN_SILHOUETTE = 0.24
_AUTO_MIN_CENTROID_DISTANCE = 0.18
_AUTO_MIN_CLUSTER_SHARE = 0.04
_AUTO_MIN_CLUSTER_EMBEDDINGS = 2
_AUTO_SIMILAR_CENTROID_DISTANCE = 0.18
_AUTO_MODERATE_SIMILAR_CENTROID_DISTANCE = 0.12
_AUTO_MULTI_SIMILAR_CENTROID_DISTANCE = 0.08
_AUTO_TINY_CLUSTER_MAX_SEC = 5.0
_AUTO_MODERATE_TINY_CLUSTER_MAX_SEC = 2.0
_AUTO_TINY_CLUSTER_MAX_SHARE = 0.08
_AUTO_SCORE_TOLERANCE = 0.07
_AUTO_HIGH_K_SCORE_TOLERANCE = 0.11
_DIARIZE_CHUNK_SEC = 2.5
_DIARIZE_CHUNK_OVERLAP_SEC = 0.4


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


def _normalize_vector(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm <= 1e-8:
        return vec.astype(np.float32, copy=False)
    return (vec / norm).astype(np.float32, copy=False)


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - np.clip(np.dot(_normalize_vector(a), _normalize_vector(b)), -1.0, 1.0))


def _cluster_centroids(embeddings: np.ndarray, labels: np.ndarray) -> dict[int, np.ndarray]:
    centroids: dict[int, np.ndarray] = {}
    for cid in sorted(set(labels.tolist())):
        mask = labels == cid
        centroids[int(cid)] = _normalize_vector(embeddings[mask].mean(axis=0))
    return centroids


def _min_centroid_distance(embeddings: np.ndarray, labels: np.ndarray) -> float:
    centroids = _cluster_centroids(embeddings, labels)
    ids = list(centroids)
    if len(ids) < 2:
        return 1.0
    best = 1.0
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            best = min(best, _cosine_distance(centroids[left], centroids[right]))
    return best


def _renumber_labels(labels: np.ndarray) -> np.ndarray:
    mapping = {old: new for new, old in enumerate(sorted(set(labels.tolist())))}
    return np.array([mapping[int(label)] for label in labels], dtype=int)


def _speaker_quality_ok(embeddings: np.ndarray, labels: np.ndarray, score: float) -> bool:
    counts = Counter(labels.tolist())
    n = len(labels)
    if len(counts) < 2:
        return False
    if score < _AUTO_MIN_SILHOUETTE:
        return False
    if min(counts.values()) < _AUTO_MIN_CLUSTER_EMBEDDINGS:
        return False
    if min(counts.values()) / max(n, 1) < _AUTO_MIN_CLUSTER_SHARE:
        return False
    if _min_centroid_distance(embeddings, labels) < _AUTO_MIN_CENTROID_DISTANCE:
        return False
    return True


def _estimate_num_speakers(
    embeddings: np.ndarray, *, min_k: int = 1, max_k: int = 8
) -> int:
    """silhouette score로 화자 수 추정.

    speechbrain 임베딩은 한 사람의 짧은 발화도 여러 클러스터로 갈라질 수 있다.
    자동 모드에서는 silhouette만 보지 않고 클러스터 크기와 중심 거리까지 확인해서
    확신이 낮으면 단일 화자로 접는다.
    """
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    n = len(embeddings)
    if n < 2:
        return 1
    max_k = min(max_k, n - 1)
    if max_k < 2:
        return 1

    candidates: list[tuple[int, float]] = []
    for k in range(max(2, min_k), max_k + 1):
        try:
            labels = AgglomerativeClustering(
                n_clusters=k, metric="cosine", linkage="average"
            ).fit_predict(embeddings)
            if len(set(labels)) < 2:
                continue
            score = silhouette_score(embeddings, labels, metric="cosine")
            if _speaker_quality_ok(embeddings, labels, score):
                candidates.append((k, float(score)))
        except Exception:
            continue
    if not candidates:
        return 1

    best_score = max(score for _, score in candidates)
    tolerance = (
        _AUTO_HIGH_K_SCORE_TOLERANCE
        if any(k >= 4 for k, _ in candidates)
        else _AUTO_SCORE_TOLERANCE
    )
    viable = [k for k, score in candidates if score >= best_score - tolerance]
    return max(viable) if viable else max(candidates, key=lambda item: item[1])[0]


def _iter_segment_windows(
    seg: dict,
    *,
    sr: int,
    min_seg_sec: float,
    chunk_sec: float = _DIARIZE_CHUNK_SEC,
    overlap_sec: float = _DIARIZE_CHUNK_OVERLAP_SEC,
) -> list[tuple[int, int, float, float]]:
    """STT 발화를 화자 임베딩용 짧은 창으로 나눈다."""
    start_sec = max(0.0, float(seg.get("start", 0.0)))
    end_sec = max(start_sec, float(seg.get("end", start_sec)))
    duration = end_sec - start_sec
    if duration < min_seg_sec:
        return []

    if duration <= chunk_sec:
        start = int(start_sec * sr)
        end = int(end_sec * sr)
        return [(start, end, start_sec, end_sec)]

    stride_sec = max(min_seg_sec, chunk_sec - overlap_sec)
    windows: list[tuple[int, int, float, float]] = []
    cur = start_sec
    while cur < end_sec:
        chunk_end_sec = min(cur + chunk_sec, end_sec)
        if chunk_end_sec - cur >= min_seg_sec:
            windows.append((
                int(cur * sr),
                int(chunk_end_sec * sr),
                cur,
                chunk_end_sec,
            ))
        if chunk_end_sec >= end_sec:
            break
        cur += stride_sec

    if windows and end_sec - windows[-1][3] >= min_seg_sec:
        chunk_start_sec = max(start_sec, end_sec - chunk_sec)
        if chunk_start_sec > windows[-1][2] + 0.25:
            windows.append((
                int(chunk_start_sec * sr),
                int(end_sec * sr),
                chunk_start_sec,
                end_sec,
            ))
    return windows


def _cluster_durations(
    labels: np.ndarray,
    chunk_meta: list[tuple[int, float, float]],
) -> dict[int, float]:
    durations = {int(cid): 0.0 for cid in set(labels.tolist())}
    for emb_idx, (_, start, end) in enumerate(chunk_meta):
        cid = int(labels[emb_idx])
        durations[cid] = durations.get(cid, 0.0) + max(0.0, end - start)
    return durations


def _nearest_temporal_label(
    target: int,
    labels: np.ndarray,
    chunk_meta: list[tuple[int, float, float]],
) -> Optional[int]:
    best_label: Optional[int] = None
    best_distance: Optional[int] = None
    chunk_labels = [int(labels[i]) for i in range(len(chunk_meta))]
    for i, label in enumerate(chunk_labels):
        if label != target:
            continue
        for step in range(1, len(chunk_labels)):
            candidates = []
            if i - step >= 0:
                candidates.append(chunk_labels[i - step])
            if i + step < len(chunk_labels):
                candidates.append(chunk_labels[i + step])
            for candidate in candidates:
                if candidate != target:
                    if best_distance is None or step < best_distance:
                        best_distance = step
                        best_label = candidate
            if best_distance == step:
                break
    return best_label


def _nearest_centroid_label(
    target: int,
    embeddings: np.ndarray,
    labels: np.ndarray,
) -> tuple[Optional[int], float]:
    centroids = _cluster_centroids(embeddings, labels)
    if target not in centroids:
        return None, 1.0
    best_label: Optional[int] = None
    best_distance = 1.0
    for cid, centroid in centroids.items():
        if cid == target:
            continue
        distance = _cosine_distance(centroids[target], centroid)
        if distance < best_distance:
            best_distance = distance
            best_label = cid
    return best_label, best_distance


def _merge_label(labels: np.ndarray, source: int, target: int) -> np.ndarray:
    merged = labels.copy()
    merged[merged == source] = target
    return _renumber_labels(merged)


def _merge_similar_clusters(
    embeddings: np.ndarray,
    labels: np.ndarray,
    *,
    max_distance: float,
) -> np.ndarray:
    while len(set(labels.tolist())) > 1:
        centroids = _cluster_centroids(embeddings, labels)
        best_pair: tuple[int, int] | None = None
        best_distance = 1.0
        ids = list(centroids)
        for i, left in enumerate(ids):
            for right in ids[i + 1:]:
                distance = _cosine_distance(centroids[left], centroids[right])
                if distance < best_distance:
                    best_distance = distance
                    best_pair = (left, right)
        if best_pair is None or best_distance >= max_distance:
            break
        counts = Counter(labels.tolist())
        left, right = best_pair
        source, target = (left, right) if counts[left] <= counts[right] else (right, left)
        labels = _merge_label(labels, source, target)
    return labels


def _merge_tiny_clusters(
    embeddings: np.ndarray,
    labels: np.ndarray,
    chunk_meta: list[tuple[int, float, float]],
    *,
    max_duration_sec: float,
) -> np.ndarray:
    while len(set(labels.tolist())) > 1:
        counts = Counter(labels.tolist())
        durations = _cluster_durations(labels, chunk_meta)
        candidates = []
        for cid, count in counts.items():
            share = count / max(len(labels), 1)
            duration = durations.get(int(cid), 0.0)
            if count == 1 and duration <= max_duration_sec:
                candidates.append((duration, count, int(cid)))
            elif share <= _AUTO_TINY_CLUSTER_MAX_SHARE and duration <= max_duration_sec:
                candidates.append((duration, count, int(cid)))
        if not candidates:
            break
        _, _, source = sorted(candidates)[0]
        nearest_centroid, centroid_distance = _nearest_centroid_label(source, embeddings, labels)
        target = _nearest_temporal_label(source, labels, chunk_meta) or nearest_centroid
        if target is None:
            break
        if centroid_distance > _AUTO_MIN_CENTROID_DISTANCE and counts[source] > 1:
            break
        labels = _merge_label(labels, source, target)
    return labels


def _apply_conservative_auto_merge(
    embeddings: np.ndarray,
    labels: np.ndarray,
    chunk_meta: list[tuple[int, float, float]],
) -> np.ndarray:
    n_labels = len(set(labels.tolist()))
    if n_labels >= 4:
        similar_distance = _AUTO_MULTI_SIMILAR_CENTROID_DISTANCE
        tiny_duration = 0.0
    elif n_labels == 3:
        similar_distance = _AUTO_MODERATE_SIMILAR_CENTROID_DISTANCE
        tiny_duration = _AUTO_MODERATE_TINY_CLUSTER_MAX_SEC
    else:
        similar_distance = _AUTO_SIMILAR_CENTROID_DISTANCE
        tiny_duration = _AUTO_TINY_CLUSTER_MAX_SEC

    labels = _merge_similar_clusters(
        embeddings,
        _renumber_labels(labels),
        max_distance=similar_distance,
    )
    if tiny_duration > 0:
        labels = _merge_tiny_clusters(
            embeddings,
            labels,
            chunk_meta,
            max_duration_sec=tiny_duration,
        )
    return _renumber_labels(labels)


def _pick_segment_label(
    seg_idx: int,
    labels: np.ndarray,
    chunk_meta: list[tuple[int, float, float]],
) -> Optional[int]:
    weights: dict[int, float] = {}
    for emb_idx, (chunk_seg_idx, start, end) in enumerate(chunk_meta):
        if chunk_seg_idx != seg_idx:
            continue
        cid = int(labels[emb_idx])
        weights[cid] = weights.get(cid, 0.0) + max(0.0, end - start)
    if not weights:
        return None
    return max(weights.items(), key=lambda item: (item[1], -item[0]))[0]


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
    chunk_meta: list[tuple[int, float, float]] = []

    for seg_idx, seg in enumerate(segments):
        windows = _iter_segment_windows(seg, sr=sr, min_seg_sec=min_seg_sec)
        for start, end, start_sec, end_sec in windows:
            chunk = audio[start:end]
            if len(chunk) < int(min_seg_sec * sr):
                continue
            try:
                emb = _embed_chunk(encoder, chunk, device=device)
                embeddings.append(emb)
                chunk_meta.append((seg_idx, start_sec, end_sec))
            except Exception:
                continue

    if not embeddings:
        return [{**s, "speaker": "SPEAKER_00"} for s in segments]

    if len(embeddings) > len(segments):
        print(
            "[info] 로컬 화자 임베딩: "
            f"발화 {len(segments)}건 → 창 {len(embeddings)}개"
        )

    emb_matrix = np.stack(embeddings)
    auto_speakers = num_speakers is None
    if auto_speakers:
        num_speakers = _estimate_num_speakers(emb_matrix)
        if num_speakers > 1:
            print(f"[info] 로컬 화자 자동 추정: {num_speakers}명 후보")
    num_speakers = max(1, min(int(num_speakers), len(emb_matrix)))

    if num_speakers == 1:
        labels = np.zeros(len(emb_matrix), dtype=int)
    else:
        from sklearn.cluster import AgglomerativeClustering
        labels = AgglomerativeClustering(
            n_clusters=num_speakers, metric="cosine", linkage="average"
        ).fit_predict(emb_matrix)
        if auto_speakers:
            before_merge = len(set(labels.tolist()))
            labels = _apply_conservative_auto_merge(
                emb_matrix, labels, chunk_meta
            )
            after_merge = len(set(labels.tolist()))
            if after_merge < before_merge:
                print(
                    "[info] 로컬 화자 자동 보정: "
                    f"{before_merge}개 → {after_merge}개 "
                    "(짧거나 유사한 클러스터 병합)"
                )

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
    for seg_idx, seg in enumerate(segments):
        label = _pick_segment_label(seg_idx, labels, chunk_meta)
        if label is None:
            speaker = last_known
        else:
            cid = int(label)
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
