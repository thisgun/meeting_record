<?php
/**
 * 그누보드5 common.php를 *전역 스코프에서* 로드한다.
 *
 * 함수 안에서 require하면 common.php의 $g5 등이 함수 로컬 변수가 되어
 * 호출자 쪽에서 빈 배열을 보게 된다. 이 파일을 endpoint에서 require하여
 * endpoint의 전역 스코프에 변수들을 정의시킨다.
 */
if (defined('METTING_G5_LOADED')) return;

if (!defined('G5_PATH_OVERRIDE')) {
    require_once __DIR__ . '/config.php';
}

$__g5_path = G5_PATH_OVERRIDE;
if (!is_dir($__g5_path)) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => "Gnuboard5 path not found: $__g5_path"]);
    exit;
}
if (!is_file($__g5_path . '/data/dbconfig.php')) {
    http_response_code(503);
    echo json_encode(['ok' => false, 'error' => 'Gnuboard5 not installed (data/dbconfig.php missing)']);
    exit;
}

// common.php의 g5_path()가 SCRIPT_FILENAME을 기반으로 경로를 계산하므로 위장
$__saved_cwd = getcwd();
$__saved_script_filename = $_SERVER['SCRIPT_FILENAME'] ?? '';
$__saved_script_name = $_SERVER['SCRIPT_NAME'] ?? '';
$__saved_php_self = $_SERVER['PHP_SELF'] ?? '';

chdir($__g5_path);
$_SERVER['SCRIPT_FILENAME'] = $__g5_path . '/index.php';
$_SERVER['SCRIPT_NAME'] = '/gnuboard5/index.php';
$_SERVER['PHP_SELF'] = '/gnuboard5/index.php';

// 출력 캡쳐 (common.php가 의도치 않은 출력을 내면 JSON 응답이 깨짐)
ob_start();
require_once $__g5_path . '/common.php';
$__g5_output = ob_get_clean();

// 원복
chdir($__saved_cwd);
$_SERVER['SCRIPT_FILENAME'] = $__saved_script_filename;
$_SERVER['SCRIPT_NAME'] = $__saved_script_name;
$_SERVER['PHP_SELF'] = $__saved_php_self;

if ($__g5_output !== '' && defined('METTING_API_DEBUG') && METTING_API_DEBUG) {
    error_log("[g5_metting_api] common.php stray output: " . substr($__g5_output, 0, 500));
}

define('METTING_G5_LOADED', true);
