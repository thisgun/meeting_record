"""임베딩/코사인 검색 공통 유틸 단위 테스트."""
import numpy as np

from src.vectorstore import cosine_topk, l2_normalize


def test_l2_normalize_unit_and_zero() -> None:
    arr = np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    n = l2_normalize(arr)
    assert abs(float(np.linalg.norm(n[0])) - 1.0) < 1e-6
    assert np.allclose(n[1], [0.0, 0.0])  # 영벡터는 그대로(0 나눗셈 방지)


def test_cosine_topk_ranks_by_similarity() -> None:
    mat = l2_normalize(np.array([[1, 0, 0], [0.7, 0.7, 0], [0, 1, 0]], dtype=np.float32))
    q = np.array([1, 0, 0], dtype=np.float32)
    res = cosine_topk(mat, q, top_k=2)
    assert [i for i, _ in res] == [0, 1]  # 0행이 가장 유사
    assert res[0][1] >= res[1][1]


def test_cosine_topk_min_score_filters() -> None:
    mat = l2_normalize(np.array([[1, 0, 0], [0.7, 0.7, 0], [0, 1, 0]], dtype=np.float32))
    q = np.array([1, 0, 0], dtype=np.float32)
    res = cosine_topk(mat, q, top_k=5, min_score=0.9)
    assert all(s >= 0.9 for _, s in res)
    assert 2 not in [i for i, _ in res]  # 직교(점수 0) 제외


def test_cosine_topk_empty() -> None:
    assert cosine_topk(np.empty((0, 0), dtype=np.float32), np.array([1.0], dtype=np.float32), top_k=3) == []
