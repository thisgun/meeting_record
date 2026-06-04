# g5_meeting_api — 그누보드5 회의록 등록 PHP 플러그인

회의록 자동 등록을 위한 그누보드5 plugin/ 표준 배치 패키지.

## 설치 위치

이 폴더의 `plugin/meeting_api/` 를 그누보드5 의 `plugin/` 안에 통째로 업로드.

```
gnuboard5/
└── plugin/
    └── meeting_api/      ← 여기에
        ├── _bootstrap.php
        ├── _load_gnuboard5.php
        ├── config.php
        ├── config.local.php          ← config.local.php.example을 복사해서 만듦
        ├── health.php
        ├── post.php
        ├── comment.php
        ├── update_post.php
        ├── list_comments.php
        ├── update_comment.php
        ├── delete_post.php
        └── setup_board.php           ← 게시판 자동 생성 후 삭제
```

## 빠른 시작

1. **FTP 업로드** — `plugin/meeting_api/` 를 그누보드5 plugin 안에 그대로
2. **운영 토큰 설정** — `config.local.php.example` → `config.local.php` 복사 후 토큰 변경
   - `setup_board.php` 실행 시에만 `define('meeting_API_ALLOW_SETUP', true);` 설정
3. **게시판 자동 생성** — `setup_board.php`에 `X-API-Token` 헤더를 포함한 POST 요청 1회
4. **`meeting_API_ALLOW_SETUP`을 false로 되돌리거나 setup_board.php 삭제** (보안)
5. **헬스체크** — `health.php`에 `X-API-Token` 헤더를 포함한 GET 요청

자세한 가이드는 상위 폴더의 [README.md](../README.md) 참고.

## API 엔드포인트

| Method | Path | 용도 |
|--------|------|------|
| GET | `health.php` | 환경 점검 |
| POST | `post.php` | 회의 요약 → 게시글 |
| POST | `comment.php` | 발화 → 댓글 |
| POST | `update_post.php` | 게시글 제목/본문 수정 |
| POST | `list_comments.php` | 게시글 댓글 목록 조회 |
| POST | `update_comment.php` | 댓글 본문/작성자 수정 |
| POST | `delete_post.php` | 게시글과 댓글 삭제 |
| POST | `setup_board.php` | 게시판 1회 자동 생성 |

모든 API 요청은 헤더 `X-API-Token` 필수.
`update_*`, `list_comments.php`, `delete_post.php`는 기본적으로 `post.php`가 생성한 marker 있는 게시글만 대상으로 동작합니다.
기존 marker 없는 글을 임시로 다뤄야 할 때는 `config.local.php`에서 `meeting_API_ALLOW_UNMARKED_WRITES`를 true로 설정한 뒤 작업 후 되돌리세요.
`setup_board.php`는 `config.local.php`에서 `meeting_API_ALLOW_SETUP`을 true로 켠 경우에만 실행됩니다.

기본 요청 크기 제한은 전체 JSON 3 MiB, 게시글 본문 2 MiB, 댓글 본문 256 KiB입니다.
운영 환경에서 조정이 필요하면 `config.local.php`에 `meeting_API_MAX_BODY_BYTES`,
`meeting_API_MAX_POST_CONTENT_BYTES`, `meeting_API_MAX_COMMENT_CONTENT_BYTES`를 정의하세요.

```bash
curl -H "X-API-Token: YOUR_TOKEN" \
  https://YOUR-DOMAIN/<그누보드폴더>/plugin/meeting_api/health.php

curl -X POST -H "X-API-Token: YOUR_TOKEN" \
  https://YOUR-DOMAIN/<그누보드폴더>/plugin/meeting_api/setup_board.php
```
