<?php
/**
 * GET /g5_metting_api/health.php
 *
 * 의존성 점검: PHP, gnuboard5 설치 여부, DB 연결, 대상 게시판 존재 여부.
 */
require_once __DIR__ . '/_bootstrap.php';
require_method('GET');

$report = [
    'php_version' => PHP_VERSION,
    'g5_path' => G5_PATH_OVERRIDE,
    'g5_path_exists' => is_dir(G5_PATH_OVERRIDE),
    'g5_installed' => is_file(G5_PATH_OVERRIDE . '/data/dbconfig.php'),
    'bo_table' => METTING_BO_TABLE,
];

if (!$report['g5_installed']) {
    api_respond(503, array_merge(['ok' => false, 'error' => 'gnuboard5 not installed'], $report));
}

require_once __DIR__ . '/_load_gnuboard5.php';

global $g5;
$db_ok = sql_fetch("SELECT 1 AS v");
$report['db_connected'] = ($db_ok && $db_ok['v'] == 1);

$board = sql_fetch("SELECT bo_table, bo_subject FROM {$g5['board_table']} WHERE bo_table = '" . METTING_BO_TABLE . "'");
$report['board_exists'] = (bool)$board;
$report['board_subject'] = $board['bo_subject'] ?? null;

api_ok($report);
