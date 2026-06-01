import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DATABASE_URL
from src.database import init_db
from src.extract import extract_from_meeting
from src.ingest import ingest_meeting
from src.transcriber import FileTranscriber

LOW_CONFIDENCE_THRESHOLD = 0.7
TOP_N_ASSIGNEE = 5
TOP_N_KEYWORDS = 10

STOPWORDS = {
    "이", "가", "을", "를", "은", "는", "의", "에", "에서", "으로", "로",
    "와", "과", "도", "만", "까지", "부터", "이다", "하다", "있다", "없다",
    "그", "저", "것", "수", "등", "및", "후", "전", "더", "잘", "좀", "다",
    "안", "못", "또", "하고", "하여", "합니다", "했습니다", "됩니다",
    "위해", "대해", "관련", "통해", "경우", "때", "이후", "해당", "위한",
    "대한", "이번", "다음", "오늘", "내일", "방향", "진행", "확인", "완료",
}

# ---------------------------------------------------------------------------
# 데이터 로딩
# ---------------------------------------------------------------------------

def _get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


@st.cache_data(ttl=60)
def load_action_items() -> pd.DataFrame:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT action_item_id, meeting_id, meeting_title, meeting_date, "
                "content, assignee, due_date, due_is_inferred, confidence, "
                "source_quote, is_ambiguous, status, extracted_at "
                "FROM mart_action_items ORDER BY extracted_at DESC"
            )
            rows = cur.fetchall()
        conn.close()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception as e:
        st.error(f"mart_action_items 로딩 실패: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_minutes() -> pd.DataFrame:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT meeting_id, meeting_title, meeting_date, summary, decisions, updated_at "
                "FROM mart_minutes ORDER BY meeting_date DESC"
            )
            rows = cur.fetchall()
        conn.close()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception as e:
        st.error(f"mart_minutes 로딩 실패: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 키워드 추출 (BoW)
# ---------------------------------------------------------------------------

def _extract_keywords(texts: list, top_n: int = TOP_N_KEYWORDS) -> dict:
    counter = Counter()
    for text in texts:
        for word in str(text).split():
            word = word.strip(".,()[]!?")
            if len(word) >= 2 and word not in STOPWORDS:
                counter[word] += 1
    return dict(counter.most_common(top_n))


# ---------------------------------------------------------------------------
# Slack 페이로드 생성
# ---------------------------------------------------------------------------

def _build_slack_payload(open_items: pd.DataFrame) -> dict:
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "오늘의 미완료 액션아이템"},
        }
    ]
    for _, row in open_items.iterrows():
        assignee = row["assignee"] if row["assignee"] else "미배정"
        text = f"*{assignee}*: {row['content']}"
        if row.get("due_date"):
            text += f"  (기한: {row['due_date']})"
        if row.get("is_ambiguous"):
            text += "  ⚠️ 담당자 불명확"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"총 {len(open_items)}건 미완료"}],
        }
    )
    return {"blocks": blocks}


# ---------------------------------------------------------------------------
# 파이프라인 실행
# ---------------------------------------------------------------------------

def _dbt_run(select: str) -> bool:
    result = subprocess.run(
        ["dbt", "run", "--project-dir", "dbt_project",
         "--profiles-dir", "dbt_project", "--select", select],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    return result.returncode == 0


def _run_pipeline(meeting, speaker_map: dict):
    for utt in meeting.utterances:
        utt.speaker = speaker_map.get(utt.speaker, utt.speaker)

    with st.status("파이프라인 실행 중...", expanded=True) as status:
        st.write("① DB 초기화")
        init_db()
        st.write("② 발화 적재 (ingest)")
        ingest_meeting(meeting)
        st.write("③ dbt staging")
        if not _dbt_run("staging"):
            status.update(label="dbt staging 실패", state="error")
            return
        st.write("④ LLM 추출 (extract)")
        extract_from_meeting(meeting.meeting_id)
        st.write("⑤ dbt marts")
        if not _dbt_run("marts"):
            status.update(label="dbt marts 실패", state="error")
            return
        status.update(label="완료!", state="complete")

    st.cache_data.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Action Recommend Dashboard", layout="wide")
st.title("회의 액션아이템 대시보드")

df = load_action_items()
minutes_df = load_minutes()

if df.empty:
    st.warning("데이터가 없습니다. 사이드바에서 파일을 업로드하거나 터미널에서 `make run`을 실행하세요.")

# ---------------------------------------------------------------------------
# 상태 요약 메트릭
# ---------------------------------------------------------------------------

if not df.empty:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("전체", len(df))
    col2.metric("Open", len(df[df["status"] == "open"]))
    col3.metric("Done", len(df[df["status"] == "done"]))
    col4.metric("Blocked", len(df[df["status"] == "blocked"]))

    # ---------------------------------------------------------------------------
    # 섹션 1: 회의·액션아이템 발생 추이
    # ---------------------------------------------------------------------------

    st.subheader("회의·액션아이템 발생 추이")
    trend = (
        df.groupby("meeting_date").size()
        .reset_index(name="건수")
        .set_index("meeting_date")
    )
    if trend.empty:
        st.info("추이 데이터 없음")
    else:
        st.bar_chart(trend)

    # ---------------------------------------------------------------------------
    # 섹션 2: 담당자별 미완료 Top N
    # ---------------------------------------------------------------------------

    st.subheader(f"담당자별 미완료 액션아이템 Top {TOP_N_ASSIGNEE}")
    open_df = df[df["status"] == "open"].copy()
    if open_df.empty:
        st.info("미완료 항목 없음")
    else:
        open_df["assignee"] = open_df["assignee"].fillna("미배정")
        top_assignee = (
            open_df.groupby("assignee").size()
            .reset_index(name="미완료 건수")
            .sort_values("미완료 건수", ascending=False)
            .head(TOP_N_ASSIGNEE)
            .set_index("assignee")
        )
        st.bar_chart(top_assignee)

    # ---------------------------------------------------------------------------
    # 섹션 3: 캠페인/광고주별 반복 이슈 키워드
    # ---------------------------------------------------------------------------

    st.subheader("캠페인/광고주별 반복 이슈 키워드")
    campaigns = df["meeting_title"].dropna().unique()
    if len(campaigns) == 0:
        st.info("키워드 데이터 없음")
    else:
        for campaign in campaigns:
            contents = df[df["meeting_title"] == campaign]["content"].tolist()
            keywords = _extract_keywords(contents, top_n=TOP_N_KEYWORDS)
            if keywords:
                with st.expander(f"{campaign}", expanded=True):
                    kw_df = pd.DataFrame(
                        list(keywords.items()), columns=["키워드", "빈도"]
                    ).set_index("키워드")
                    st.bar_chart(kw_df)

    # ---------------------------------------------------------------------------
    # 섹션 4: confidence 분포 + 저신뢰도 드릴다운
    # ---------------------------------------------------------------------------

    st.subheader(f"LLM 추출 신뢰도 분포 (confidence)")

    bins = [round(i * 0.1, 1) for i in range(11)]
    labels = [f"{round(i*0.1,1)}~{round((i+1)*0.1,1)}" for i in range(10)]
    conf_df = df.copy()
    conf_df["conf_bucket"] = pd.cut(
        conf_df["confidence"], bins=bins, labels=labels, include_lowest=True
    )
    hist = conf_df["conf_bucket"].value_counts().sort_index().reset_index()
    hist.columns = ["구간", "건수"]
    st.bar_chart(hist.set_index("구간"))

    st.markdown(f"**저신뢰도 항목 검수 (confidence < {LOW_CONFIDENCE_THRESHOLD})**")
    low_conf = df[df["confidence"] < LOW_CONFIDENCE_THRESHOLD][
        ["content", "assignee", "confidence", "is_ambiguous", "source_quote", "status"]
    ].copy()
    low_conf["assignee"] = low_conf["assignee"].fillna("미배정")
    if low_conf.empty:
        st.info("저신뢰도 항목 없음")
    else:
        st.dataframe(
            low_conf,
            use_container_width=True,
            column_config={
                "confidence": st.column_config.NumberColumn(format="%.2f"),
                "is_ambiguous": st.column_config.CheckboxColumn("애매함"),
            },
        )

    # ---------------------------------------------------------------------------
    # 섹션 5: 주요 의사결정
    # ---------------------------------------------------------------------------

    st.subheader("주요 의사결정")
    if minutes_df.empty:
        st.info("회의록 데이터 없음")
    else:
        for _, row in minutes_df.iterrows():
            meeting_label = row.get("meeting_title") or row["meeting_id"]
            with st.expander(f"{meeting_label} ({row.get('meeting_date', '')})", expanded=True):
                st.markdown("**요약**")
                st.write(row["summary"])
                st.markdown("**결정사항**")
                decisions = row["decisions"]
                if isinstance(decisions, str):
                    decisions = json.loads(decisions)
                for d in decisions:
                    st.markdown(f"- {d}")

# ---------------------------------------------------------------------------
# 사이드바: 회의 업로드
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("새 회의 업로드")

    uploaded_file = st.file_uploader("transcript JSON", type=["json"])

    if uploaded_file is not None:
        file_key = uploaded_file.name

        if st.session_state.get("uploaded_file_name") != file_key:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as f:
                f.write(uploaded_file.getvalue())
                tmp_path = f.name
            try:
                meeting = FileTranscriber().load(tmp_path)
                st.session_state["uploaded_file_name"] = file_key
                st.session_state["pending_meeting"] = meeting
                speakers = sorted(set(u.speaker for u in meeting.utterances))
                st.session_state["speaker_map"] = {s: s for s in speakers}
            except Exception as e:
                st.error(f"파일 파싱 오류: {e}")
                st.session_state.pop("pending_meeting", None)

        meeting = st.session_state.get("pending_meeting")
        if meeting:
            speakers = sorted(set(u.speaker for u in meeting.utterances))
            st.write(f"**발화자 {len(speakers)}명 감지**")

            speaker_map = st.session_state.get("speaker_map", {})
            updated_map = {}
            for spk in speakers:
                updated_map[spk] = st.text_input(
                    label=spk,
                    value=speaker_map.get(spk, spk),
                    key=f"spk_{spk}",
                )
            st.session_state["speaker_map"] = updated_map

            if st.button("파이프라인 실행", type="primary", use_container_width=True):
                _run_pipeline(meeting, st.session_state["speaker_map"])

    st.divider()

    # ---------------------------------------------------------------------------
    # 사이드바: Slack 페이로드
    # ---------------------------------------------------------------------------

    st.header("Slack 알림 페이로드 (Mock)")
    if df.empty:
        st.info("데이터 없음")
    else:
        open_items = df[df["status"] == "open"]
        if open_items.empty:
            st.info("미완료 항목 없음")
        else:
            payload = _build_slack_payload(open_items)
            st.json(payload)
            st.download_button(
                label="JSON 다운로드",
                data=json.dumps(payload, ensure_ascii=False, indent=2),
                file_name="slack_payload.json",
                mime="application/json",
            )
