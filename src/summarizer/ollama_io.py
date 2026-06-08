"""Ollama 스트리밍 호출 + JSON 검증 재시도 레이어."""
from __future__ import annotations

from .parsing import SummaryParseError


def _stream_chat(client, *, model, messages, options, format, keep_alive):
    """Ollama 스트리밍 1회 시도. (content, chunk_count, elapsed_sec) 반환.

    스트림 도중 RemoteProtocolError 등으로 끊기면 부분 content와 함께
    raise — 호출부에서 재시도 여부 결정.
    """
    import sys
    import time as _time

    sys.stdout.write(
        "    Ollama 응답 대기 중... 첫 실행/서버 재시작 직후에는 "
        "모델 로딩으로 60~90초 동안 출력이 없을 수 있습니다.\n"
    )
    sys.stdout.flush()

    response_iter = client.chat(
        model=model,
        messages=messages,
        options=options,
        format=format,
        keep_alive=keep_alive,
        stream=True,
    )

    parts: list[str] = []
    chunk_count = 0
    last_report = 0.0
    start = _time.time()
    try:
        for chunk in response_iter:
            piece = chunk.get("message", {}).get("content", "") if isinstance(chunk, dict) \
                    else getattr(chunk, "message", None) and chunk.message.content or ""
            if piece:
                parts.append(piece)
                chunk_count += 1
                now = _time.time()
                if now - last_report >= 3.0:
                    elapsed = int(now - start)
                    sys.stdout.write(f"\r    생성 중... {chunk_count}청크 ({elapsed}s 경과)")
                    sys.stdout.flush()
                    last_report = now
    except Exception as e:
        # 부분 결과를 보존하여 상위에 전달
        elapsed = int(_time.time() - start)
        sys.stdout.write(f"\r    스트림 중단 ({chunk_count}청크, {elapsed}s): {type(e).__name__}{' '*20}\n")
        if chunk_count == 0:
            sys.stdout.write(
                "    첫 응답 전에 중단됨. 이전 stuck 이후 Ollama 서버 스케줄러가 "
                "좀비 상태일 수 있습니다.\n"
            )
        sys.stdout.flush()
        e._partial_content = "".join(parts)  # type: ignore[attr-defined]
        e._partial_chunks = chunk_count  # type: ignore[attr-defined]
        raise

    sys.stdout.write(f"\r    생성 완료 ({chunk_count}청크, {int(_time.time()-start)}s 소요){' '*20}\n")
    sys.stdout.flush()
    return "".join(parts), chunk_count, int(_time.time() - start)


def _chat_json_with_retries(
    client,
    *,
    model: str,
    messages: list[dict],
    options: dict,
    keep_alive: str,
    max_retries: int,
    parser,
    label: str,
) -> dict:
    import sys
    import time as _time

    content = ""
    last_error: Exception | None = None
    last_partial = ""
    for attempt in range(1, max_retries + 1):
        try:
            content, _chunks, _elapsed = _stream_chat(
                client,
                model=model,
                messages=messages,
                options=options,
                format="json",
                keep_alive=keep_alive,
            )
            try:
                return parser(content)
            except SummaryParseError as e:
                last_error = e
                if attempt < max_retries:
                    backoff = 3 * attempt
                    sys.stdout.write(
                        f"    {label} JSON 검증 실패 — 재시도 {attempt}/{max_retries - 1} "
                        f"({backoff}s 후, 응답 앞부분: {content.strip()[:80]!r})...\n"
                    )
                    sys.stdout.flush()
                    _time.sleep(backoff)
                    continue
                raise
        except SummaryParseError:
            raise
        except Exception as e:
            last_error = e
            partial = getattr(e, "_partial_content", "") or ""
            if len(partial) > len(last_partial):
                last_partial = partial
            if attempt < max_retries:
                backoff = 3 * attempt
                sys.stdout.write(
                    f"    {label} 재시도 {attempt}/{max_retries - 1} "
                    f"({type(e).__name__}, {backoff}s 후)...\n"
                )
                sys.stdout.flush()
                _time.sleep(backoff)
            else:
                sys.stdout.write(
                    f"    {label} 모든 재시도 실패 — partial {len(last_partial)}자로 복구 시도\n"
                )
                sys.stdout.flush()
                content = last_partial

    if last_error is not None and not content.strip() and not last_partial:
        raise RuntimeError(
            "Ollama가 첫 응답을 보내지 못했습니다. 이전 stuck 이후 서버 스케줄러가 "
            f"좀비 상태일 수 있습니다. 'ollama stop {model}' 또는 Ollama 재시작 후 "
            "다시 실행하세요. STT 캐시가 있으면 다음 실행은 요약 단계부터 이어집니다."
        ) from last_error

    try:
        return parser(content)
    except SummaryParseError as e:
        raise RuntimeError(
            f"{label} 응답을 JSON으로 복구하지 못했습니다. "
            f"응답 앞부분: {content.strip()[:200]!r}. "
            "STT 캐시가 있으면 다음 실행은 요약 단계부터 이어집니다."
        ) from e
