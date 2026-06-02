import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from src.action_items import update_action_item_status
from src.config import DATABASE_URL, LLM_MODE, SLACK_WEBHOOK_URL
from src.database import reset_db
from src.extract import _embed_text, extract_from_meeting
from src.ingest import ingest_meeting
from src.transcriber import AUDIO_EXTENSIONS, FileTranscriber, WhisperTranscriber

LOW_CONFIDENCE_THRESHOLD = 0.7
TOP_N_ASSIGNEE = 5
TOP_N_KEYWORDS = 10
STATUS_OPTIONS = ["open", "done", "blocked"]

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
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT action_item_id, meeting_id, meeting_title, meeting_date, "
                "content, assignee, due_date, due_is_inferred, confidence, "
                "source_quote, is_ambiguous, related_campaign, status, extracted_at "
                "FROM mart_action_items ORDER BY extracted_at DESC"
            )
            rows = cur.fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception as e:
        st.error(f"mart_action_items 로딩 실패: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            conn.close()


@st.cache_data(ttl=60)
def load_minutes() -> pd.DataFrame:
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT meeting_id, meeting_title, meeting_date, summary, decisions, updated_at "
                "FROM mart_minutes ORDER BY meeting_date DESC"
            )
            rows = cur.fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception as e:
        st.error(f"mart_minutes 로딩 실패: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# 키워드 추출 (BoW)
# ---------------------------------------------------------------------------

def load_similar_decisions(query: str, top_k: int = 5) -> pd.DataFrame:
    embedding = _embed_text(query)
    if embedding is None:
        return pd.DataFrame()
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.meeting_id, m.meeting_title, m.meeting_date,
                       m.summary, m.decisions,
                       (rm.embedding <=> %s::vector) AS distance
                FROM mart_minutes m
                JOIN raw_minutes rm USING (meeting_id)
                WHERE rm.embedding IS NOT NULL
                ORDER BY distance
                LIMIT %s
                """,
                (str(embedding), top_k),
            )
            rows = cur.fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception as e:
        st.error(f"유사 의사결정 검색 실패: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            conn.close()


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
        confidence = row.get("confidence", 1.0) or 1.0
        conf_label = f"🔴 {confidence:.2f}" if confidence < LOW_CONFIDENCE_THRESHOLD else f"🟢 {confidence:.2f}"
        text = f"*{assignee}*: {row['content']}  {conf_label}"
        if row.get("due_date"):
            inferred = " _(추론)_" if row.get("due_is_inferred") else ""
            text += f"  (기한: {row['due_date']}{inferred})"
        if row.get("related_campaign"):
            text += f"  [{row['related_campaign']}]"
        if row.get("is_ambiguous"):
            text += "  ⚠️ 담당자 불명확"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    low_conf_count = int((open_items.get("confidence", pd.Series(dtype=float)) < LOW_CONFIDENCE_THRESHOLD).sum())
    summary = f"총 {len(open_items)}건 미완료"
    if low_conf_count:
        summary += f"  |  🔴 낮은 신뢰도 {low_conf_count}건 검수 필요"
    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": summary}],
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
    if result.returncode != 0:
        st.error(f"dbt 실패 ({select}):\n```\n{result.stderr}\n```")
    return result.returncode == 0


def _run_status_step(label: str, fn):
    started_at = time.monotonic()
    st.write(f"{label} 시작")
    result = fn()
    elapsed = time.monotonic() - started_at
    st.write(f"{label} 완료 ({elapsed:.1f}s)")
    return result


def _run_pipeline(meeting, speaker_map: dict):
    for utt in meeting.utterances:
        utt.speaker = speaker_map.get(utt.speaker, utt.speaker)

    with st.status("파이프라인 실행 중...", expanded=True) as status:
        status.update(label="1/5 DB 초기화 및 기존 데이터 삭제 중...", state="running")
        _run_status_step("1/5 DB 초기화 및 기존 데이터 삭제", reset_db)

        status.update(label="2/5 발화 적재 중...", state="running")
        _run_status_step(
            f"2/5 발화 적재 ({len(meeting.utterances)}개)",
            lambda: ingest_meeting(meeting),
        )

        status.update(label="3/5 dbt staging 실행 중...", state="running")
        if not _run_status_step("3/5 dbt staging", lambda: _dbt_run("staging")):
            status.update(label="dbt staging 실패", state="error")
            return

        status.update(label="4/5 LLM 추출 중...", state="running")
        _run_status_step(
            f"4/5 LLM 추출 ({meeting.meeting_id})",
            lambda: extract_from_meeting(meeting.meeting_id),
        )

        status.update(label="5/5 dbt marts 실행 중...", state="running")
        if not _run_status_step("5/5 dbt marts", lambda: _dbt_run("marts")):
            status.update(label="dbt marts 실패", state="error")
            return
        status.update(label="파이프라인 완료", state="complete")

    st.cache_data.clear()
    st.rerun()


def _sync_marts_after_status_update() -> bool:
    return _dbt_run("marts")


def _save_status_updates(original_df: pd.DataFrame, edited_df: pd.DataFrame) -> int:
    updated_count = 0
    edited_rows = edited_df.reset_index(drop=True)
    original_rows = original_df.reset_index(drop=True)
    for index, row in edited_rows.iterrows():
        action_item_id = original_rows.at[index, "action_item_id"]
        original_status = original_rows.at[index, "status"]
        next_status = row["status"]
        if next_status != original_status:
            update_action_item_status(action_item_id, next_status)
            updated_count += 1
    return updated_count


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
    _today = pd.Timestamp.today().normalize()
    _overdue_count = int(
        (
            (df["status"] == "open")
            & (pd.to_datetime(df["due_date"], errors="coerce") < _today)
        ).sum()
    )
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("전체", len(df))
    col2.metric("Open", len(df[df["status"] == "open"]))
    col3.metric("Done", len(df[df["status"] == "done"]))
    col4.metric("Blocked", len(df[df["status"] == "blocked"]))
    col5.metric("기한 초과", _overdue_count)

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
    # 섹션 3: 캠페인별 미완료 건수
    # ---------------------------------------------------------------------------

    st.subheader("캠페인별 미완료 건수")
    if open_df.empty:
        st.info("미완료 항목 없음")
    else:
        campaign_counts = (
            open_df["related_campaign"].fillna("미연결")
            .value_counts()
            .rename_axis("캠페인")
            .reset_index(name="미완료 건수")
            .set_index("캠페인")
        )
        st.bar_chart(campaign_counts)

    # ---------------------------------------------------------------------------
    # 섹션 4: 캠페인/광고주별 반복 이슈 키워드
    # ---------------------------------------------------------------------------

    st.subheader("캠페인별 반복 이슈 키워드")
    st.caption("※ 다수 회의 적재 시 캠페인별 비교가 활성화됩니다")
    campaign_groups = df["related_campaign"].dropna().unique()
    if len(campaign_groups) == 0:
        st.info("캠페인 정보 없음 (related_campaign 미추출)")
    else:
        for campaign in campaign_groups:
            contents = df[df["related_campaign"] == campaign]["content"].tolist()
            keywords = _extract_keywords(contents, top_n=TOP_N_KEYWORDS)
            if keywords:
                with st.expander(f"{campaign}", expanded=True):
                    kw_df = pd.DataFrame(
                        list(keywords.items()), columns=["키워드", "빈도"]
                    ).set_index("키워드")
                    st.bar_chart(kw_df)

    # ---------------------------------------------------------------------------
    # 섹션 5: confidence 분포 + 저신뢰도 드릴다운
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
    # 섹션 6: 기한 초과 현황
    # ---------------------------------------------------------------------------

    st.subheader("기한 초과 현황")
    overdue_df = df[
        (df["status"] == "open")
        & (pd.to_datetime(df["due_date"], errors="coerce") < _today)
    ].copy()
    if overdue_df.empty:
        st.info("기한 초과 항목 없음")
    else:
        st.warning(f"기한 초과 {len(overdue_df)}건 — 즉시 확인 필요")
        display_cols = ["content", "assignee", "due_date", "confidence", "related_campaign", "status"]
        overdue_display = overdue_df[display_cols].rename(columns={
            "content": "내용", "assignee": "담당자", "due_date": "기한",
            "confidence": "신뢰도", "related_campaign": "캠페인", "status": "상태",
        })
        overdue_display["담당자"] = overdue_display["담당자"].fillna("미배정")
        st.dataframe(
            overdue_display,
            use_container_width=True,
            column_config={"신뢰도": st.column_config.NumberColumn(format="%.2f")},
        )

    # ---------------------------------------------------------------------------
    # 섹션 7: 액션아이템 상태 업데이트
    # ---------------------------------------------------------------------------

    st.subheader("액션아이템 상태 업데이트")
    status_cols = [
        "action_item_id", "content", "assignee", "due_date",
        "related_campaign", "confidence", "status",
    ]
    status_df = df[status_cols].copy()
    status_df["assignee"] = status_df["assignee"].fillna("미배정")
    status_df["related_campaign"] = status_df["related_campaign"].fillna("미연결")

    status_display_df = status_df.drop(columns=["action_item_id"])
    edited_status_df = st.data_editor(
        status_display_df,
        use_container_width=True,
        hide_index=True,
        column_order=[
            "content", "assignee", "due_date",
            "related_campaign", "confidence", "status",
        ],
        disabled=[
            "content", "assignee", "due_date",
            "related_campaign", "confidence",
        ],
        column_config={
            "content": st.column_config.TextColumn("내용"),
            "assignee": st.column_config.TextColumn("담당자"),
            "due_date": st.column_config.DateColumn("기한"),
            "related_campaign": st.column_config.TextColumn("캠페인"),
            "confidence": st.column_config.NumberColumn("신뢰도", format="%.2f"),
            "status": st.column_config.SelectboxColumn(
                "상태",
                options=STATUS_OPTIONS,
                required=True,
            ),
        },
        key="action_item_status_editor",
    )

    if st.button("상태 변경 저장", type="primary"):
        try:
            updated_count = _save_status_updates(status_df, edited_status_df)
            if updated_count == 0:
                st.info("변경된 상태가 없습니다.")
            elif _sync_marts_after_status_update():
                st.success(f"상태 {updated_count}건 저장 완료")
                st.cache_data.clear()
                st.rerun()
        except Exception as e:
            st.error(f"상태 저장 실패: {e}")

    # ---------------------------------------------------------------------------
    # 섹션 8: 주요 의사결정
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
    # 섹션 9: 유사 의사결정 검색
    # ---------------------------------------------------------------------------

    st.subheader("유사 의사결정 검색")
    if LLM_MODE == "mock":
        st.caption("mock 모드: 키워드 기반 토픽 임베딩으로 동작합니다. (`make seed` 데이터 필요)")
    search_query = st.text_input(
        "검색어 (예: 예산 증액, 소재 검수, 온보딩)",
        placeholder="지난 회의에서 비슷하게 결정된 내용을 검색합니다",
    )
    if st.button("검색", key="similar_search"):
        if not search_query.strip():
            st.warning("검색어를 입력하세요.")
        else:
            with st.spinner("임베딩 생성 중..."):
                similar_df = load_similar_decisions(search_query.strip())
            if similar_df.empty:
                st.info("유사한 의사결정이 없습니다. `make seed`로 시드 데이터를 먼저 적재하세요.")
            else:
                for _, row in similar_df.iterrows():
                    similarity = 1 - float(row["distance"])
                    label = row.get("meeting_title") or row["meeting_id"]
                    with st.expander(
                        f"{label} ({row.get('meeting_date', '')})  —  유사도 {similarity:.2f}",
                        expanded=True,
                    ):
                        st.markdown(f"**요약**: {row['summary']}")
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

    uploaded_file = st.file_uploader(
        "transcript JSON 또는 음성 파일",
        type=["json", "mp3", "wav", "m4a", "flac"],
    )

    if uploaded_file is not None:
        suffix = Path(uploaded_file.name).suffix.lower()
        expected_speaker_count = None
        if suffix in AUDIO_EXTENSIONS:
            speaker_count_hint = st.number_input(
                "예상 화자 수 (0=자동 추정)",
                min_value=0,
                max_value=10,
                value=3,
                step=1,
                help="테스트 mp3는 검증용 transcript 기준 화자 3명입니다. 실제 회의에서 모르면 0으로 두세요.",
            )
            expected_speaker_count = int(speaker_count_hint) or None

        file_key = f"{uploaded_file.name}:{expected_speaker_count or 'auto'}"

        if st.session_state.get("uploaded_file_name") != file_key:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb") as f:
                f.write(uploaded_file.getvalue())
                tmp_path = f.name
            try:
                if suffix in AUDIO_EXTENSIONS:
                    st.info("음성 파일 감지 — WhisperX STT + 화자 분리 실행 중... (수 분 소요)")
                    with st.status("WhisperX 처리 준비 중...", expanded=True) as audio_status:
                        audio_started_at = time.monotonic()

                        def show_audio_progress(message: str) -> None:
                            elapsed = time.monotonic() - audio_started_at
                            audio_status.update(
                                label=f"WhisperX 처리 중... ({elapsed:.1f}s)",
                                state="running",
                            )
                            st.write(f"{elapsed:.1f}s - {message}")

                        meeting = WhisperTranscriber(
                            model_size="base",
                            expected_speaker_count=expected_speaker_count,
                            progress_callback=show_audio_progress,
                        ).load(tmp_path)
                        audio_elapsed = time.monotonic() - audio_started_at
                        audio_status.update(
                            label=(
                                "WhisperX 완료: "
                                f"{len(meeting.utterances)}개 발화, "
                                f"{len(meeting.participants)}명 화자 "
                                f"({audio_elapsed:.1f}s)"
                            ),
                            state="complete",
                        )
                else:
                    meeting = FileTranscriber().load(tmp_path)

                st.session_state["uploaded_file_name"] = file_key
                st.session_state["pending_meeting"] = meeting
                speakers = sorted(set(u.speaker for u in meeting.utterances))
                st.session_state["speaker_map"] = {s: s for s in speakers}
            except Exception as e:
                st.error(f"파일 처리 오류: {e}")
                st.session_state.pop("pending_meeting", None)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

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

    st.header("Slack 알림 페이로드")
    if df.empty:
        st.info("데이터 없음")
    else:
        open_items = df[df["status"] == "open"]
        if open_items.empty:
            st.info("미완료 항목 없음")
        else:
            payload = _build_slack_payload(open_items)
            st.json(payload)

            col_a, col_b = st.columns(2)
            with col_a:
                st.download_button(
                    label="JSON 다운로드",
                    data=json.dumps(payload, ensure_ascii=False, indent=2),
                    file_name="slack_payload.json",
                    mime="application/json",
                    use_container_width=True,
                )
            with col_b:
                if SLACK_WEBHOOK_URL:
                    if st.button("Slack으로 전송", use_container_width=True, type="primary"):
                        try:
                            res = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
                            if res.status_code == 200:
                                st.success("Slack 전송 완료!")
                            else:
                                st.error(f"전송 실패: {res.status_code}")
                        except Exception as e:
                            st.error(f"전송 오류: {e}")
                else:
                    st.caption("SLACK_WEBHOOK_URL 미설정")
