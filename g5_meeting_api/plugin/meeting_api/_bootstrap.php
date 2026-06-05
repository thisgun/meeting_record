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

function meeting_client_ip() {
    return trim((string)($_SERVER['REMOTE_ADDR'] ?? ''));
}

function meeting_ip_matches_cidr($ip, $cidr) {
    $parts = explode('/', $cidr, 2);
    if (count($parts) !== 2) {
        return false;
    }
    $network = trim($parts[0]);
    $prefix = trim($parts[1]);
    if ($network === '' || $prefix === '' || !ctype_digit($prefix)) {
        return false;
    }
    $ip_bin = @inet_pton($ip);
    $network_bin = @inet_pton($network);
    if ($ip_bin === false || $network_bin === false || strlen($ip_bin) !== strlen($network_bin)) {
        return false;
    }
    $prefix_bits = (int)$prefix;
    $max_bits = strlen($ip_bin) * 8;
    if ($prefix_bits < 0 || $prefix_bits > $max_bits) {
        return false;
    }
    $full_bytes = intdiv($prefix_bits, 8);
    $remaining_bits = $prefix_bits % 8;
    if ($full_bytes > 0 && substr($ip_bin, 0, $full_bytes) !== substr($network_bin, 0, $full_bytes)) {
        return false;
    }
    if ($remaining_bits === 0) {
        return true;
    }
    $mask = (0xff << (8 - $remaining_bits)) & 0xff;
    return (ord($ip_bin[$full_bytes]) & $mask) === (ord($network_bin[$full_bytes]) & $mask);
}

function meeting_ip_matches_rule($ip, $rule) {
    $ip = trim((string)$ip);
    $rule = trim((string)$rule);
    if ($ip === '' || $rule === '') {
        return false;
    }
    if ($rule === '*') {
        return true;
    }
    if (strpos($rule, '/') !== false) {
        return meeting_ip_matches_cidr($ip, $rule);
    }
    $ip_bin = @inet_pton($ip);
    $rule_bin = @inet_pton($rule);
    return $ip_bin !== false && $rule_bin !== false && hash_equals($rule_bin, $ip_bin);
}

function meeting_ip_allowed($ip, $rules) {
    $rules = trim((string)$rules);
    if ($rules === '') {
        return true;
    }
    foreach (explode(',', $rules) as $rule) {
        if (meeting_ip_matches_rule($ip, $rule)) {
            return true;
        }
    }
    return false;
}

function meeting_require_allowed_ip() {
    $rules = defined('meeting_API_ALLOWED_IPS') ? (string)meeting_API_ALLOWED_IPS : '';
    if ($rules === '') {
        return;
    }
    $ip = meeting_client_ip();
    if (!meeting_ip_allowed($ip, $rules)) {
        api_error(403, 'Client IP is not allowed for meeting_api.');
    }
}

/**
 * API 토큰 인증
 *
 * 헤더: X-API-Token: <토큰>
 */
function require_auth() {
    meeting_require_allowed_ip();

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

function meeting_request_scheme() {
    $forwarded = strtolower(trim((string)($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')));
    if ($forwarded !== '') {
        $first = trim(explode(',', $forwarded)[0]);
        if ($first === 'https' || $first === 'http') {
            return $first;
        }
    }
    $https = strtolower(trim((string)($_SERVER['HTTPS'] ?? '')));
    if ($https !== '' && $https !== 'off') {
        return 'https';
    }
    return ((string)($_SERVER['SERVER_PORT'] ?? '') === '443') ? 'https' : 'http';
}

function meeting_public_g5_url() {
    if (defined('meeting_PUBLIC_BASE_URL') && trim((string)meeting_PUBLIC_BASE_URL) !== '') {
        return rtrim((string)meeting_PUBLIC_BASE_URL, '/');
    }

    $host = trim((string)($_SERVER['HTTP_X_FORWARDED_HOST'] ?? ''));
    if ($host !== '') {
        $host = trim(explode(',', $host)[0]);
    }
    if ($host === '') {
        $host = trim((string)($_SERVER['HTTP_HOST'] ?? ($_SERVER['SERVER_NAME'] ?? 'localhost')));
    }

    $script = (string)($_SERVER['SCRIPT_NAME'] ?? ($_SERVER['PHP_SELF'] ?? ''));
    $base_path = '';
    $marker = '/plugin/meeting_api';
    $pos = strpos($script, $marker);
    if ($pos !== false) {
        $base_path = substr($script, 0, $pos);
    } else {
        // /gnu5624/plugin/meeting_api/post.php 형태가 아니어도 endpoint 위치 기준으로 추정
        $base_path = dirname(dirname(dirname($script)));
        if ($base_path === '.' || $base_path === DIRECTORY_SEPARATOR) {
            $base_path = '';
        }
    }
    $base_path = rtrim(str_replace('\\', '/', $base_path), '/');
    return meeting_request_scheme() . '://' . $host . $base_path;
}

function meeting_public_post_url($bo_table, $wr_id) {
    return meeting_public_g5_url()
        . '/bbs/board.php?bo_table=' . rawurlencode((string)$bo_table)
        . '&wr_id=' . (int)$wr_id;
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
