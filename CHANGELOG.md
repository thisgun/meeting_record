# Changelog

이 프로젝트의 모든 주요 변경 사항을 이 파일에 기록합니다.

형식: [Keep a Changelog](https://keepachangelog.com/), [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-06-05

### 추가
- **STT 오타 교정** 기능 (전사 후 자동 보정)
  - 규칙 기반 치환: `TYPO_CORRECTION_RULES` (예: `오타1=정타1, 오타2=정타2`)
  - Ollama AI 문맥 교정: `TYPO_CORRECTION_AI` (청크 단위)
  - 환경변수: `TYPO_CORRECTION`, `TYPO_CORRECTION_RULES`, `TYPO_CORRECTION_AI`,
    `TYPO_CORRECTION_AI_MODEL`, `TYPO_CORRECTION_AI_CHUNK_SIZE`
  - `doctor.py` 진단에 오타 교정 설정 표시, 사전(dictionary) 단위 테스트 추가

### 개선
- 요약 실패 시 복구(fallback) 강화 — 청크 단위 부분 요약 등

## [0.3.0] - 2026-06-05

### 추가
- 그누보드5 유지보수 API + 다중 타겟(G5_TARGETS) 동기화, 멱등성 강화

### 개선
- **ffmpeg**: PATH 자동 탐색·런타임 주입으로 whisperx `FFmpegNotFound` 해결, 출력 인코딩(cp949) 안전화
- **GPU**: CUDA 가속을 환경 독립적 선택 옵션으로 정리(배포 대응), `doctor.py` GPU 안내 개선
- **Ollama**: 요약 전 torch 메모리 해제, 스트림 끊김/멈춤 복구
- 공개 배포 안전장치·설치 기본값 정비, CLI·검색 이식성 개선
- 전용 venv(`.venv-meetingrec`) 안내, GitHub Social Preview 이미지

### 문서
- `metting` 잔여 오타 정리, 저장소명 변경(`metting_record` → `meeting_record`) 반영

## [0.2.0] - 2026-06-04

### 변경 (Breaking)
- 게시판 코드 `metting` → `meeting` 으로 일괄 변경
  - 새 게시판 `meeting` + 새 테이블 `g5_write_meeting` 자동 생성
  - 기존 `metting` 데이터는 보존 (롤백 가능)
- PHP 플러그인 폴더: `plugin/metting_api/` → `plugin/meeting_api/`
- PHP 상수: `METTING_*` → `MEETING_*` (API_TOKEN, BO_TABLE 등)
- 환경 변수 기본값: `G5_BO_TABLE=meeting`, `G5_API_BASE` 새 경로
- 저장소 폴더: `g5_metting_api/` → `g5_meeting_api/`
- ZIP 패키지 이름: `g5_meeting_api-vX.Y.Z.zip`

### 마이그레이션 (v0.1.0 → v0.2.0)
1. SQL: `scripts/migrate_metting_to_meeting.sql` 1회 실행
2. PHP: 원격 그누보드5의 `plugin/metting_api/` 폴더 옆에 `plugin/meeting_api/` 업로드
3. .env: `G5_API_BASE` URL과 `G5_BO_TABLE=meeting` 으로 변경

### 안내
프로젝트명/디렉토리명/GitHub 저장소명에 남은 `metting`(오타)은 호환성 유지를 위해 유지합니다.

## [0.1.0] - 2026-06-04

첫 공개 릴리스.

### 핵심 기능
- 음성 파일 → STT (WhisperX + 한국어 wav2vec2 align)
- 화자 분리 (speechbrain ECAPA-TDNN, HuggingFace 토큰 불필요)
- Ollama 로컬 LLM 회의 요약 (gemma4:e2b 기본)
- SQLite 저장 + FTS5 전문 검색
- 그누보드5 자동 등록 (게시글 + 발화 댓글)

### 도구
- `main.py` — CLI 메인 파이프라인
- `app.py` — Streamlit 웹 UI (회의 목록/검색/비교/사전/화자 관리)
- `doctor.py` — 시스템 진단
- `watcher.py` — 폴더 자동 감시 데몬
- `dict.py` — 도메인 사전 (STT 정확도 향상)
- `enroll.py` — 화자 등록 (사용자N → 실제 이름)
- `compare.py` — 회의 비교/시계열 분석
- `export.py` — Word(.docx) / HTML 출력
- `stats.py` — 화자 통계
- `search.py` — FTS5 검색

### 옵션 기능
- DEVICE=auto/cpu/cuda (GPU 가속)
- Whisper 모델 선택 (tiny/base/small/medium/large-v3)
- 도메인 사전 (Whisper initial_prompt + 정규식 후처리)
- 한국어 형태소 분석 (kiwipiepy, 선택)
- PII 마스킹 (주민번호/휴대폰/카드 등)
- Slack/이메일 알림
- 자동 백업 (SQLite + MariaDB)
- 멀티 G5 타겟 (로컬 + 원격 동시 등록)

### 그누보드5 통합
- 표준 plugin/meeting_api/ 디렉토리 배치 (원본 무수정)
- 게시판 자동 생성 스크립트
- 환경별 토큰 분리 (config.local.php)
