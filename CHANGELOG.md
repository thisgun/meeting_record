# Changelog

이 프로젝트의 모든 주요 변경 사항을 이 파일에 기록합니다.

형식: [Keep a Changelog](https://keepachangelog.com/), [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
- 표준 plugin/metting_api/ 디렉토리 배치 (원본 무수정)
- 게시판 자동 생성 스크립트
- 환경별 토큰 분리 (config.local.php)
