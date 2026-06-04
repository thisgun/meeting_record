<?php
/**
 * g5_meeting_api 설정 (그누보드5 plugin/meeting_api 표준 배치)
 *
 * 위치: <그누보드5루트>/plugin/meeting_api/
 *
 * 그누보드5 경로는 plugin 폴더의 2단계 상위로 자동 결정됨.
 * 별도 설정 없이 어디에 설치되어 있든 동작.
 *
 * 운영 토큰 분리:
 * - 같은 폴더에 config.local.php 를 만들어 define() 으로 토큰을 정의하면
 *   이 파일의 기본값을 덮어쓴다. config.local.php 는 git에 올리지 않는다.
 */

// 운영 환경 오버라이드 먼저 로드 (정의된 값은 아래 if (!defined())에서 보존)
if (is_file(__DIR__ . '/config.local.php')) {
    @include_once(__DIR__ . '/config.local.php');
}

// 그누보드5 경로 — plugin/meeting_api/ 의 2단계 상위가 그누보드5 루트
if (!defined('G5_PATH_OVERRIDE')) {
    $__root = realpath(__DIR__ . '/../..');
    if (!$__root) $__root = dirname(__DIR__, 2);
    define('G5_PATH_OVERRIDE', $__root);
}

// 기본 설정 (config.local.php에서 덮어쓸 수 있음)
if (!defined('meeting_BO_TABLE')) define('meeting_BO_TABLE', 'meeting');
if (!defined('meeting_API_TOKEN')) define('meeting_API_TOKEN', 'change-me-please-use-strong-random-token');
if (!defined('meeting_MB_ID')) define('meeting_MB_ID', '');
if (!defined('meeting_WR_NAME')) define('meeting_WR_NAME', '회의록봇');
if (!defined('meeting_WR_PASSWORD')) define('meeting_WR_PASSWORD', 'meeting_bot');
if (!defined('meeting_WR_EMAIL')) define('meeting_WR_EMAIL', '');
if (!defined('meeting_WR_HOMEPAGE')) define('meeting_WR_HOMEPAGE', '');
if (!defined('meeting_API_MARKER')) define('meeting_API_MARKER', 'meeting_api');
if (!defined('meeting_API_ALLOW_UNMARKED_WRITES')) define('meeting_API_ALLOW_UNMARKED_WRITES', false);
if (!defined('meeting_API_ALLOW_SETUP')) define('meeting_API_ALLOW_SETUP', false);
if (!defined('meeting_API_MAX_BODY_BYTES')) define('meeting_API_MAX_BODY_BYTES', 3145728); // 3 MiB
if (!defined('meeting_API_MAX_POST_CONTENT_BYTES')) define('meeting_API_MAX_POST_CONTENT_BYTES', 2097152); // 2 MiB
if (!defined('meeting_API_MAX_COMMENT_CONTENT_BYTES')) define('meeting_API_MAX_COMMENT_CONTENT_BYTES', 262144); // 256 KiB

// 운영 안전을 위해 디버그는 기본 false. 필요할 때 config.local.php에서 명시적으로 true 지정.
if (!defined('meeting_API_DEBUG')) define('meeting_API_DEBUG', false);
