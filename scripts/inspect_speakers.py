"""화자 분포 점검용."""
import json
from pathlib import Path
from collections import Counter

cache = Path("./data/work/- 모두가 안전하게 일할 수 있는 나라 - 산업안전 강화 기관장 회의.segments.json")
data = json.load(open(cache, encoding="utf-8"))

def ts(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

print(f"=== 전체: {len(data)}건 ===")
c = Counter(s["speaker"] for s in data)
for sp, n in c.most_common():
    print(f"  {sp}: {n}건 ({n*100/len(data):.1f}%)")

# 시간대별 화자 점유율 확인 (인공적 분리인지 진짜 분리인지)
print()
print("=== 10분 구간별 화자 분포 (인공 vs 진짜 분리 판단) ===")
for chunk_start in range(0, 6500, 600):
    chunk_segs = [s for s in data if chunk_start <= s["start"] < chunk_start + 600]
    if not chunk_segs:
        continue
    cc = Counter(s["speaker"] for s in chunk_segs)
    summary = ", ".join(f"{sp}:{n}" for sp, n in cc.most_common())
    print(f"  [{ts(chunk_start)} ~ {ts(chunk_start+600)}] {summary}")

# 각 화자의 발화 샘플
print()
for speaker in ["사용자1", "사용자2", "사용자3"]:
    segs = [s for s in data if s["speaker"] == speaker]
    if not segs:
        continue
    print(f"=== {speaker} 샘플 (앞 3건 + 뒤 2건) ===")
    samples = segs[:3] + (["..."] if len(segs) > 5 else []) + segs[-2:] if len(segs) > 5 else segs
    for s in samples:
        if s == "...":
            print("  ... (중간 생략) ...")
            continue
        print(f"  [{ts(s['start'])}] {s['text'][:100]}")
    print()
