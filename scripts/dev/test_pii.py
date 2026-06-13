"""PII 마스킹 smoke test."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.pii import mask_text

samples = [
    "담당자 010-1234-5678로 연락주세요",
    "제 이메일은 hong.gildong@example.com 입니다",
    "주민번호는 901234-1234567 이고 통장은 110-123-456789",
    "카드번호 1234-5678-9012-3456 입력하시면 됩니다",
    "회사 대표번호 02-1234-5678, 고객센터 1588-1234",
    "회의 안건 (PII 없음 일반 텍스트)",
]

print("=== partial 모드 ===")
for s in samples:
    print(f"  원본: {s}")
    print(f"  결과: {mask_text(s, level='partial')}")
    print()

print("=== full 모드 ===")
for s in samples:
    print(f"  원본: {s}")
    print(f"  결과: {mask_text(s, level='full')}")
    print()
