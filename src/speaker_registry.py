"""화자 등록부.

등록된 사람들의 음성 임베딩을 SQLite BLOB로 저장하고,
회의 처리 시 cosine 유사도로 매칭.

사용:
    from src.speaker_registry import SpeakerRegistry
    reg = SpeakerRegistry("./data/meetings.db")
    reg.enroll("장관님", "./samples/장관님.wav")
    name = reg.match(embedding)  # → "장관님" 또는 None
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np


SPEAKERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS speakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    embedding BLOB NOT NULL,        -- numpy float32 (192,) bytes
    samples_count INTEGER DEFAULT 1,
    sample_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def _connect(db_path: str | Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """L2 정규화 후 dot product. 두 벡터 모두 unit이면 cosine."""
    a = _norm(a.astype(np.float32))
    b = _norm(b.astype(np.float32))
    return float(np.dot(a, b))


def _extract_embedding(wav_path: str | Path, device: str = "cpu") -> np.ndarray:
    """음성 파일에서 ECAPA-TDNN 임베딩 추출 (전체 파일 단일 임베딩)."""
    from src.diarizer_local import _get_encoder, _load_audio_16k_mono, _embed_chunk
    encoder = _get_encoder(device=device)
    audio, _ = _load_audio_16k_mono(str(wav_path))
    return _embed_chunk(encoder, audio, device=device)


class SpeakerRegistry:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(self.db_path) as conn:
            conn.executescript(SPEAKERS_SCHEMA)

    def enroll(self, name: str, audio_path: str | Path) -> dict:
        """음성 샘플로 화자 등록 또는 갱신.

        같은 이름이 이미 있으면 임베딩을 평균내서 갱신 (samples_count +1).
        """
        name = name.strip()
        if not name:
            raise ValueError("name이 비어있습니다")

        emb = _extract_embedding(audio_path)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, embedding, samples_count FROM speakers WHERE name=?",
                (name,),
            ).fetchone()
            if row:
                # 기존 임베딩과 평균 (등록 횟수 가중)
                prev = np.frombuffer(row["embedding"], dtype=np.float32)
                n = row["samples_count"]
                merged = _norm((prev * n + emb) / (n + 1))
                conn.execute(
                    "UPDATE speakers SET embedding=?, samples_count=?, sample_path=?, updated_at=? WHERE id=?",
                    (merged.tobytes(), n + 1, str(audio_path), now, row["id"]),
                )
                return {"name": name, "samples_count": n + 1, "action": "updated"}
            else:
                conn.execute(
                    "INSERT INTO speakers (name, embedding, samples_count, sample_path, created_at, updated_at) VALUES (?, ?, 1, ?, ?, ?)",
                    (name, _norm(emb).tobytes(), str(audio_path), now, now),
                )
                return {"name": name, "samples_count": 1, "action": "added"}

    def delete(self, name: str) -> int:
        with _connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM speakers WHERE name=?", (name,))
            return cur.rowcount

    def list_all(self) -> list[dict]:
        with _connect(self.db_path) as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id, name, samples_count, sample_path, created_at, updated_at FROM speakers ORDER BY name"
            ).fetchall()]

    def all_embeddings(self) -> list[tuple[str, np.ndarray]]:
        """매칭용. (name, embedding) 리스트."""
        with _connect(self.db_path) as conn:
            rows = conn.execute("SELECT name, embedding FROM speakers").fetchall()
        return [(r["name"], np.frombuffer(r["embedding"], dtype=np.float32)) for r in rows]

    def match(self, embedding: np.ndarray, threshold: float = 0.75) -> Optional[str]:
        """단일 임베딩 → 가장 유사한 등록 화자명. 임계값 미만이면 None."""
        best_name, best_score = None, -1.0
        for name, ref in self.all_embeddings():
            score = _cosine(embedding, ref)
            if score > best_score:
                best_name, best_score = name, score
        return best_name if best_score >= threshold else None

    def match_clusters(
        self,
        cluster_centroids: dict[int, np.ndarray],
        threshold: float = 0.75,
    ) -> dict[int, str]:
        """클러스터 ID → 등록된 화자명 매핑 (임계값 미만은 매핑 안 함).

        cluster_centroids: {0: ndarray, 1: ndarray, ...}
        반환: {0: "장관님", 2: "김부장님"} (매핑된 것만)
        """
        result = {}
        registered = self.all_embeddings()
        if not registered:
            return result
        for cid, centroid in cluster_centroids.items():
            best_name, best_score = None, -1.0
            for name, ref in registered:
                score = _cosine(centroid, ref)
                if score > best_score:
                    best_name, best_score = name, score
            if best_score >= threshold:
                result[cid] = best_name
        return result
