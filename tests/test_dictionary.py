import sys
import types

from src import dictionary


def test_inline_typo_rules_are_literal_replacements(tmp_path) -> None:
    segments = [
        {"speaker": "사용자1", "start": 0, "end": 1, "text": "태양관 현장과 지개차 사고"},
    ]

    corrected, changed = dictionary.apply_to_segments(
        tmp_path / "meetings.db",
        segments,
        inline_rules="태양관=>태양광;지개차=>지게차",
    )

    assert changed == 1
    assert corrected[0]["text"] == "태양광 현장과 지게차 사고"


def test_typo_correction_can_be_disabled(tmp_path) -> None:
    db_path = tmp_path / "meetings.db"
    dictionary.add_term(db_path, "산업안전", pattern="산업안정")
    segments = [
        {"speaker": "사용자1", "start": 0, "end": 1, "text": "산업안정 회의"},
    ]

    corrected, changed = dictionary.apply_to_segments(
        db_path,
        segments,
        enabled=False,
        inline_rules="산업안정=>산업안전",
    )

    assert changed == 0
    assert corrected[0]["text"] == "산업안정 회의"


def test_parse_ai_correction_response_preserves_unsafe_rewrites() -> None:
    originals = ["이번 터론은 집단지선에 필요한 주제들", "짧은 말"]
    raw = (
        '{"items":['
        '{"i":0,"text":"이번 토론은 집단지성에 필요한 주제들"},'
        '{"i":1,"text":"짧은 말을 아주 길고 전혀 다른 방향으로 과하게 다시 작성합니다. '
        '이것은 오타 보정이 아니라 재작성에 가깝기 때문에 버려져야 합니다. '
        '추가 설명까지 붙입니다."}'
        ']}'
    )

    corrected = dictionary.parse_ai_correction_response(raw, originals)

    assert corrected[0] == "이번 토론은 집단지성에 필요한 주제들"
    assert corrected[1] == "짧은 말"


def test_apply_ai_correction_to_segments_uses_ollama_json(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, host, timeout):
            self.host = host
            self.timeout = timeout

        def chat(self, **kwargs):
            return {
                "message": {
                    "content": '{"items":[{"i":0,"text":"이번 토론은 집단지성에 필요한 주제들"}]}'
                }
            }

    monkeypatch.setitem(sys.modules, "ollama", types.SimpleNamespace(Client=FakeClient))
    corrected, changed = dictionary.apply_ai_correction_to_segments(
        [
            {
                "speaker": "사용자1",
                "start": 0,
                "end": 1,
                "text": "이번 터론은 집단지선에 필요한 주제들",
            }
        ],
        host="http://127.0.0.1:11434",
        model="gemma4:e2b",
        timeout=30,
    )

    assert changed == 1
    assert corrected[0]["speaker"] == "사용자1"
    assert corrected[0]["text"] == "이번 토론은 집단지성에 필요한 주제들"
