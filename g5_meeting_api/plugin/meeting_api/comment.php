<?php
/**
 * POST /plugin/meeting_api/comment.php
 *
 * 회의 발화 1건을 댓글로 작성한다.
 *
 * 요청 헤더: X-API-Token: <토큰> / Content-Type: application/json
 * 요청 바디:  { "wr_id": 123, "content": "...", "bo_table": "meeting", "idempotency_key": "..." }
 * 응답:      { "ok": true, "comment_id": 456, "idempotent": false }
 *
 * 참고: 그누보드5 common.php가 글로벌 $bo_table, $wr_id를 덮어쓰므로
 *       입력값은 m_ prefix 로컬 변수에 보관 후 common.php를 로드한다.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_wr_id = (int)($m_body['wr_id'] ?? 0);
$m_content = (string)($m_body['content'] ?? '');
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);
$m_author_name = trim((string)($m_body['author_name'] ?? ''));  // 선택: 화자별 작성자명
$m_idempotency_key = meeting_normalize_idempotency_key($m_body['idempotency_key'] ?? '');

if ($m_wr_id <= 0) api_error(400, 'wr_id (int, > 0) is required');
if ($m_content === '') api_error(400, 'content is required');
meeting_require_max_bytes('content', $m_content, meeting_API_MAX_COMMENT_CONTENT_BYTES);

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table = write_table_of($m_bo_table);
$write_table_sql = meeting_sql_identifier($write_table);
$board_new_table_sql = meeting_sql_identifier($GLOBALS['g5']['board_new_table']);
$board_table_sql = meeting_sql_identifier($GLOBALS['g5']['board_table']);

meeting_db_begin();
$parent = sql_fetch("SELECT wr_id, wr_num, ca_name, wr_10 FROM $write_table_sql
    WHERE wr_id = '$m_wr_id' AND wr_is_comment = 0
    FOR UPDATE");
if (!$parent) {
    api_error(404, "Parent post not found: wr_id=$m_wr_id");
}
meeting_require_api_owned_marker($parent['wr_10'] ?? '');

$wr_content = meeting_sql_escape($m_content);
// 화자별 작성자명: 요청에 author_name 있으면 사용, 없으면 기본값
$effective_name = $m_author_name !== '' ? $m_author_name : meeting_WR_NAME;
$wr_name = meeting_sql_escape(mb_substr($effective_name, 0, 50, 'UTF-8'));
$wr_password = meeting_WR_PASSWORD ? meeting_sql_escape(sql_password(meeting_WR_PASSWORD)) : '';
$wr_email = meeting_sql_escape(meeting_WR_EMAIL);
$wr_homepage = meeting_sql_escape(meeting_WR_HOMEPAGE);
$mb_id_esc = meeting_sql_escape(meeting_MB_ID);
$api_marker = meeting_sql_escape(meeting_API_MARKER);
$idempotency_key = meeting_sql_escape($m_idempotency_key);
$ca_name = meeting_sql_escape($parent['ca_name'] ?? '');
$wr_num = (int)$parent['wr_num'];
$ip = meeting_sql_escape($_SERVER['REMOTE_ADDR'] ?? '127.0.0.1');
$now = G5_TIME_YMDHIS;
$bo_table_esc = meeting_sql_escape($m_bo_table);

if ($m_idempotency_key !== '') {
    $existing = sql_fetch("SELECT wr_id FROM $write_table_sql
        WHERE wr_parent = '$m_wr_id'
          AND wr_is_comment = 1
          AND wr_9 = '$idempotency_key'
          AND wr_10 = '$api_marker'
        ORDER BY wr_id ASC
        LIMIT 1");
    if ($existing && (int)$existing['wr_id'] > 0) {
        meeting_db_commit();
        api_ok([
            'comment_id' => (int)$existing['wr_id'],
            'wr_id' => $m_wr_id,
            'bo_table' => $m_bo_table,
            'idempotent' => true,
        ]);
    }
}

$row = sql_fetch("SELECT MAX(wr_comment) AS max_comment
    FROM $write_table_sql
    WHERE wr_parent = '$m_wr_id' AND wr_is_comment = 1");
$tmp_comment = (int)($row['max_comment'] ?? 0) + 1;

$sql = "INSERT INTO $write_table_sql SET
    ca_name = '$ca_name',
    wr_option = '',
    wr_num = '$wr_num',
    wr_reply = '',
    wr_parent = '$m_wr_id',
    wr_is_comment = 1,
    wr_comment = '$tmp_comment',
    wr_comment_reply = '',
    wr_subject = '',
    wr_content = '$wr_content',
    mb_id = '$mb_id_esc',
    wr_password = '$wr_password',
    wr_name = '$wr_name',
    wr_email = '$wr_email',
    wr_homepage = '$wr_homepage',
    wr_datetime = '$now',
    wr_last = '',
    wr_ip = '$ip',
    wr_1 = '', wr_2 = '', wr_3 = '', wr_4 = '', wr_5 = '',
    wr_6 = '', wr_7 = '', wr_8 = '', wr_9 = '$idempotency_key', wr_10 = '$api_marker'";

meeting_sql_query_or_error($sql, 'Failed to insert comment');
$new_comment_id = sql_insert_id();
if (!$new_comment_id) {
    api_error(500, 'Failed to insert comment');
}

meeting_sql_query_or_error("UPDATE $write_table_sql
    SET wr_comment = wr_comment + 1, wr_last = '$now'
    WHERE wr_id = '$m_wr_id'",
    'Failed to update parent comment count'
);

meeting_sql_query_or_error("INSERT INTO $board_new_table_sql
    (bo_table, wr_id, wr_parent, bn_datetime, mb_id)
    VALUES ('$bo_table_esc', '$new_comment_id', '$m_wr_id', '$now', '$mb_id_esc')",
    'Failed to insert board_new record'
);

meeting_sql_query_or_error("UPDATE $board_table_sql
    SET bo_count_comment = bo_count_comment + 1
    WHERE bo_table = '$bo_table_esc'",
    'Failed to update board comment count'
);
meeting_db_commit();

api_ok([
    'comment_id' => (int)$new_comment_id,
    'wr_id' => $m_wr_id,
    'bo_table' => $m_bo_table,
    'idempotent' => false,
]);
