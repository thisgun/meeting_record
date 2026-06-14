<?php
/**
 * POST /plugin/meeting_api/posts.php
 *
 * 게시판 글을 배치로 반환한다. (시맨틱 검색 인덱서가 게시판 전체를 순회 수집하는 용도)
 *
 * 요청 헤더:
 *   X-API-Token: <토큰>
 *   Content-Type: application/json
 *
 * 요청 바디 (JSON):
 *   {
 *     "bo_table": "free",       // 대상 게시판
 *     "offset": 0,               // 시작 위치 (기본 0)
 *     "limit": 100               // 최대 개수 (기본 100, 최대 500)
 *   }
 *
 * 응답: { "ok": true, "bo_table": "free", "total": N, "count": M, "offset": 0,
 *         "posts": [ { "wr_id": 5, "subject": "...", "content": "...",
 *                      "name": "...", "datetime": "...", "comment_count": 0 } ] }
 *
 * 원글(wr_is_comment=0)만 반환하며 wr_id 오름차순으로 페이지네이션한다.
 * 읽기 전용이라 marker를 요구하지 않는다(누구의 글이든 검색 인덱싱 대상).
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);
$m_offset = (int)($m_body['offset'] ?? 0);
if ($m_offset < 0) $m_offset = 0;
$m_limit = (int)($m_body['limit'] ?? 100);
if ($m_limit < 1) $m_limit = 100;
if ($m_limit > 500) $m_limit = 500;

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table_sql = meeting_sql_identifier(write_table_of($m_bo_table));

$total_row = sql_fetch("SELECT COUNT(*) AS cnt FROM $write_table_sql WHERE wr_is_comment = 0");
$total = (int)($total_row['cnt'] ?? 0);

$result = sql_query("SELECT wr_id, wr_subject, wr_content, wr_name, wr_datetime, wr_comment
    FROM $write_table_sql
    WHERE wr_is_comment = 0
    ORDER BY wr_id ASC
    LIMIT $m_offset, $m_limit");

$posts = [];
while ($row = sql_fetch_array($result)) {
    $posts[] = [
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
    'total' => $total,
    'offset' => $m_offset,
    'count' => count($posts),
    'posts' => $posts,
]);
