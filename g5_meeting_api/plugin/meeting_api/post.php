<?php
/**
 * POST /plugin/meeting_api/post.php
 *
 * 회의 요약을 게시글로 작성한다.
 *
 * 요청 헤더:
 *   X-API-Token: <토큰>
 *   Content-Type: application/json
 *
 * 요청 바디 (JSON):
 *   {
 *     "subject": "회의 제목",
 *     "content": "마크다운 본문",
 *     "bo_table": "meeting",   // 선택, 미지정 시 config의 meeting_BO_TABLE
 *     "idempotency_key": "meeting_record:post:1:default" // 선택, 중복 생성 방지
 *   }
 *
 * 응답: { "ok": true, "wr_id": 123, "url": "...", "idempotent": false }
 *
 * 참고: 그누보드5 common.php가 글로벌 스코프에 $bo_table, $wr_id 등을 정의하므로,
 *      common.php 로드 전에 입력값을 m_ prefix 로컬 변수로 저장한다.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_subject = trim((string)($m_body['subject'] ?? ''));
$m_content = (string)($m_body['content'] ?? '');
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);
$m_idempotency_key = meeting_normalize_idempotency_key($m_body['idempotency_key'] ?? '');

if ($m_subject === '') api_error(400, 'subject is required');
if ($m_content === '') api_error(400, 'content is required');

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table = write_table_of($m_bo_table);
$write_table_sql = meeting_sql_identifier($write_table);
$board_new_table_sql = meeting_sql_identifier($GLOBALS['g5']['board_new_table']);
$board_table_sql = meeting_sql_identifier($GLOBALS['g5']['board_table']);

$wr_subject = meeting_sql_escape(mb_substr($m_subject, 0, 255, 'UTF-8'));
$wr_content = meeting_sql_escape($m_content);
$wr_name = meeting_sql_escape(meeting_WR_NAME);
$wr_password = meeting_WR_PASSWORD ? meeting_sql_escape(sql_password(meeting_WR_PASSWORD)) : '';
$wr_email = meeting_sql_escape(meeting_WR_EMAIL);
$wr_homepage = meeting_sql_escape(meeting_WR_HOMEPAGE);
$mb_id_esc = meeting_sql_escape(meeting_MB_ID);
$api_marker = meeting_sql_escape(meeting_API_MARKER);
$idempotency_key = meeting_sql_escape($m_idempotency_key);
$ip = meeting_sql_escape($_SERVER['REMOTE_ADDR'] ?? '127.0.0.1');
$now = G5_TIME_YMDHIS;
$bo_table_esc = meeting_sql_escape($m_bo_table);

$url_base = G5_BBS_URL . '/board.php?bo_table=' . urlencode($m_bo_table) . '&wr_id=';

if ($m_idempotency_key !== '') {
    $existing = sql_fetch("SELECT wr_id FROM $write_table_sql
        WHERE wr_is_comment = 0
          AND wr_9 = '$idempotency_key'
          AND wr_10 = '$api_marker'
        ORDER BY wr_id ASC
        LIMIT 1");
    if ($existing && (int)$existing['wr_id'] > 0) {
        $existing_wr_id = (int)$existing['wr_id'];
        api_ok([
            'wr_id' => $existing_wr_id,
            'bo_table' => $m_bo_table,
            'url' => $url_base . $existing_wr_id,
            'idempotent' => true,
        ]);
    }
}

$sql = "INSERT INTO $write_table_sql SET
    wr_num = (SELECT IFNULL(MIN(wr_num) - 1, -1) FROM $write_table_sql AS sq),
    wr_reply = '',
    wr_comment = 0,
    ca_name = '',
    wr_option = '',
    wr_subject = '$wr_subject',
    wr_content = '$wr_content',
    wr_link1 = '', wr_link2 = '',
    wr_link1_hit = 0, wr_link2_hit = 0,
    wr_hit = 0, wr_good = 0, wr_nogood = 0,
    mb_id = '$mb_id_esc',
    wr_password = '$wr_password',
    wr_name = '$wr_name',
    wr_email = '$wr_email',
    wr_homepage = '$wr_homepage',
    wr_datetime = '$now',
    wr_last = '$now',
    wr_ip = '$ip',
    wr_1 = '', wr_2 = '', wr_3 = '', wr_4 = '', wr_5 = '',
    wr_6 = '', wr_7 = '', wr_8 = '', wr_9 = '$idempotency_key', wr_10 = '$api_marker'";

sql_query($sql);
$new_wr_id = sql_insert_id();
if (!$new_wr_id) {
    api_error(500, 'Failed to insert post (sql_insert_id returned 0)');
}

sql_query("UPDATE $write_table_sql SET wr_parent = '$new_wr_id' WHERE wr_id = '$new_wr_id'");

sql_query("INSERT INTO $board_new_table_sql
    (bo_table, wr_id, wr_parent, bn_datetime, mb_id)
    VALUES ('$bo_table_esc', '$new_wr_id', '$new_wr_id', '$now', '$mb_id_esc')");

sql_query("UPDATE $board_table_sql
    SET bo_count_write = bo_count_write + 1
    WHERE bo_table = '$bo_table_esc'");

api_ok([
    'wr_id' => (int)$new_wr_id,
    'bo_table' => $m_bo_table,
    'url' => $url_base . $new_wr_id,
    'idempotent' => false,
]);
