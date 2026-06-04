<?php
/**
 * meeting 게시판 자동 생성/검증 (1회 실행).
 *
 * 그누보드5 plugin/meeting_api 폴더로 업로드한 후,
 * X-API-Token 헤더를 포함한 POST 요청으로 1회 호출.
 *
 * 작업:
 * 1. 그누보드5 common.php 로드 + DB 연결 확인
 * 2. 기존 'free' 게시판이 있으면 그것을 복사해 'meeting' 게시판 생성
 * 3. g5_write_meeting 테이블 생성 (g5_write_free 복제)
 * 4. 이미 있으면 그대로 둠 (idempotent)
 *
 * 보안: 인증 토큰 일치 + meeting_API_ALLOW_SETUP=true 일 때만 동작.
 *       작업 끝나면 false로 되돌리거나 이 파일 삭제 권장.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('POST');
require_auth();

if (!defined('meeting_API_ALLOW_SETUP') || !meeting_API_ALLOW_SETUP) {
    api_error(
        403,
        'setup_board.php is disabled. Set meeting_API_ALLOW_SETUP=true in config.local.php only during initial setup.'
    );
}

require_once __DIR__ . '/_load_gnuboard5.php';
global $g5;

$bo_table = meeting_BO_TABLE;
$bo_table_safe = meeting_normalize_bo_table($bo_table);
$bo_table_esc = meeting_sql_escape($bo_table_safe);
$board_table_sql = meeting_sql_identifier($g5['board_table']);
$tmp_table_sql = meeting_sql_identifier('_tmp_meeting');

// 1. 기존 게시판 확인
$existing = sql_fetch("SELECT bo_table, bo_subject FROM $board_table_sql WHERE bo_table = '$bo_table_esc'");

$report = [
    'g5_path' => G5_PATH_OVERRIDE,
    'bo_table' => $bo_table_safe,
    'board_existed' => (bool)$existing,
];

if (!$existing) {
    // 'free' 또는 임의의 기존 게시판을 복사
    $template = sql_fetch("SELECT * FROM $board_table_sql WHERE bo_table = 'free'");
    if (!$template) {
        $template = sql_fetch("SELECT * FROM $board_table_sql LIMIT 1");
    }
    if (!$template) {
        api_error(500, '복사할 기존 게시판이 없습니다. 그누보드5 관리자에서 free 게시판을 먼저 만들어주세요.');
    }
    $template_bo = (string)$template['bo_table'];
    $template_bo_esc = meeting_sql_escape($template_bo);

    // 임시 변수에 복사 후 bo_table만 변경해서 INSERT
    meeting_sql_query_or_error("SET SESSION sql_mode = ''", 'Failed to set SQL mode');
    meeting_sql_query_or_error("CREATE TEMPORARY TABLE $tmp_table_sql LIKE $board_table_sql", 'Failed to create temporary board table');
    meeting_sql_query_or_error("INSERT INTO $tmp_table_sql SELECT * FROM $board_table_sql WHERE bo_table = '$template_bo_esc'", 'Failed to copy board template');
    meeting_sql_query_or_error("UPDATE $tmp_table_sql SET bo_table = '$bo_table_esc', bo_subject = '회의록', bo_count_write = 0, bo_count_comment = 0", 'Failed to prepare board template');
    meeting_sql_query_or_error("INSERT INTO $board_table_sql SELECT * FROM $tmp_table_sql", 'Failed to create board');
    meeting_sql_query_or_error("DROP TEMPORARY TABLE $tmp_table_sql", 'Failed to drop temporary board table');
    $report['board_created'] = true;
    $report['copied_from'] = $template_bo;
} else {
    $report['board_subject'] = $existing['bo_subject'];
}

// 2. write_table 확인 및 생성
$write_table = $g5['write_prefix'] . $bo_table_safe;
$write_table_esc = meeting_sql_escape($write_table);
$write_table_sql = meeting_sql_identifier($write_table);
$tbl_check = sql_fetch("SHOW TABLES LIKE '$write_table_esc'");
$report['write_table'] = $write_table;
$report['write_table_existed'] = (bool)$tbl_check;
if (!$tbl_check) {
    // 'free' write 테이블 또는 임의의 기존 write 테이블을 LIKE
    meeting_sql_query_or_error("SET SESSION sql_mode = ''", 'Failed to set SQL mode');
    $tpl_write = $g5['write_prefix'] . 'free';
    $tpl_write_esc = meeting_sql_escape($tpl_write);
    $exists = sql_fetch("SHOW TABLES LIKE '$tpl_write_esc'");
    if (!$exists) {
        // free가 없으면 첫번째 write_* 테이블 사용
        $prefix_like = meeting_sql_escape($g5['write_prefix'] . '%');
        $row = sql_fetch("SHOW TABLES LIKE '$prefix_like'");
        if ($row) {
            $tpl_write = reset($row);
        } else {
            api_error(500, '복사할 기존 write_* 테이블이 없습니다');
        }
    }
    $tpl_write_sql = meeting_sql_identifier($tpl_write);
    meeting_sql_query_or_error("CREATE TABLE $write_table_sql LIKE $tpl_write_sql", 'Failed to create write table');
    $report['write_table_created'] = true;
    $report['copied_from_table'] = $tpl_write;
}

api_ok([
    'message' => '게시판 준비 완료',
    'next_steps' => [
        '1. config.local.php 의 meeting_API_TOKEN 이 강력한 값인지 확인',
        '2. config.local.php 의 meeting_API_DEBUG = false 확인',
        '3. config.local.php 의 meeting_API_ALLOW_SETUP 을 false로 되돌리거나 setup_board.php 파일 삭제',
        '4. Python .env 의 G5_API_BASE, G5_API_TOKEN 을 원격으로 설정',
        '5. python doctor.py 로 원격 health 확인',
    ],
    'report' => $report,
]);
