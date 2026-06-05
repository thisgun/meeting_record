from src.summarizer import _build_ollama_options


def test_ollama_options_cap_context_for_low_memory() -> None:
    transcript = "회의 내용 " * 10000

    options = _build_ollama_options(
        transcript,
        max_ctx=8192,
        num_predict=4096,
        num_gpu=0,
    )

    assert options["num_ctx"] == 8192
    assert options["num_predict"] == 4096
    assert options["num_gpu"] == 0


def test_ollama_options_omit_num_gpu_when_auto() -> None:
    options = _build_ollama_options("짧은 회의", num_gpu=None)

    assert options["num_ctx"] == 4096
    assert "num_gpu" not in options
