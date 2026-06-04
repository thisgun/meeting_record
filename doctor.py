"""시스템 진단 스크립트.

GPU/CUDA, PyTorch, FFmpeg, Ollama, MariaDB, 그누보드5 API 등
모든 의존성의 가용성을 한 번에 확인.

사용:
    python doctor.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _print(symbol: str, color: str, label: str, detail: str = "") -> None:
    msg = f"{color}{symbol}{RESET} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def ok(label: str, detail: str = "") -> None:
    _print("✓", GREEN, label, detail)


def warn(label: str, detail: str = "") -> None:
    _print("!", YELLOW, label, detail)


def fail(label: str, detail: str = "") -> None:
    _print("✗", RED, label, detail)


def section(title: str) -> None:
    print(f"\n{BOLD}── {title} ──{RESET}")


def check_python():
    section("Python")
    ver = sys.version_info
    if ver >= (3, 10):
        ok(f"Python {ver.major}.{ver.minor}.{ver.micro}")
    else:
        fail(f"Python {ver.major}.{ver.minor}.{ver.micro}", "3.10+ 권장")


def check_pytorch():
    section("PyTorch + CUDA")
    try:
        import torch
        ok(f"torch {torch.__version__}")
        if torch.cuda.is_available():
            ok(f"CUDA available", f"build={torch.version.cuda}, GPU={torch.cuda.device_count()}개")
            for i in range(torch.cuda.device_count()):
                name = torch.cuda.get_device_name(i)
                props = torch.cuda.get_device_properties(i)
                vram = props.total_memory / 1024 ** 3
                ok(f"  GPU {i}", f"{name} ({vram:.1f} GB)")
        else:
            if "+cpu" in torch.__version__:
                warn("PyTorch는 CPU 전용 빌드입니다",
                     "GPU 사용하려면: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121")
            else:
                warn("CUDA 사용 불가",
                     "NVIDIA 드라이버 또는 CUDA Toolkit 미설치 가능성")
    except ImportError as e:
        fail("torch import 실패", str(e))


def check_nvidia():
    section("NVIDIA 드라이버")
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        warn("nvidia-smi 없음", "NVIDIA GPU 없음 또는 드라이버 미설치")
        return
    try:
        r = subprocess.run([nvsmi, "--query-gpu=name,driver_version,memory.total",
                            "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                ok(f"GPU", line.strip())
        else:
            fail("nvidia-smi 실행 실패", r.stderr.strip()[:200])
    except Exception as e:
        fail("nvidia-smi 호출 실패", str(e))


def check_ffmpeg():
    section("FFmpeg")
    exe = shutil.which("ffmpeg")
    if not exe:
        fail("ffmpeg 없음", "winget install Gyan.FFmpeg --source winget")
        return
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=5)
        first = r.stdout.split("\n")[0]
        ok(first[:80])
    except Exception as e:
        fail("ffmpeg 실행 실패", str(e))


def check_ollama():
    section("Ollama")
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=3) as r:
            import json
            data = json.loads(r.read())
            ok(f"Ollama 서버 응답", f"v{data.get('version')}")
    except Exception as e:
        fail("Ollama 서버 접속 실패", str(e)[:100])
        return

    # 사용 가능 모델 확인
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            import json
            data = json.loads(r.read())
            names = [m["name"] for m in data.get("models", [])]
            if names:
                ok(f"설치된 모델 {len(names)}개", ", ".join(names[:5]) + (" ..." if len(names) > 5 else ""))
            else:
                warn("설치된 모델 없음", "ollama pull gemma4:e2b")
    except Exception as e:
        warn("모델 목록 조회 실패", str(e)[:100])


def check_config():
    section("프로젝트 설정 (.env)")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from config import load_config
        cfg = load_config()
        ok(f"DEVICE = {cfg.device}")
        ok(f"WHISPER_MODEL = {cfg.whisper_model}")
        ok(f"WHISPER_COMPUTE_TYPE = {cfg.whisper_compute_type}")
        ok(f"OLLAMA_MODEL = {cfg.ollama_model}")
        ok(f"OLLAMA_HOST = {cfg.ollama_host}")
        ok(f"G5_API_BASE = {cfg.g5_api_base}")
    except Exception as e:
        fail("config 로드 실패", str(e))


def check_models():
    section("로컬 AI 모델 (data/models)")
    models_dir = Path(__file__).resolve().parent / "data" / "models"
    if not models_dir.exists():
        warn("data/models 폴더 없음", "python scripts/download_models.py")
        return
    for sub in sorted(models_dir.iterdir()):
        if sub.is_dir():
            try:
                size = sum(f.stat().st_size for f in sub.rglob("*") if f.is_file()) / 1024 ** 2
                ok(f"{sub.name}", f"{size:.0f} MB")
            except Exception:
                ok(sub.name)


def check_streamlit():
    section("Streamlit 웹 UI")
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health", timeout=2) as r:
            txt = r.read().decode("utf-8", errors="ignore").strip()
            if txt == "ok":
                ok("Streamlit 서버 응답", "http://localhost:8501")
            else:
                warn("Streamlit 응답 이상", txt[:80])
    except Exception:
        warn("Streamlit 서버 미실행", "실행: python -m streamlit run app.py")


def check_keyword_extractor():
    section("키워드 추출")
    try:
        from src.comparator import get_extraction_method
        ok(get_extraction_method())
    except Exception as e:
        warn("keyword extractor 확인 실패", str(e))


def check_notifier():
    section("알림 설정")
    try:
        from src.notifier import is_configured
        cfg = is_configured()
        level = cfg.get("level", "off")
        ok(f"NOTIFY_LEVEL = {level}")
        if cfg.get("slack"):
            ok("Slack webhook 설정됨")
        else:
            warn("Slack webhook 미설정", "선택사항 — .env에 NOTIFY_SLACK_WEBHOOK 설정")
        if cfg.get("email"):
            ok("이메일 SMTP 설정됨")
        else:
            warn("이메일 미설정", "선택사항 — .env에 NOTIFY_EMAIL_* 설정")
    except Exception as e:
        warn("notifier 확인 실패", str(e))


def check_xampp():
    section("XAMPP (MariaDB / Apache / PHP)")
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1/g5_metting_api/health.php", timeout=3) as r:
            import json
            data = json.loads(r.read())
            if data.get("ok"):
                ok("g5_metting_api health", f"PHP {data.get('php_version')}, DB={data.get('db_connected')}, board={data.get('board_exists')}")
            else:
                warn("API health 응답에 ok=false", str(data)[:200])
    except Exception as e:
        warn("g5_metting_api 접속 실패", "Apache 또는 MariaDB가 중지된 상태일 수 있음")


def check_g5_targets():
    section("G5 타겟 (단일/멀티)")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from config import load_config
        from src.g5_client import build_clients_from_env
        cfg = load_config()
        clients = build_clients_from_env(cfg)
        if not clients:
            warn("G5 클라이언트 없음", ".env의 G5_API_BASE/G5_API_TOKEN 확인")
            return
        for c in clients:
            try:
                h = c.health()
                board_ok = h.get("board_exists")
                ok(f"[{c.name}] {c.api_base}", f"DB={h.get('db_connected')}, board={board_ok}")
            except Exception as e:
                msg = str(e)
                if "Invalid or missing X-API-Token" in msg:
                    warn(f"[{c.name}] 토큰 불일치", c.api_base)
                else:
                    warn(f"[{c.name}] 접속 실패", msg[:120])
    except Exception as e:
        warn("타겟 확인 실패", str(e))


def check_packages():
    section("Python 핵심 패키지")
    deps = ["whisperx", "faster_whisper", "torch", "torchaudio",
            "speechbrain", "sklearn", "soundfile", "ollama",
            "dotenv", "watchdog", "docx", "streamlit", "kiwipiepy"]
    for d in deps:
        try:
            mod = __import__(d)
            ver = getattr(mod, "__version__", "?")
            ok(f"{d}", f"v{ver}")
        except ImportError:
            fail(f"{d}", "pip install -r requirements.txt")


def main() -> int:
    print(f"\n{BOLD}===== metting_record 시스템 진단 ====={RESET}")
    check_python()
    check_pytorch()
    check_nvidia()
    check_ffmpeg()
    check_packages()
    check_models()
    check_ollama()
    check_xampp()
    check_g5_targets()
    check_streamlit()
    check_keyword_extractor()
    check_notifier()
    check_config()
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
