"""src/runtime_memory.py — 메모리 스냅샷 포맷 테스트."""
from src.runtime_memory import MemorySnapshot, format_snapshot, snapshot


def test_format_snapshot_unavailable():
    assert format_snapshot(MemorySnapshot()) == "memory info unavailable"


def test_format_snapshot_ram_only():
    assert format_snapshot(MemorySnapshot(ram_available_gib=7.5)) == "free RAM: 7.5 GiB"


def test_format_snapshot_ram_and_vram():
    out = format_snapshot(MemorySnapshot(
        ram_available_gib=7.53, cuda_free_mib=3802.4, cuda_total_mib=8188.0))
    assert "free RAM: 7.5 GiB" in out
    assert "free VRAM: 3802/8188 MiB" in out


def test_snapshot_returns_dataclass():
    assert isinstance(snapshot(), MemorySnapshot)
