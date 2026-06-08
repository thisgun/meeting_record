import sqlite3
from pathlib import Path

from src import storage


def test_save_search_and_sync_target(tmp_path: Path) -> None:
    db_path = tmp_path / "meetings.db"

    meeting_id = storage.save_meeting(
        db_path,
        source_file="sample.mp3",
        title="샘플 회의",
        summary_md="## 요약\n- 테스트",
        duration_sec=12.3,
        utterances=[
            {"speaker": "SPEAKER_00", "start": 0, "end": 2, "text": "안녕하세요"},
            {"speaker": "SPEAKER_01", "start": 2, "end": 5, "text": "반갑습니다"},
        ],
    )

    meeting = storage.get_meeting(db_path, meeting_id)

    assert meeting is not None
    assert meeting["meeting"]["title"] == "샘플 회의"
    assert len(meeting["utterances"]) == 2
    assert storage.search_meetings(db_path, "테스트")
    assert storage.search_utterances(db_path, "반갑습니다")

    storage.mark_meeting_synced(db_path, meeting_id, "8", target_name="ci", primary=True)

    assert storage.get_meeting_target(db_path, meeting_id, "ci")["sync_status"] == "synced"


class _FakeCursor:
    def fetchall(self):
        return []


class _FakeFtsConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.created_sql = ""

    def execute(self, sql: str):
        self.executed.append(sql)
        return _FakeCursor()

    def executescript(self, sql: str) -> None:
        if "tokenize='trigram'" in sql:
            raise sqlite3.OperationalError("no such tokenizer: trigram")
        self.created_sql = sql


def test_fts_schema_falls_back_to_unicode61() -> None:
    conn = _FakeFtsConnection()

    tokenizer = storage._ensure_fts_schema(conn)  # noqa: SLF001

    assert tokenizer == "unicode61"
    assert "tokenize='unicode61'" in conn.created_sql
    assert any("DROP TABLE IF EXISTS meetings_fts" in sql for sql in conn.executed)


def test_recreate_fts_with_explicit_unicode61(tmp_path: Path) -> None:
    db_path = tmp_path / "meetings.db"
    storage.save_meeting(
        db_path,
        source_file="sample.mp3",
        title="재생성 테스트",
        summary_md="## 요약\n- 검색 인덱스",
        duration_sec=1.0,
        utterances=[
            {"speaker": "SPEAKER_00", "start": 0, "end": 1, "text": "검색 재생성 확인"},
        ],
    )

    tokenizer = storage.recreate_fts(db_path, tokenizer="unicode61")

    assert tokenizer == "unicode61"
    assert storage.get_fts_info(db_path)["tokenizer"] == "unicode61"
    assert storage.search_meetings(db_path, "검색")
    assert storage.search_utterances(db_path, "재생성")


def test_blocked_meeting_is_not_resynced(tmp_path: Path) -> None:
    db_path = tmp_path / "meetings.db"
    meeting_id = storage.save_meeting(
        db_path,
        source_file="bad.mp3",
        title="확인 필요",
        summary_md="## 품질 경고\n- 낮음",
        duration_sec=300.0,
        utterances=[
            {"speaker": "사용자1", "start": 0, "end": 2, "text": "테스트"},
        ],
    )

    storage.mark_meeting_upload_blocked(
        db_path,
        meeting_id,
        "quality gate",
        target_names=["remote"],
    )

    meeting = storage.get_meeting(db_path, meeting_id)

    assert meeting["meeting"]["sync_status"] == "blocked"
    assert meeting["sync_targets"][0]["sync_status"] == "blocked"
    assert storage.list_unsynced(db_path) == []
    assert storage.list_unsynced(db_path, target_names=["remote"]) == []


def test_missing_named_target_is_still_unsynced(tmp_path: Path) -> None:
    db_path = tmp_path / "meetings.db"
    meeting_id = storage.save_meeting(
        db_path,
        source_file="sample.mp3",
        title="기존 회의",
        summary_md="## 요약\n- 내용",
        duration_sec=60.0,
        utterances=[
            {"speaker": "사용자1", "start": 0, "end": 2, "text": "테스트"},
        ],
    )
    storage.mark_meeting_synced(db_path, meeting_id, "10", target_name="default")

    unsynced = storage.list_unsynced(db_path, target_names=["remote"])

    assert [row["id"] for row in unsynced] == [meeting_id]
