<?php
/**
 * POST /plugin/meeting_api/hide_post.php
 *
 * 글을 비밀글(secret)로 전환/해제해 일반 노출에서 가린다(소프트 숨김).
 * 완전 삭제(delete_post)와 달리 복구가 가능해 모더레이션 오탐에 안전하다.
 *
 * 요청 헤더: X-API-Token: <토큰> / Content-Type: application/json
 * 요청 바디:  { "wr_id": 123, "bo_table": "free", "hidden": true }
 *             hidden=false 면 secret 해제(다시 공개).
 * 응답:      { "ok": true, "wr_id": 123, "hidden": true, "wr_option": "secret" }
 *
 * 숨김은 관리자/모더레이터 행위이므로 marker(봇 소유)를 요구하지 않는다.
 * 토큰 인증으로 충분하다(사람이 쓴 스팸 글도 가려야 함).
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

$m_body = read_json_body();
$m_wr_id = (int)($m_body['wr_id'] ?? 0);
$m_bo_table = meeting_normalize_bo_table($m_body['bo_table'] ?? meeting_BO_TABLE);
$m_hidden = array_key_exists('hidden', $m_body) ? (bool)$m_body['hidden'] : true;

if ($m_wr_id <= 0) api_error(400, 'wr_id (int, > 0) is required');

require_once __DIR__ . '/_load_gnuboard5.php';

$board = get_board_or_die($m_bo_table);
$write_table_sql = meeting_sql_identifier(write_table_of($m_bo_table));

$post = sql_fetch("SELECT wr_id, wr_option FROM $write_table_sql
    WHERE wr_id = '$m_wr_id' AND wr_is_comment = 0");
if (!$post) {
    api_error(404, "Post not found: wr_id=$m_wr_id");
}

// wr_option(콤마 구분)에서 secret 추가/제거
$opts = array_values(array_filter(array_map('trim', explode(',', (string)$post['wr_option']))));
$has_secret = in_array('secret', $opts, true);
if ($m_hidden && !$has_secret) {
    $opts[] = 'secret';
} elseif (!$m_hidden && $has_secret) {
    $opts = array_values(array_diff($opts, ['secret']));
}
$new_option = implode(',', $opts);
$new_option_esc = meeting_sql_escape($new_option);

meeting_sql_query_or_error(
    "UPDATE $write_table_sql SET wr_option = '$new_option_esc' WHERE wr_id = '$m_wr_id'",
    'Failed to update wr_option'
);

api_ok([
    'wr_id' => $m_wr_id,
    'bo_table' => $m_bo_table,
    'hidden' => $m_hidden,
    'wr_option' => $new_option,
]);
