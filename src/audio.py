import shutil
import subprocess
import uuid
from pathlib import Path


class FFmpegNotFoundError(RuntimeError):
    pass


class AudioConvertError(RuntimeError):
    pass


def _ensure_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FFmpegNotFoundError(
            "ffmpeg를 찾을 수 없습니다. 'winget install ffmpeg' 또는 "
            "https://ffmpeg.org 에서 설치 후 PATH에 등록하세요."
        )
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
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioConvertError(
            f"ffmpeg 변환 실패 (exit {proc.returncode}):\n{proc.stderr[-2000:]}"
        )
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise AudioConvertError("ffmpeg 출력 파일이 비어있습니다.")
    return out_path


def get_duration_sec(wav_path: str | Path) -> float:
    """ffprobe로 길이(초) 조회."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise FFmpegNotFoundError("ffprobe를 찾을 수 없습니다 (ffmpeg 패키지에 포함).")
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AudioConvertError(f"ffprobe 실패: {proc.stderr}")
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m src.audio <audio_file> [out_dir]")
        sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "./data/work"
    wav = normalize(src, out)
    print(f"OK: {wav}  ({get_duration_sec(wav):.1f}s)")
