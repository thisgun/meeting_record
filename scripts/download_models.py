"""모델 사전 다운로드 (Windows symlink 권한 회피).

기본 HF cache는 symlink 사용 → Windows에서 권한 부족으로 실패.
이 스크립트는 모델을 우리 프로젝트 폴더에 직접 다운로드한다.

사용:
    python scripts/download_models.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 경고 끄기
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# 프로젝트 루트
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MODELS_DIR = ROOT / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

from config import load_config


def download(repo_id: str, local_subdir: str) -> Path:
    """모델 저장소를 local_dir에 직접 다운로드."""
    from huggingface_hub import snapshot_download
    target = MODELS_DIR / local_subdir
    print(f"[{repo_id}] → {target}")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(target),
        # symlink 비활성화 (Windows 호환)
        # 신버전 huggingface_hub은 이 옵션이 deprecate되었지만 여전히 동작.
        # 신버전은 기본적으로 직접 다운로드(local_dir에 실파일)함.
    )
    return target


def main():
    cfg = load_config()
    print(f"모델 저장 폴더: {MODELS_DIR}")
    print()

    # 1) faster-whisper (한국어 STT) — 사용자가 .env에서 모델 선택
    whisper_size = cfg.whisper_model
    # 환경변수 WHISPER_DOWNLOAD_ALL=1 이면 small/medium/large-v3 모두 사전 다운로드
    sizes = [whisper_size]
    if os.getenv("WHISPER_DOWNLOAD_ALL") == "1":
        sizes = ["small", "medium", "large-v3"]
    for size in sizes:
        download(f"Systran/faster-whisper-{size}", f"faster-whisper-{size}")

    # 참고: 이전 WhisperX 정렬용 wav2vec2 모델(kresnik/wav2vec2-large-xlsr-korean)은
    # 더 이상 받지 않는다. faster-whisper의 내장 단어 타임스탬프(word_timestamps)로 대체됨.

    # speechbrain ECAPA-TDNN은 이미 ./data/models/spkrec-ecapa-voxceleb 에 받음 (LocalStrategy.COPY)
    sb_path = MODELS_DIR / "spkrec-ecapa-voxceleb"
    if sb_path.exists():
        print(f"[speechbrain/spkrec-ecapa-voxceleb] 이미 받음 → {sb_path}")
    else:
        print("[speechbrain/spkrec-ecapa-voxceleb] 첫 diarize_local() 호출 시 자동 다운로드")

    print()
    print("[ok] 모든 모델 준비 완료.")


if __name__ == "__main__":
    sys.exit(main() or 0)
