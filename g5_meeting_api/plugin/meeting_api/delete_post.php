<?php
/**
 * POST /plugin/meeting_api/delete_post.php
 *
 * Delete a post and its comments. Used for connection-test cleanup too.
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
$board_new_table_sql = meeting_sql_identifier($GLOBALS['g5']['board_new_table']);
$board_table_sql = meeting_sql_identifier($GLOBALS['g5']['board_table']);
$bo_table_esc = meeting_sql_escape($m_bo_table);

$post = sql_fetch("SELECT wr_id, wr_10 FROM $write_table_sql WHERE wr_id = '$m_wr_id' AND wr_is_comment = 0");
if (!$post) {
    api_error(404, "Post not found: wr_id=$m_wr_id");
}
meeting_require_api_owned_marker($post['wr_10'] ?? '');

$row = sql_fetch("SELECT COUNT(*) AS cnt FROM $write_table_sql WHERE wr_parent = '$m_wr_id' AND wr_is_comment = 1");
$comment_count = (int)($row['cnt'] ?? 0);

sql_query("DELETE FROM $write_table_sql WHERE wr_parent = '$m_wr_id'");
sql_query("DELETE FROM $board_new_table_sql WHERE bo_table = '$bo_table_esc' AND wr_parent = '$m_wr_id'");
sql_query("UPDATE $board_table_sql
    SET bo_count_write = GREATEST(bo_count_write - 1, 0),
        bo_count_comment = GREATEST(bo_count_comment - $comment_count, 0)
    WHERE bo_table = '$bo_table_esc'");

api_ok([
    'wr_id' => $m_wr_id,
    'bo_table' => $m_bo_table,
    'deleted' => true,
    'deleted_comments' => $comment_count,
]);
