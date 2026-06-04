<?php
/**
 * metting 게시판 자동 생성/검증 (1회 실행).
 *
 * 그누보드5 옆에 g5_metting_api 폴더로 업로드한 후,
 * 브라우저에서 https://YOUR-DOMAIN/g5_metting_api/setup_board.php?token=YOUR_TOKEN 1회 호출.
 *
 * 작업:
 * 1. 그누보드5 common.php 로드 + DB 연결 확인
 * 2. 기존 'free' 게시판이 있으면 그것을 복사해 'metting' 게시판 생성
 * 3. g5_write_metting 테이블 생성 (g5_write_free 복제)
 * 4. 이미 있으면 그대로 둠 (idempotent)
 *
 * 보안: 인증 토큰 일치할 때만 동작. 작업 끝나면 이 파일 삭제 권장.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('GET');

// 토큰 확인 (URL 파라미터로 받음 — 1회용)
$provided = $_GET['token'] ?? '';
if (!METTING_API_TOKEN || !hash_equals(METTING_API_TOKEN, $provided)) {
    api_error(401, 'Invalid token. URL에 ?token=YOUR_TOKEN 추가하세요.');
}

require_once __DIR__ . '/_load_gnuboard5.php';
global $g5;

$bo_table = METTING_BO_TABLE;
$bo_table_safe = preg_replace('/[^a-z0-9_]/i', '', $bo_table);
if (!$bo_table_safe) api_error(400, 'bo_table 이름이 유효하지 않습니다');

// 1. 기존 게시판 확인
$existing = sql_fetch("SELECT bo_table, bo_subject FROM {$g5['board_table']} WHERE bo_table = '$bo_table_safe'");

$report = [
    'g5_path' => G5_PATH_OVERRIDE,
    'bo_table' => $bo_table_safe,
    'board_existed' => (bool)$existing,
];

if (!$existing) {
    // 'free' 또는 임의의 기존 게시판을 복사
    $template = sql_fetch("SELECT * FROM {$g5['board_table']} WHERE bo_table = 'free'");
    if (!$template) {
        $template = sql_fetch("SELECT * FROM {$g5['board_table']} LIMIT 1");
    }
    if (!$template) {
        api_error(500, '복사할 기존 게시판이 없습니다. 그누보드5 관리자에서 free 게시판을 먼저 만들어주세요.');
    }
    $template_bo = $template['bo_table'];

    // 임시 변수에 복사 후 bo_table만 변경해서 INSERT
    sql_query("SET SESSION sql_mode = ''");
    sql_query("CREATE TEMPORARY TABLE _tmp_metting LIKE {$g5['board_table']}");
    sql_query("INSERT INTO _tmp_metting SELECT * FROM {$g5['board_table']} WHERE bo_table = '$template_bo'");
    sql_query("UPDATE _tmp_metting SET bo_table = '$bo_table_safe', bo_subject = '회의록', bo_count_write = 0, bo_count_comment = 0");
    sql_query("INSERT INTO {$g5['board_table']} SELECT * FROM _tmp_metting");
    sql_query("DROP TEMPORARY TABLE _tmp_metting");
    $report['board_created'] = true;
    $report['copied_from'] = $template_bo;
} else {
    $report['board_subject'] = $existing['bo_subject'];
}

// 2. write_table 확인 및 생성
$write_table = $g5['write_prefix'] . $bo_table_safe;
$tbl_check = sql_fetch("SHOW TABLES LIKE '$write_table'");
$report['write_table'] = $write_table;
$report['write_table_existed'] = (bool)$tbl_check;
if (!$tbl_check) {
    // 'free' write 테이블 또는 임의의 기존 write 테이블을 LIKE
    sql_query("SET SESSION sql_mode = ''");
    $tpl_write = $g5['write_prefix'] . 'free';
    $exists = sql_fetch("SHOW TABLES LIKE '$tpl_write'");
    if (!$exists) {
        // free가 없으면 첫번째 write_* 테이블 사용
        $row = sql_fetch("SHOW TABLES LIKE '{$g5['write_prefix']}%'");
        if ($row) {
            $tpl_write = reset($row);
        } else {
            api_error(500, '복사할 기존 write_* 테이블이 없습니다');
        }
    }
    sql_query("CREATE TABLE `$write_table` LIKE `$tpl_write`");
    $report['write_table_created'] = true;
    $report['copied_from_table'] = $tpl_write;
}

api_ok([
    'message' => '게시판 준비 완료',
    'next_steps' => [
        '1. config.local.php 의 METTING_API_TOKEN 을 강력한 값으로 변경',
        '2. config.local.php 의 METTING_API_DEBUG = false 확인',
        '3. setup_board.php 파일 삭제 (보안)',
        '4. Python .env 의 G5_API_BASE, G5_API_TOKEN 을 원격으로 설정',
        '5. python doctor.py 로 원격 health 확인',
    ],
    'report' => $report,
]);
