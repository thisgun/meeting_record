"""회의록 자동 기록 CLI.

사용법:
    python main.py <audio_file>                # 전체 파이프라인 + 업로드
    python main.py <audio_file> --no-upload    # 로컬 저장만
    python main.py --resync                    # 업로드 실패분/멀티 타겟 누락분 재전송
    python main.py --show <meeting_id>         # DB에서 회의 조회
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from config import load_config
from meeting_record.console import configure_utf8_stdio
from src import audio, cache, dictionary, notifier, pii, storage, summarizer, transcriber
from src.g5_client import (
    G5ApiError,
    build_clients_from_env,
    format_utterance_comment,
    legacy_default_target_name,
)
from src.runtime_memory import format_snapshot, release_torch_memory, wait_for_min_free_ram


def _print_step(n: int, total: int, msg: str) -> None:
    print(f"\n[{n}/{total}] {msg}", flush=True)


def _utterance_for_comment(row: dict) -> dict:
    return {
        "speaker": row["speaker"],
        "start": row["start_sec"],
        "end": row["end_sec"],
        "text": row["text"],
    }


def _safe_key_part(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    return "".join(ch if ch in allowed else "_" for ch in str(value or "").lower())


def _remote_idempotency_key(
    kind: str,
    meeting_uuid: str,
    target_name: str,
    *,
    utterance_uuid: str | None = None,
) -> str:
    meeting_ref = _safe_key_part(meeting_uuid)
    target = _safe_key_part(target_name or "default")
    if not meeting_ref:
        raise ValueError("meeting_uuid is required for remote idempotency")
    if utterance_uuid is None:
        return f"meeting_record:{kind}:{meeting_ref}:{target}"
    utterance_ref = _safe_key_part(utterance_uuid)
    if not utterance_ref:
        raise ValueError("utterance_uuid is required for comment idempotency")
    return f"meeting_record:{kind}:{meeting_ref}:{utterance_ref}:{target}"


def _adopt_legacy_default_target(cfg, clients) -> None:
    target_name = legacy_default_target_name(clients)
    if not target_name:
        return
    meetings, comments = storage.adopt_default_sync_target(cfg.db_path, target_name)
    if meetings or comments:
        print(
            f"[info] legacy default 동기화 정보를 '{target_name}' 타겟으로 승계: "
            f"회의 {meetings}건, 댓글 {comments}건"
        )


def _backfill_comment_targets(
    cfg,
    *,
    client,
    meeting_data: dict,
    wr_id: int,
    target_name: str,
    primary: bool,
) -> int:
    utterances = meeting_data.get("utterances", [])
    missing = [
        u for u in utterances
        if not (storage.get_utterance_target(cfg.db_path, u["id"], target_name) or {}).get("remote_comment_id")
    ]
    if not missing:
        return 0

    comments = client.list_comments(wr_id)
    if len(comments) != len(utterances):
        return 0

    n = 0
    for utt, comment in zip(utterances, comments):
        if not comment.get("comment_id"):
            continue
        storage.mark_utterance_synced(
            cfg.db_path,
            utt["id"],
            str(comment["comment_id"]),
            target_name=target_name,
            primary=primary,
        )
        n += 1
    return n


def run_pipeline(input_path: str, *, upload: bool, num_speakers: int | None = None) -> int:
    cfg = load_config()
    src_path = Path(input_path).resolve()
    if not src_path.exists():
        print(f"[error] 파일이 존재하지 않습니다: {src_path}", file=sys.stderr)
        return 2

    pipeline_start = time.time()

    total_steps = 6 if upload else 5
    clients = []
    if upload:
        clients = build_clients_from_env(cfg)
        if not clients:
            print(
                "[error] G5 업로드 설정이 없습니다. 처음 테스트라면 "
                "'python main.py <audio_file> --no-upload'로 로컬 저장만 실행하세요. "
                "G5 업로드를 쓰려면 .env의 G5_API_BASE/G5_API_TOKEN 또는 G5_TARGETS를 설정하세요.",
                file=sys.stderr,
            )
            return 3
        _adopt_legacy_default_target(cfg, clients)

    # ffmpeg 위치 확인 + PATH 주입 (whisperx 등 서드파티의 bare 'ffmpeg' 호출 대비).
    # 없으면 여기서 친절한 안내와 함께 즉시 중단.
    try:
        audio.ensure_ffmpeg_on_path()
    except audio.FFmpegNotFoundError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    # 1) 원본 보관 + WAV 변환
    _print_step(1, total_steps, f"오디오 변환 (ffmpeg): {src_path.name}")
    t0 = time.time()
    archived = cfg.upload_dir / src_path.name
    if src_path.resolve() != archived.resolve():
        shutil.copy2(src_path, archived)
    wav_path = audio.normalize(archived, cfg.work_dir)
    duration = audio.get_duration_sec(wav_path)
    print(f"    → {wav_path.name} ({duration:.1f}s, {time.time()-t0:.1f}s 소요)")

    # 디바이스 정보 출력
    print(f"[info] DEVICE={cfg.device}, compute_type={cfg.whisper_compute_type}")

    # 2) STT + 화자 분리 (캐시 사용 가능)
    cache_path = cache.segments_cache_path(src_path, cfg.work_dir)
    # --speakers가 지정되면 캐시의 화자 라벨은 무시하고 재분리
    rediarize_only = cache_path.exists() and num_speakers is not None
    if cache_path.exists() and not rediarize_only:
        _print_step(2, total_steps,
                    f"발화 캐시 사용: {cache_path.name}")
        segments = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"    → 발화 {len(segments)}건, 화자 {len({s['speaker'] for s in segments})}명 (캐시)")
    elif rediarize_only:
        _print_step(2, total_steps,
                    f"화자 재분리 ({num_speakers}명 강제, STT 캐시 사용)")
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        # 텍스트/시간만 보존, 화자 라벨 무시
        base_segments = [
            {"start": s["start"], "end": s["end"], "text": s["text"], "speaker": "UNKNOWN"}
            for s in cached
        ]
        t0 = time.time()
        from src.diarizer_local import diarize_local
        segments = diarize_local(
            str(wav_path), base_segments,
            num_speakers=num_speakers,
            enrollment_db=str(cfg.db_path),
            device=cfg.device,
        )
        segments = transcriber.remap_speakers(segments)
        segments = transcriber.merge_consecutive(segments)
        # 캐시 덮어쓰기
        cache_path.write_text(
            json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"    → 발화 {len(segments)}건, 화자 {len({s['speaker'] for s in segments})}명 "
              f"({time.time()-t0:.1f}s, 캐시 갱신)")
    else:
        diarize_mode = "pyannote (HF)" if cfg.huggingface_token else "로컬 (speechbrain)"
        _print_step(2, total_steps,
                    f"음성 인식 + 화자 분리 (WhisperX {cfg.whisper_model}, 분리: {diarize_mode})")
        print("    ※ CPU 환경에서는 오래 걸립니다 (1분 오디오당 2~4분).")
        t0 = time.time()
        # 사전의 용어들을 Whisper에게 미리 알림 (정확도 ↑)
        whisper_prompt = dictionary.build_whisper_prompt(cfg.db_path)
        segments = transcriber.transcribe_and_diarize(
            str(wav_path),
            hf_token=cfg.huggingface_token,
            model_name=cfg.whisper_model,
            language=cfg.whisper_language,
            compute_type=cfg.whisper_compute_type,
            device=cfg.device,
            num_speakers=num_speakers,
            enrollment_db=str(cfg.db_path),
            cpu_threads=cfg.whisper_cpu_threads,
            batch_size=cfg.whisper_batch_size,
            vad_filter=cfg.whisper_vad_filter,
            initial_prompt=whisper_prompt,
        )
        # STT 후 사전 치환 적용 (Whisper가 못 잡은 오류 자동 교정)
        segments, n_fixed = dictionary.apply_to_segments(cfg.db_path, segments)
        if n_fixed > 0:
            print(f"    → 사전 치환 적용: {n_fixed}건")
        # PII 마스킹 (PII_MASK_LEVEL 설정 시)
        if pii.is_enabled():
            segments, n_masked = pii.mask_segments(segments)
            if n_masked > 0:
                print(f"    → PII 마스킹 적용: {n_masked}건 발화")
        segments = transcriber.remap_speakers(segments)
        segments = transcriber.merge_consecutive(segments)
        # 캐시 저장 (다음 실패 시 재사용)
        cache_path.write_text(
            json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"    → 발화 {len(segments)}건, 화자 {len({s['speaker'] for s in segments})}명 "
              f"({time.time()-t0:.1f}s, 캐시: {cache_path.name})")

    # 3) 요약 — Ollama가 모델을 로드할 수 있도록 whisperx/pyannote 메모리 먼저 해제
    release_torch_memory("STT 후")
    memory_ok, memory_snapshot = wait_for_min_free_ram(
        cfg.ollama_min_free_ram_gib,
        timeout_sec=cfg.ollama_memory_wait_sec,
    )
    if not memory_ok:
        print(
            "[error] Ollama 모델을 로드하기에 메모리가 부족합니다: "
            f"{format_snapshot(memory_snapshot)} "
            f"(필요 free RAM {cfg.ollama_min_free_ram_gib:.1f} GiB 이상)",
            file=sys.stderr,
        )
        print(
            f"[error] STT 결과 캐시는 저장되어 있습니다: {cache_path.name}. "
            "브라우저/IDE/다른 Python 프로세스를 종료하거나 "
            "OLLAMA_MODEL을 더 작은 모델로 낮춘 뒤 다시 실행하세요.",
            file=sys.stderr,
        )
        return 5
    _print_step(3, total_steps, f"회의 요약 (Ollama {cfg.ollama_model})")
    t0 = time.time()
    try:
        summary = summarizer.summarize(
            segments,
            model=cfg.ollama_model,
            host=cfg.ollama_host,
            timeout=cfg.ollama_timeout_sec,
            keep_alive=cfg.ollama_keep_alive,
            max_ctx=cfg.ollama_num_ctx_max,
            num_predict=cfg.ollama_num_predict,
            num_gpu=cfg.ollama_num_gpu,
        )
    except Exception as e:
        print(f"[error] Ollama 요약 실패: {e}", file=sys.stderr)
        print(
            f"[error] STT 결과 캐시는 저장되어 있습니다: {cache_path.name}. "
            f"'ollama stop {cfg.ollama_model}' 또는 Ollama 재시작 후 다시 실행하세요.",
            file=sys.stderr,
        )
        return 5
    # 요약 본문에도 마스킹 (LLM이 발화의 번호를 그대로 옮길 가능성)
    if pii.is_enabled():
        summary["summary_md"] = pii.mask_text(summary["summary_md"])
        summary["title"] = pii.mask_text(summary["title"])
    print(f"    → 제목: {summary['title']} ({time.time()-t0:.1f}s)")

    # 4) DB 저장
    _print_step(4, total_steps, f"SQLite 저장 ({cfg.db_path})")
    meeting_id = storage.save_meeting(
        cfg.db_path,
        source_file=str(src_path),
        title=summary["title"],
        summary_md=summary["summary_md"],
        duration_sec=duration,
        utterances=segments,
    )
    print(f"    → meeting_id={meeting_id}")

    # 5) 결과 미리보기
    _print_step(5, total_steps, "요약 미리보기")
    print("─" * 60)
    print(f"# {summary['title']}\n")
    print(summary["summary_md"])
    print("─" * 60)

    if not upload:
        print("\n✓ 완료 (--no-upload: 원격 업로드 생략)")
        print(f"  meeting_id={meeting_id}")
        notifier.notify_meeting_done(
            meeting_id=meeting_id,
            title=summary["title"],
            source_file=str(src_path),
            duration_sec=duration,
            speaker_count=len({s["speaker"] for s in segments}),
            utterance_count=len(segments),
            elapsed_sec=time.time() - pipeline_start,
        )
        return 0

    # 6) 그누보드5 업로드 (멀티 타겟 지원: G5_TARGETS=local,remote)
    target_names = ", ".join(c.name for c in clients)
    _print_step(6, total_steps, f"그누보드5 업로드 (타겟: {target_names})")

    meeting_data = storage.get_meeting(cfg.db_path, meeting_id) or {}
    last_wr_id = None
    last_post_url = None
    any_success = False
    partial_failure = False
    for client in clients:
        print(f"  [{client.name}] {client.api_base}")
        try:
            meeting_uuid = meeting_data["meeting"]["uuid"]
            post = client.create_post(
                summary["title"],
                summary["summary_md"],
                idempotency_key=_remote_idempotency_key("post", meeting_uuid, client.name),
            )
            wr_id = int(post["wr_id"])
            print(f"    → 게시글 wr_id={wr_id} ({post.get('url', '')})")
            last_wr_id = wr_id
            last_post_url = post.get("url")
            is_primary = not any_success
            storage.mark_meeting_posted(
                cfg.db_path,
                meeting_id,
                str(wr_id),
                target_name=client.name,
                primary=is_primary,
            )

            n_fail = 0
            for utt_row in meeting_data.get("utterances", []):
                utt = _utterance_for_comment(utt_row)
                author = f"회의_{utt_row['speaker']}"
                try:
                    resp = client.create_comment(
                        wr_id,
                        format_utterance_comment(utt),
                        author_name=author,
                        idempotency_key=_remote_idempotency_key(
                            "comment",
                            meeting_uuid,
                            client.name,
                            utterance_uuid=utt_row["uuid"],
                        ),
                    )
                    storage.mark_utterance_synced(
                        cfg.db_path,
                        utt_row["id"],
                        str(resp["comment_id"]),
                        target_name=client.name,
                        primary=is_primary,
                    )
                except G5ApiError as e:
                    n_fail += 1
                    storage.mark_utterance_failed(
                        cfg.db_path,
                        utt_row["id"],
                        str(e),
                        target_name=client.name,
                    )
                    if n_fail <= 3:
                        print(f"    [warn] 댓글 실패 (seq={utt_row['seq']}): {e}")
            print(f"    → 댓글 {len(meeting_data.get('utterances', []))}건 시도 (실패 {n_fail}건)")
            if n_fail:
                partial_failure = True
            if n_fail == 0:
                storage.mark_meeting_synced(
                    cfg.db_path,
                    meeting_id,
                    str(wr_id),
                    target_name=client.name,
                    primary=is_primary,
                )
            else:
                storage.mark_meeting_partial(
                    cfg.db_path,
                    meeting_id,
                    str(wr_id),
                    f"{n_fail} comments failed; run python main.py --resync",
                    target_name=client.name,
                    primary=is_primary,
                )
            any_success = True
        except G5ApiError as e:
            print(f"    [error] '{client.name}' 업로드 실패: {e}")
            storage.mark_meeting_failed(
                cfg.db_path,
                meeting_id,
                str(e),
                target_name=client.name,
            )

    if not any_success:
        storage.mark_meeting_failed(cfg.db_path, meeting_id, "all G5 targets failed")
        print("    → 로컬 DB에는 저장되었습니다. 'python main.py --resync'로 재전송 가능.")
        return 3

    if partial_failure:
        print("    → 일부 댓글 업로드가 실패했습니다. 'python main.py --resync'로 남은 댓글을 재전송하세요.")
        notifier.notify_meeting_failed(
            source_file=str(src_path),
            error="Some G5 comments failed; run python main.py --resync",
            stage="G5 comment upload",
            elapsed_sec=time.time() - pipeline_start,
        )
        return 4

    print(f"\n✓ 완료. meeting_id={meeting_id}, 마지막 wr_id={last_wr_id}")
    notifier.notify_meeting_done(
        meeting_id=meeting_id,
        title=summary["title"],
        source_file=str(src_path),
        duration_sec=duration,
        speaker_count=len({s["speaker"] for s in segments}),
        utterance_count=len(segments),
        wr_id=last_wr_id,
        g5_url=last_post_url,
        elapsed_sec=time.time() - pipeline_start,
    )
    return 0


def resync_failed() -> int:
    cfg = load_config()
    storage.init_db(cfg.db_path)

    clients = build_clients_from_env(cfg)
    if not clients:
        print("[error] .env의 G5_API_BASE/G5_API_TOKEN 또는 G5_TARGETS 설정 확인", file=sys.stderr)
        return 3
    _adopt_legacy_default_target(cfg, clients)

    unsynced = storage.list_unsynced(cfg.db_path, target_names=[c.name for c in clients])
    print(f"미동기화 회의: {len(unsynced)}건")
    if not unsynced:
        return 0

    fail = 0
    for m in unsynced:
        mid = m["id"]
        print(f"\n[meeting_id={mid}] {m['title']}")
        data = storage.get_meeting(cfg.db_path, mid) or {}
        meeting_uuid = (data.get("meeting") or {}).get("uuid") or m.get("uuid")
        any_target_failed = False
        primary_set = bool(m.get("remote_post_id"))
        for client in clients:
            target = storage.get_meeting_target(cfg.db_path, mid, client.name)
            if target and target.get("sync_status") == "synced":
                print(f"  [{client.name}] 이미 동기화됨")
                continue

            wr_id = None
            try:
                if target and target.get("remote_post_id"):
                    wr_id = int(target["remote_post_id"])
                    client.update_post(wr_id, subject=m["title"], content=m["summary_md"])
                    print(f"  [{client.name}] 기존 게시글 wr_id={wr_id} 갱신 후 남은 댓글 재전송")
                    n_backfilled = _backfill_comment_targets(
                        cfg,
                        client=client,
                        meeting_data=data,
                        wr_id=wr_id,
                        target_name=client.name,
                        primary=False,
                    )
                    if n_backfilled:
                        print(f"  [{client.name}] 댓글 ID {n_backfilled}건 백필")
                else:
                    post = client.create_post(
                        m["title"],
                        m["summary_md"],
                        idempotency_key=_remote_idempotency_key("post", meeting_uuid, client.name),
                    )
                    wr_id = int(post["wr_id"])
                    is_primary = not primary_set
                    storage.mark_meeting_posted(
                        cfg.db_path,
                        mid,
                        str(wr_id),
                        target_name=client.name,
                        primary=is_primary,
                    )
                    if is_primary:
                        primary_set = True
                    print(f"  [{client.name}] 게시글 wr_id={wr_id}")

                n_fail = 0
                for utt in data.get("utterances", []):
                    utt_target = storage.get_utterance_target(cfg.db_path, utt["id"], client.name)
                    if utt_target and utt_target.get("sync_status") == "synced":
                        continue
                    u = _utterance_for_comment(utt)
                    author = f"회의_{utt['speaker']}"
                    try:
                        if utt_target and utt_target.get("remote_comment_id"):
                            comment_id = int(utt_target["remote_comment_id"])
                            client.update_comment(
                                comment_id,
                                content=format_utterance_comment(u),
                                author_name=author,
                            )
                        else:
                            resp = client.create_comment(
                                wr_id,
                                format_utterance_comment(u),
                                author_name=author,
                                idempotency_key=_remote_idempotency_key(
                                    "comment",
                                    meeting_uuid,
                                    client.name,
                                    utterance_uuid=utt["uuid"],
                                ),
                            )
                            comment_id = int(resp["comment_id"])
                        storage.mark_utterance_synced(
                            cfg.db_path,
                            utt["id"],
                            str(comment_id),
                            target_name=client.name,
                            primary=False,
                        )
                    except G5ApiError as e:
                        n_fail += 1
                        storage.mark_utterance_failed(
                            cfg.db_path,
                            utt["id"],
                            str(e),
                            target_name=client.name,
                        )
                        print(f"  [{client.name}] [warn] 댓글 실패 seq={utt['seq']}: {e}")
                if n_fail == 0:
                    storage.mark_meeting_synced(
                        cfg.db_path,
                        mid,
                        str(wr_id),
                        target_name=client.name,
                        primary=False,
                    )
                    print(f"  [{client.name}] 동기화 완료")
                else:
                    storage.mark_meeting_partial(
                        cfg.db_path,
                        mid,
                        str(wr_id),
                        f"{n_fail} comments failed during resync",
                        target_name=client.name,
                        primary=False,
                    )
                    any_target_failed = True
            except G5ApiError as e:
                storage.mark_meeting_failed(cfg.db_path, mid, str(e), target_name=client.name)
                print(f"  [{client.name}] [error] 실패: {e}")
                any_target_failed = True
            except (TypeError, ValueError) as e:
                storage.mark_meeting_failed(
                    cfg.db_path,
                    mid,
                    f"invalid remote_post_id: {e}",
                    target_name=client.name,
                )
                print(f"  [{client.name}] [error] remote_post_id 오류: {e}")
                any_target_failed = True
        if any_target_failed:
            fail += 1

    print(f"\n완료. 실패 {fail}건.")
    return 0 if fail == 0 else 4


def show_meeting(meeting_id: int) -> int:
    cfg = load_config()
    data = storage.get_meeting(cfg.db_path, meeting_id)
    if not data:
        print(f"meeting_id={meeting_id} 없음", file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()

    parser = argparse.ArgumentParser(description="회의록 자동 기록")
    parser.add_argument("audio_file", nargs="?", help="입력 오디오 파일 (m4a/mp3/wav/amr)")
    parser.add_argument("--no-upload", action="store_true",
                        help="원격 업로드 생략, 로컬 저장만")
    parser.add_argument("--speakers", type=int, default=None, metavar="N",
                        help="화자 수 지정 (지정 시 자동 추정 대신 N명으로 클러스터링)")
    parser.add_argument("--show", type=int, metavar="MEETING_ID",
                        help="DB에서 회의 조회")
    parser.add_argument("--resync", action="store_true",
                        help="업로드 실패한 회의 재전송")

    args = parser.parse_args(argv)

    if args.show is not None:
        return show_meeting(args.show)

    if args.resync:
        return resync_failed()

    if not args.audio_file:
        parser.print_help()
        return 1

    return run_pipeline(
        args.audio_file,
        upload=not args.no_upload,
        num_speakers=args.speakers,
    )


if __name__ == "__main__":
    sys.exit(main())
