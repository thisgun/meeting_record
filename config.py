import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# override=True: .env 값이 시스템 환경변수보다 우선
# (예: 시스템에 OLLAMA_HOST=0.0.0.0 같은 게 있어도 .env의 http://127.0.0.1:11434 사용)
load_dotenv(override=True)

PROJECT_ROOT = Path(__file__).parent.resolve()


@dataclass(frozen=True)
class Config:
    huggingface_token: str
    ollama_host: str
    ollama_model: str
    device: str                       # "cpu" | "cuda" (auto는 load_config에서 해석됨)
    whisper_model: str
    whisper_compute_type: str
    whisper_language: str
    whisper_cpu_threads: int
    whisper_batch_size: int
    whisper_vad_filter: bool
    g5_api_base: str
    g5_api_token: str
    g5_bo_table: str
    db_path: Path
    work_dir: Path
    upload_dir: Path
    # RAG 챗봇 (ask.py / qa_watcher.py)
    embed_model: str                  # Ollama 임베딩 모델 (예: bge-m3)
    rag_top_k: int                    # 검색할 청크 수
    qa_bo_table: str                  # 질문 게시판 bo_table
    qa_poll_sec: float                # 질문 게시판 폴링 주기(초)


def _path(env_key: str, default: str) -> Path:
    raw = os.getenv(env_key, default)
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    if env_key != "DB_PATH":
        p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_device(requested: str) -> str:
    """DEVICE 환경변수를 해석. auto는 CUDA 가용성으로 결정. cuda는 실패 시 fallback 경고."""
    requested = (requested or "auto").lower().strip()
    if requested not in ("auto", "cpu", "cuda"):
        print(f"[warn] 알 수 없는 DEVICE='{requested}', cpu로 fallback")
        return "cpu"
    if requested == "cpu":
        return "cpu"

    # cuda or auto → CUDA 가용성 체크
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
    except Exception as e:
        cuda_ok = False
        torch_err = str(e)
    else:
        torch_err = ""

    if cuda_ok:
        if requested == "auto":
            print("[info] DEVICE=auto → CUDA 감지됨, GPU 사용")
        return "cuda"

    # CUDA 실패
    if requested == "cuda":
        print("[warn] DEVICE=cuda 지정했으나 CUDA 사용 불가 → CPU fallback")
        print("[warn]   원인: PyTorch가 CPU 전용 빌드이거나 NVIDIA 드라이버/CUDA 미설치")
        print("[warn]   PyTorch GPU 설치: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121")
        if torch_err:
            print(f"[warn]   torch 에러: {torch_err}")
    return "cpu"


def _resolve_compute_type(device: str, requested: str) -> str:
    """compute_type을 device에 맞춰 자동 조정. 사용자가 명시한 값이 있으면 그대로 사용."""
    requested = (requested or "").strip()
    # inline 주석 안전 제거 (.env에서 `KEY=value # 주석` 형식 방어)
    if "#" in requested:
        requested = requested.split("#", 1)[0].strip()
    requested = requested.lower()
    if requested:
        return requested
    return "float16" if device == "cuda" else "int8"


def _validated_ollama_host(default: str = "http://127.0.0.1:11434") -> str:
    """OLLAMA_HOST가 'http://' 없이 호스트만 있어도 보정."""
    raw = (os.getenv("OLLAMA_HOST") or default).strip()
    if not raw:
        return default
    if not raw.startswith(("http://", "https://")):
        # 예: "0.0.0.0", "0.0.0.0:11434", "127.0.0.1" 등을 정상화
        host = raw if ":" in raw else f"{raw}:11434"
        # 0.0.0.0은 서버 바인드 주소이지 클라이언트 접속 주소가 아니므로 127.0.0.1로 교체
        if host.startswith("0.0.0.0"):
            host = host.replace("0.0.0.0", "127.0.0.1", 1)
        return f"http://{host}"
    return raw


def load_config() -> Config:
    device = _resolve_device(os.getenv("DEVICE", "auto"))
    compute_type = _resolve_compute_type(device, os.getenv("WHISPER_COMPUTE_TYPE", ""))
    return Config(
        huggingface_token=os.getenv("HUGGINGFACE_TOKEN", ""),
        ollama_host=_validated_ollama_host(),
        ollama_model=os.getenv("OLLAMA_MODEL", "gemma4:e4b"),
        device=device,
        whisper_model=os.getenv("WHISPER_MODEL", "medium"),
        whisper_compute_type=compute_type,
        whisper_language=os.getenv("WHISPER_LANGUAGE", "ko"),
        whisper_cpu_threads=int(os.getenv("WHISPER_CPU_THREADS", "0")),
        whisper_batch_size=int(os.getenv("WHISPER_BATCH_SIZE", "8")),
        whisper_vad_filter=os.getenv("WHISPER_VAD_FILTER", "1") not in ("0", "false", "False", ""),
        g5_api_base=os.getenv("G5_API_BASE", "").rstrip("/"),
        g5_api_token=os.getenv("G5_API_TOKEN", ""),
        g5_bo_table=os.getenv("G5_BO_TABLE", "meeting"),
        db_path=_path("DB_PATH", "./data/meetings.db"),
        work_dir=_path("WORK_DIR", "./data/work"),
        upload_dir=_path("UPLOAD_DIR", "./data/uploads"),
        embed_model=os.getenv("EMBED_MODEL", "bge-m3"),
        rag_top_k=int(os.getenv("RAG_TOP_K", "6")),
        qa_bo_table=os.getenv("QA_BO_TABLE", "ask"),
        qa_poll_sec=float(os.getenv("QA_POLL_SEC", "20")),
    )
