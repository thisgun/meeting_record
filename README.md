# 회의록 자동 기록 시스템 (meeting_record)

[![Release](https://img.shields.io/github/v/release/thisgun/meeting_record?style=flat)](https://github.com/thisgun/meeting_record/releases)
[![License](https://img.shields.io/badge/license-LGPL--2.1-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)

핸드폰으로 녹음한 회의 음성 파일을 업로드하면, AI가 자동으로 화자를 구분하고 텍스트로 변환한 뒤 요약해서 게시판에 등록해주는 도구입니다.

**모든 처리는 로컬 PC에서 일어납니다** — 음성/텍스트가 외부 클라우드로 나가지 않고, 비용도 0원.

> **⚠️ 안내:** 초기 버전에서 `meeting`을 `metting`으로 잘못 표기했으나, 저장소명·게시판 `bo_table=meeting`·PHP 폴더 `plugin/meeting_api/`·환경변수 `MEETING_*` 등 전반을 `meeting`으로 정정했습니다. 기존 `metting` 설치본을 쓰시는 경우 마이그레이션 절차는 [CHANGELOG](CHANGELOG.md)를 참고하세요.

## 빠른 시작

### 1. Python 파이프라인 (회의 처리)

```powershell
git clone https://github.com/thisgun/meeting_record.git
cd meeting_record

# 전용 가상환경 생성·활성화 (권장 — 전역 파이썬 오염/버전 충돌 방지)
python -m venv .venv-meetingrec
.\.venv-meetingrec\Scripts\Activate.ps1      # PowerShell
# .venv-meetingrec\Scripts\activate.bat      # cmd(명령 프롬프트)일 경우 이 줄

cp .env.example .env                   # 환경 변수 채우기
pip install -r requirements.txt
pip install -e . --no-deps              # 선택: meeting-record 같은 CLI 명령 등록
ollama pull gemma4:e2b               # 기본 요약 모델
python scripts/download_models.py     # AI 모델 사전 다운로드 (~6GB)
python doctor.py                       # 시스템 진단
python main.py "회의.mp3" --no-upload   # 첫 실행: G5 없이 로컬 저장만
```

> **💡 가상환경을 꼭 쓰세요.** 이 프로젝트는 `torch`·`faster-whisper`·`pyannote.audio` 등 무거운 패키지를 최신 버전으로 끌어옵니다. 전역 파이썬에 바로 설치하면 `open-webui` 처럼 버전을 고정해 쓰는 다른 앱과 충돌(`numpy`, `faster-whisper` 등)이 납니다. 전용 venv로 격리하면 안전합니다. 이후 작업할 때마다 새 터미널에서 먼저 활성화하세요.
>
> **셸별 활성화 명령** (사용하는 터미널에 맞게):
>
> | 셸 | 활성화 |
> |---|---|
> | PowerShell | `.\.venv-meetingrec\Scripts\Activate.ps1` |
> | cmd(명령 프롬프트) | `.venv-meetingrec\Scripts\activate.bat` |
> | Git Bash | `source .venv-meetingrec/Scripts/activate` |
>
> 활성화되면 프롬프트 앞에 `(.venv-meetingrec)` 가 붙습니다.
> - **cmd에서 `Activate.ps1`을 실행하면 메모장이 열립니다** — `.ps1`은 PowerShell 전용이라 cmd에선 파일이 "열기"만 됩니다. cmd에선 위 `activate.bat`을 쓰세요.
> - **PowerShell에서 "실행 정책" 오류**가 나면 한 번만: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 2. 그누보드5 PHP 플러그인 (게시판 자동 등록)

[Releases 페이지](https://github.com/thisgun/meeting_record/releases/latest)에서 `g5_meeting_api-vX.Y.Z.zip` 다운로드 → 압축 풀어서 안의 `plugin/meeting_api/` 폴더를 그누보드5의 `plugin/` 안에 FTP 업로드. 자세한 절차는 아래 [그누보드5 plugin 표준 배치](#그누보드5-plugin-표준-배치) 섹션.

### 3. 웹 UI (선택)

```bash
python -m streamlit run app.py
```
브라우저에서 `http://localhost:8501` — 회의 목록/검색/비교/편집/Export 모두 GUI.

## 필수 외부 의존성

- **Python 3.10 ~ 3.14** ([python.org](https://python.org)) — 3.9 이하 불가. 최신 3.14까지 동작합니다.
- **ffmpeg** — 오디오 변환에 필수. OS별 설치:
  | OS | 설치 명령 |
  |---|---|
  | Windows | `winget install Gyan.FFmpeg --source winget` |
  | macOS | `brew install ffmpeg` |
  | Linux | `sudo apt install ffmpeg` (또는 배포판 패키지 매니저) |

  > ⚠️ **설치 후 반드시 새 터미널을 여세요.** PATH는 새 셸부터 반영되므로, 설치한 *같은* 창에서 바로 실행하면 `FFmpegNotFoundError`가 그대로 납니다. (winget 사용자가 가장 자주 겪는 함정)
- **Ollama** + 모델 (예: `ollama pull gemma4:e2b`)
- **그누보드5 + XAMPP/cafe24** (로컬 또는 원격 호스팅)

`python doctor.py` 로 모든 의존성을 한 번에 점검 가능. (ffmpeg가 PATH에 없어도 winget/choco/scoop 표준 설치 위치를 자동 탐색하므로, 새 터미널을 못 연 경우에도 대개 동작합니다.)

---

## 목차

1. [이게 뭐 하는 프로그램인가요?](#1-이게-뭐-하는-프로그램인가요)
2. [전체 시스템 구조](#2-전체-시스템-구조)
3. [디렉토리 구조 상세](#3-디렉토리-구조-상세)
4. [데이터 흐름 (실행 순서)](#4-데이터-흐름-실행-순서)
5. [핵심 용어 정리](#5-핵심-용어-정리)
6. [환경 구성](#6-환경-구성)
7. [실행 방법](#7-실행-방법)
8. [자주 발생하는 문제 (트러블슈팅)](#8-자주-발생하는-문제-트러블슈팅)
9. [운영 시 점검 사항](#9-운영-시-점검-사항)

---

## 1. 이게 뭐 하는 프로그램인가요?

### 사용 시나리오

회의를 마치고 이런 작업을 자동화하고 싶다고 상상해보세요:

1. 회의 중에 핸드폰으로 녹음 버튼만 누름
2. 녹음 끝나고 PC에 음성 파일을 옮김
3. 명령어 한 번 실행
4. 자동으로:
   - 누가 어떤 말을 했는지 화자별로 구분
   - 음성을 한국어 텍스트로 변환
   - 회의 제목, 개요, 결정 사항, 액션 아이템으로 요약
   - 로컬 데이터베이스에 저장
   - 사내 게시판(그누보드5)에 자동 등록

이 모든 걸 한 번의 명령으로 처리합니다.

### 왜 만들었나?

- **회의록 작성 시간 절약**: 매번 손으로 정리 안 해도 됨
- **검색 가능한 기록**: 모든 회의가 DB와 게시판에 누적됨
- **프라이버시**: 모든 처리가 로컬 PC에서 수행됨 (음성/텍스트가 외부 클라우드로 안 나감)
- **비용 0원**: 오픈소스 + 로컬 LLM (Ollama)만 사용

---

## 2. 전체 시스템 구조

이 프로젝트는 **3개의 독립된 구성 요소**가 협력합니다.

```
┌────────────────────────────────────────────────────────────────┐
│  ① Python 파이프라인  (meeting_record/)                       │
│                                                                │
│   음성파일.mp3 → ffmpeg → WhisperX → speechbrain → Ollama     │
│        ↓                                              ↓        │
│   SQLite 저장 ───────────────────────────────────────►         │
│                                                       │        │
└──────────────────────────────────────────────────────┼─────────┘
                                                       │ HTTP
                                                       ▼
┌──────────────────────────────────────────────────────┬─────────┐
│  ② PHP REST API  (g5_meeting_api/plugin/meeting_api) │         │
│                                                       │         │
│   /health.php  /post.php  /comment.php  /update_*.php          │
│   /list_comments.php  /delete_post.php ◄────────────┘          │
│        │                                                       │
│        │ 그누보드5 common.php 로드                              │
│        ▼                                                       │
├────────────────────────────────────────────────────────────────┤
│  ③ 그누보드5  (<그누보드5루트>/) ← 원본 무수정                  │
│                                                                │
│   PHP 게시판 엔진 + MariaDB (XAMPP)                            │
│   "meeting" 게시판에 게시글 + 댓글 등록                       │
└────────────────────────────────────────────────────────────────┘
```

### 왜 3개로 나눴나?

- **① Python 파이프라인** — AI/ML 라이브러리(PyTorch, Whisper)를 쓰려면 Python이 필수
- **② PHP REST API** — 그누보드5는 PHP 기반이라 PHP에서 호출하는 게 가장 안전. 원본을 건드리지 않고 별도 폴더에서 외부 API 제공
- **③ 그누보드5 원본** — 사용자가 원본 코드를 수정하지 않기로 요구. 향후 그누보드5 업그레이드 시 충돌 없음

각 구성 요소는 독립적으로 교체 가능합니다. 예: 그누보드5 대신 워드프레스를 쓰고 싶으면 ②만 다시 만들면 됨.

---

## 3. 디렉토리 구조 상세

```
meeting_record/
│
├── main.py                    # CLI 진입점
├── config.py                  # .env 파일 로드 및 검증
├── requirements.txt           # Python 패키지 목록
├── .env                       # 환경 변수 (사용자 비밀값, git 무시)
├── .env.example               # .env 작성 가이드
│
├── src/                       # 핵심 모듈
│   ├── audio.py               # 오디오 파일을 16kHz WAV로 변환
│   ├── transcriber.py         # 음성 → 텍스트 + 화자 분리
│   ├── diarizer_local.py      # 로컬 화자 분리 (HF 토큰 불필요)
│   ├── summarizer.py          # Ollama gemma4:e2b로 요약
│   ├── storage.py             # SQLite 저장/조회
│   └── g5_client.py           # 그누보드5 API 호출
│
├── scripts/
│   └── download_models.py     # AI 모델 사전 다운로드
│
├── data/                      # 데이터 저장소 (git 무시)
│   ├── meetings.db            # SQLite 데이터베이스
│   ├── uploads/               # 원본 음성 파일 백업
│   ├── work/                  # 변환된 WAV + 발화 캐시(JSON)
│   └── models/                # 다운로드한 AI 모델
│
├── g5_meeting_api/            # ② PHP REST API 배포 패키지
│   ├── README.md
│   └── plugin/meeting_api/
│       ├── _bootstrap.php       # 공통 헬퍼: 인증, JSON 응답
│       ├── _load_gnuboard5.php  # 그누보드5 common.php 로드 (트릭 포함)
│       ├── config.php           # API 토큰, bo_table 설정
│       ├── health.php           # GET: 헬스 체크
│       ├── post.php             # POST: 회의 요약을 게시글로 등록
│       ├── comment.php          # POST: 발화 1건을 댓글로 등록
│       ├── update_post.php      # POST: 게시글 제목/본문 수정
│       ├── list_comments.php    # POST: 게시글 댓글 목록 조회
│       ├── update_comment.php   # POST: 댓글 본문/작성자 수정
│       ├── delete_post.php      # POST: 게시글과 댓글 삭제
│       ├── cleanup_tests.php    # POST: 오래된 연결 테스트 글 정리
│       └── setup_board.php      # POST: 게시판 자동 생성
│
└── <그누보드5루트>/             # ③ 별도 설치 위치. 저장소에는 포함되지 않음
    └── plugin/meeting_api/      # 위 배포 패키지를 복사해 배치
```

### Apache가 접근하는 방식

XAMPP Apache는 기본적으로 `C:\xampp\htdocs\` 폴더를 서비스합니다. 로컬 테스트에서 그누보드5를 `C:\xampp\htdocs\gnuboard5\`에 설치했다면, 이 저장소의 `g5_meeting_api\plugin\meeting_api\` 폴더를 아래 위치로 복사합니다:

```
C:\xampp\htdocs\gnuboard5\plugin\meeting_api\
```

원격 서버에서도 같은 원칙입니다. ZIP 안의 `plugin/meeting_api/` 폴더를 그누보드5의 `plugin/` 폴더 안에 업로드하면 됩니다.

---

## 4. 데이터 흐름 (실행 순서)

`python main.py "회의.mp3"` 명령을 실행하면 다음 단계로 흘러갑니다:

```
┌─────────────────────────────────────────────────────────────────┐
│ [1/6] 오디오 변환                                                │
│       audio.py가 ffmpeg를 호출                                   │
│       회의.mp3 → 16kHz mono WAV (음성인식에 최적화된 포맷)        │
│       data\uploads\ 에 원본 백업, data\work\<uuid>.wav 생성     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ [2/6] 음성 인식 + 화자 분리                                       │
│       transcriber.py: faster-whisper(small) → 한국어 텍스트 변환 │
│       + 내장 word_timestamps로 단어별 시작/끝 시간 산출          │
│       + diarizer_local.py: speechbrain으로 화자 임베딩 추출       │
│       + scikit-learn 클러스터링으로 화자 N명 자동 추정             │
│                                                                  │
│       결과: [{"start":0.5, "end":2.3, "speaker":"사용자1",       │
│              "text":"안녕하세요"}, ...]                          │
│                                                                  │
│       ★ 이 결과를 data\work\회의.<파일지문>.segments.json 에 캐시 저장 │
│         (다음 실행 시 STT 안 다시 돌림)                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ [3/6] 회의 요약                                                  │
│       summarizer.py: Ollama gemma4:e2b 호출                     │
│       프롬프트: "다음 회의를 정리해주세요" + 발화 전체           │
│       출력: JSON {"title": "...", "summary_md": "## 개요 ..."}  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ [4/6] 로컬 DB 저장                                               │
│       storage.py: SQLite (data\meetings.db)                     │
│       - meetings 테이블: 회의 제목, 요약, 길이, 동기화 상태       │
│       - utterances 테이블: 발화 23건 각각 (화자, 시간, 텍스트)    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ [5/6] 요약 미리보기 (화면 출력)                                   │
│       제목, 마크다운 요약을 콘솔에 표시                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ [6/6] 그누보드5 업로드                                            │
│       g5_client.py가 HTTP POST                                  │
│       → /plugin/meeting_api/post.php                            │
│         (게시글 1개 = 회의 요약)                                 │
│       → /plugin/meeting_api/comment.php                         │
│         (댓글 23개 = 발화 각각 "[03:15] 사용자1: ...")          │
│                                                                  │
│       PHP API → common.php 로드 → MariaDB에 직접 INSERT          │
│                 → g5_board / g5_write_meeting 테이블 갱신        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                        ✓ 완료
                        http://127.0.0.1/gnuboard5/bbs/board.php?bo_table=meeting
                        에서 결과 확인
```

---

## 5. 핵심 용어 정리

| 용어 | 설명 |
|------|------|
| **STT** | Speech-to-Text. 음성을 텍스트로 변환하는 기술 |
| **Whisper** | OpenAI가 공개한 다국어 음성 인식 모델. 한국어 정확도 우수 |
| **faster-whisper** | Whisper를 CTranslate2로 가속한 구현. 단어 단위 타임스탬프 제공 (Python 3.9~3.14) |
| **Diarization** | 화자 분리. "누가 언제 말했는지" 구분하는 기술 |
| **pyannote** | 화자 분리의 사실상 표준 라이브러리. HuggingFace 토큰 필요 |
| **speechbrain** | 음성 임베딩 라이브러리. 우리는 ECAPA-TDNN 모델로 화자 임베딩 추출 |
| **ECAPA-TDNN** | 사람 목소리를 192차원 벡터로 변환하는 신경망. 비슷한 목소리는 비슷한 벡터 |
| **클러스터링** | 비슷한 벡터끼리 묶기. 발화별 음성 벡터를 묶어 화자 그룹 형성 |
| **LLM** | Large Language Model. 텍스트 입출력 AI. 우리는 요약에 사용 |
| **Ollama** | 로컬에서 LLM을 실행하는 도구. 외부 API 호출 없이 PC 안에서 돌아감 |
| **gemma4:e2b** | Google Gemma 4 효율 모델. 7.7GB. 한국어 요약 품질과 속도 균형 |
| **그누보드5** | 한국에서 인기 있는 무료 PHP 게시판 엔진 |
| **XAMPP** | Apache + MariaDB + PHP를 한 번에 설치해주는 패키지 |
| **MariaDB** | MySQL의 오픈소스 포크. 호환됨 |
| **bo_table** | 그누보드5에서 게시판 한 개를 식별하는 코드. 우리는 `"meeting"` 사용 |
| **wr_id** | 그누보드5 게시글 또는 댓글의 고유 ID |
| **wr_is_comment** | 0이면 게시글, 1이면 댓글 (같은 테이블 사용) |

---

## 6. 환경 구성

### 운영 환경 (현재 설치 완료)

| 구성 요소 | 버전 | 위치 |
|-----------|------|------|
| Windows 11 Pro | - | - |
| Python | 3.13.3 | `C:\Python313` |
| ffmpeg | 8.1.1 | PATH에 등록됨 (winget 설치) |
| XAMPP (Apache + MariaDB + PHP) | PHP 8.2.12, MariaDB 10.4.32 | `C:\xampp\` |
| Ollama | 0.23.1 | 서비스로 실행 중 |
| gemma4:e2b 모델 | 7.7GB | Ollama가 관리 |

### Python 패키지 (requirements.txt)

```text
faster-whisper    # Whisper STT 엔진 (단어 타임스탬프 포함, Python 3.9~3.14)
pyannote.audio    # 고정밀 화자 분리 (선택, HF 토큰 필요 / Python 3.13+는 자동 설치 제외)
torch             # 딥러닝 프레임워크 (CPU 버전)
torchaudio        # 오디오 처리
speechbrain       # 로컬 화자 임베딩 (HF 토큰 불필요)
scikit-learn      # 클러스터링
soundfile         # WAV 파일 입출력
ollama            # Ollama Python 클라이언트
requests          # HTTP 호출 (그누보드5 API)
python-dotenv     # .env 파일 로드
pydub             # 오디오 메타데이터
psutil            # RAM/VRAM 진단 및 저메모리 안전장치
```

설치 명령:
```powershell
cd meeting_record

# 전용 가상환경 생성·활성화 (최초 1회)
python -m venv .venv-meetingrec
.\.venv-meetingrec\Scripts\Activate.ps1      # PowerShell
# .venv-meetingrec\Scripts\activate.bat      # cmd일 경우 이 줄

pip install -r requirements.txt
pip install -e . --no-deps              # 선택: meeting-record 같은 CLI 명령 등록
```

> 활성화된 venv 안에서는 프롬프트 앞에 `(.venv-meetingrec)` 가 표시됩니다. 새 터미널을 열 때마다 다시 활성화해야 합니다 — 셸별 명령은 위 [빠른 시작](#1-python-파이프라인-회의-처리)의 활성화 표를 참고하세요. (cmd에서 `Activate.ps1`을 실행하면 메모장이 열리니 `activate.bat`을 쓰고, PowerShell 실행정책 오류가 나면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 를 1회 실행)

### AI 모델 (사전 다운로드, ~600MB · small 기준)

| 모델 | 용도 | 크기 | 다운로드 위치 |
|------|------|------|---------------|
| faster-whisper-small | 한국어 음성 → 텍스트 (단어 타임스탬프 포함) | 500MB | `data\models\faster-whisper-small\` |
| spkrec-ecapa-voxceleb | 화자 임베딩 | 85MB | `data\models\spkrec-ecapa-voxceleb\` |

> **왜 사전 다운로드?** Windows에서 HuggingFace는 기본적으로 캐시에 심볼릭 링크를 만드는데, 일반 사용자 권한으로는 실패합니다. 그래서 `scripts/download_models.py`가 우리 프로젝트 폴더에 직접 다운로드하도록 해두었습니다.

다운로드 명령:
```powershell
python scripts\download_models.py
```

### 환경 변수 (.env)

```env
# HuggingFace 토큰 (선택)
# 비워두면 로컬 화자 분리 (speechbrain) 자동 사용
# 채우면 더 정확한 pyannote 사용 (https://hf.co/pyannote/speaker-diarization-3.1 약관 동의 필요)
HUGGINGFACE_TOKEN=

# Ollama 설정
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=gemma4:e2b
OLLAMA_KEEP_ALIVE=0
OLLAMA_NUM_CTX_MAX=32768
OLLAMA_NUM_PREDICT=8192
OLLAMA_NUM_GPU=
OLLAMA_TIMEOUT_SEC=300
OLLAMA_SUMMARY_CHUNK_SEC=900
OLLAMA_MIN_FREE_RAM_GB=4
OLLAMA_MEMORY_WAIT_SEC=30

# Whisper 설정
WHISPER_MODEL=small              # tiny/base/small/medium/large-v3
WHISPER_COMPUTE_TYPE=int8        # CPU에서는 int8 권장
WHISPER_LANGUAGE=ko
TYPO_CORRECTION=1                # STT 후 사전/.env 오타 보정 적용
TYPO_CORRECTION_RULES=           # 예: 지개차=>지게차;태양관=>태양광
TYPO_CORRECTION_AI=0             # 1이면 로컬 Ollama로 명백한 STT 오타만 추가 검사

# 품질 게이트
QUALITY_CHECK=1                  # STT/화자 분리 위험 신호를 회의록 상단에 표시
QUALITY_BLOCK_UPLOAD=1           # 품질이 낮으면 G5 자동 업로드 차단

# 그누보드5 API
G5_API_BASE=http://127.0.0.1/gnuboard5/plugin/meeting_api
G5_API_TOKEN=
G5_BO_TABLE=meeting

# 경로 (보통 변경 안 함)
DB_PATH=./data/meetings.db
WORK_DIR=./data/work
UPLOAD_DIR=./data/uploads
```

> **중요:** `config.py`는 `.env` 값이 시스템 환경변수보다 **우선** 적용되도록 `load_dotenv(override=True)`로 설정되어 있습니다. 시스템에 `OLLAMA_HOST=0.0.0.0` 같은 잘못된 값이 있어도 `.env`가 이깁니다.

---

## 7. 실행 방법

### 기본 실행

```powershell
cd meeting_record
python main.py "회의녹음.mp3" --no-upload
```

진행 단계가 화면에 출력됩니다:
```
[1/6] 오디오 변환 (ffmpeg)
[2/6] 음성 인식 + 화자 분리 (WhisperX small, 분리: 로컬 (speechbrain))
[3/5] 회의 요약 (Ollama gemma4:e2b)
[4/5] SQLite 저장
[5/5] 요약 미리보기
✓ 완료 (--no-upload: 원격 업로드 생략)
  meeting_id=1
```

그누보드5 플러그인과 `.env`의 `G5_API_BASE/G5_API_TOKEN`을 설정한 뒤에는 `--no-upload` 없이 실행하면 게시판까지 업로드됩니다.

`pip install -e . --no-deps`를 실행했다면 같은 명령을 짧게 쓸 수도 있습니다:
```powershell
meeting-record "회의녹음.mp3" --no-upload
meeting-doctor
meeting-export 5 --format html
```

### CLI 옵션

```powershell
# 화자 수를 강제 지정 (자동 추정 끄기)
python main.py "회의.mp3" --speakers 3

# 다인원 회의가 1~2명으로 뭉치면 실제 예상 화자 수로 다시 분리
# STT 캐시가 있어도 화자 라벨만 다시 계산해서 캐시를 갱신합니다.
python main.py "회의.mp3" --speakers 6

# STT는 그대로 두고 새 자동 화자 분리 로직만 다시 적용
python main.py "회의.mp3" --rediarize

# 그누보드5 업로드 생략 (로컬 DB에만 저장)
python main.py "회의.mp3" --no-upload

# 품질 게이트가 업로드를 막아도 꼭 올려야 할 때만 강행
python main.py "회의.mp3" --force-upload

# DB에 저장된 회의 조회
python main.py --show 1

# 업로드 실패한 회의 재전송
python main.py --resync

# 도움말
python main.py --help
```

기본 자동 화자 분리는 배포용 사용성을 우선해 적응형으로 동작합니다. 로컬 `speechbrain`
분리 결과가 1인/소수 발화처럼 애매하면 짧거나 비슷한 클러스터를 병합해 한 사람을
`사용자1`, `사용자2`로 쪼개는 오류를 줄입니다. 반대로 다인원 회의 신호가 뚜렷하면
긴 발화를 짧은 창으로 나눠 임베딩을 뽑고, 높은 화자 수 후보를 보존하며 병합을 약하게
적용합니다. 실제 화자 수를 알고 있고 더 세밀한 분리가 필요할 때만 `--speakers N` 또는
`WATCH_SPEAKERS=N`을 사용하세요.

### 품질 게이트

이 도구는 회의록을 자동으로 “확정”하지 않고, STT/화자 분리 결과가 위험해 보이면 회의록 상단에 `품질 경고`를 붙입니다.

다음 신호가 겹치면 품질을 `낮음`으로 판정하고, 기본값에서는 G5 자동 업로드를 차단합니다.

- 긴 녹음인데 발화가 거의 감지되지 않음
- 긴 회의인데 화자가 1명으로만 인식됨
- 같거나 비슷한 문장이 반복됨
- Whisper 신뢰도 지표가 낮거나 무음 구간이 텍스트화됨

차단된 회의록은 로컬 SQLite DB에는 저장됩니다. 원문을 확인한 뒤 정말 올려야 하면 `python main.py "회의.mp3" --force-upload`로 강행하거나 `.env`에서 `QUALITY_BLOCK_UPLOAD=0`으로 바꿀 수 있습니다.

### 처리 시간 가이드 (CPU 환경)

#### Whisper 모델 선택 (`.env` 의 `WHISPER_MODEL`)

| 모델 | 크기 | 107분 오디오 STT 예상 | 한국어 정확도 |
|------|------|----------------------|--------------|
| `tiny` | 75MB | ~15분 | 낮음 (회의록 부적합) |
| `base` | 150MB | ~25분 | 보통 |
| **`small`** | **500MB** | **~40분** | **양호** (기본값, 권장) |
| `medium` | 1.5GB | ~115분 | 매우 좋음 |
| `large-v3` | 3GB | ~250분 | 최고 |

#### LLM 모델 선택 (`.env` 의 `OLLAMA_MODEL`)

| 모델 | 크기 | 171발화 요약 예상 | 품질 |
|------|------|------------------|------|
| `qwen3:4b` | 2.5GB | ~10분 | 양호 |
| `gemma3:4b` | 3.3GB | ~12분 | 양호 |
| `exaone3.5:7.8b` | 4.8GB | ~20분 | 한국어 특화, 좋음 |
| **`gemma4:e2b`** | **7.7GB** | **~30분** | **매우 좋음** (기본값) |
| `gemma4:e4b` | 9.6GB | 30분+ (긴 context 불가) | 짧은 회의만 |

`gemma4:e2b`가 기본값입니다. 다만 RTX 3050 Laptop 4GB처럼 VRAM이 작은 환경에서는
모델 전체를 GPU에 올릴 수 없고, CPU fallback도 free RAM이 부족하면 멈춘 것처럼 보일 수
있습니다. 이 프로젝트는 STT/화자분리 직후 WhisperX, pyannote, speechbrain 캐시를 정리한
뒤 free RAM이 `OLLAMA_MIN_FREE_RAM_GB`보다 낮으면 Ollama 호출을 시작하지 않습니다. 이때
STT 캐시는 남으므로 메모리를 비우고 다시 실행하면 요약 단계부터 이어갈 수 있습니다.

저메모리 환경 권장값:

```env
OLLAMA_MODEL=gemma4:e2b
OLLAMA_KEEP_ALIVE=0
OLLAMA_NUM_CTX_MAX=32768     # 100분 안팎 긴 회의 권장. 짧은 회의만 8192~16384 가능
OLLAMA_NUM_PREDICT=8192
OLLAMA_SUMMARY_CHUNK_SEC=900 # 긴 회의는 15분 단위 상세 요약 후 최종 통합
OLLAMA_MIN_FREE_RAM_GB=6     # gemma4:e2b는 4GB보다 6~8GB 권장
# GPU offload가 계속 실패하면 CPU만 사용. 단, free RAM이 충분해야 합니다.
# OLLAMA_NUM_GPU=0
# 4GB VRAM에서는 OLLAMA_NUM_GPU=999 같은 전체 GPU 강제 값을 쓰지 마세요.
WHISPER_BATCH_SIZE=4
```

긴 회의는 기본적으로 `OLLAMA_SUMMARY_CHUNK_SEC` 기준으로 구간별 상세 요약을 만든 뒤 최종
회의록으로 통합합니다. `OLLAMA_NUM_CTX_MAX`를 너무 낮추면 구간 요약 또는 최종 통합 단계에서
JSON 지시가 context 밖으로 밀려 `##` 같은 조각 응답이 나올 수 있습니다. 요약 품질보다
안정성이 더 중요하거나 free RAM 확보가 어렵다면 `qwen3:4b` 같은 더 작은 모델을 먼저 사용해 보세요.

#### 추천 조합 (107분 회의 기준)

| 우선순위 | Whisper | LLM | 총 예상 시간 |
|---------|---------|-----|-------------|
| **속도 최우선** | `small` | `qwen3:4b` | **~50분** |
| **균형 (권장)** | `small` | `gemma4:e2b` | ~70분 |
| 정확도 우선 | `medium` | `gemma4:e2b` | ~145분 |
| 최고 품질 | `large-v3` | `exaone3.5:7.8b` | ~270분 |

> **변경 후 모델 다운로드**: 새 Whisper 모델 사용 시 `python scripts/download_models.py` 실행 (또는 `WHISPER_DOWNLOAD_ALL=1` 환경변수로 전체 받기)

#### CPU 최적화 추가 옵션

`.env`에서 설정:
```
WHISPER_VAD_FILTER=1         # 무음 구간 사전 필터링 (5~15% 단축)
WHISPER_CPU_THREADS=0        # 0=모든 코어 자동 사용
WHISPER_BATCH_SIZE=8         # 메모리 여유 있으면 16으로
```

#### GPU(CUDA) 가속

NVIDIA GPU가 있으면 STT가 **10~30배 빨라집니다**. 107분 회의가 **5~10분**에 끝납니다.

**1단계: 시스템 진단**
```powershell
python doctor.py
```
출력에서 다음 확인:
- `✓ CUDA available` 이면 바로 사용 가능 (3단계로 점프)
- `! PyTorch는 CPU 전용 빌드입니다` 이면 2단계 실행 필요
- `! nvidia-smi 없음` 이면 NVIDIA GPU 또는 드라이버 없음 → 하드웨어 추가 필요

**2단계: PyTorch GPU 빌드 재설치** (venv 활성화 상태에서)
```powershell
# 기존 CPU 버전 제거 (torchvision도 반드시 함께 — 안 그러면 whisperx/pyannote가 깨집니다)
pip uninstall -y torch torchaudio torchvision

# CUDA 빌드 설치 (최신 드라이버면 cu128 권장)
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu128
```

> ⚠️ **CUDA 버전은 환경마다 다릅니다.** 위 `cu128`은 비교적 최신 드라이버 기준입니다. 구형 GPU·드라이버이거나 Linux/다른 CUDA 버전이라면, OS·CUDA를 선택해 정확한 명령을 생성해 주는 **[PyTorch 공식 설치 셀렉터](https://pytorch.org/get-started/locally/)** 를 사용하세요. 지원 CUDA 버전은 `nvidia-smi` 우측 상단의 `CUDA Version` 으로 확인합니다.
>
> NVIDIA 드라이버는 NVIDIA 공식 사이트에서 받으세요. CUDA Toolkit은 PyTorch가 번들 라이브러리를 쓰므로 별도 설치가 필요 없습니다.

**3단계: `.env`에서 활성화**
```env
DEVICE=auto                 # CUDA 자동 감지 (권장)
# 또는 명시적으로
# DEVICE=cuda

WHISPER_MODEL=medium        # GPU에서는 medium/large-v3도 충분히 빠름
WHISPER_COMPUTE_TYPE=       # 빈 값 = 자동 (cuda면 float16)
WHISPER_BATCH_SIZE=16       # VRAM 8GB+ 권장, 12GB+면 32
```

**검증**
```powershell
python doctor.py            # DEVICE=cuda 표시 확인
python main.py "회의.mp3"   # [info] DEVICE=cuda, compute_type=float16 출력
```

**GPU 권장 사양**
| GPU | VRAM | 권장 Whisper | 처리 시간 (107분 회의) |
|-----|------|-------------|----------------------|
| RTX 3050 Laptop | 4GB | small, batch 4~8 | STT는 가능, LLM은 free RAM 확보 필요 |
| GTX 1660 / RTX 2060 | 6GB | small | ~10분 |
| RTX 3060 12GB | 12GB | medium | ~7분 |
| RTX 4070 / 3080 | 12GB | large-v3 | ~6분 |
| RTX 4090 / A100 | 24GB+ | large-v3 + batch_size 64 | ~3분 |

**Fallback 동작**
- `DEVICE=cuda` 지정했으나 PyTorch GPU 빌드 없음 → 자동으로 CPU fallback + 경고
- `DEVICE=auto` (기본) → CUDA 가용 시 자동 사용, 아니면 CPU
- 어떤 경우든 동작은 항상 보장됨

> **첫 실행은 느림**: 모델 다운로드 (~6GB) + 모델 메모리 로딩으로 추가 시간 필요. 두 번째부터는 위 표 적용.

### 결과 확인

```powershell
# 1) 로컬 SQLite
python main.py --show 1

# 2) 그누보드5 게시판 (브라우저)
start http://127.0.0.1/gnuboard5/bbs/board.php?bo_table=meeting

# 3) 특정 회의 직접 보기
start http://127.0.0.1/gnuboard5/bbs/board.php?bo_table=meeting&wr_id=8
```

### 웹 UI (Streamlit) — 브라우저로 회의록 관리

CLI 대신 브라우저에서 회의 목록 조회/편집/검색/export까지 모두 가능.

```powershell
cd meeting_record
# 최초 1회: .env에 STREAMLIT_ACCESS_PASSWORD=강력한-비밀번호 설정
python -m streamlit run app.py
```

브라우저 자동으로 열리거나 `http://localhost:8501` 접속 후 비밀번호로 로그인.

**핸드폰/다른 PC에서 접속** (같은 Wi-Fi):
```powershell
python -m streamlit run app.py --server.address 0.0.0.0
```
→ `http://<PC-IP>:8501` 로 접속 (예: `http://192.168.45.246:8501`)

> 외부 접속을 열 때는 `STREAMLIT_ACCESS_PASSWORD`를 반드시 설정하세요. 기본값은 12시간 세션 만료, 5회 실패 시 300초 잠금이며 실패/잠금 상태는 `data/app_auth_state.json`에 저장됩니다. 필요하면 `.env`에서 `STREAMLIT_SESSION_TTL_SEC`, `STREAMLIT_AUTH_MAX_ATTEMPTS`, `STREAMLIT_AUTH_LOCKOUT_SEC`, `STREAMLIT_AUTH_STATE_PATH`를 조정하세요. 로컬 테스트에서만 인증을 끄려면 `.env`에 `STREAMLIT_ALLOW_NO_AUTH=1`을 명시합니다. 인터넷에 공개해야 한다면 앱 비밀번호만 믿지 말고 VPN, Cloudflare Access, Nginx/Apache Basic Auth 같은 앞단 인증을 함께 두는 것을 권장합니다.

**페이지 구성:**

| 페이지 | 기능 |
|--------|------|
| 📋 **회의 목록** | 전체 회의 + 상세 보기 (요약/발화/통계/편집/Export 탭) |
| 🔍 **검색** | FTS5 회의 + 발화 검색 |
| 📚 **사전 관리** | 도메인 사전 추가/삭제 + Whisper 프롬프트 미리보기 |
| 👤 **화자 등록** | 등록된 화자 목록 + 관리 |

**회의 상세 편집 탭에서 가능한 작업:**
- 화자 라벨 일괄 변경 (`사용자3` → `장관님`)
- 발화 텍스트 인라인 수정 (검색 → 수정 → 저장)
- 요약 본문 마크다운 직접 편집
- 회의 삭제 (확인 입력 필수)

**Export 탭에서 가능한 작업:**
- `.docx` 다운로드
- `.html` 다운로드 (브라우저 Ctrl+P로 PDF 변환 가능)
- 그누보드5 게시글 바로 이동 링크

> **참고**: 모든 변경 사항은 즉시 SQLite에 반영되고 FTS 인덱스도 자동 동기화됩니다. 그누보드5는 별도 sync가 필요한 부분 (현재 발화 텍스트는 자동 sync, 화자명/요약은 수동 갱신).

### 외부 디바이스에서 접속

같은 Wi-Fi의 핸드폰/노트북에서:
```
http://<PC의-LAN-IP>/gnuboard5/bbs/board.php?bo_table=meeting
```

PC의 IP 확인: `ipconfig` 명령 또는 `Get-NetIPAddress`

### 민감 정보(PII) 자동 마스킹

회의 중 의도치 않게 노출되는 개인정보(주민번호/휴대폰/카드/계좌/이메일/일반전화)를 자동으로 가립니다.

**`.env` 설정** (`.env.example` 기본값은 `partial` — 관공서/민감 회의 권장):
```env
PII_MASK_LEVEL=partial   # 일부 가림: 901234-1****67  ← 권장
# PII_MASK_LEVEL=full    # 라벨 대체: [주민번호]
# PII_MASK_LEVEL=off     # 마스킹 안 함 (코드 미설정 시 기본)
```

> ⚠️ 회의 중 언급된 긴 숫자(예산·통계 등)가 드물게 오탐 마스킹될 수 있습니다. 정확한 숫자가 더 중요하면 `off`로 두되, **게시판 공개 전 직접 검수**하세요. 실행 시 현재 마스킹 레벨이 콘솔에 표시됩니다(off면 경고).

**처리 시점**: STT 후 + 요약 후 자동 적용 (발화와 요약 본문 모두). 그누보드5에 등록되는 댓글/게시글도 자동으로 마스킹된 결과가 올라갑니다.

**예시 (partial)**:
- `010-1234-5678` → `010-****-**78`
- `hong.gildong@example.com` → `h**********g@example.com`
- `901234-1234567` → `901234-1****67`
- `1234-5678-9012-3456` → `1234-****-****-3456`

### 데이터 자동 백업

```powershell
# 수동 실행
python scripts/backup.py                            # ./data/backups/<날짜>/ 로 백업
python scripts/backup.py --out D:\backup            # 출력 폴더 지정
python scripts/backup.py --keep 14                  # 14일 초과 백업 자동 삭제
python scripts/backup.py --no-mysql                 # SQLite만
```

MariaDB 위치나 계정이 기본값과 다르면 `.env`에 설정합니다:

```env
MYSQLDUMP_PATH=C:\xampp\mysql\bin\mysqldump.exe
MYSQL_DATABASE=meeting
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
```

**Windows 작업 스케줄러로 자동화** (관리자 PowerShell):
```powershell
$project = (Resolve-Path .).Path
schtasks /create /tn "MeetingRecordBackup" /sc DAILY /st 03:00 `
    /tr "cmd /c `"cd /d $project && python scripts\backup.py --keep 30`""
```

매일 새벽 3시에 자동 백업 + 30일 초과 자동 정리.

백업 내용:
- `meetings.db` (SQLite, sqlite3.backup() API로 안전한 복사)
- `meeting.sql` (MariaDB mysqldump, 트리거/이벤트/루틴 포함)

### 회의록 export (Word / HTML)

```powershell
python export.py 5                              # meeting_id=5 → ./data/exports/<title>.docx
python export.py 5 --format html                # HTML로
python export.py 5 --format all                 # docx + html 둘 다
python export.py 5 --no-transcript              # 발화 전문 제외 (요약만)
python export.py --all                          # 모든 회의 일괄
```

**PDF가 필요하면**: HTML로 export 후 브라우저에서 `Ctrl+P` → "PDF로 저장"이 가장 깨끗합니다. 한국어 폰트 문제 없고, 표/리스트도 그대로 보입니다.

생성된 docx 포함 내용:
- 표지 + 메타정보 표 (작성일시/원본/길이/화자수)
- 마크다운 요약 본문 (헤더/리스트/굵게 등 변환)
- 발화 전문 표 (시간/화자/내용) — `--no-transcript`로 제외 가능

### 회의 통계

```powershell
python stats.py 5                    # 화자별 발언 횟수/시간/비율
python stats.py 5 --time              # 시간 구간별 분포 추가
python stats.py 5 --json              # JSON 출력 (다른 도구 연동용)
```

예시 출력:
```
화자                      발언 횟수      총 발언 시간      평균 발언     비율
사용자4                       44      30분 55초        42초  32.7%
사용자3 (장관)                62       28분 6초        27초  29.7%
```

### 처리 결과 알림 (Slack / 이메일)

회의 처리 완료/실패 시 자동으로 통보합니다. **두 채널 모두 옵션**이고, 설정된 채널만 작동합니다.

**.env 설정 예시**

```env
NOTIFY_LEVEL=all                                # all=성공/실패, fail=실패만, off=알림 끔

# Slack
NOTIFY_SLACK_WEBHOOK=https://hooks.slack.com/services/T.../B.../...

# 이메일 (Gmail 예시: 앱 비밀번호 사용)
NOTIFY_EMAIL_HOST=smtp.gmail.com
NOTIFY_EMAIL_PORT=587
NOTIFY_EMAIL_USER=sender@gmail.com
NOTIFY_EMAIL_PASS=앱비밀번호
NOTIFY_EMAIL_FROM=sender@gmail.com
NOTIFY_EMAIL_TO=receiver1@example.com,receiver2@example.com
```

**Slack 메시지 예시:**
```
✅ 회의록 처리 완료
제목: 산업안전 강화 기관장 회의...
원본: 회의.mp3
길이: 1시간 46분 / 발화 171건 / 화자 6명
처리 시간: 33분 12초
게시글: wr_id=548
```

watcher.py로 무인 운영 시에도 자동 적용됩니다.

### 도메인 사전 — STT 정확도 향상

회의에 자주 등장하는 고유명사/전문용어를 사전에 등록해두면 STT가 더 정확하게 인식하고, 자주 발생하는 오인식은 자동으로 교정됩니다.

**`.env`에서 간단 오타 보정**

몇 개만 빠르게 고치고 싶다면 DB 사전에 등록하지 않고 `.env`에 문자 그대로 치환 규칙을 넣을 수 있습니다.

```env
TYPO_CORRECTION=1
TYPO_CORRECTION_RULES=중대재수자=>중대재해;태양관=>태양광;지개차=>지게차
```

- 여러 규칙은 `;`로 구분합니다.
- `TYPO_CORRECTION_RULES`는 정규식이 아니라 단순 문자열 치환입니다.
- 회의 처리 시 캐시를 쓰더라도 발화 텍스트에 다시 적용되고, 보정이 있으면 `.segments.json` 캐시도 갱신됩니다.
- 복잡한 정규식이나 많은 용어는 아래 `dict.py` 사전 관리 기능을 쓰는 편이 좋습니다.

**로컬 AI 오타 보정 (선택)**

규칙으로 등록하지 않은 명백한 STT 오인식까지 문맥으로 잡고 싶다면 로컬 Ollama 보정을 켤 수 있습니다.

```env
TYPO_CORRECTION=1
TYPO_CORRECTION_AI=1
TYPO_CORRECTION_AI_MODEL=          # 빈 값이면 OLLAMA_MODEL 사용
TYPO_CORRECTION_AI_CHUNK_SIZE=30   # 한 번에 검사할 발화 수
```

AI 보정은 발화의 `text`만 고치며 화자, 시간, 발화 순서는 바꾸지 않습니다. 프롬프트는 요약/문체 개선/순화/재작성을 금지하고 “명백한 STT 오타만” 고치도록 제한되어 있습니다. 그래도 고유명사나 농담 표현을 잘못 고칠 수 있으므로 중요한 회의에서는 `TYPO_CORRECTION_RULES` 또는 `dict.py` 사전 규칙을 우선 권장합니다.

**기본 사용**

```powershell
# 1) 회의에 등장할 용어 등록 (Whisper에게 컨텍스트 제공)
python dict.py add 산업안전감독관
python dict.py add 노동부

# 2) 자주 발생하는 오인식 교정 패턴 등록
python dict.py add 산업안전 --pattern 산업안정              # "산업안정"으로 인식되면 "산업안전"으로
python dict.py add 이민재 --pattern "(?:이민자|이민제)"     # 정규식 매칭
python dict.py add 중대재해 --pattern 중대제해

# 3) 미리보기
python dict.py test "산업안정 강화 회의"                    # 어떻게 치환되는지 확인
python dict.py prompt                                       # Whisper에게 전달될 컨텍스트 확인
```

**작동 방식**

1. **회의 처리 시 자동 적용** (`main.py` 또는 `watcher.py` 어느 쪽이든):
   - Whisper의 `initial_prompt`로 등록된 용어들 전달 → 처음부터 정확한 인식
   - STT 결과에 후처리 치환 적용 → Whisper가 놓친 오류 교정
2. **기존 회의에 소급 적용**:
   ```powershell
   python dict.py apply-to-meeting 5            # meeting_id=5 의 발화 + 요약 + 그누보드5 일괄 갱신
   python dict.py apply-to-meeting 5 --skip-remote   # 그누보드5는 건드리지 않고 로컬만
   ```

**CSV 일괄 등록**

```csv
term,pattern,replacement,notes
산업안전,산업안정,,STT 흔한 오류
중대재해,중대제해,,
이민재,(?:이민자|이민제),,정책실장
```
```powershell
python dict.py import-csv dictionary.csv
```

**관리**

```powershell
python dict.py list                          # 전체 목록
python dict.py disable 3                     # id=3 비활성화 (삭제는 아님)
python dict.py enable 3
python dict.py delete 3                      # 완전 삭제
```

**예시: 정부 회의 도메인**

```powershell
python dict.py add 산업안전강화 --pattern 산업안정강화
python dict.py add 기관장 --pattern 기간장
python dict.py add 중대재해
python dict.py add 노동부
python dict.py add 안전공단
python dict.py add 갈매기특공대 --pattern "갈매기 특공대"
```

> **권장**: 첫 회의 처리 후 STT 결과를 훑어보며 흔한 오류 단어를 등록하세요. 두 번째 회의부터 같은 오류가 자동 교정됩니다.

### 그누보드5 plugin 표준 배치

회의록 등록 PHP API는 **그누보드5의 표준 `plugin/` 디렉토리** 안에 `meeting_api/` 폴더로 설치합니다. 그누보드5 원본 코드는 한 줄도 수정하지 않고 새 폴더만 추가하는 방식.

**디렉토리 구조**:
```
gnuboard5/                         ← 원본 (수정 안 함)
└── plugin/
    └── meeting_api/               ← 추가하는 폴더
        ├── _bootstrap.php
        ├── _load_gnuboard5.php
        ├── config.php             ← G5 경로 자동 (../../로 그누보드5 루트)
        ├── config.local.php       ← 운영 토큰 (git 제외)
        ├── health.php
        ├── post.php
        ├── comment.php
        ├── update_post.php
        ├── list_comments.php
        ├── update_comment.php
        ├── delete_post.php
        └── setup_board.php        ← 게시판 자동 생성 (1회 후 삭제)
```

**호출 URL**: `https://YOUR-DOMAIN/<gnuboard폴더>/plugin/meeting_api/health.php`

#### 로컬 (XAMPP)
로컬 그누보드5를 쓰는 경우 `<그누보드5루트>\plugin\meeting_api\`에 설치합니다.
```powershell
curl -H "X-API-Token: YOUR_TOKEN" http://127.0.0.1/gnuboard5/plugin/meeting_api/health.php
python doctor.py
```

#### 원격 (cafe24 등) — 4단계

**배포 패키지**: GitHub Releases의 `g5_meeting_api-vX.Y.Z.zip`

1. **FTP 업로드** — ZIP 풀면 안에 `plugin/meeting_api/` 폴더가 그대로 있음. 이 폴더를 원격 그누보드5의 `plugin/` 안에 업로드:
   ```
   /home/<user>/www/
   └── gnu5615/
       └── plugin/
           └── meeting_api/        ← 업로드
   ```

2. **운영 토큰 설정** — `config.local.php.example` → `config.local.php` 복사 후 토큰/디버그 변경:
   ```php
   define('meeting_API_TOKEN', '강력한_랜덤_48자_이상');
   define('meeting_API_DEBUG', false);
   // 선택: 호출 가능한 IP/CIDR 제한. 비워두면 IP 제한 없음.
   // define('meeting_API_ALLOWED_IPS', '203.0.113.10,203.0.113.0/24');
   // setup_board.php 실행 시에만 true. 성공 후 false로 되돌리거나 파일 삭제.
   define('meeting_API_ALLOW_SETUP', true);
   // 선택: 전체 JSON/게시글/댓글 본문 크기 제한 조정
   // define('meeting_API_MAX_BODY_BYTES', 3145728);
   // define('meeting_API_MAX_POST_CONTENT_BYTES', 2097152);
   // define('meeting_API_MAX_COMMENT_CONTENT_BYTES', 262144);
   ```

3. **게시판 자동 생성 (1회)**:
   ```bash
   curl -X POST -H "X-API-Token: YOUR_TOKEN" \
     https://YOUR-DOMAIN/gnu5615/plugin/meeting_api/setup_board.php
   ```
   성공 후 `meeting_API_ALLOW_SETUP`을 `false`로 되돌리거나 **setup_board.php를 즉시 삭제**.

   기존 버전에서 생성된 marker 없는 글을 임시로 수정/삭제해야 한다면
   `config.local.php`에 `define('meeting_API_ALLOW_UNMARKED_WRITES', true);`를 잠깐 추가할 수 있습니다.
   작업 후에는 다시 제거하거나 `false`로 되돌리세요.

4. **Python `.env`**:
   ```env
   G5_API_BASE=https://YOUR-DOMAIN/gnu5615/plugin/meeting_api
   G5_API_TOKEN=원격_토큰
   ```

#### 로컬 + 원격 동시 등록

```env
G5_TARGETS=local,remote
G5_API_BASE_LOCAL=http://127.0.0.1/gnuboard5/plugin/meeting_api
G5_API_TOKEN_LOCAL=로컬_토큰
G5_API_BASE_REMOTE=https://YOUR-DOMAIN/gnu5615/plugin/meeting_api
G5_API_TOKEN_REMOTE=원격_토큰
# 기존 단일 설정(default)이 원격 게시판이었다면 remote로 승계
G5_LEGACY_TARGET=remote
```

회의 처리 시 두 게시판에 동시 등록하며, `python main.py --resync`는 타겟별 누락분을 다시 전송합니다.

#### 검증

```powershell
python doctor.py                                # G5 타겟 섹션
python scripts/check_g5_remote.py               # 전체 타겟 health + 쓰기/수정/삭제 테스트
python scripts/check_g5_remote.py --target remote
python scripts/check_g5_remote.py --cleanup-stale --cleanup-minutes 60
```

Python 코드 변경 후에는 빠른 단위 테스트도 실행할 수 있습니다:
```powershell
python -m pip install pytest
python -m pytest -q
```

#### plugin 방식의 장점

- ✅ **그누보드5 원본 무수정** — `plugin/` 표준 디렉토리에 새 폴더만 추가
- ✅ **그누보드5 업그레이드 안전** — 충돌 없음
- ✅ **G5 경로 자동** — `__DIR__ . '/../..'` 로 루트 인식
- ✅ **common.php 안전 로드** — plugin 안에서는 SCRIPT_FILENAME 위장 없이 정상 동작

#### 기존 별도 `g5_meeting_api` 배치 정리 (선택)

이전 방식(그누보드5 옆 별도 폴더) 잔재. 선택사항:
```powershell
Remove-Item C:\xampp\htdocs\g5_meeting_api      # junction 정리
# Remove-Item <이전-g5_meeting_api-폴더> -Recurse   # 원본 폴더 (백업 후)
```

#### 보안 주의사항

- `config.local.php` 절대 git/FTP에서 공유 안 함 (토큰 노출)
- `setup_board.php` 작업 후 `meeting_API_ALLOW_SETUP=false`로 되돌리거나 파일 즉시 삭제
- 가능하면 `meeting_API_ALLOWED_IPS`로 Python 실행 PC/서버 IP만 허용
- API 본문 크기 제한 유지 (`meeting_API_MAX_*_BYTES`) — 기본값을 크게 올릴수록 서버 부하 위험 증가
- 그누보드5 `install/` 폴더 운영 시 삭제
- HTTPS 사용 (토큰 평문 전송 보호)

### 화자 등록 (enrollment) — "사용자N" 대신 실제 이름

한 번 사람의 음성을 등록해두면 이후 회의에서 자동으로 실제 이름이 매핑됩니다.

**등록 방법 1: 외부 wav 파일로 등록**
```powershell
# 10초 이상의 깨끗한 음성 (한 사람만, 잡음 적게)
python enroll.py add "장관님" samples/장관님.wav
python enroll.py add "김부장님" samples/김부장.wav
```

**등록 방법 2: 기존 회의에서 자동 추출**

이미 처리한 회의가 있다면 거기서 화자 샘플을 뽑을 수 있습니다:
```powershell
# meeting_id=5 의 "사용자3"의 가장 긴 단일 발화 → wav로 추출
python enroll.py extract-from 5 사용자3 --out data/samples/장관님.wav --target 30
# 그 wav로 등록
python enroll.py add "장관님" data/samples/장관님.wav
```

**확인 / 관리**
```powershell
python enroll.py list                                    # 등록된 화자 목록
python enroll.py test data/samples/test.wav              # 입력 음성이 누구인지 매칭 테스트
python enroll.py delete "장관님"                          # 삭제
```

**자동 매칭**

화자가 등록되어 있으면 `python main.py audio.mp3` 실행 시 다음과 같이 동작:

1. 평소처럼 STT + 화자 분리 (clustering)
2. 각 클러스터의 중심 임베딩을 등록된 화자들과 cosine 유사도 비교
3. 임계값(기본 0.75) 이상 매칭되는 클러스터 → 실제 이름 사용
4. 매칭 안 되는 클러스터 → `SPEAKER_00` → `사용자1` 폴백

콘솔에 매칭 결과가 표시됩니다:
```
[info] 등록 화자 매칭: {0: '장관님', 2: '사회자'}
```

그누보드5 댓글에도 `회의_장관님`, `회의_사회자` 같은 작성자명으로 등록됩니다.

> ⚠️ 한 회의에 한 사람을 매번 정확히 같은 라벨로 매핑하려면 30초 이상의 깨끗한 단일 발화 샘플이 좋습니다.

### 회의 비교 분석

여러 회의 간 통계/키워드 비교 및 시간대별 추이 분석.

**CLI**:

```powershell
# 두 회의 직접 비교 (메타/화자/공통 키워드/A에만/B에만)
python compare.py 3 5

# 월별 회의 통계 (몇 건, 평균 길이, 총 발화)
python compare.py --timeline
python compare.py --timeline --since 2026-01-01 --until 2026-12-31

# 특정 키워드의 월별 등장 빈도
python compare.py --keyword-trend "산업재해"

# 특정 화자의 월별 발언 추이
python compare.py --speaker-trend 사용자3

# 특정 회의의 상위 키워드 (한국어 빈도 분석)
python compare.py --top-keywords 5 --top 30
```

**웹 UI** (`📊 비교` 페이지) 5개 탭:
1. **두 회의 비교** — A/B 선택 → 메타 차이 + 화자 (공통/A만/B만) + 키워드 (공통/A만/B만)
2. **월별 통계** — 월별 회의 수/총 길이/평균/발화 수 표 + 차트
3. **키워드 추이** — 특정 단어가 언제 많이 다뤄졌는지
4. **화자 추이** — 한 사람의 월별 발언량/회의 참여 추이
5. **상위 키워드** — 회의별 가장 자주 나오는 단어 + 차트

**한국어 키워드 추출**:
- `kiwipiepy` (한국어 형태소 분석기)가 설치되어 있으면 자동으로 사용 — **명사 위주 정확한 추출** (NNG/NNP 태그)
- 미설치 시 정규식 기반 폴백 (부사/조사 결합형이 일부 섞일 수 있음)
- 인접 명사는 자동으로 결합 (예: "산업/안전/감독관" → "산업안전감독관")
- 현재 사용 중인 방식: `python doctor.py` 의 "키워드 추출" 섹션에 표시

설치:
```powershell
pip install "kiwipiepy>=0.20.0"        # 형태소 분석 활성화 (선택)
```

### 회의록 검색 (FTS5)

누적된 회의록을 키워드로 검색:

```powershell
python search.py "산업재해"                    # 회의 제목/요약 + 발화 동시 검색
python search.py "지게차" --speaker 사용자3     # 특정 화자의 발화만
python search.py "AI 도입" --meetings-only      # 회의 요약만
python search.py "안전" --since 2026-01-01     # 이 날짜 이후
python search.py "산업재해 OR 지게차" --advanced # FTS5 문법 직접 사용
python search.py --rebuild                      # FTS 인덱스 재구축 (스키마 변경 시)
python search.py --recreate-fts --tokenizer trigram # FTS 테이블을 trigram으로 재생성
```

기본 검색은 일반 검색어를 안전하게 처리합니다. 아래 FTS5 문법을 직접 쓰려면 `--advanced`를 붙이세요.

**FTS5 고급 쿼리 문법**:
- `"단어 단어"` — AND (기본)
- `"단어 OR 단어"` — OR
- `"정확한 구문"` — 따옴표로 묶기
- `"단어1 NEAR/5 단어2"` — 5단어 이내 근접
- `"산업*"` — 접두사 와일드카드

**한국어 검색 팁**: 기본은 trigram 토크나이저라 **최소 3글자** 검색이 가능합니다. 2글자(예: "산재")는 결과가 안 나올 수 있으니 "산업재해", "산재 사망" 처럼 longer 검색을 사용하세요. SQLite 빌드에 trigram이 없으면 자동으로 `unicode61`로 fallback되어 검색 품질이 다소 낮아질 수 있습니다. 현재 tokenizer는 `python doctor.py`의 "SQLite 검색" 섹션에서 확인할 수 있습니다. 나중에 trigram 지원 환경으로 옮겼다면 `python search.py --recreate-fts --tokenizer trigram`으로 FTS 테이블을 다시 만들 수 있습니다.

### 폴더 자동 감시 (watcher)

CLI 명령을 매번 치는 대신, **특정 폴더에 음성 파일을 떨어뜨리기만 하면 자동 처리**됩니다.

```powershell
cd meeting_record
python watcher.py
```

G5 설정 전에는 로컬 DB 저장만 먼저 테스트할 수 있습니다:
```powershell
python watcher.py --no-upload
```

실행 후 `data\watch\` 폴더에 `.mp3`, `.m4a`, `.mp4` 등 음성/동영상 파일을 드롭하면:
1. 파일 크기 변화 감지 (5초간 안정 = 복사 완료로 판단)
2. `main.py` 자동 실행 (`.env`의 `WATCH_SPEAKERS` 적용)
3. STT → 화자 분리 → 품질 점검 → 요약 → DB → 그누보드5 업로드까지 자동 처리
4. 처리 결과는 콘솔 + `data\watch.log`에 기록

품질이 `낮음`으로 판정되면 기본값에서는 G5 업로드가 차단되고 로컬 DB에만 저장됩니다. watcher에서도 강행 업로드가 필요하면 `.env`의 `QUALITY_BLOCK_UPLOAD=0`을 사용하세요.

**Ollama 대기 동작**
- watcher를 다시 켠 직후 첫 요약은 `gemma4:e2b` 콜드 로딩 때문에 step 3에서 60~90초 동안 출력이 없을 수 있습니다. 이후 `생성 중... N청크`가 보이면 정상입니다.
- `OLLAMA_TIMEOUT_SEC` 동안 첫 청크가 전혀 없으면 실패로 처리합니다. 이전 stuck 이후 Ollama 서버 스케줄러가 좀비 상태일 수 있으므로 `ollama stop gemma4:e2b` 또는 Ollama 재시작 후 `python watcher.py`를 다시 실행하세요.
- 메모리 여유가 충분하고 연속 파일 처리 속도가 중요하면 `OLLAMA_KEEP_ALIVE=10m`처럼 모델을 잠시 유지할 수 있습니다. RTX 3050 4GB/저메모리 환경에서는 기본값 `0`이 더 안전합니다.

**핵심 설정 (`.env`)**:
```
# 지원 확장자: mp3, m4a, wav, amr, aac, ogg, flac, wma, mp4
WATCH_DIR=./data/watch          # 감시할 폴더
WATCH_SPEAKERS=6                # 화자 수 (빈 값이면 자동 추정)
WATCH_STABILITY_SEC=5           # 파일 안정 확인 시간
WATCH_NO_UPLOAD=0               # 1이면 G5 업로드 생략
WATCH_LOG=./data/watch.log      # 처리 이력
```

다인원 회의인데 자동 추정 결과가 `사용자1`, `사용자2` 정도로 뭉치면 `WATCH_SPEAKERS=6`처럼 실제 예상 화자 수를 지정하세요. 기존 `.segments.json` 캐시가 있어도 watcher가 `main.py --speakers 6`으로 실행하므로 STT는 재사용하고 화자 라벨만 다시 분리합니다.

**활용 예시:**
- 핸드폰 SMB 공유로 `data\watch\` 폴더에 직접 업로드 → 자동 처리
- 회의 끝나고 PC에 파일 옮기기만 하면 됨 (CLI 명령 안 적어도 됨)
- Windows 시작 시 watcher 자동 실행: 작업 스케줄러 등록

**옵션 명령:**
```powershell
python watcher.py --scan-now    # 폴더의 기존 파일만 처리 후 종료
```

---

## 8. 자주 발생하는 문제 (트러블슈팅)

### 문제 1: "ffmpeg를 찾을 수 없습니다"

**원인**: ffmpeg가 설치되지 않았거나 PATH에 없음.

**해결**:
```powershell
winget install Gyan.FFmpeg --source winget
# 새 PowerShell 창에서:
ffmpeg -version
```

### 문제 2: "MariaDB가 자꾸 다운돼요"

**원인**: XAMPP Control Panel이 외부에서 시작된 mysqld를 인식하지 못해 stale 상태로 표시하고, 사용자가 Start 버튼을 누르면 중복 실행을 시도해 첫 번째 인스턴스가 ibdata1 파일 잠금을 가진 채로 두 번째 인스턴스가 즉시 죽음.

**증상**:
- XAMPP Control Panel에 "Stopped" 표시
- Start 누르면 잠깐 켜졌다가 즉시 죽음
- 에러 로그에 `[ERROR] InnoDB: The innodb_system data file 'ibdata1' must be writable`

**해결**:
1. **현재 실행 중인지 확인**: `Get-Process mysqld`
2. 살아있으면 Start 버튼 누르지 말 것
3. **영구 해결책**: my.ini 의 pid_file을 절대 경로로 변경 (이미 적용됨):
   ```ini
   [mysqld]
   pid_file="C:/xampp/mysql/data/mysql.pid"
   ```
4. **가장 안정적**: Windows 서비스로 등록 (관리자 권한 필요)

### 문제 3: "Failed to connect to Ollama" (Python에서)

**원인 A**: 시스템 환경변수 `OLLAMA_HOST=0.0.0.0`이 설정되어 있는데 Python이 이걸 가져다가 사용. `0.0.0.0`은 서버 바인드 주소이지 클라이언트 접속 주소가 아니므로 연결 실패.

**해결 (이미 적용됨)**:
- `config.py`의 `load_dotenv(override=True)`로 `.env` 우선
- `_validated_ollama_host()` 함수가 `0.0.0.0` → `127.0.0.1` 자동 변환

**원인 B**: STT 처리 중 CPU 100% 점유로 Ollama가 일시적으로 응답 못함.

**해결**:
- `summarizer.py`가 `OLLAMA_TIMEOUT_SEC` 동안 첫 토큰/다음 청크를 기다린 뒤 실패 처리
- step 3에서 처음 60~90초 출력이 없는 것은 모델 콜드 로딩이면 정상
- 발화 캐시(`*.{파일지문}.segments.json`) 덕분에 실패해도 재실행 시 STT 안 다시 함

### 문제 4: "OSError [WinError 1314] symlink 권한 부족"

**원인**: HuggingFace가 모델 다운로드 시 캐시에 심볼릭 링크를 만드는데, Windows 일반 사용자는 권한 없음.

**해결 (이미 적용됨)**: `scripts/download_models.py`가 우리 프로젝트 폴더에 직접 다운로드 (심볼릭 링크 없이). `transcriber.py`는 로컬 폴더를 우선 사용.

만약 다시 발생하면:
```powershell
python scripts\download_models.py
```

### 문제 5: "common.php 로드 시 mysqli 연결 실패"

**원인**: 그누보드5 `common.php`는 `$_SERVER['SCRIPT_FILENAME']`을 기준으로 자기 경로를 계산하므로, 외부 폴더에서 require하면 경로 계산이 깨짐 → dbconfig.php를 못 찾음.

**해결 (이미 적용됨)**: `_load_gnuboard5.php`가 `$_SERVER['SCRIPT_FILENAME']`을 임시로 그누보드5의 index.php 경로로 위장하고 require.

### 문제 6: "그누보드5 게시판에 글이 안 보여요"

**원인 A**: `meeting` 게시판이 만들어지지 않음.

**해결**: API 헬스 체크로 확인
```powershell
curl -H "X-API-Token: YOUR_TOKEN" http://127.0.0.1/gnuboard5/plugin/meeting_api/health.php
# board_exists: true 인지 확인
```

`false`면 SQL로 생성:
```sql
SET SESSION sql_mode='';
INSERT INTO g5_board SELECT * FROM g5_board WHERE bo_table='free';
UPDATE g5_board SET bo_table = 'meeting', bo_subject='회의록',
    bo_count_write=0, bo_count_comment=0 WHERE bo_table='free' LIMIT 1;
CREATE TABLE g5_write_meeting LIKE g5_write_free;
```

**원인 B**: 비회원 글 작성이 막혀있음.

**해결**: 그누보드5 관리자(`http://127.0.0.1/gnuboard5/adm/`)에서 meeting 게시판의 글쓰기 권한을 "모두"로 변경.

### 문제 7: "회의가 너무 길어서 요약이 잘려요"

**원인**: 기본 Ollama context window가 4096 토큰. 긴 회의는 입력이 잘림.

**해결 (이미 적용됨)**: `summarizer.py`가 transcript 길이를 보고 동적으로 num_ctx를
4096~`OLLAMA_NUM_CTX_MAX` 범위에서 자동 조정합니다. 기본값은 32768이며, 메모리가 부족한
PC에서는 `.env`에서 낮출 수 있습니다.

```env
OLLAMA_NUM_CTX_MAX=8192
OLLAMA_NUM_PREDICT=4096
```

### 문제 8: Ollama가 `GPULayers:[]` 이후 멈춘 것처럼 보임

**원인**: WhisperX, pyannote, speechbrain 모델이 같은 Python 프로세스에서 RAM/VRAM을
붙잡고 있는 상태에서 Ollama가 `gemma4:e2b` 같은 큰 모델을 로드하려고 하면 GPU 적재 실패
후 CPU fallback도 메모리 부족으로 진행이 멈출 수 있습니다. RTX 3050 Laptop 4GB 환경에서
특히 자주 발생합니다.

**해결 (이미 적용됨)**:
- STT/화자분리 직후 WhisperX, pyannote, speechbrain 캐시와 CUDA 캐시를 정리합니다.
- Ollama 호출 전 free RAM이 `OLLAMA_MIN_FREE_RAM_GB`보다 낮으면 요약을 시작하지 않고
  STT 캐시만 남긴 뒤 종료합니다.
- `.env`에서 `OLLAMA_KEEP_ALIVE=0`으로 요약 후 Ollama 모델을 바로 해제합니다.

권장 조치:

```powershell
python doctor.py
```

`Ollama 실행 전 여유 RAM 부족`이 보이면 브라우저, IDE, 다른 Python 프로세스, 기존
Ollama 모델을 종료한 뒤 다시 실행하세요.

```powershell
ollama stop gemma4:e2b
```

그래도 부족하면 `.env`에서 다음처럼 낮춥니다.

```env
OLLAMA_NUM_CTX_MAX=8192
OLLAMA_NUM_PREDICT=4096
WHISPER_BATCH_SIZE=4
# 마지막 수단: 더 작은 LLM 사용
# OLLAMA_MODEL=qwen3:4b
```

### 문제 9: watcher 재실행 후에도 새 chat 요청이 계속 대기함

**증상**: 메모리 정리 로그는 정상 출력되고, Python 워커도 `chat()` 호출까지 갔지만
`생성 중...` 청크가 전혀 나오지 않습니다. 첫 stuck 이후 Ollama 서버 내부 스케줄러에
잔존 상태가 남아 새 요청이 계속 대기하는 좀비 상태일 수 있습니다.

**정상 대기와 구분**:
- 정상: `python watcher.py` 재실행 후 첫 요약에서 60~90초 정도 조용하다가 `생성 중... N청크`가 출력됨
- 비정상: `OLLAMA_TIMEOUT_SEC`가 지날 때까지 첫 청크가 전혀 없고 요약 실패로 종료됨

**해결**:
```powershell
ollama stop gemma4:e2b
# 그래도 안 풀리면 Ollama 앱/서비스 재시작 후
python watcher.py
```

이미 STT 캐시가 저장된 파일은 다음 실행 때 발화 캐시를 사용하므로 WhisperX를 다시 돌리지
않고 요약 단계부터 이어갈 수 있습니다. 메모리 여유가 충분한 PC에서 연속 파일 처리 속도가
중요하면 `OLLAMA_KEEP_ALIVE=10m`처럼 모델을 잠시 유지할 수 있지만, 저메모리 환경에서는
`OLLAMA_KEEP_ALIVE=0`을 유지하세요.

### 문제 10: 요약 결과가 `회의록 (자동 생성 실패)` 또는 원본 응답 `##`로 나옴

**원인**: Ollama가 정상 연결은 됐지만 JSON 대신 `##` 같은 마크다운 조각만 반환한 경우입니다.
긴 회의에서 `OLLAMA_NUM_CTX_MAX`가 부족해 JSON 출력 지시가 context 밖으로 잘렸거나, 모델이
JSON 출력 지시를 놓쳤거나, 이전 요청 실패 뒤 모델 상태가 불안정할 때 발생할 수 있습니다.

**해결 (이미 적용됨)**:
- JSON 파싱 실패 시 즉시 성공 처리하지 않고 재시도합니다.
- 재시도 후에도 JSON이 아니면 DB 저장과 그누보드5 업로드 전에 실패로 종료합니다.
- 긴 회의는 `OLLAMA_SUMMARY_CHUNK_SEC` 기준으로 구간별 상세 요약을 만든 뒤 최종 통합합니다.
- 최종 요약에 6개 필수 섹션이 없거나 본문이 너무 짧으면 업로드하지 않습니다.
- transcript가 현재 `OLLAMA_NUM_CTX_MAX`보다 크면 Ollama 호출 전에 필요한 권장 context를
  안내하고 중단합니다.
- STT 캐시는 남아 있으므로 다음 실행은 음성 인식부터 다시 하지 않습니다.

이미 실패 요약이 올라간 게시글은 그누보드5 관리자에서 삭제한 뒤 다시 실행하세요. 계속 반복되면
다음처럼 context와 출력 길이를 조정하거나 Ollama 모델을 재시작합니다.

```powershell
ollama stop gemma4:e2b
python watcher.py
```

```env
OLLAMA_NUM_CTX_MAX=32768
OLLAMA_NUM_PREDICT=8192
OLLAMA_SUMMARY_CHUNK_SEC=900
```

### 문제 11: 업로드 성공 후 출력되는 게시글 URL 경로가 이상함

**증상**: 업로드는 성공했지만 URL이
`/gnuboard5/index.php/.../bbs/board.php?...`처럼 실제 그누보드5 공개 경로와 다르게 출력됩니다.

**원인**: 일부 호스팅 환경에서 그누보드5의 `G5_BBS_URL` 상수가 서버 내부 경로나
`SCRIPT_NAME` 보정값을 섞어 계산하는 경우가 있습니다.

**해결 (이미 적용됨)**:
- Python 클라이언트가 `G5_API_BASE`에서 공개 그누보드5 루트를 계산해 게시글 URL을 보정합니다.
- PHP 플러그인도 `G5_BBS_URL`에 의존하지 않고 `/plugin/meeting_api` 앞 경로를 기준으로 URL을 만듭니다.
- 그래도 특수 호스팅에서 어긋나면 `config.local.php`에 공개 루트를 직접 지정하세요.

```php
define('meeting_PUBLIC_BASE_URL', 'https://YOUR-DOMAIN/gnu5624');
```

---

## 9. 운영 시 점검 사항

### 보안

1. **API 토큰 강화**: `gnuboard5\plugin\meeting_api\config.local.php`
   ```php
   define('meeting_API_TOKEN', '강력한-48자-이상-랜덤-문자열');
   define('meeting_API_DEBUG', false);  // 디버그 정보 노출 차단
   define('meeting_API_ALLOW_SETUP', false);  // 설치 후 비활성화
   // define('meeting_API_ALLOWED_IPS', '203.0.113.10,203.0.113.0/24');
   ```
   동일 토큰을 프로젝트 폴더의 `.env`에 있는 `G5_API_TOKEN`에도 설정.

   토큰 생성:
   ```powershell
   [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
   ```

2. **그누보드5 관리자 계정**: 첫 가입 회원이 자동 최고관리자.
   가입: `http://127.0.0.1/gnuboard5/bbs/register.php`

3. **MariaDB root 비밀번호**: XAMPP 기본은 빈 값. 변경 권장.
   ```sql
   ALTER USER 'root'@'localhost' IDENTIFIED BY '새비밀번호';
   ```

### 백업 대상

회의 데이터를 잃지 않으려면 정기 백업:

| 항목 | 경로 | 주기 |
|------|------|------|
| 로컬 DB | `.\data\meetings.db` | 매주 |
| 원본 음성 | `.\data\uploads\` | 매월 |
| 그누보드5 DB | `meeting` (MariaDB) | 매주 |
| 그누보드5 첨부파일 | `<그누보드5루트>\data\file\meeting\` | 매월 |

MariaDB 백업:
```powershell
& "C:\xampp\mysql\bin\mysqldump.exe" -u root meeting > backup.sql
```

### 디스크 공간

장기 운영 시 디스크 사용 추정:

| 항목 | 1회 평균 | 100회 누적 |
|------|----------|------------|
| AI 모델 (고정) | ~6GB | 6GB |
| 원본 음성 (1시간) | ~60MB | 6GB |
| WAV (1시간) | ~115MB | 11.5GB |
| 캐시 JSON | ~50KB | 5MB |
| DB | ~수십KB | ~수MB |

→ 100회 회의 기준 약 **24GB**. 정기적으로 `data\work\*.wav` 정리 권장 (캐시 JSON은 유지).

### 정기 점검 명령

```powershell
# 1. 모든 서비스 상태
Get-Process mysqld, httpd, ollama -ErrorAction SilentlyContinue
Invoke-WebRequest http://127.0.0.1:11434/api/version
Invoke-WebRequest http://127.0.0.1/gnuboard5/plugin/meeting_api/health.php `
  -Headers @{ "X-API-Token" = "YOUR_TOKEN" }

# 2. 디스크 사용량
Get-ChildItem .\data -Recurse |
    Measure-Object -Property Length -Sum

# 3. 미동기화 회의 확인
python main.py --resync
```

---

## 부록: 작업 흐름 도식 (전체)

```
[사용자]                              [PC]                                [브라우저]
   │                                   │                                      │
   │ 회의 녹음                          │                                      │
   ├──────────────────────────────────►│                                      │
   │                                   │ python main.py meeting.mp3           │
   │                                   ├─►[1] ffmpeg: mp3→wav                 │
   │                                   ├─►[2] WhisperX: 음성→텍스트            │
   │                                   │      speechbrain: 화자 분리           │
   │                                   ├─►[3] Ollama gemma4:e2b: 요약          │
   │                                   ├─►[4] SQLite 저장                      │
   │                                   ├─►[5] 콘솔에 미리보기 출력             │
   │                                   ├─►[6] HTTP POST                       │
   │                                   │      ↓                              │
   │                                   │   PHP API → MariaDB INSERT          │
   │                                   │                                      │
   │ "완료. wr_id=8"                    │                                      │
   │◄──────────────────────────────────┤                                      │
   │                                   │                                      │
   │ 브라우저에서 결과 확인              │                                      │
   ├───────────────────────────────────────────────────────────────────────►│
   │                                   │                                      ↓
   │                                   │                            그누보드5 게시판
   │                                   │                            회의록 게시글 + 댓글
```
