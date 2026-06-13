import numpy as np
import pytest

from src import diarizer_local as diarizer


def _norm(rows):
    arr = np.array(rows, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.maximum(norms, 1e-8)


def test_estimate_num_speakers_keeps_similar_embeddings_as_one() -> None:
    pytest.importorskip("sklearn")
    embeddings = _norm([
        [1.00, 0.00, 0.00],
        [0.99, 0.08, 0.00],
        [0.99, -0.07, 0.00],
        [0.98, 0.15, 0.00],
        [0.98, -0.14, 0.00],
        [0.97, 0.22, 0.00],
    ])

    assert diarizer._estimate_num_speakers(embeddings) == 1


def test_estimate_num_speakers_detects_clear_two_speaker_split() -> None:
    pytest.importorskip("sklearn")
    embeddings = _norm([
        [1.00, 0.00, 0.00],
        [0.99, 0.04, 0.00],
        [0.98, -0.05, 0.00],
        [0.00, 1.00, 0.00],
        [0.03, 0.99, 0.00],
        [-0.04, 0.98, 0.00],
    ])

    assert diarizer._estimate_num_speakers(embeddings) == 2


def test_estimate_num_speakers_preserves_clear_five_speaker_split() -> None:
    pytest.importorskip("sklearn")
    embeddings = _norm([
        [1.00, 0.00, 0.00, 0.00, 0.00],
        [0.99, 0.03, 0.00, 0.00, 0.00],
        [0.98, -0.04, 0.00, 0.00, 0.00],
        [0.00, 1.00, 0.00, 0.00, 0.00],
        [0.03, 0.99, 0.00, 0.00, 0.00],
        [-0.04, 0.98, 0.00, 0.00, 0.00],
        [0.00, 0.00, 1.00, 0.00, 0.00],
        [0.00, 0.02, 0.99, 0.00, 0.00],
        [0.00, -0.03, 0.98, 0.00, 0.00],
        [0.00, 0.00, 0.00, 1.00, 0.00],
        [0.00, 0.00, 0.03, 0.99, 0.00],
        [0.00, 0.00, -0.03, 0.98, 0.00],
        [0.00, 0.00, 0.00, 0.00, 1.00],
        [0.00, 0.00, 0.00, 0.03, 0.99],
        [0.00, 0.00, 0.00, -0.03, 0.98],
    ])

    assert diarizer._estimate_num_speakers(embeddings) == 5


def test_conservative_auto_merge_absorbs_one_short_tiny_cluster() -> None:
    embeddings = _norm([
        [1.00, 0.00, 0.00],
        [0.98, 0.05, 0.00],
        [0.00, 1.00, 0.00],
        [0.99, -0.04, 0.00],
    ])
    labels = np.array([0, 0, 1, 0], dtype=int)
    chunk_meta = [
        (0, 0.0, 3.0),
        (1, 3.2, 6.0),
        (2, 6.1, 7.0),
        (3, 7.1, 10.0),
    ]

    merged = diarizer._apply_conservative_auto_merge(
        embeddings, labels, chunk_meta
    )

    assert set(merged.tolist()) == {0}


def test_auto_merge_does_not_absorb_short_cluster_in_multi_speaker_case() -> None:
    embeddings = _norm([
        [1.00, 0.00, 0.00, 0.00, 0.00],
        [0.98, 0.04, 0.00, 0.00, 0.00],
        [0.00, 1.00, 0.00, 0.00, 0.00],
        [0.00, 0.02, 0.99, 0.00, 0.00],
        [0.00, 0.00, 0.00, 1.00, 0.00],
        [0.00, 0.00, 0.00, 0.03, 0.99],
    ])
    labels = np.array([0, 0, 1, 2, 3, 4], dtype=int)
    chunk_meta = [
        (0, 0.0, 4.0),
        (1, 4.1, 8.0),
        (2, 8.2, 9.0),
        (3, 9.1, 10.0),
        (4, 10.1, 11.0),
        (5, 11.1, 12.0),
    ]

    merged = diarizer._apply_conservative_auto_merge(
        embeddings, labels, chunk_meta
    )

    assert len(set(merged.tolist())) == 5


def test_iter_segment_windows_splits_long_segments() -> None:
    windows = diarizer._iter_segment_windows(
        {"start": 10.0, "end": 18.0},
        sr=16000,
        min_seg_sec=0.5,
        chunk_sec=2.5,
        overlap_sec=0.4,
    )

    assert len(windows) > 1
    assert windows[0][2] == pytest.approx(10.0)
    assert windows[-1][3] == pytest.approx(18.0)


def test_pick_segment_label_uses_chunk_duration_majority() -> None:
    labels = np.array([0, 1, 1], dtype=int)
    chunk_meta = [
        (0, 0.0, 1.0),
        (0, 1.0, 2.5),
        (0, 2.5, 4.0),
    ]

    assert diarizer._pick_segment_label(0, labels, chunk_meta) == 1
