# Project Agent Instructions

## Project Overview

이 저장소는 한국어 회의 음성 파일을 로컬 PC에서 처리해 회의록으로 만드는 도구입니다. 핵심 흐름은 `ffmpeg` 오디오 변환 → WhisperX STT → pyannote 또는 speechbrain 화자 분리 → Ollama `gemma4:e2b` 요약 → SQLite 저장 → 선택적으로 그누보드5 PHP API 업로드입니다.

프로젝트의 중요한 성격은 다음과 같습니다.

- 사용자의 회의 음성, 발화 텍스트, 게시판 토큰을 다루는 개인정보/비밀값 민감 프로젝트입니다.
- Python AI 파이프라인과 PHP 그누보드5 플러그인이 함께 있는 하이브리드 저장소입니다.
- GitHub 배포를 전제로 하므로 로컬 한 사람의 환경만이 아니라 Windows, macOS, Linux, XAMPP, cafe24, 저사양 PC를 함께 고려해야 합니다.
- 로컬 LLM/Ollama 기반이라 네트워크 API 키보다 RAM/VRAM, 모델 크기, 캐시 해제가 자주 문제 됩니다.

## Tech Stack

- Python: 3.10+ 권장, 주요 진입점은 `main.py`, `doctor.py`, `app.py`
- AI/STT: `whisperx`, `faster-whisper`, `pyannote.audio`, `speechbrain`, `torch`, `torchaudio`
- LLM: Ollama, 기본 모델은 `gemma4:e2b`
- Storage: SQLite, 작업 데이터는 `data/` 아래
- Web UI: Streamlit `app.py`
- Remote publishing: PHP 기반 그누보드5 플러그인 `g5_meeting_api/plugin/meeting_api/`
- Packaging: `pyproject.toml`, `requirements.txt`
- Tests: `pytest`, 일부 PHP bootstrap 테스트

## Safety Boundaries

- 절대 커밋하면 안 되는 파일: `.env`, `data/**`, 오디오 파일, `g5_meeting_api/plugin/meeting_api/config.local.php`.
- `.env.example`과 `config.local.php.example`에는 실제 URL, 실제 토큰, 실제 개인정보를 넣지 않습니다.
- 사용자의 실제 `G5_API_TOKEN`, 원격 사이트 URL, 회의 데이터, 음성 파일명은 필요 이상으로 출력하거나 문서에 박제하지 않습니다.
- `data/` 안의 SQLite DB, 캐시, 업로드 파일은 개인정보일 수 있으므로 테스트용으로도 무단 열람/수정하지 않습니다.
- 사용자가 명시하지 않으면 `git reset --hard`, 강제 checkout, 데이터 삭제, 원격 게시글 삭제 같은 파괴적 작업을 하지 않습니다.

## Development Workflow

- 빠른 검색은 `rg`와 `rg --files`를 우선 사용합니다.
- 파일 수정은 수동 편집 시 `apply_patch`를 사용합니다.
- 변경 전에는 관련 파일과 현재 패턴을 먼저 읽고, 기존 구조를 보존합니다.
- 기능 변경 후 가능한 최소 검증을 실행합니다.
- Python 변경 후 기본 검증:

```powershell
python -m compileall config.py doctor.py main.py src tests
python -m pytest
```

- 환경/의존성 진단 변경 후:

```powershell
python doctor.py
```

- PHP 플러그인 변경 시 문법 확인 가능하면:

```powershell
php -l g5_meeting_api/plugin/meeting_api/파일명.php
```

## Coding Conventions

- 한국어 사용자 대상 프로젝트이므로 README, 경고 메시지, CLI 안내는 자연스러운 한국어를 우선합니다.
- 공개 배포용 문서는 Windows PowerShell 예시를 기본으로 하되, OS 차이가 있으면 macOS/Linux도 함께 고려합니다.
- Python 코드는 작은 함수 단위로 유지하고, CLI 출력은 사용자가 원인과 다음 행동을 바로 알 수 있게 씁니다.
- 설정은 가능한 한 `.env` → `config.py` → 호출부 흐름으로 노출합니다.
- 새로운 환경 변수는 `.env.example`, README, `doctor.py` 진단 출력을 함께 갱신합니다.
- 기존 단일 타겟 G5 설정과 멀티 타겟 설정의 하위 호환성을 깨지 않습니다.
- 그누보드5 원본 수정은 피하고, `plugin/meeting_api/` 안에서만 API를 확장합니다.

## Runtime And Memory Notes

- 저사양 PC, 특히 4GB VRAM GPU에서는 WhisperX/pyannote/speechbrain 모델이 해제되지 않으면 Ollama가 멈출 수 있습니다.
- STT 이후 Ollama 호출 전에는 `src.runtime_memory.release_torch_memory()`와 free RAM 확인 흐름을 유지합니다.
- `gemma4:e2b`는 기본 안내 모델이지만, 모든 환경에서 GPU 적재가 된다는 뜻은 아닙니다. RAM/VRAM 부족 상황에서는 `OLLAMA_NUM_CTX_MAX`, `OLLAMA_NUM_PREDICT`, `WHISPER_BATCH_SIZE`, `OLLAMA_MIN_FREE_RAM_GB`를 조정할 수 있어야 합니다.
- `OLLAMA_KEEP_ALIVE=0` 기본 의도는 요약 후 모델을 붙잡지 않고 메모리를 돌려주는 것입니다. 변경 시 저메모리 영향을 고려합니다.
- Ollama가 첫 청크를 보내지 못하고 대기하면 메모리 문제가 아니라 서버 스케줄러 좀비 상태일 수 있습니다. `OLLAMA_TIMEOUT_SEC`, `ollama stop <model>`, Ollama 재시작 안내를 함께 고려합니다.
- Ollama가 `##` 같은 invalid JSON을 반환하면 context 부족 가능성을 먼저 확인합니다. 실패 회의록으로 저장/업로드하지 말고 재시도 후 안전하게 중단해야 합니다.
- 긴 회의는 `OLLAMA_SUMMARY_CHUNK_SEC` 기준으로 구간 요약 후 최종 통합해야 합니다. 한 번에 전체 transcript를 요약하면 앞뒤 맥락과 세부 안건이 쉽게 사라집니다.
- `OLLAMA_NUM_GPU=999`처럼 GPU 레이어를 과하게 강제하는 설정은 저VRAM 환경에서 위험합니다.

## Repository Map

- `main.py`: CLI 전체 파이프라인
- `config.py`: `.env` 로드, 경로/장치/Ollama 설정 검증
- `doctor.py`: 사용자 환경 진단
- `app.py`: Streamlit 웹 UI
- `watcher.py`: 폴더 감시 자동 처리
- `src/audio.py`: ffmpeg 탐색 및 WAV 정규화
- `src/transcriber.py`: WhisperX STT와 화자 분리 통합
- `src/diarizer_local.py`: speechbrain 기반 로컬 화자 분리
- `src/summarizer.py`: Ollama 요약 및 JSON 파싱
- `src/storage.py`: SQLite 저장/검색/동기화 상태
- `src/g5_client.py`: 그누보드5 API 클라이언트
- `g5_meeting_api/plugin/meeting_api/`: 그누보드5 PHP REST API
- `tests/`: Python 테스트

## Documentation Rules

- README는 초보 사용자가 그대로 따라 할 수 있게 명령어와 예상 오류를 함께 씁니다.
- 설치/실행 문서는 실제 비밀값 없이 예시 도메인과 placeholder를 사용합니다.
- 새 기능을 추가하면 README의 빠른 시작, 환경 변수, 트러블슈팅 중 영향받는 부분을 같이 확인합니다.
- GitHub 배포 관점에서 “내 PC에서는 됨”보다 “다른 사람이 처음 설치해도 실패 원인을 알 수 있음”을 우선합니다.

## Commit Guidance

- 사용자가 커밋을 요청하기 전에는 커밋하지 않습니다.
- 커밋 전 `git status --short`로 `.env`나 `data/`가 포함되지 않았는지 확인합니다.
- 관련 없는 기존 변경은 되돌리지 않습니다.
- 커밋 메시지는 짧고 구체적으로 씁니다. 예: `Harden Ollama memory handoff`, `Document low-memory setup`.
