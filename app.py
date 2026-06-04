"""Streamlit 웹 UI — 회의록 조회/편집/관리.

실행:
    streamlit run app.py

기본 포트 8501에서 시작. 외부 접속 허용 시:
    streamlit run app.py --server.address 0.0.0.0
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from config import load_config
from src import comparator, dictionary, exporter, stats, storage


st.set_page_config(page_title="회의록 관리", page_icon="📝", layout="wide")


@st.cache_resource
def get_cfg():
    return load_config()


def _ts(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_dur(sec: float) -> str:
    return stats.format_duration(sec)


# ── 사이드바: 페이지 선택 ─────────────────────────────────
PAGES = ["📋 회의 목록", "🔍 검색", "📊 비교", "📚 사전 관리", "👤 화자 등록"]
with st.sidebar:
    st.title("📝 회의록 관리")
    page = st.radio("페이지", PAGES, label_visibility="collapsed")
    st.divider()
    cfg = get_cfg()
    st.caption(f"DB: `{cfg.db_path.name}`")
    st.caption(f"DEVICE: `{cfg.device}` / Whisper: `{cfg.whisper_model}`")
    st.caption(f"LLM: `{cfg.ollama_model}`")


# ────────────────────────────────────────────────────────
# 회의 목록 + 상세
# ────────────────────────────────────────────────────────
def render_meeting_list():
    st.header("📋 회의 목록")
    cfg = get_cfg()
    storage.init_db(cfg.db_path)
    meetings = storage.list_meetings(cfg.db_path, limit=200)

    if not meetings:
        st.info("저장된 회의가 없습니다. `python main.py audio.mp3`로 처리하세요.")
        return

    # 회의 선택
    options = {f"#{m['id']:>3} | {m['title']} ({m['created_at'][:10]})": m["id"] for m in meetings}
    selected = st.selectbox(f"총 {len(meetings)}개 회의", list(options.keys()))
    meeting_id = options[selected]

    render_meeting_detail(meeting_id)


def render_meeting_detail(meeting_id: int):
    cfg = get_cfg()
    data = storage.get_meeting(cfg.db_path, meeting_id)
    if not data:
        st.error(f"meeting_id={meeting_id} 없음")
        return
    m = data["meeting"]
    utts = data["utterances"]

    st.subheader(f"#{meeting_id} · {m['title']}")

    # 메타 카드
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("회의 길이", _fmt_dur(m["duration_sec"]))
    col2.metric("발화 수", len(utts))
    col3.metric("화자 수", m["speaker_count"])
    col4.metric("그누보드5", f"wr_id={m['remote_post_id']}" if m["remote_post_id"] else "미등록")

    # 탭
    tab_summary, tab_utts, tab_stats, tab_edit, tab_export = st.tabs(
        ["📄 요약", "💬 발화", "📊 통계", "✏️ 편집", "📤 Export"]
    )

    with tab_summary:
        st.markdown(m["summary_md"])

    with tab_utts:
        # 화자 필터
        speakers = sorted({u["speaker"] for u in utts})
        sel_sp = st.multiselect("화자 필터", speakers, default=speakers, key=f"utt_sp_{meeting_id}")
        keyword = st.text_input("발화 본문 검색 (단순 포함)", key=f"utt_kw_{meeting_id}")
        filtered = [u for u in utts if u["speaker"] in sel_sp and (not keyword or keyword in u["text"])]
        st.caption(f"표시: {len(filtered)}건 / 전체 {len(utts)}건")
        for u in filtered:
            with st.container(border=True):
                cols = st.columns([1, 1, 5])
                cols[0].caption(f"⏱ {_ts(u['start_sec'])}")
                cols[1].caption(f"🗣 {u['speaker']}")
                cols[2].write(u["text"])

    with tab_stats:
        utts_for_stats = [{
            "speaker": u["speaker"], "start": u["start_sec"], "end": u["end_sec"], "text": u["text"],
        } for u in utts]
        sp_stats = stats.per_speaker_stats(utts_for_stats)
        st.subheader("화자별 통계")
        st.dataframe(
            [{
                "화자": s["speaker"],
                "발언 횟수": s["count"],
                "총 발언 시간": _fmt_dur(s["total_sec"]),
                "평균 발언": _fmt_dur(s["avg_sec"]),
                "비율(%)": s["ratio_pct"],
            } for s in sp_stats],
            use_container_width=True,
            hide_index=True,
        )
        # 막대 그래프
        st.subheader("발언 시간 분포")
        chart_data = {s["speaker"]: s["total_sec"] for s in sp_stats}
        st.bar_chart(chart_data, horizontal=True)

        st.subheader("시간 구간별 분포 (10분 단위)")
        tl = stats.time_distribution(utts_for_stats)
        st.dataframe(
            [{
                "구간": f"{_fmt_dur(t['chunk_start'])}~{_fmt_dur(t['chunk_end'])}",
                "발화": t["count"],
                "주도 화자": f"{t['top_speaker']} ({t['top_speaker_count']}건)",
            } for t in tl],
            use_container_width=True,
            hide_index=True,
        )

    with tab_edit:
        st.warning("⚠️ 변경 사항은 즉시 DB에 반영됩니다. 그누보드5 동기화는 별도 버튼.")

        st.subheader("화자 라벨 일괄 변경")
        speakers = sorted({u["speaker"] for u in utts})
        col1, col2, col3 = st.columns([2, 2, 1])
        old = col1.selectbox("기존 라벨", speakers, key=f"old_sp_{meeting_id}")
        new = col2.text_input("새 라벨", value=old, key=f"new_sp_{meeting_id}")
        if col3.button("변경", key=f"btn_sp_{meeting_id}"):
            if new and new != old:
                n = storage.update_speaker_label(cfg.db_path, meeting_id, old, new)
                st.success(f"{n}건 변경됨 → 새로고침")
                st.rerun()

        st.divider()
        st.subheader("발화 텍스트 인라인 수정")
        st.caption("수정 후 '저장' 버튼을 눌러주세요. (검색 → 수정이 효율적)")
        kw = st.text_input("수정할 발화 검색", key=f"edit_kw_{meeting_id}")
        if kw:
            edit_utts = [u for u in utts if kw in u["text"]][:10]
            for u in edit_utts:
                with st.form(key=f"edit_form_{u['id']}", border=True):
                    st.caption(f"⏱ {_ts(u['start_sec'])} | 🗣 {u['speaker']} | id={u['id']}")
                    new_text = st.text_area("내용", value=u["text"], key=f"text_{u['id']}", height=80)
                    submitted = st.form_submit_button("저장")
                    if submitted and new_text != u["text"]:
                        storage.update_utterance_text(cfg.db_path, u["id"], new_text)
                        st.success("저장됨 → 새로고침")
                        st.rerun()

        st.divider()
        st.subheader("요약 본문 직접 수정 (마크다운)")
        with st.form(key=f"edit_summary_form_{meeting_id}"):
            new_title = st.text_input("제목", value=m["title"])
            new_md = st.text_area("요약 본문", value=m["summary_md"], height=300)
            if st.form_submit_button("요약 저장"):
                storage.update_meeting_summary(cfg.db_path, meeting_id, title=new_title, summary_md=new_md)
                st.success("저장됨")
                st.rerun()

        st.divider()
        st.subheader("⚠️ 회의 삭제")
        with st.popover("삭제하기"):
            st.error("이 작업은 되돌릴 수 없습니다.")
            confirm = st.text_input(f"확인을 위해 #{meeting_id} 을 입력하세요")
            if st.button("정말 삭제", type="primary"):
                if confirm == f"#{meeting_id}":
                    storage.delete_meeting(cfg.db_path, meeting_id)
                    st.success("삭제됨")
                    st.rerun()
                else:
                    st.error("입력값 불일치")

    with tab_export:
        col1, col2 = st.columns(2)
        include_transcript = col1.checkbox("발화 전문 포함", value=True)
        if col2.button("📥 .docx 다운로드", use_container_width=True):
            out_path = Path(f"./data/exports/{meeting_id:03d}_{m['title'][:30]}.docx")
            exporter.to_docx(m, utts, out_path, include_transcript=include_transcript)
            with open(out_path, "rb") as f:
                st.download_button("다운로드 받기", f.read(), file_name=out_path.name)

        if col1.button("🌐 .html 다운로드", use_container_width=True):
            out_path = Path(f"./data/exports/{meeting_id:03d}_{m['title'][:30]}.html")
            exporter.to_html(m, utts, out_path, include_transcript=include_transcript)
            with open(out_path, "rb") as f:
                st.download_button("HTML 다운로드", f.read(), file_name=out_path.name)

        st.divider()
        st.caption("그누보드5 게시판 링크")
        if m["remote_post_id"]:
            g5_url = f"{cfg.g5_api_base.replace('/g5_meeting_api','')}/gnuboard5/bbs/board.php?bo_table={cfg.g5_bo_table}&wr_id={m['remote_post_id']}"
            st.link_button("🔗 그누보드5에서 보기", g5_url)
        else:
            st.info("그누보드5에 미등록 — `python main.py --resync` 실행")


# ────────────────────────────────────────────────────────
# 검색
# ────────────────────────────────────────────────────────
def render_search():
    st.header("🔍 회의록 검색 (FTS5)")
    cfg = get_cfg()
    storage.init_db(cfg.db_path)

    col1, col2 = st.columns([3, 1])
    query = col1.text_input("검색어", placeholder="예: 산업재해 / 지게차 / 안전점검", key="q")
    target = col2.radio("대상", ["전체", "회의 요약만", "발화만"], horizontal=False, key="t")

    if not query:
        st.info("검색어를 입력하세요. trigram 토크나이저로 최소 3글자 권장.")
        return

    if target in ("전체", "회의 요약만"):
        st.subheader("📚 회의 요약 결과")
        try:
            rows = storage.search_meetings(cfg.db_path, query, limit=10)
            for r in rows:
                with st.container(border=True):
                    st.markdown(f"**#{r['id']} · {r['title']}** · {r['created_at'][:10]}")
                    st.caption(r["snippet"])
            if not rows:
                st.caption("결과 없음")
        except Exception as e:
            st.error(f"검색 실패: {e}")

    if target in ("전체", "발화만"):
        st.subheader("💬 발화 검색 결과")
        try:
            rows = storage.search_utterances(cfg.db_path, query, limit=30)
            for r in rows:
                with st.container(border=True):
                    cols = st.columns([1, 1, 5])
                    cols[0].caption(f"⏱ {_ts(r['start_sec'])}")
                    cols[1].caption(f"🗣 {r['speaker']}")
                    cols[2].caption(f"📂 #{r['meeting_id']} · {r['meeting_title']}")
                    st.write(r["snippet"])
            if not rows:
                st.caption("결과 없음")
        except Exception as e:
            st.error(f"검색 실패: {e}")


# ────────────────────────────────────────────────────────
# 비교
# ────────────────────────────────────────────────────────
def render_compare():
    st.header("📊 회의 비교 분석")
    cfg = get_cfg()
    storage.init_db(cfg.db_path)
    meetings = storage.list_meetings(cfg.db_path, limit=200)
    if not meetings:
        st.info("저장된 회의가 없습니다.")
        return

    tab_pair, tab_timeline, tab_kw_trend, tab_sp_trend, tab_top = st.tabs(
        ["두 회의 비교", "월별 통계", "키워드 추이", "화자 추이", "상위 키워드"]
    )

    label_map = {f"#{m['id']:>3} | {m['title'][:50]} ({m['created_at'][:10]})": m["id"] for m in meetings}
    labels = list(label_map.keys())

    with tab_pair:
        col1, col2 = st.columns(2)
        sel_a = col1.selectbox("회의 A", labels, key="cmp_a")
        sel_b = col2.selectbox("회의 B", labels, index=min(1, len(labels)-1), key="cmp_b")
        if sel_a == sel_b:
            st.warning("서로 다른 두 회의를 선택하세요")
        else:
            id_a, id_b = label_map[sel_a], label_map[sel_b]
            try:
                result = comparator.compare_two(cfg.db_path, id_a, id_b)
            except ValueError as e:
                st.error(str(e))
            else:
                md = result["meta_diff"]
                col1, col2 = st.columns(2)
                with col1:
                    ma = result["meetings"]["a"]
                    st.markdown(f"**[A] #{id_a}** {ma['title']}")
                    st.caption(f"{ma['created_at'][:10]} · {_fmt_dur(md['duration_sec_a'])} · 발화 {md['utterance_count_a']} · 화자 {md['speaker_count_a']}")
                with col2:
                    mb = result["meetings"]["b"]
                    st.markdown(f"**[B] #{id_b}** {mb['title']}")
                    st.caption(f"{mb['created_at'][:10]} · {_fmt_dur(md['duration_sec_b'])} · 발화 {md['utterance_count_b']} · 화자 {md['speaker_count_b']}")

                st.divider()
                sp = result["speakers"]
                cols = st.columns(3)
                cols[0].markdown("**공통 화자**")
                cols[0].write(", ".join(sp["common"]) or "—")
                cols[1].markdown("**A에만**")
                cols[1].write(", ".join(sp["only_in_a"]) or "—")
                cols[2].markdown("**B에만**")
                cols[2].write(", ".join(sp["only_in_b"]) or "—")

                st.divider()
                kw = result["keywords"]
                st.subheader("공통 핵심어 (상위 15)")
                if kw["shared"]:
                    st.dataframe(
                        [{"단어": w, "A": na, "B": nb, "합계": na+nb} for w, na, nb in kw["shared"][:15]],
                        use_container_width=True, hide_index=True,
                    )
                else:
                    st.caption("공통 키워드 없음")

                col1, col2 = st.columns(2)
                col1.subheader("A에만 자주")
                col1.dataframe(
                    [{"단어": w, "횟수": n} for w, n in kw["only_a"][:15]],
                    use_container_width=True, hide_index=True,
                ) if kw["only_a"] else col1.caption("없음")
                col2.subheader("B에만 자주")
                col2.dataframe(
                    [{"단어": w, "횟수": n} for w, n in kw["only_b"][:15]],
                    use_container_width=True, hide_index=True,
                ) if kw["only_b"] else col2.caption("없음")

    with tab_timeline:
        col1, col2 = st.columns(2)
        since = col1.text_input("시작 (YYYY-MM-DD)", key="tl_since")
        until = col2.text_input("종료 (YYYY-MM-DD)", key="tl_until")
        rows = comparator.timeline_stats(cfg.db_path, since=since or None, until=until or None)
        if not rows:
            st.info("기간 내 회의 없음")
        else:
            st.dataframe(
                [{
                    "월": r["month"], "회의 수": r["count"],
                    "총 길이": _fmt_dur(r["total_sec"]),
                    "평균": _fmt_dur(r["avg_sec"]),
                    "총 발화": r["utterance_count"],
                } for r in rows],
                use_container_width=True, hide_index=True,
            )
            st.subheader("월별 회의 수")
            st.bar_chart({r["month"]: r["count"] for r in rows})
            st.subheader("월별 총 발화 수")
            st.bar_chart({r["month"]: r["utterance_count"] for r in rows})

    with tab_kw_trend:
        kw = st.text_input("키워드", placeholder="예: 산업재해 / 안전 / 지게차", key="kt_kw")
        col1, col2 = st.columns(2)
        since = col1.text_input("시작 (YYYY-MM-DD)", key="kt_since")
        until = col2.text_input("종료 (YYYY-MM-DD)", key="kt_until")
        if kw:
            rows = comparator.keyword_trend(cfg.db_path, kw, since=since or None, until=until or None)
            if rows:
                st.dataframe(
                    [{"월": r["month"], "회의 수": r["meeting_count"], "등장 횟수": r["occurrence_count"]} for r in rows],
                    use_container_width=True, hide_index=True,
                )
                st.bar_chart({r["month"]: r["occurrence_count"] for r in rows})
            else:
                st.info(f"'{kw}' 등장한 회의 없음")

    with tab_sp_trend:
        all_speakers = set()
        with storage.connect(cfg.db_path) as conn:
            for r in conn.execute("SELECT DISTINCT speaker FROM utterances ORDER BY speaker").fetchall():
                all_speakers.add(r["speaker"])
        if not all_speakers:
            st.info("화자 데이터 없음")
        else:
            sp = st.selectbox("화자", sorted(all_speakers), key="st_sp")
            col1, col2 = st.columns(2)
            since = col1.text_input("시작 (YYYY-MM-DD)", key="st_since")
            until = col2.text_input("종료 (YYYY-MM-DD)", key="st_until")
            rows = comparator.speaker_trend(cfg.db_path, sp, since=since or None, until=until or None)
            if rows:
                st.dataframe(
                    [{
                        "월": r["month"], "참여 회의": r["meeting_count"],
                        "발화 수": r["utterance_count"], "발언 시간": _fmt_dur(r["total_sec"]),
                    } for r in rows],
                    use_container_width=True, hide_index=True,
                )
                st.bar_chart({r["month"]: r["utterance_count"] for r in rows})

    with tab_top:
        st.caption("회의의 상위 한국어 키워드 (단순 빈도 + 흔한 조사/어미 제외)")
        sel = st.selectbox("회의 선택", labels, key="top_sel")
        meeting_id = label_map[sel]
        data = storage.get_meeting(cfg.db_path, meeting_id)
        if data:
            texts = [u["text"] for u in data["utterances"]]
            n_top = st.slider("표시 개수", 10, 100, 30, step=10)
            kws = comparator.top_keywords(texts, top_n=n_top)
            if kws:
                col1, col2 = st.columns([1, 1])
                col1.dataframe(
                    [{"단어": w, "횟수": n} for w, n in kws],
                    use_container_width=True, hide_index=True,
                )
                col2.bar_chart({w: n for w, n in kws[:20]}, horizontal=True)


# ────────────────────────────────────────────────────────
# 사전 관리
# ────────────────────────────────────────────────────────
def render_dictionary():
    st.header("📚 도메인 사전 관리")
    cfg = get_cfg()
    dictionary.init_dictionary(cfg.db_path)

    st.subheader("새 용어 등록")
    with st.form("add_term"):
        col1, col2 = st.columns(2)
        term = col1.text_input("정확한 표기 (term)", placeholder="산업안전")
        pattern = col2.text_input("오인식 패턴 (pattern, 선택)", placeholder="산업안정")
        notes = st.text_input("설명", placeholder="자주 틀리는 단어")
        if st.form_submit_button("등록"):
            if term:
                res = dictionary.add_term(cfg.db_path, term, pattern=pattern or None, notes=notes or None)
                st.success(f"{res['action']}: {term}")
                st.rerun()

    st.divider()
    st.subheader("등록된 용어")
    rows = dictionary.list_all(cfg.db_path)
    if not rows:
        st.info("등록된 용어 없음")
        return
    for r in rows:
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([1, 3, 2, 1])
            col1.caption(f"#{r['id']}")
            col2.write(f"**{r['term']}**" + (f" ← `{r['pattern']}`" if r["pattern"] else ""))
            col3.caption(r["notes"] or "")
            if col4.button("삭제", key=f"del_term_{r['id']}"):
                dictionary.remove_term(cfg.db_path, r["id"])
                st.rerun()

    st.divider()
    st.subheader("Whisper initial_prompt 미리보기")
    st.code(dictionary.build_whisper_prompt(cfg.db_path) or "(빈 값)", language=None)


# ────────────────────────────────────────────────────────
# 화자 등록
# ────────────────────────────────────────────────────────
def render_speakers():
    st.header("👤 화자 등록 관리")
    from src.speaker_registry import SpeakerRegistry
    cfg = get_cfg()
    reg = SpeakerRegistry(cfg.db_path)

    st.subheader("등록된 화자")
    rows = reg.list_all()
    if not rows:
        st.info("등록된 화자 없음. CLI로 등록: `python enroll.py add 장관님 sample.wav`")
    else:
        for r in rows:
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                col1.write(f"**{r['name']}** (id={r['id']})")
                col2.caption(f"샘플 {r['samples_count']}개 · {r['created_at'][:10]}")
                if col3.button("삭제", key=f"del_sp_{r['id']}"):
                    reg.delete(r["name"])
                    st.rerun()

    st.divider()
    st.subheader("기존 회의에서 샘플 추출")
    st.caption("CLI 사용 권장: `python enroll.py extract-from <meeting_id> <speaker> --out path.wav`")
    st.code(
        "python enroll.py extract-from 5 사용자3 --out data/samples/장관님.wav --target 30\n"
        "python enroll.py add \"장관님\" data/samples/장관님.wav",
        language="powershell",
    )


# ────────────────────────────────────────────────────────
# 라우팅
# ────────────────────────────────────────────────────────
if page == "📋 회의 목록":
    render_meeting_list()
elif page == "🔍 검색":
    render_search()
elif page == "📊 비교":
    render_compare()
elif page == "📚 사전 관리":
    render_dictionary()
elif page == "👤 화자 등록":
    render_speakers()
