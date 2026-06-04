<?php
/**
 * POST /plugin/meeting_api/update_post.php
 *
 * Update an existing meeting post title and/or content.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_wr_id = (int)($m_body['wr_id'] ?? 0);
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);
$has_subject = array_key_exists('subject', $m_body);
$has_content = array_key_exists('content', $m_body);
$m_subject = $has_subject ? trim((string)$m_body['subject']) : null;
$m_content = $has_content ? (string)$m_body['content'] : null;

if ($m_wr_id <= 0) api_error(400, 'wr_id (int, > 0) is required');
if (!$has_subject && !$has_content) api_error(400, 'subject or content is required');
if ($has_subject && $m_subject === '') api_error(400, 'subject must not be empty');
if ($has_content && $m_content === '') api_error(400, 'content must not be empty');
if ($has_content) meeting_require_max_bytes('content', $m_content, meeting_API_MAX_POST_CONTENT_BYTES);

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table_sql = meeting_sql_identifier(write_table_of($m_bo_table));

$post = sql_fetch("SELECT wr_id, wr_10 FROM $write_table_sql WHERE wr_id = '$m_wr_id' AND wr_is_comment = 0");
if (!$post) {
    api_error(404, "Post not found: wr_id=$m_wr_id");
}
meeting_require_api_owned_marker($post['wr_10'] ?? '');

$sets = [];
if ($has_subject) {
    $sets[] = "wr_subject = '" . meeting_sql_escape(mb_substr($m_subject, 0, 255, 'UTF-8')) . "'";
}
if ($has_content) {
    $sets[] = "wr_content = '" . meeting_sql_escape($m_content) . "'";
}
$sets[] = "wr_last = '" . meeting_sql_escape(G5_TIME_YMDHIS) . "'";

meeting_sql_query_or_error(
    "UPDATE $write_table_sql SET " . implode(', ', $sets) . " WHERE wr_id = '$m_wr_id'",
    'Failed to update post'
);

api_ok([
    'wr_id' => $m_wr_id,
    'bo_table' => $m_bo_table,
    'updated' => true,
]);
