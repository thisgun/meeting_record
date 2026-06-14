"""RAG 검색/컨텍스트/출처 포맷 단위 테스트 (LLM 호출 없는 순수 로직)."""
from src import rag


def test_fts_query_from_question_builds_or() -> None:
    q = rag._fts_query_from_question("회의에서 결정된 사항은 무엇인가")
    assert q is not None
    assert "OR" in q
    assert '"결정된"' in q


def test_fts_query_none_when_no_long_tokens() -> None:
    # 3자 미만 토큰만 있으면 None (trigram 토크나이저 한계 회피)
    assert rag._fts_query_from_question("a b 안 의") is None


def test_format_timestamp() -> None:
    assert rag._format_timestamp(None) == ""
    assert rag._format_timestamp(65) == " 01:05~"


def test_build_context_dedupes_sources_by_meeting() -> None:
    hits = [
        {"meeting_id": 1, "kind": "summary", "start_sec": None, "text": "요약 내용",
         "title": "회의A", "created_at": "2026-06-01T00:00:00", "remote_post_id": "10"},
        {"meeting_id": 1, "kind": "utterance", "start_sec": 5.0, "text": "발화 내용",
         "title": "회의A", "created_at": "2026-06-01T00:00:00", "remote_post_id": "10"},
        {"meeting_id": 2, "kind": "summary", "start_sec": None, "text": "요약 내용2",
         "title": "회의B", "created_at": "2026-06-02T00:00:00", "remote_post_id": "20"},
    ]
    context, sources = rag.build_context(hits)
    assert len(sources) == 2  # 같은 회의(1)는 출처 1개로 합쳐짐
    assert sources[0]["no"] == 1 and sources[1]["no"] == 2
    assert "[출처 1]" in context
    assert "[출처 2]" in context


def test_post_url_builds_board_link() -> None:
    url = rag.post_url("http://host/gnuboard5/plugin/meeting_api", "ask", 5)
    assert url is not None
    assert "bo_table=ask" in url
    assert "wr_id=5" in url
    assert "/bbs/board.php" in url


def test_post_url_returns_none_without_wr_id() -> None:
    assert rag.post_url("http://host/gnuboard5/plugin/meeting_api", "ask", None) is None


def test_format_sources_footer_includes_links() -> None:
    sources = [
        {"no": 1, "meeting_id": 1, "title": "회의A", "created_at": "2026-06-01",
         "remote_post_id": "10"},
        {"no": 2, "meeting_id": 2, "title": "회의B", "created_at": "2026-06-02",
         "remote_post_id": None},  # 업로드 안 된 회의는 링크 없이
    ]
    footer = rag.format_sources_footer(
        sources, api_base="http://host/gnuboard5/plugin/meeting_api", bo_table="meeting"
    )
    assert "회의A" in footer
    assert "wr_id=10" in footer
    assert "회의B" in footer  # 링크는 없어도 제목은 표기


def test_format_sources_footer_empty() -> None:
    assert rag.format_sources_footer([], api_base="http://h", bo_table="meeting") == ""


def _sources(*nos):
    return [{"no": n, "meeting_id": n, "title": f"회의{n}", "created_at": "2026-06-01",
             "remote_post_id": str(n)} for n in nos]


def test_cited_source_numbers() -> None:
    assert rag._cited_source_numbers("근거는 [출처 1]과 [출처 3] 입니다.") == {1, 3}
    assert rag._cited_source_numbers("[출처 2] 만") == {2}
    assert rag._cited_source_numbers("인용 없음") == set()
    # 모델이 소괄호/괄호 없이 써도 인식해야 한다
    assert rag._cited_source_numbers("결정 사항입니다. (출처 4)") == {4}
    assert rag._cited_source_numbers("내용 출처 2 참고") == {2}


def test_select_shown_sources_only_cited() -> None:
    # 답변이 [출처 2]만 인용 → 검색된 1,2,3 중 2만 노출
    shown = rag.select_shown_sources("결론은 [출처 2] 에 있습니다.", _sources(1, 2, 3))
    assert [s["no"] for s in shown] == [2]


def test_select_shown_sources_no_citation_hides_all() -> None:
    # 인용이 전혀 없으면(주로 '못 찾음' 답변) 무관한 검색 결과를 출처로 노출하지 않는다
    shown = rag.select_shown_sources("회의록에서 관련 내용을 찾지 못했습니다.", _sources(1, 2, 3))
    assert shown == []
    shown2 = rag.select_shown_sources("채용 관련 내용은 포함되어 있지 않습니다.", _sources(1, 2))
    assert shown2 == []
