"""python -m src.summarizer 데모 (간단 샘플 요약)."""
from __future__ import annotations

import json

from .sections import summarize

if __name__ == "__main__":
    sample = [
        {"speaker": "사용자1", "text": "다음 주 출시 일정 확정해야 할 것 같습니다."},
        {"speaker": "사용자2", "text": "QA가 수요일까지 끝나니까 금요일 출시 어때요?"},
        {"speaker": "사용자1", "text": "좋습니다. 금요일 오전 10시로 합시다."},
        {"speaker": "사용자3", "text": "릴리즈 노트는 제가 목요일까지 정리하겠습니다."},
    ]
    out = summarize(sample)
    print(json.dumps(out, ensure_ascii=False, indent=2))
