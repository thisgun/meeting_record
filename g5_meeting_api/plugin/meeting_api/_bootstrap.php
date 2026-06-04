<?php
/**
 * 부트스트랩: 설정 로드, 인증, 그누보드5 common.php 로드, 응답 헬퍼.
 *
 * 그누보드5 원본 파일을 수정하지 않고 함수/DB만 활용한다.
 */

// _GNUBOARD_ 상수는 그누보드5 config.php가 정의하므로 여기서는 정의하지 않는다.
// (load_gnuboard5() 호출 후 사용 가능)

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');

require_once __DIR__ . '/config.php';

// 에러 표시
if (defined('meeting_API_DEBUG') && meeting_API_DEBUG) {
    error_reporting(E_ALL);
    ini_set('display_errors', '1');
} else {
    error_reporting(0);
    ini_set('display_errors', '0');
}

/**
 * JSON 응답 후 종료
 */
function api_respond($status_code, $data) {
    http_response_code($status_code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
    exit;
}

function api_ok($data = []) {
    api_respond(200, array_merge(['ok' => true], $data));
}

function api_error($status_code, $message, $extra = []) {
    api_respond($status_code, array_merge([
        'ok' => false,
        'error' => $message,
    ], $extra));
}

/**
 * 요청 메서드 강제
 */
function require_method($expected) {
    $method = $_SERVER['REQUEST_METHOD'] ?? '';
    if (strtoupper($method) !== strtoupper($expected)) {
        api_error(405, "Method Not Allowed. Expected: $expected");
    }
}

/**
 * API 토큰 인증
 *
 * 헤더: X-API-Token: <토큰>
 */
function require_auth() {
    $headers = function_exists('getallheaders') ? getallheaders() : [];
    // 헤더 키 대소문자 정규화
    $headers_lower = [];
    foreach ($headers as $k => $v) {
        $headers_lower[strtolower($k)] = $v;
    }
    $token = $headers_lower['x-api-token']
        ?? ($_SERVER['HTTP_X_API_TOKEN'] ?? '');

    $is_default = (meeting_API_TOKEN === 'change-me-please-use-strong-random-token');
    if (!meeting_API_TOKEN) {
        api_error(500, 'Server misconfigured: API token is empty in config.php');
    }
    if ($is_default && !meeting_API_DEBUG) {
        api_error(500, 'Server misconfigured: default API token used in production. Change meeting_API_TOKEN in config.php.');
    }
    if (!hash_equals(meeting_API_TOKEN, $token)) {
        api_error(401, 'Invalid or missing X-API-Token');
    }
}

/**
 * JSON 바디 파싱
 */
function read_json_body() {
    $raw = file_get_contents('php://input');
    if ($raw === '' || $raw === false) return [];
    $data = json_decode($raw, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        api_error(400, 'Invalid JSON body: ' . json_last_error_msg());
    }
    return is_array($data) ? $data : [];
}

/**
 * 게시판 정보 조회 (write_table 이름 등 포함)
 *
 * 호출 전에 _load_gnuboard5.php가 endpoint의 전역 스코프에서 require되어야 한다.
 * 함수 안에서 require하면 common.php의 $g5 등이 함수 로컬에 갇혀버린다.
 */
function get_board_or_die($bo_table) {
    global $g5;
    $bo_table = preg_replace('/[^a-z0-9_]/i', '', $bo_table);
    $row = sql_fetch("SELECT * FROM {$g5['board_table']} WHERE bo_table = '$bo_table'");
    if (!$row) {
        api_error(404, "Board not found: bo_table=$bo_table. 그누보드5 관리자에서 게시판을 먼저 생성하세요.");
    }
    return $row;
}

function write_table_of($bo_table) {
    global $g5;
    $bo_table = preg_replace('/[^a-z0-9_]/i', '', $bo_table);
    return $g5['write_prefix'] . $bo_table;
}
