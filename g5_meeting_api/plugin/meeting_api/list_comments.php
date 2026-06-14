<?php
/**
 * POST /plugin/meeting_api/list_comments.php
 *
 * Return comments for a post in stable board order.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_wr_id = (int)($m_body['wr_id'] ?? 0);
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);

if ($m_wr_id <= 0) api_error(400, 'wr_id (int, > 0) is required');

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table_sql = meeting_sql_identifier(write_table_of($m_bo_table));

$post = sql_fetch("SELECT wr_id, wr_10 FROM $write_table_sql WHERE wr_id = '$m_wr_id' AND wr_is_comment = 0");
if (!$post) {
    api_error(404, "Parent post not found: wr_id=$m_wr_id");
}
// 읽기 전용이므로 marker를 요구하지 않는다 (질문 게시판 글은 사람이 작성해 marker가 없음).
// 수정/삭제 엔드포인트(update/delete)에서만 marker로 봇 소유를 강제한다.

$result = sql_query("SELECT wr_id, wr_parent, wr_name, wr_content, wr_datetime, wr_comment
    FROM $write_table_sql
    WHERE wr_parent = '$m_wr_id' AND wr_is_comment = 1
    ORDER BY wr_comment, wr_id");

$comments = [];
while ($row = sql_fetch_array($result)) {
    $comments[] = [
        'comment_id' => (int)$row['wr_id'],
        'wr_id' => (int)$row['wr_parent'],
        'author_name' => $row['wr_name'],
        'content' => $row['wr_content'],
        'created_at' => $row['wr_datetime'],
        'comment_seq' => (int)$row['wr_comment'],
    ];
}

api_ok([
    'wr_id' => $m_wr_id,
    'bo_table' => $m_bo_table,
    'comments' => $comments,
]);
