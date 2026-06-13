<?php
/**
 * POST /plugin/meeting_api/cleanup_tests.php
 *
 * Remove stale connection-test posts created by scripts/check_g5_remote.py.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);
$m_older_than_minutes = max(0, (int)($m_body['older_than_minutes'] ?? 60));
$m_limit = min(100, max(1, (int)($m_body['limit'] ?? 50)));
$m_dry_run = !empty($m_body['dry_run']);

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table_sql = meeting_sql_identifier(write_table_of($m_bo_table));
$board_new_table_sql = meeting_sql_identifier($GLOBALS['g5']['board_new_table']);
$board_table_sql = meeting_sql_identifier($GLOBALS['g5']['board_table']);
$bo_table_esc = meeting_sql_escape($m_bo_table);
$api_marker = meeting_sql_escape(meeting_API_MARKER);
$key_prefix = meeting_sql_escape('meeting_record:check_g5_remote:post:%');
$cutoff = meeting_sql_escape(date('Y-m-d H:i:s', time() - ($m_older_than_minutes * 60)));

$rows = meeting_sql_query_or_error("SELECT wr_id, wr_subject, wr_datetime
    FROM $write_table_sql
    WHERE wr_is_comment = 0
      AND wr_10 = '$api_marker'
      AND wr_9 LIKE '$key_prefix'
      AND wr_datetime <= '$cutoff'
    ORDER BY wr_id ASC
    LIMIT $m_limit",
    'Failed to list stale test posts'
);

$candidates = [];
while ($row = sql_fetch_array($rows)) {
    $candidates[] = [
        'wr_id' => (int)$row['wr_id'],
        'subject' => $row['wr_subject'],
        'datetime' => $row['wr_datetime'],
    ];
}

if ($m_dry_run || !$candidates) {
    api_ok([
        'bo_table' => $m_bo_table,
        'dry_run' => $m_dry_run,
        'older_than_minutes' => $m_older_than_minutes,
        'matched' => count($candidates),
        'deleted_posts' => 0,
        'deleted_comments' => 0,
        'candidates' => $candidates,
    ]);
}

$deleted_posts = 0;
$deleted_comments = 0;
meeting_db_begin();
foreach ($candidates as $candidate) {
    $wr_id = (int)$candidate['wr_id'];
    $row = sql_fetch("SELECT COUNT(*) AS cnt FROM $write_table_sql WHERE wr_parent = '$wr_id' AND wr_is_comment = 1");
    $comment_count = (int)($row['cnt'] ?? 0);
    meeting_sql_query_or_error(
        "DELETE FROM $write_table_sql WHERE wr_parent = '$wr_id'",
        'Failed to delete stale test post rows'
    );
    meeting_sql_query_or_error(
        "DELETE FROM $board_new_table_sql WHERE bo_table = '$bo_table_esc' AND wr_parent = '$wr_id'",
        'Failed to delete stale test board_new rows'
    );
    $deleted_posts += 1;
    $deleted_comments += $comment_count;
}
meeting_sql_query_or_error("UPDATE $board_table_sql
    SET bo_count_write = GREATEST(bo_count_write - $deleted_posts, 0),
        bo_count_comment = GREATEST(bo_count_comment - $deleted_comments, 0)
    WHERE bo_table = '$bo_table_esc'",
    'Failed to update board counts after stale test cleanup'
);
meeting_db_commit();

api_ok([
    'bo_table' => $m_bo_table,
    'dry_run' => false,
    'older_than_minutes' => $m_older_than_minutes,
    'matched' => count($candidates),
    'deleted_posts' => $deleted_posts,
    'deleted_comments' => $deleted_comments,
    'candidates' => $candidates,
]);
