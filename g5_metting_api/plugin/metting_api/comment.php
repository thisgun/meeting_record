<?php
/**
 * POST /g5_metting_api/comment.php
 *
 * 회의 발화 1건을 댓글로 작성한다.
 *
 * 요청 헤더: X-API-Token: <토큰> / Content-Type: application/json
 * 요청 바디:  { "wr_id": 123, "content": "...", "bo_table": "metting" }
 * 응답:      { "ok": true, "comment_id": 456 }
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
$m_bo_table = trim((string)($m_body['bo_table'] ?? METTING_BO_TABLE));
$m_author_name = trim((string)($m_body['author_name'] ?? ''));  // 선택: 화자별 작성자명

if ($m_wr_id <= 0) api_error(400, 'wr_id (int, > 0) is required');
if ($m_content === '') api_error(400, 'content is required');
if ($m_bo_table === '') api_error(400, 'bo_table is required');

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table = write_table_of($m_bo_table);

$parent = sql_fetch("SELECT wr_id, wr_num, ca_name FROM $write_table
    WHERE wr_id = '$m_wr_id' AND wr_is_comment = 0");
if (!$parent) {
    api_error(404, "Parent post not found: wr_id=$m_wr_id");
}

$row = sql_fetch("SELECT MAX(wr_comment) AS max_comment
    FROM $write_table
    WHERE wr_parent = '$m_wr_id' AND wr_is_comment = 1");
$tmp_comment = (int)($row['max_comment'] ?? 0) + 1;

$wr_content = addslashes($m_content);
// 화자별 작성자명: 요청에 author_name 있으면 사용, 없으면 기본값
$effective_name = $m_author_name !== '' ? $m_author_name : METTING_WR_NAME;
$wr_name = addslashes(mb_substr($effective_name, 0, 50, 'UTF-8'));
$wr_password = METTING_WR_PASSWORD ? sql_password(METTING_WR_PASSWORD) : '';
$wr_email = addslashes(METTING_WR_EMAIL);
$wr_homepage = addslashes(METTING_WR_HOMEPAGE);
$mb_id_esc = addslashes(METTING_MB_ID);
$ca_name = addslashes($parent['ca_name'] ?? '');
$wr_num = (int)$parent['wr_num'];
$ip = $_SERVER['REMOTE_ADDR'] ?? '127.0.0.1';
$now = G5_TIME_YMDHIS;
$bo_table_esc = addslashes($m_bo_table);

$sql = "INSERT INTO $write_table SET
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
    wr_6 = '', wr_7 = '', wr_8 = '', wr_9 = '', wr_10 = ''";

sql_query($sql);
$new_comment_id = sql_insert_id();
if (!$new_comment_id) {
    api_error(500, 'Failed to insert comment');
}

sql_query("UPDATE $write_table
    SET wr_comment = wr_comment + 1, wr_last = '$now'
    WHERE wr_id = '$m_wr_id'");

sql_query("INSERT INTO {$GLOBALS['g5']['board_new_table']}
    (bo_table, wr_id, wr_parent, bn_datetime, mb_id)
    VALUES ('$bo_table_esc', '$new_comment_id', '$m_wr_id', '$now', '$mb_id_esc')");

sql_query("UPDATE {$GLOBALS['g5']['board_table']}
    SET bo_count_comment = bo_count_comment + 1
    WHERE bo_table = '$bo_table_esc'");

api_ok([
    'comment_id' => (int)$new_comment_id,
    'wr_id' => $m_wr_id,
    'bo_table' => $m_bo_table,
]);
