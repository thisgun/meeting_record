"""그누보드5 metting API 클라이언트.

c:\\dev2\\g5_metting_api\\ 의 PHP endpoint에 HTTP로 회의 게시글/댓글을 등록한다.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

import requests


class G5ApiError(RuntimeError):
    pass


class G5ClientBase(ABC):
    @abstractmethod
    def health(self) -> dict: ...

    @abstractmethod
    def create_post(self, subject: str, content: str, bo_table: Optional[str] = None) -> dict: ...

    @abstractmethod
    def create_comment(
        self,
        wr_id: int,
        content: str,
        bo_table: Optional[str] = None,
        author_name: Optional[str] = None,
    ) -> dict: ...


class G5MettingApiClient(G5ClientBase):
    """c:\\dev2\\g5_metting_api 의 PHP endpoint 호출용."""

    def __init__(
        self,
        api_base: str,
        api_token: str,
        bo_table: str = "metting",
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        retry_backoff_sec: float = 1.5,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_token = api_token
        self.bo_table = bo_table
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_sec = retry_backoff_sec
        self._session = requests.Session()
        self._session.headers.update({"X-API-Token": api_token})

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.api_base}/{path.lstrip('/')}"
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                r = self._session.post(url, json=payload, timeout=self.timeout)
                try:
                    data = r.json()
                except ValueError:
                    raise G5ApiError(f"Non-JSON response from {url}: {r.text[:500]}")
                if r.status_code >= 400 or not data.get("ok"):
                    raise G5ApiError(
                        f"{url} → HTTP {r.status_code}: {data.get('error') or data}"
                    )
                return data
            except (requests.RequestException, G5ApiError) as e:
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_sec * (attempt + 1))
                    continue
                raise G5ApiError(f"Failed after {attempt + 1} attempts: {e}") from e
        raise G5ApiError(f"Unreachable, last_err={last_err}")  # pragma: no cover

    def _get(self, path: str) -> dict:
        url = f"{self.api_base}/{path.lstrip('/')}"
        r = self._session.get(url, timeout=self.timeout)
        try:
            data = r.json()
        except ValueError:
            raise G5ApiError(f"Non-JSON response from {url}: {r.text[:500]}")
        if r.status_code >= 400 or not data.get("ok"):
            raise G5ApiError(f"{url} → HTTP {r.status_code}: {data}")
        return data

    def health(self) -> dict:
        return self._get("health.php")

    def create_post(self, subject: str, content: str, bo_table: Optional[str] = None) -> dict:
        payload = {
            "subject": subject,
            "content": content,
            "bo_table": bo_table or self.bo_table,
        }
        return self._post("post.php", payload)

    def create_comment(
        self,
        wr_id: int,
        content: str,
        bo_table: Optional[str] = None,
        author_name: Optional[str] = None,
    ) -> dict:
        payload = {
            "wr_id": int(wr_id),
            "content": content,
            "bo_table": bo_table or self.bo_table,
        }
        if author_name:
            payload["author_name"] = author_name
        return self._post("comment.php", payload)


def format_utterance_comment(utterance: dict) -> str:
    """발화 dict → 댓글 본문 (간단한 포맷)."""
    speaker = utterance.get("speaker", "?")
    start = float(utterance.get("start", 0.0))
    text = (utterance.get("text") or "").strip()
    mm, ss = divmod(int(start), 60)
    return f"[{mm:02d}:{ss:02d}] {speaker}: {text}"


if __name__ == "__main__":
    import json
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    client = G5MettingApiClient(
        api_base=os.getenv("G5_API_BASE", "http://127.0.0.1/g5_metting_api"),
        api_token=os.getenv("G5_API_TOKEN", ""),
        bo_table=os.getenv("G5_BO_TABLE", "metting"),
    )

    cmd = sys.argv[1] if len(sys.argv) > 1 else "health"
    if cmd == "health":
        print(json.dumps(client.health(), ensure_ascii=False, indent=2))
    elif cmd == "test":
        post = client.create_post(
            "API 클라이언트 테스트",
            "## 개요\n메인 파이프라인 통합 전 테스트입니다.",
        )
        print("POST:", post)
        wr_id = post["wr_id"]
        for s in [
            {"speaker": "사용자1", "start": 0.0, "end": 1.0, "text": "안녕하세요"},
            {"speaker": "사용자2", "start": 1.5, "end": 3.0, "text": "반갑습니다"},
        ]:
            c = client.create_comment(wr_id, format_utterance_comment(s))
            print("COMMENT:", c)
    else:
        print(f"unknown cmd: {cmd}. usage: python -m src.g5_client [health|test]")
