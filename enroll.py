"""화자 등록 CLI.

등록된 화자는 회의 처리 시 자동으로 매칭되어 "사용자N" 대신 실제 이름이 등록됩니다.

사용:
    python enroll.py add "장관님" samples/장관님.wav      # 등록 (같은 이름 다시 → 임베딩 평균 갱신)
    python enroll.py list                                  # 등록된 화자 목록
    python enroll.py delete "장관님"                       # 삭제
    python enroll.py test samples/test.wav                 # 입력 음성이 누구인지 매칭 테스트
    python enroll.py extract-from <meeting_id> <speaker>   # 기존 회의에서 화자의 가장 긴 발화 구간을 wav로 추출

샘플 wav 가이드:
    - 10초 이상 깨끗한 음성 (잡음 적게)
    - 16kHz mono 권장 (다른 포맷도 자동 변환됨)
    - 한 사람의 연속 발화여야 함 (다른 사람 끼면 매칭 정확도 저하)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from meeting_record.console import configure_utf8_stdio
from src.speaker_registry import SpeakerRegistry


def cmd_add(args) -> int:
    cfg = load_config()
    reg = SpeakerRegistry(cfg.db_path)
    audio_path = Path(args.audio).resolve()
    if not audio_path.exists():
        print(f"파일 없음: {audio_path}", file=sys.stderr)
        return 1
    print(f"음성 임베딩 추출 중... ({audio_path.name})")
    res = reg.enroll(args.name, audio_path)
    print(f"✓ {res['action']}: {res['name']} (총 샘플 {res['samples_count']}개)")
    return 0


def cmd_list(args) -> int:
    cfg = load_config()
    reg = SpeakerRegistry(cfg.db_path)
    rows = reg.list_all()
    if not rows:
        print("등록된 화자가 없습니다.")
        return 0
    print(f"\n등록된 화자: {len(rows)}명\n")
    print(f"{'ID':>4} {'이름':<20} {'샘플':>4} {'등록일':<20} 샘플 경로")
    print("-" * 100)
    for r in rows:
        print(f"{r['id']:>4} {r['name']:<20} {r['samples_count']:>4} {r['created_at'][:19]:<20} {r['sample_path'] or ''}")
    return 0


def cmd_delete(args) -> int:
    cfg = load_config()
    reg = SpeakerRegistry(cfg.db_path)
    n = reg.delete(args.name)
    if n:
        print(f"✓ '{args.name}' 삭제 완료")
        return 0
    print(f"'{args.name}' 없음", file=sys.stderr)
    return 1


def cmd_test(args) -> int:
    from src.speaker_registry import _extract_embedding, _cosine
    cfg = load_config()
    reg = SpeakerRegistry(cfg.db_path)
    audio_path = Path(args.audio).resolve()
    if not audio_path.exists():
        print(f"파일 없음: {audio_path}", file=sys.stderr)
        return 1
    print(f"임베딩 추출 중... ({audio_path.name})")
    emb = _extract_embedding(audio_path)
    print()
    print("등록된 화자와의 유사도:")
    scores = sorted(
        [(name, _cosine(emb, ref)) for name, ref in reg.all_embeddings()],
        key=lambda x: -x[1],
    )
    if not scores:
        print("  (등록된 화자 없음)")
        return 0
    for name, score in scores:
        mark = "★" if score >= args.threshold else " "
        print(f"  {mark} {name}: {score:.4f}")
    print()
    best = scores[0]
    if best[1] >= args.threshold:
        print(f"→ 매칭: {best[0]} (score={best[1]:.4f}, threshold={args.threshold})")
    else:
        print(f"→ 매칭 실패 (최고 score={best[1]:.4f} < threshold={args.threshold})")
    return 0


def cmd_extract_from(args) -> int:
    """기존 회의에서 특정 화자의 가장 긴 연속 발화를 wav로 추출 (enrollment 샘플용)."""
    import subprocess
    import shutil
    from src import storage

    cfg = load_config()
    data = storage.get_meeting(cfg.db_path, args.meeting_id)
    if not data:
        print(f"meeting_id={args.meeting_id} 없음", file=sys.stderr)
        return 1

    utts = [u for u in data["utterances"] if u["speaker"] == args.speaker]
    if not utts:
        print(f"meeting_id={args.meeting_id}에 화자 '{args.speaker}' 없음", file=sys.stderr)
        return 2

    # 가장 긴 단일 발화 구간 찾기
    longest = max(utts, key=lambda u: u["end_sec"] - u["start_sec"])
    duration = longest["end_sec"] - longest["start_sec"]
    print(f"가장 긴 단일 발화: {duration:.1f}초")
    print(f"  텍스트: {longest['text'][:100]}...")

    # 가장 긴 단일 발화 우선 (다른 화자 끼지 않은 가장 깨끗한 샘플).
    # target_sec보다 짧으면 시간상 가까운 같은 화자 발화를 추가하되,
    # 발화 사이 간격이 너무 크면(다른 사람이 끼었을 가능성) 중단.
    target_sec = max(args.target, 5.0)
    sorted_utts = sorted(utts, key=lambda u: u["start_sec"])
    # longest를 중심으로 양쪽으로 확장
    idx = sorted_utts.index(longest)
    selected = [longest]
    total = longest["end_sec"] - longest["start_sec"]
    MAX_GAP_SEC = 3.0  # 같은 화자 발화 사이 허용 간격 (초과 시 중단)

    # 오른쪽 확장
    last_end = longest["end_sec"]
    for u in sorted_utts[idx + 1:]:
        if total >= target_sec:
            break
        if u["start_sec"] - last_end > MAX_GAP_SEC:
            break
        selected.append(u)
        total += u["end_sec"] - u["start_sec"]
        last_end = u["end_sec"]

    # 왼쪽 확장
    first_start = longest["start_sec"]
    for u in reversed(sorted_utts[:idx]):
        if total >= target_sec:
            break
        if first_start - u["end_sec"] > MAX_GAP_SEC:
            break
        selected.insert(0, u)
        total += u["end_sec"] - u["start_sec"]
        first_start = u["start_sec"]

    selected.sort(key=lambda u: u["start_sec"])
    start = selected[0]["start_sec"]
    end = selected[-1]["end_sec"]
    span = end - start
    print(f"\n추출 구간: {start:.1f}s ~ {end:.1f}s (span {span:.1f}초, 같은 화자 발화 {len(selected)}개)")
    if span > target_sec * 3:
        print(f"  ⚠️ 추출 구간이 목표보다 너무 깁니다. 다른 화자가 끼었을 수 있습니다.")

    src_audio = Path(data["meeting"]["source_file"])
    if not src_audio.exists():
        print(f"원본 음성 파일을 못 찾음: {src_audio}", file=sys.stderr)
        return 3
    out = Path(args.out) if args.out else Path(f"./data/samples/{args.speaker}.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg를 찾을 수 없습니다", file=sys.stderr)
        return 4
    cmd = [
        ffmpeg, "-y", "-i", str(src_audio),
        "-ss", str(start), "-to", str(end),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ffmpeg 실패: {r.stderr[-500:]}", file=sys.stderr)
        return 5
    print(f"\n✓ 추출 완료: {out}")
    print(f"  enroll 명령:")
    print(f"    python enroll.py add \"실제이름\" \"{out}\"")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="화자 등록 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="화자 등록")
    p_add.add_argument("name", help="화자명 (예: 장관님)")
    p_add.add_argument("audio", help="음성 샘플 wav/mp3")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="등록된 화자 목록")
    p_list.set_defaults(func=cmd_list)

    p_del = sub.add_parser("delete", help="화자 삭제")
    p_del.add_argument("name")
    p_del.set_defaults(func=cmd_delete)

    p_test = sub.add_parser("test", help="입력 음성이 누구인지 매칭 테스트")
    p_test.add_argument("audio")
    p_test.add_argument("--threshold", type=float, default=0.75)
    p_test.set_defaults(func=cmd_test)

    p_ex = sub.add_parser("extract-from", help="기존 회의에서 화자 샘플 추출")
    p_ex.add_argument("meeting_id", type=int)
    p_ex.add_argument("speaker", help="추출할 화자명 (예: 사용자3)")
    p_ex.add_argument("--target", type=float, default=30.0, help="목표 길이(초)")
    p_ex.add_argument("--out", help="출력 wav 경로 (기본 ./data/samples/<speaker>.wav)")
    p_ex.set_defaults(func=cmd_extract_from)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
