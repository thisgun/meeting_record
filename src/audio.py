import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


class FFmpegNotFoundError(RuntimeError):
    pass


class AudioConvertError(RuntimeError):
    pass


_INSTALL_HINT = (
    "ffmpeg를 찾을 수 없습니다. OS에 맞게 설치하세요:\n"
    "  - Windows : winget install Gyan.FFmpeg --source winget\n"
    "  - macOS   : brew install ffmpeg\n"
    "  - Linux   : sudo apt install ffmpeg   (또는 배포판 패키지 매니저)\n"
    "설치 후 반드시 '새 터미널'을 열어야 PATH가 갱신됩니다 "
    "— 같은 창에서 재시도하면 설치했어도 동일한 오류가 납니다.\n"
    "수동 설치 시 https://ffmpeg.org 에서 받아 bin 폴더를 PATH에 등록하세요."
)


def _candidate_bin_dirs() -> list[Path]:
    """PATH 외에 ffmpeg/ffprobe가 흔히 설치되는 위치들 (OS별).

    winget 설치 직후 터미널을 재시작하지 않아 PATH에 아직 반영되지 않은
    경우 등을 대비한 fallback 탐색 경로.
    """
    dirs: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
            if pkgs.is_dir():
                dirs += sorted(pkgs.glob("Gyan.FFmpeg*/*/bin"))   # winget (Gyan.FFmpeg)
            dirs.append(Path(local) / "Microsoft" / "WindowsApps")  # winget 실행 별칭
        profile = os.environ.get("USERPROFILE")
        if profile:
            dirs.append(Path(profile) / "scoop" / "shims")          # scoop
        dirs += [
            Path(r"C:\ProgramData\chocolatey\bin"),                  # chocolatey
            Path(r"C:\ffmpeg\bin"),
            Path(r"C:\Program Files\ffmpeg\bin"),
        ]
    else:
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin")]
    return dirs


def _find_tool(name: str) -> str | None:
    """PATH → 표준 설치 위치 순으로 실행 파일을 찾는다."""
    exe = shutil.which(name)
    if exe:
        return exe
    filename = f"{name}.exe" if sys.platform == "win32" else name
    for d in _candidate_bin_dirs():
        candidate = d / filename
        if candidate.is_file():
            return str(candidate)
    return None


def _ensure_ffmpeg() -> str:
    exe = _find_tool("ffmpeg")
    if not exe:
        raise FFmpegNotFoundError(_INSTALL_HINT)
    return exe


def ensure_ffmpeg_on_path() -> str:
    """ffmpeg 위치를 확인하고, PATH에 없으면 PATH 앞에 추가한다.

    whisperx 등 서드파티 라이브러리는 bare ``ffmpeg`` 를 subprocess로 직접
    호출하므로(우리 resolver를 거치지 않음), fallback 위치에서 찾았더라도 그
    디렉터리를 PATH에 주입해야 그쪽 호출도 성공한다. winget 설치 후 터미널을
    재시작하지 않은 경우에 특히 중요. (이미 PATH에 있으면 아무 일도 하지 않음)
    """
    exe = _ensure_ffmpeg()
    bin_dir = str(Path(exe).parent)
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if bin_dir not in parts:
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    return exe


def normalize(input_path: str | Path, out_dir: str | Path) -> Path:
    """입력 오디오를 16kHz mono PCM WAV로 변환한다."""
    ffmpeg = _ensure_ffmpeg()
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {src}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{uuid.uuid4().hex}.wav"

    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise AudioConvertError(
            f"ffmpeg 변환 실패 (exit {proc.returncode}):\n{proc.stderr[-2000:]}"
        )
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise AudioConvertError("ffmpeg 출력 파일이 비어있습니다.")
    return out_path


def get_duration_sec(wav_path: str | Path) -> float:
    """ffprobe로 길이(초) 조회."""
    ffprobe = _find_tool("ffprobe")
    if not ffprobe:
        raise FFmpegNotFoundError(
            "ffprobe를 찾을 수 없습니다 (ffmpeg 패키지에 포함되어 있습니다).\n" + _INSTALL_HINT
        )
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise AudioConvertError(f"ffprobe 실패: {proc.stderr}")
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m src.audio <audio_file> [out_dir]")
        sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "./data/work"
    wav = normalize(src, out)
    print(f"OK: {wav}  ({get_duration_sec(wav):.1f}s)")
