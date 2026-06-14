"""임베딩/코사인 검색 공통 유틸 (RAG·게시판 시맨틱 검색 공유).

embeddings.py(회의록 rag_chunks)와 post_index.py(게시판 post_chunks)가 공유하는
순수 벡터 연산을 모은다. 테이블별 DB 입출력은 각 모듈이 담당한다.

임베딩은 L2 정규화해 저장하므로, 검색 시 쿼리 벡터만 정규화하면 내적 = 코사인 유사도.
저장 형식은 float32 little-endian bytes로, PHP `unpack('g*')`와 호환된다.
"""
from __future__ import annotations

import numpy as np


def l2_normalize(arr: np.ndarray) -> np.ndarray:
    """행 단위 L2 정규화 (영벡터는 그대로)."""
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def embed_texts(
    texts: list[str],
    *,
    model: str = "bge-m3",
    host: str = "http://127.0.0.1:11434",
    batch_size: int = 32,
    timeout: float = 300.0,
) -> np.ndarray:
    """텍스트 리스트 → L2 정규화된 float32 행렬 (N, dim). Ollama 임베딩 API 사용."""
    try:
        from ollama import Client
    except ImportError as e:
        raise RuntimeError("ollama 패키지가 필요합니다: pip install ollama") from e

    client = Client(host=host, timeout=timeout)
    vecs: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = client.embed(model=model, input=batch)
        embs = resp.get("embeddings") if isinstance(resp, dict) else resp.embeddings
        vecs.extend(embs)
    arr = np.asarray(vecs, dtype=np.float32)
    return l2_normalize(arr)


def cosine_topk(
    matrix: np.ndarray,
    qvec: np.ndarray,
    *,
    top_k: int,
    min_score: float = 0.0,
) -> list[tuple[int, float]]:
    """정규화된 행렬·쿼리벡터의 코사인 상위 top_k. [(행 인덱스, 점수)] 반환."""
    if matrix.size == 0:
        return []
    scores = matrix @ qvec
    order = np.argsort(-scores)
    out: list[tuple[int, float]] = []
    for i in order:
        score = float(scores[int(i)])
        if min_score and score < min_score:
            continue
        out.append((int(i), score))
        if len(out) >= max(1, int(top_k)):
            break
    return out
