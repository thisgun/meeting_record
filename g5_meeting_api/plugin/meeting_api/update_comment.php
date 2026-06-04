<?php
/**
 * POST /plugin/meeting_api/update_comment.php
 *
 * Update an existing comment content and/or author name.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_comment_id = (int)($m_body['comment_id'] ?? 0);
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);
$has_content = array_key_exists('content', $m_body);
$has_author = array_key_exists('author_name', $m_body);
$m_content = $has_content ? (string)$m_body['content'] : null;
$m_author_name = $has_author ? trim((string)$m_body['author_name']) : null;

if ($m_comment_id <= 0) api_error(400, 'comment_id (int, > 0) is required');
if (!$has_content && !$has_author) api_error(400, 'content or author_name is required');
if ($has_content && $m_content === '') api_error(400, 'content must not be empty');
if ($has_author && $m_author_name === '') api_error(400, 'author_name must not be empty');

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table_sql = meeting_sql_identifier(write_table_of($m_bo_table));

$comment = sql_fetch("SELECT c.wr_id, c.wr_parent, p.wr_10 AS parent_marker
    FROM $write_table_sql c
    LEFT JOIN $write_table_sql p ON p.wr_id = c.wr_parent
    WHERE c.wr_id = '$m_comment_id' AND c.wr_is_comment = 1");
if (!$comment) {
    api_error(404, "Comment not found: comment_id=$m_comment_id");
}
meeting_require_api_owned_marker($comment['parent_marker'] ?? '');

$sets = [];
if ($has_content) {
    $sets[] = "wr_content = '" . meeting_sql_escape($m_content) . "'";
}
if ($has_author) {
    $sets[] = "wr_name = '" . meeting_sql_escape(mb_substr($m_author_name, 0, 50, 'UTF-8')) . "'";
}

sql_query("UPDATE $write_table_sql SET " . implode(', ', $sets) . " WHERE wr_id = '$m_comment_id'");

if ($has_content) {
    $parent_id = (int)$comment['wr_parent'];
    $now = meeting_sql_escape(G5_TIME_YMDHIS);
    sql_query("UPDATE $write_table_sql SET wr_last = '$now' WHERE wr_id = '$parent_id'");
}

api_ok([
    'comment_id' => $m_comment_id,
    'wr_id' => (int)$comment['wr_parent'],
    'bo_table' => $m_bo_table,
    'updated' => true,
]);
