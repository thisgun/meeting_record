"""src/exporter.py — HTML/마크다운 변환 테스트 (순수 문자열 생성)."""
from src import exporter


def test_inline_md_bold_italic_and_escape():
    assert exporter._inline_md_to_html("**굵게** 일반 *기울임*") == \
        "<strong>굵게</strong> 일반 <em>기울임</em>"
    assert exporter._inline_md_to_html("<script>") == "&lt;script&gt;"


def test_markdown_to_html_header_list_paragraph():
    out = exporter._markdown_to_html("## 제목\n- 항목1\n- 항목2\n\n일반 단락")
    assert "<h2>제목</h2>" in out
    assert "<ul>" in out and "<li>항목1</li>" in out and "<li>항목2</li>" in out
    assert "<p>일반 단락</p>" in out


def test_markdown_checkbox_rendering():
    out = exporter._markdown_to_html("- [x] 완료된 일\n- [ ] 남은 일")
    assert "☑ 완료된 일" in out
    assert "☐ 남은 일" in out


def test_to_html_writes_file_with_escaped_content(tmp_path):
    meeting = {
        "title": "산업안전 <회의>",
        "created_at": "2026-06-09",
        "source_file": "/x/a.mp3",
        "duration_sec": 125,
        "speaker_count": 3,
    }
    utts = [{"start_sec": 5, "speaker": "사용자1", "text": "안녕<>"}]
    out = exporter.to_html(meeting, utts, tmp_path / "m.html")
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "산업안전 &lt;회의&gt;" in content      # 제목 escape
    assert "발화 전문" in content                  # transcript 포함
    assert "사용자1" in content
    assert "안녕&lt;&gt;" in content               # 발화 text escape


def test_to_html_skip_transcript(tmp_path):
    out = exporter.to_html(
        {"title": "t"}, [{"start_sec": 0, "speaker": "a", "text": "x"}],
        tmp_path / "n.html", include_transcript=False,
    )
    assert "발화 전문" not in out.read_text(encoding="utf-8")
