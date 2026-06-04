"""Package-safe console script wrappers.

The project keeps its historical CLI files at repository root. These wrappers
load those files by path so console scripts do not collide with unrelated
top-level modules named ``main`` or ``export`` from other packages.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_cli_module(module_name: str) -> ModuleType:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    module_path = PROJECT_ROOT / f"{module_name}.py"
    if not module_path.exists():
        return importlib.import_module(module_name)

    safe_name = f"_meeting_record_{module_name}"
    spec = importlib.util.spec_from_file_location(safe_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[safe_name] = module
    spec.loader.exec_module(module)
    return module


def _run(module_name: str) -> int:
    module = _load_cli_module(module_name)
    return int(module.main() or 0)


def record() -> int:
    return _run("main")


def doctor() -> int:
    return _run("doctor")


def export() -> int:
    return _run("export")


def search() -> int:
    return _run("search")


def stats() -> int:
    return _run("stats")


def compare() -> int:
    return _run("compare")


def dictionary() -> int:
    return _run("dict")


def enroll() -> int:
    return _run("enroll")


def watch() -> int:
    return _run("watcher")
