<?php
/**
 * g5_metting_api 설정 (그누보드5 plugin/metting_api 표준 배치)
 *
 * 위치: <그누보드5루트>/plugin/metting_api/
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

// 그누보드5 경로 — plugin/metting_api/ 의 2단계 상위가 그누보드5 루트
if (!defined('G5_PATH_OVERRIDE')) {
    $__root = realpath(__DIR__ . '/../..');
    if (!$__root) $__root = dirname(__DIR__, 2);
    define('G5_PATH_OVERRIDE', $__root);
}

// 기본 설정 (config.local.php에서 덮어쓸 수 있음)
if (!defined('METTING_BO_TABLE')) define('METTING_BO_TABLE', 'metting');
if (!defined('METTING_API_TOKEN')) define('METTING_API_TOKEN', 'change-me-please-use-strong-random-token');
if (!defined('METTING_MB_ID')) define('METTING_MB_ID', '');
if (!defined('METTING_WR_NAME')) define('METTING_WR_NAME', '회의록봇');
if (!defined('METTING_WR_PASSWORD')) define('METTING_WR_PASSWORD', 'meeting_bot');
if (!defined('METTING_WR_EMAIL')) define('METTING_WR_EMAIL', '');
if (!defined('METTING_WR_HOMEPAGE')) define('METTING_WR_HOMEPAGE', '');

// 디버그 모드 자동: localhost면 true, 외부 도메인이면 false
if (!defined('METTING_API_DEBUG')) {
    $__is_remote = (
        !empty($_SERVER['HTTP_HOST'])
        && !preg_match('/^(127\.0\.0\.\d+|localhost|::1)/', $_SERVER['HTTP_HOST'])
    );
    define('METTING_API_DEBUG', !$__is_remote);
}
