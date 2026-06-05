"""Runtime memory cleanup helpers for local AI model handoff.

WhisperX, pyannote, and speechbrain can leave Python references or PyTorch
allocator caches behind.  Ollama then has to load another large model in the
same machine, so the CLI calls these helpers between STT/diarization and LLM
summarization.
"""
from __future__ import annotations

import gc
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class MemorySnapshot:
    ram_available_gib: float | None = None
    cuda_free_mib: float | None = None
    cuda_total_mib: float | None = None


def _ram_available_gib() -> float | None:
    try:
        import psutil

        return psutil.virtual_memory().available / 1024**3
    except Exception:
        return None


def _cuda_mem_mib() -> tuple[float, float] | tuple[None, None]:
    try:
        import torch

        if not torch.cuda.is_available():
            return None, None
        free, total = torch.cuda.mem_get_info()
        return free / 1024**2, total / 1024**2
    except Exception:
        return None, None


def snapshot() -> MemorySnapshot:
    free_mib, total_mib = _cuda_mem_mib()
    return MemorySnapshot(
        ram_available_gib=_ram_available_gib(),
        cuda_free_mib=free_mib,
        cuda_total_mib=total_mib,
    )


def format_snapshot(snap: MemorySnapshot) -> str:
    parts: list[str] = []
    if snap.ram_available_gib is not None:
        parts.append(f"free RAM: {snap.ram_available_gib:.1f} GiB")
    if snap.cuda_free_mib is not None and snap.cuda_total_mib is not None:
        parts.append(f"free VRAM: {snap.cuda_free_mib:.0f}/{snap.cuda_total_mib:.0f} MiB")
    return ", ".join(parts) if parts else "memory info unavailable"


def clear_known_model_caches() -> None:
    """Clear project-level model singletons that gc cannot see as garbage."""
    try:
        from src.diarizer_local import clear_encoder_cache

        clear_encoder_cache()
    except Exception:
        pass


def release_torch_memory(label: str = "", *, verbose: bool = True) -> MemorySnapshot:
    """Drop Python/PyTorch caches and report the remaining free memory."""
    clear_known_model_caches()
    for _ in range(3):
        gc.collect()

    try:
        import torch

        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
    except Exception:
        pass

    snap = snapshot()
    if verbose:
        prefix = "    -> 메모리 정리 완료"
        if label:
            prefix = f"    -> 메모리 정리 ({label})"
        print(f"{prefix} - {format_snapshot(snap)}", flush=True)
    return snap


def wait_for_min_free_ram(
    min_free_gib: float,
    *,
    timeout_sec: int = 30,
    interval_sec: int = 5,
) -> tuple[bool, MemorySnapshot]:
    """Wait briefly for OS/Python allocators to return enough RAM.

    Returns (ok, latest_snapshot).  If psutil is unavailable, ok is True because
    the threshold cannot be measured reliably.
    """
    snap = release_torch_memory("Ollama 준비", verbose=False)
    if min_free_gib <= 0 or snap.ram_available_gib is None:
        return True, snap
    if snap.ram_available_gib >= min_free_gib:
        return True, snap

    deadline = time.time() + max(0, timeout_sec)
    print(
        f"    [warn] Ollama 실행 전 free RAM {snap.ram_available_gib:.1f} GiB "
        f"< 권장 {min_free_gib:.1f} GiB",
        flush=True,
    )

    while time.time() < deadline:
        sleep_for = min(interval_sec, max(0.0, deadline - time.time()))
        if sleep_for > 0:
            time.sleep(sleep_for)
        snap = release_torch_memory("Ollama 재확인", verbose=False)
        if snap.ram_available_gib is None or snap.ram_available_gib >= min_free_gib:
            return True, snap
        print(f"    -> 아직 부족: {format_snapshot(snap)}", flush=True)

    return False, snap
