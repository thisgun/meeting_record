"""그누보드5 metting API 클라이언트.

c:\\dev2\\g5_meeting_api\\ 의 PHP endpoint에 HTTP로 회의 게시글/댓글을 등록한다.

멀티 타겟 지원 (로컬 + 원격 동시 등록):
    G5MultiClient([G5MettingApiClient(local), G5MettingApiClient(remote)])
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

import requests


def build_clients_from_env(cfg) -> list["G5MettingApiClient"]:
    """cfg에서 G5 클라이언트 목록 생성 (단일 또는 멀티 타겟).

    .env 옵션:
        G5_TARGETS=local,remote     ← 멀티 타겟 활성화 (지정한 prefix들의 설정 사용)
        G5_API_BASE_LOCAL=http://127.0.0.1/g5_meeting_api
        G5_API_TOKEN_LOCAL=...
        G5_API_BASE_REMOTE=https://thisgun01.mycafe24.com/g5_meeting_api
        G5_API_TOKEN_REMOTE=...

    G5_TARGETS 가 비어있으면 기존 단일 설정 (G5_API_BASE, G5_API_TOKEN) 사용.
    """
    import os
    targets = (os.getenv("G5_TARGETS") or "").strip()
    bo_table = cfg.g5_bo_table

    if not targets:
        # 단일 설정 (기존 방식)
        if not cfg.g5_api_base or not cfg.g5_api_token:
            return []
        return [G5MettingApiClient(
            api_base=cfg.g5_api_base, api_token=cfg.g5_api_token, bo_table=bo_table,
            name="default",
        )]

    clients: list[G5MettingApiClient] = []
    for name in [t.strip().upper() for t in targets.split(",") if t.strip()]:
        base = (os.getenv(f"G5_API_BASE_{name}") or "").strip()
        token = (os.getenv(f"G5_API_TOKEN_{name}") or "").strip()
        if not base or not token:
            print(f"[warn] G5 target '{name.lower()}' — G5_API_BASE_{name} 또는 G5_API_TOKEN_{name} 누락, 스킵")
            continue
        clients.append(G5MettingApiClient(
            api_base=base, api_token=token, bo_table=bo_table, name=name.lower(),
        ))
    return clients


def legacy_default_target_name(clients: list["G5MettingApiClient"]) -> str | None:
    """기존 단일 설정(default) 동기화 행을 어느 named target으로 볼지 결정한다."""
    import os

    names = {c.name for c in clients}
    explicit = (os.getenv("G5_LEGACY_TARGET") or "").strip().lower()
    if explicit:
        return explicit if explicit in names and explicit != "default" else None
    if len(clients) == 1 and clients[0].name != "default":
        return clients[0].name
    if "remote" in names:
        return "remote"
    return None


class G5ApiError(RuntimeError):
    pass


class G5ClientBase(ABC):
    @abstractmethod
    def health(self) -> dict: ...

    @abstractmethod
    def create_post(
        self,
        subject: str,
        content: str,
        bo_table: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict: ...

    @abstractmethod
    def create_comment(
        self,
        wr_id: int,
        content: str,
        bo_table: Optional[str] = None,
        author_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict: ...

    @abstractmethod
    def update_post(
        self,
        wr_id: int,
        subject: Optional[str] = None,
        content: Optional[str] = None,
        bo_table: Optional[str] = None,
    ) -> dict: ...

    @abstractmethod
    def list_comments(self, wr_id: int, bo_table: Optional[str] = None) -> list[dict]: ...

    @abstractmethod
    def update_comment(
        self,
        comment_id: int,
        content: Optional[str] = None,
        bo_table: Optional[str] = None,
        author_name: Optional[str] = None,
    ) -> dict: ...

    @abstractmethod
    def delete_post(self, wr_id: int, bo_table: Optional[str] = None) -> dict: ...


class G5MettingApiClient(G5ClientBase):
    """c:\\dev2\\g5_meeting_api 의 PHP endpoint 호출용."""

    def __init__(
        self,
        api_base: str,
        api_token: str,
        bo_table: str = "meeting",
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        retry_backoff_sec: float = 1.5,
        name: str = "default",
    ):
        self.api_base = api_base.rstrip("/")
        self.api_token = api_token
        self.bo_table = bo_table
        self.name = name
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_sec = retry_backoff_sec
        self._session = requests.Session()
        self._session.headers.update({"X-API-Token": api_token})

    def __repr__(self):
        return f"G5MettingApiClient(name={self.name!r}, base={self.api_base!r})"

    def _post(self, path: str, payload: dict, *, max_retries: Optional[int] = None) -> dict:
        url = f"{self.api_base}/{path.lstrip('/')}"
        last_err: Optional[Exception] = None
        retries = self.max_retries if max_retries is None else max(0, int(max_retries))
        for attempt in range(retries + 1):
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
                if attempt < retries:
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

    def create_post(
        self,
        subject: str,
        content: str,
        bo_table: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        payload = {
            "subject": subject,
            "content": content,
            "bo_table": bo_table or self.bo_table,
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return self._post("post.php", payload, max_retries=0)

    def create_comment(
        self,
        wr_id: int,
        content: str,
        bo_table: Optional[str] = None,
        author_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        payload = {
            "wr_id": int(wr_id),
            "content": content,
            "bo_table": bo_table or self.bo_table,
        }
        if author_name:
            payload["author_name"] = author_name
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return self._post("comment.php", payload, max_retries=0)

    def update_post(
        self,
        wr_id: int,
        subject: Optional[str] = None,
        content: Optional[str] = None,
        bo_table: Optional[str] = None,
    ) -> dict:
        payload = {
            "wr_id": int(wr_id),
            "bo_table": bo_table or self.bo_table,
        }
        if subject is not None:
            payload["subject"] = subject
        if content is not None:
            payload["content"] = content
        return self._post("update_post.php", payload)

    def list_comments(self, wr_id: int, bo_table: Optional[str] = None) -> list[dict]:
        payload = {
            "wr_id": int(wr_id),
            "bo_table": bo_table or self.bo_table,
        }
        data = self._post("list_comments.php", payload)
        return list(data.get("comments") or [])

    def update_comment(
        self,
        comment_id: int,
        content: Optional[str] = None,
        bo_table: Optional[str] = None,
        author_name: Optional[str] = None,
    ) -> dict:
        payload = {
            "comment_id": int(comment_id),
            "bo_table": bo_table or self.bo_table,
        }
        if content is not None:
            payload["content"] = content
        if author_name is not None:
            payload["author_name"] = author_name
        return self._post("update_comment.php", payload)

    def delete_post(self, wr_id: int, bo_table: Optional[str] = None) -> dict:
        payload = {
            "wr_id": int(wr_id),
            "bo_table": bo_table or self.bo_table,
        }
        return self._post("delete_post.php", payload, max_retries=0)


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
        api_base=os.getenv("G5_API_BASE", "http://127.0.0.1/g5_meeting_api"),
        api_token=os.getenv("G5_API_TOKEN", ""),
        bo_table=os.getenv("G5_BO_TABLE", "meeting"),
    )

    cmd = sys.argv[1] if len(sys.argv) > 1 else "health"
    if cmd == "health":
        print(json.dumps(client.health(), ensure_ascii=False, indent=2))
    elif cmd == "test":
        wr_id = None
        try:
            post = client.create_post(
                "API 클라이언트 테스트",
                "## 개요\n메인 파이프라인 통합 전 테스트입니다.",
                idempotency_key="meeting_record:g5_client_test:post",
            )
            print("POST:", post)
            wr_id = int(post["wr_id"])
            for idx, s in enumerate([
                {"speaker": "사용자1", "start": 0.0, "end": 1.0, "text": "안녕하세요"},
                {"speaker": "사용자2", "start": 1.5, "end": 3.0, "text": "반갑습니다"},
            ], start=1):
                c = client.create_comment(
                    wr_id,
                    format_utterance_comment(s),
                    idempotency_key=f"meeting_record:g5_client_test:comment:{idx}",
                )
                print("COMMENT:", c)
        finally:
            if wr_id:
                deleted = client.delete_post(wr_id)
                print("DELETE:", deleted)
    else:
        print(f"unknown cmd: {cmd}. usage: python -m src.g5_client [health|test]")
