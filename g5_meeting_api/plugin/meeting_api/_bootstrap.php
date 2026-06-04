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
    meeting_db_rollback_if_open();
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
    if ($is_default) {
        api_error(500, 'Server misconfigured: default API token is not allowed. Set meeting_API_TOKEN in config.local.php.');
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
    $max_bytes = (int)meeting_API_MAX_BODY_BYTES;
    if ($max_bytes > 0 && strlen($raw) > $max_bytes) {
        api_error(413, 'JSON body is too large', ['max_bytes' => $max_bytes]);
    }
    $data = json_decode($raw, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        api_error(400, 'Invalid JSON body: ' . json_last_error_msg());
    }
    return is_array($data) ? $data : [];
}

function meeting_require_max_bytes($field, $value, $max_bytes) {
    $max_bytes = (int)$max_bytes;
    if ($max_bytes > 0 && strlen((string)$value) > $max_bytes) {
        api_error(413, "$field is too large", [
            'field' => $field,
            'max_bytes' => $max_bytes,
        ]);
    }
}

/**
 * 게시판 코드 검증.
 *
 * 그누보드 게시판 코드는 영문/숫자/underscore만 허용한다. 잘못된 문자를
 * 조용히 제거하면 의도와 다른 게시판에 쓰일 수 있으므로 400으로 막는다.
 */
function meeting_normalize_bo_table($bo_table) {
    $bo_table = trim((string)$bo_table);
    if ($bo_table === '' || !preg_match('/^[A-Za-z0-9_]+$/', $bo_table)) {
        api_error(400, 'Invalid bo_table. Use letters, numbers, and underscore only.');
    }
    return $bo_table;
}

/**
 * SQL 문자열 escape.
 *
 * common.php 로드 후 그누보드의 DB escape 함수를 우선 사용한다.
 */
function meeting_sql_escape($value) {
    $value = (string)$value;
    if (function_exists('sql_escape_string')) {
        return sql_escape_string($value);
    }
    if (function_exists('sql_real_escape_string')) {
        return sql_real_escape_string($value);
    }
    api_error(500, 'Server misconfigured: SQL escape function unavailable.');
}

function meeting_sql_identifier($name) {
    $name = trim((string)$name);
    if ($name === '' || !preg_match('/^[A-Za-z0-9_]+$/', $name)) {
        api_error(500, 'Unsafe SQL identifier.');
    }
    return "`$name`";
}

/**
 * 게시판 정보 조회 (write_table 이름 등 포함)
 *
 * 호출 전에 _load_gnuboard5.php가 endpoint의 전역 스코프에서 require되어야 한다.
 * 함수 안에서 require하면 common.php의 $g5 등이 함수 로컬에 갇혀버린다.
 */
function get_board_or_die($bo_table) {
    global $g5;
    $bo_table = meeting_normalize_bo_table($bo_table);
    $bo_table_esc = meeting_sql_escape($bo_table);
    $board_table_sql = meeting_sql_identifier($g5['board_table']);
    $row = sql_fetch("SELECT * FROM $board_table_sql WHERE bo_table = '$bo_table_esc'");
    if (!$row) {
        api_error(404, "Board not found: bo_table=$bo_table. 그누보드5 관리자에서 게시판을 먼저 생성하세요.");
    }
    return $row;
}

function write_table_of($bo_table) {
    global $g5;
    $bo_table = meeting_normalize_bo_table($bo_table);
    return $g5['write_prefix'] . $bo_table;
}

function meeting_require_api_owned_marker($marker) {
    $marker = (string)$marker;
    if ($marker === (string)meeting_API_MARKER) {
        return;
    }
    if (defined('meeting_API_ALLOW_UNMARKED_WRITES') && meeting_API_ALLOW_UNMARKED_WRITES && $marker === '') {
        return;
    }
    api_error(403, 'Refusing to modify a post that was not created by meeting_api.');
}

function meeting_normalize_idempotency_key($value) {
    $key = trim((string)$value);
    if ($key === '') {
        return '';
    }
    if (strlen($key) > 190) {
        api_error(400, 'idempotency_key is too long');
    }
    if (!preg_match('/^[A-Za-z0-9._:-]+$/', $key)) {
        api_error(400, 'idempotency_key may contain only letters, numbers, dot, colon, underscore, and hyphen');
    }
    return $key;
}

function meeting_db_rollback_if_open() {
    if (!empty($GLOBALS['meeting_api_transaction_open'])) {
        @sql_query('ROLLBACK', false);
        $GLOBALS['meeting_api_transaction_open'] = false;
    }
}

function meeting_sql_query_or_error($sql, $message = 'Database query failed') {
    $result = sql_query($sql, false);
    if (!$result) {
        $extra = [];
        if (defined('meeting_API_DEBUG') && meeting_API_DEBUG && function_exists('sql_error')) {
            $extra['detail'] = sql_error();
        }
        api_error(500, $message, $extra);
    }
    return $result;
}

function meeting_db_begin() {
    meeting_sql_query_or_error('START TRANSACTION', 'Failed to start database transaction');
    $GLOBALS['meeting_api_transaction_open'] = true;
}

function meeting_db_commit() {
    if (!empty($GLOBALS['meeting_api_transaction_open'])) {
        meeting_sql_query_or_error('COMMIT', 'Failed to commit database transaction');
        $GLOBALS['meeting_api_transaction_open'] = false;
    }
}
