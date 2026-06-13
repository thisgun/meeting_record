from src.pii import mask_text


def test_partial_masks_common_korean_pii() -> None:
    text = "담당자 010-1234-5678, 이메일 hong.gildong@example.com, 주민번호 901234-1234567"

    masked = mask_text(text, level="partial")

    assert "010-1234-5678" not in masked
    assert "hong.gildong@example.com" not in masked
    assert "901234-1234567" not in masked
    assert "010-" in masked
    assert "@example.com" in masked


def test_full_masks_with_labels() -> None:
    text = "카드번호 1234-5678-9012-3456, 계좌 110-123-456789"

    masked = mask_text(text, level="full")

    assert "[카드번호]" in masked
    assert "[계좌번호]" in masked
    assert "1234-5678-9012-3456" not in masked


def test_off_leaves_text_unchanged() -> None:
    text = "회의 안건 010-1234-5678"

    assert mask_text(text, level="off") == text
