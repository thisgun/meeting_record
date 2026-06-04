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
        └── setup_board.php           ← 게시판 자동 생성 후 삭제
```

## 빠른 시작

1. **FTP 업로드** — `plugin/meeting_api/` 를 그누보드5 plugin 안에 그대로
2. **운영 토큰 설정** — `config.local.php.example` → `config.local.php` 복사 후 토큰 변경
3. **게시판 자동 생성** — `setup_board.php`에 `X-API-Token` 헤더를 포함한 POST 요청 1회
4. **setup_board.php 삭제** (보안)
5. **헬스체크** — `health.php`에 `X-API-Token` 헤더를 포함한 GET 요청

자세한 가이드는 상위 폴더의 [README.md](../README.md) 참고.

## API 엔드포인트

| Method | Path | 용도 |
|--------|------|------|
| GET | `health.php` | 환경 점검 |
| POST | `post.php` | 회의 요약 → 게시글 |
| POST | `comment.php` | 발화 → 댓글 |
| POST | `setup_board.php` | 게시판 1회 자동 생성 |

모든 API 요청은 헤더 `X-API-Token` 필수.

```bash
curl -H "X-API-Token: YOUR_TOKEN" \
  https://YOUR-DOMAIN/<그누보드폴더>/plugin/meeting_api/health.php

curl -X POST -H "X-API-Token: YOUR_TOKEN" \
  https://YOUR-DOMAIN/<그누보드폴더>/plugin/meeting_api/setup_board.php
```
