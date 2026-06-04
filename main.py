"""회의록 자동 기록 CLI.

사용법:
    python main.py <audio_file>                # 전체 파이프라인 + 업로드
    python main.py <audio_file> --no-upload    # 로컬 저장만
    python main.py --resync                    # 업로드 실패분 재전송 (8단계 구현 예정)
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
from src import audio, dictionary, notifier, pii, storage, summarizer, transcriber
from src.g5_client import G5ApiError, G5MettingApiClient, build_clients_from_env, format_utterance_comment


def _print_step(n: int, total: int, msg: str) -> None:
    print(f"\n[{n}/{total}] {msg}", flush=True)


def run_pipeline(input_path: str, *, upload: bool, num_speakers: int | None = None) -> int:
    cfg = load_config()
    src_path = Path(input_path).resolve()
    if not src_path.exists():
        print(f"[error] 파일이 존재하지 않습니다: {src_path}", file=sys.stderr)
        return 2

    pipeline_start = time.time()

    total_steps = 6 if upload else 5

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
    cache_path = cfg.work_dir / f"{src_path.stem}.segments.json"
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

    # 3) 요약
    _print_step(3, total_steps, f"회의 요약 (Ollama {cfg.ollama_model})")
    t0 = time.time()
    summary = summarizer.summarize(
        segments, model=cfg.ollama_model, host=cfg.ollama_host
    )
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
    clients = build_clients_from_env(cfg)
    if not clients:
        print("[error] G5 클라이언트 없음 — .env의 G5_API_BASE/G5_API_TOKEN 확인")
        return 3
    target_names = ", ".join(c.name for c in clients)
    _print_step(6, total_steps, f"그누보드5 업로드 (타겟: {target_names})")

    meeting_data = storage.get_meeting(cfg.db_path, meeting_id) or {}
    last_wr_id = None
    last_post_url = None
    any_success = False
    for client in clients:
        print(f"  [{client.name}] {client.api_base}")
        try:
            post = client.create_post(summary["title"], summary["summary_md"])
            wr_id = int(post["wr_id"])
            print(f"    → 게시글 wr_id={wr_id} ({post.get('url', '')})")
            last_wr_id = wr_id
            last_post_url = post.get("url")
            if not any_success:
                storage.mark_meeting_synced(cfg.db_path, meeting_id, str(wr_id))

            n_fail = 0
            for utt_row in meeting_data.get("utterances", []):
                utt = {
                    "speaker": utt_row["speaker"],
                    "start": utt_row["start_sec"],
                    "end": utt_row["end_sec"],
                    "text": utt_row["text"],
                }
                author = f"회의_{utt_row['speaker']}"
                try:
                    resp = client.create_comment(
                        wr_id, format_utterance_comment(utt), author_name=author
                    )
                    if not any_success:
                        storage.mark_utterance_synced(
                            cfg.db_path, utt_row["id"], str(resp["comment_id"])
                        )
                except G5ApiError as e:
                    n_fail += 1
                    if n_fail <= 3:
                        print(f"    [warn] 댓글 실패 (seq={utt_row['seq']}): {e}")
            print(f"    → 댓글 {len(meeting_data.get('utterances', []))}건 시도 (실패 {n_fail}건)")
            any_success = True
        except G5ApiError as e:
            print(f"    [error] '{client.name}' 업로드 실패: {e}")

    if not any_success:
        storage.mark_meeting_failed(cfg.db_path, meeting_id, "all G5 targets failed")
        print("    → 로컬 DB에는 저장되었습니다. 'python main.py --resync'로 재전송 가능.")
        return 3

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
    unsynced = storage.list_unsynced(cfg.db_path)
    print(f"미동기화 회의: {len(unsynced)}건")
    if not unsynced:
        return 0

    client = G5MettingApiClient(
        api_base=cfg.g5_api_base,
        api_token=cfg.g5_api_token,
        bo_table=cfg.g5_bo_table,
    )

    fail = 0
    for m in unsynced:
        mid = m["id"]
        print(f"\n[meeting_id={mid}] {m['title']}")
        data = storage.get_meeting(cfg.db_path, mid) or {}
        try:
            post = client.create_post(m["title"], m["summary_md"])
            wr_id = int(post["wr_id"])
            storage.mark_meeting_synced(cfg.db_path, mid, str(wr_id))
            print(f"  → 게시글 wr_id={wr_id}")
            for utt in data.get("utterances", []):
                if utt.get("sync_status") == "synced":
                    continue
                u = {
                    "speaker": utt["speaker"],
                    "start": utt["start_sec"],
                    "end": utt["end_sec"],
                    "text": utt["text"],
                }
                author = f"회의_{utt['speaker']}"
                try:
                    resp = client.create_comment(
                        wr_id, format_utterance_comment(u), author_name=author
                    )
                    storage.mark_utterance_synced(cfg.db_path, utt["id"], str(resp["comment_id"]))
                except G5ApiError as e:
                    print(f"  [warn] 댓글 실패 seq={utt['seq']}: {e}")
        except G5ApiError as e:
            storage.mark_meeting_failed(cfg.db_path, mid, str(e))
            print(f"  [error] 실패: {e}")
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
