"""src/audio.py — ffmpeg 탐색 헬퍼 테스트 (실제 ffmpeg 불필요, PATH 로직만)."""
from pathlib import Path

from src import audio


def test_candidate_bin_dirs_returns_paths():
    dirs = audio._candidate_bin_dirs()
    assert isinstance(dirs, list)
    assert all(isinstance(d, Path) for d in dirs)


def test_find_tool_uses_path_first(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda n: "/usr/bin/" + n)
    assert audio._find_tool("ffmpeg") == "/usr/bin/ffmpeg"


def test_find_tool_none_when_missing(monkeypatch):
    # PATH에도 없고 표준 설치 위치에도 없는 가짜 도구 → None
    monkeypatch.setattr(audio.shutil, "which", lambda n: None)
    assert audio._find_tool("definitely_missing_tool_xyz_987") is None
