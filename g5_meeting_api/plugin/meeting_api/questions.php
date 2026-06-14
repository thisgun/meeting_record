<?php
/**
 * POST /plugin/meeting_api/questions.php
 *
 * 질문 게시판의 새 글 목록을 반환한다. (RAG 챗봇 qa_watcher 폴링용)
 *
 * 요청 헤더:
 *   X-API-Token: <토큰>
 *   Content-Type: application/json
 *
 * 요청 바디 (JSON):
 *   {
 *     "bo_table": "ask",        // 질문 게시판
 *     "since_wr_id": 0,          // 이 wr_id 초과의 글만 (기본 0)
 *     "limit": 20                // 최대 개수 (기본 20, 최대 100)
 *   }
 *
 * 응답: { "ok": true, "bo_table": "ask", "count": N, "questions": [
 *          { "wr_id": 5, "subject": "...", "content": "...",
 *            "name": "홍길동", "datetime": "2026-06-13 10:00:00",
 *            "comment_count": 0 } ] }
 *
 * 질문은 사람이 작성하므로 meeting_api marker를 요구하지 않는다.
 * 답변 댓글(wr_is_comment=1)은 wr_is_comment=0 조건으로 자동 제외된다.
 *
 * 참고: 그누보드5 common.php가 글로벌 스코프에 $bo_table, $wr_id 등을 정의하므로,
 *      common.php 로드 전에 입력값을 m_ prefix 로컬 변수로 저장한다.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);
$m_since = (int)($m_body['since_wr_id'] ?? 0);
if ($m_since < 0) $m_since = 0;
$m_limit = (int)($m_body['limit'] ?? 20);
if ($m_limit < 1) $m_limit = 20;
if ($m_limit > 100) $m_limit = 100;

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table_sql = meeting_sql_identifier(write_table_of($m_bo_table));

$result = sql_query("SELECT wr_id, wr_subject, wr_content, wr_name, wr_datetime, wr_comment
    FROM $write_table_sql
    WHERE wr_is_comment = 0 AND wr_id > '$m_since'
    ORDER BY wr_id ASC
    LIMIT $m_limit");

$questions = [];
while ($row = sql_fetch_array($result)) {
    $questions[] = [
        'wr_id' => (int)$row['wr_id'],
        'subject' => (string)$row['wr_subject'],
        'content' => (string)$row['wr_content'],
        'name' => (string)$row['wr_name'],
        'datetime' => (string)$row['wr_datetime'],
        'comment_count' => (int)$row['wr_comment'],
    ];
}

api_ok([
    'bo_table' => $m_bo_table,
    'count' => count($questions),
    'questions' => $questions,
]);
