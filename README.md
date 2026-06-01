# Action Recommend — 회의 액션아이템 자동 추출 PoC

모비데이즈 AI Tech Lab 사전과제.  
회의 transcript → 액션아이템 자동 추출 → 분석 대시보드까지 이어지는 end-to-end 파이프라인.

---

## 기술 스택 및 선정 이유

| 영역 | 선택 | 선정 이유 |
|---|---|---|
| **Database** | PostgreSQL (Docker Compose) | 아래 비교표 참고 |
| **Data Transformation** | dbt-core + dbt-utils | SQL 변환 단계에서 `ref()` 기반 자동 lineage와 `schema.yml` 선언 테스트를 제공. 별도 품질 검증 로직 없이 `dbt test` 한 번으로 적재 후 데이터 품질을 보증. |
| **LLM** | Gemini API + Mock 토글 (`LLM_MODE`) | 실제 호출만 쓰면 재현성·레이트리밋 리스크 있음. Mock 고정 출력을 기본값으로 두어 멱등성을 보장하고, 환경변수 하나로 실제 호출로 전환 가능하게 설계. |
| **Validation** | Pydantic v2 | LLM 출력의 환각·포맷 붕괴를 적재 전에 차단. 스키마 위반 시 재시도 루프를 돌고, 그래도 실패하면 `confidence=0`으로 검수 큐로 보내는 2단 방어선의 첫 번째 관문. |
| **STT** | Transcript JSON 직접 사용 (Transcriber 인터페이스) | 외부 API 유출 금지 원칙 + 시간 제약. STT를 `BaseTranscriber` 추상 인터페이스 뒤에 두어 추후 Whisper/마이크 실시간 입력으로 교체 비용을 최소화. |
| **Dashboard** | Streamlit | Python 단일 스택 유지. 별도 BI 서버 없이 코드로 위젯·드릴다운을 자유롭게 구성 가능. |

### Database 선정 근거 — SQLite vs DuckDB vs PostgreSQL

**각 후보 비교**

| 항목 | SQLite | DuckDB | PostgreSQL |
|---|---|---|---|
| **아키텍처** | 파일 기반, 서버리스 | 파일 기반, 서버리스 | 클라이언트-서버 |
| **주 용도** | 단일 앱 로컬 저장 | 분석(OLAP), 배치 집계 | 트랜잭션(OLTP) + 분석 혼합 |
| **동시 쓰기** | WAL 모드에서도 단일 writer | 멀티 프로세스 동시 쓰기 미지원 | MVCC 기반 다중 동시 쓰기 지원 |
| **Upsert 지원** | `INSERT OR REPLACE` (부분적) | `INSERT OR REPLACE` (부분적) | `ON CONFLICT DO UPDATE` (완전 지원) |
| **JSONB 지원** | 미지원 (TEXT 저장) | JSON 지원 (인덱싱 제한) | JSONB 네이티브 지원 + 인덱싱 |
| **Production 이관** | 별도 마이그레이션 필수 | 별도 마이그레이션 필수 | PoC → Production 동일 엔진 |
| **설치 비용** | 없음 (Python 내장) | 없음 (pip 설치) | Docker Compose 필요 |

**PostgreSQL을 선택한 이유**

이 PoC의 도입 가정은 **사내 100명 동시 사용**이다. 핵심 시나리오는 여러 담당자가 동시에 자신의 액션아이템 `status`를 `open → done`으로 업데이트하는 상황인데, 이때 **동시 쓰기 충돌**이 발생한다.

- **SQLite**: WAL 모드에서도 write는 직렬화된다. 동시 사용자가 늘수록 병목이 생기며, production 서버 환경에 사용하는 DB가 아니다.
- **DuckDB**: OLAP(분석 집계)에 특화되어 읽기 성능은 탁월하지만, 멀티 프로세스 동시 쓰기를 공식 지원하지 않는다. 액션아이템 업데이트처럼 빈번한 단건 OLTP 쓰기에는 부적합하다.
- **PostgreSQL**: MVCC(다중 버전 동시성 제어)로 동시 쓰기를 안전하게 처리한다. `ON CONFLICT (action_item_id) DO UPDATE` 구문으로 파이프라인 재실행 시 멱등성을 선언적으로 확보할 수 있고, `decisions` 필드를 JSONB로 네이티브 저장·인덱싱할 수 있다. 무엇보다 **PoC와 production 타깃 엔진을 일치**시킴으로써, 추후 실제 도입 시 마이그레이션 리스크가 없다.

> Docker Compose 셋업 비용이 유일한 단점이나, 단일 컨테이너로 구성해 이를 최소화했다.

---

## 아키텍처 흐름

```
[입력 소스]
  FileTranscriber (JSON)          ← 현재 지원 (구 포맷 / 신 포맷 자동 감지)
  WhisperTranscriber (mp3)        ← Step 2 예정
  MicTranscriber (마이크 실시간)   ← Step 3 예정
        ↓ Meeting 객체
  → ① ingest.py          raw_utterances (Postgres, 불변)
  → ② dbt staging        stg_utterances (화자 정규화, 잡음 제거)
  → ③ extract.py + LLM   action_items_raw / raw_minutes (pydantic 검증 + upsert)
  → ④ dbt marts + test   mart_action_items / mart_minutes
  → ⑤ Streamlit          대시보드 (위젯 4종) / Slack JSON 페이로드
```

- **Python**: 추출·적재(EL) + LLM 로직
- **dbt**: SQL 변환(T) + 데이터 품질 테스트
- **Transcriber 인터페이스**: 입력 소스를 파이프라인과 분리 — JSON·음성파일·마이크를 동일한 `Meeting` 객체로 추상화

---

## 디렉토리 구조

```
Action_recommend/
├── Makefile                    # 파이프라인 전체 실행 오케스트레이터
├── README.md
├── AI_USAGE.md                 # AI 도구 활용 내역
├── docker-compose.yml          # PostgreSQL 컨테이너 구성
├── requirements.txt
├── data/
│   └── sample_meeting.json     # 광고 미디어 도메인 샘플 회의 (16발화, 구 포맷)
├── src/
│   ├── config.py               # 환경 변수, DB URI, LLM_MODE 관리
│   ├── database.py             # DDL 초기화 (raw 테이블 4종)
│   ├── transcriber.py          # BaseTranscriber 추상 인터페이스 + FileTranscriber (구/신 포맷 자동 감지)
│   ├── ingest.py               # EL: transcript → raw_utterances
│   └── extract.py              # LLM 추출 + pydantic 검증 → action_items_raw / raw_minutes
├── dbt_project/
│   ├── dbt_project.yml
│   ├── packages.yml            # dbt-utils 의존성
│   ├── profiles.yml            # DB 연결 프로필 (.gitignore 차단)
│   └── models/
│       ├── staging/
│       │   ├── schema.yml
│       │   └── stg_utterances.sql
│       └── marts/
│           ├── schema.yml      # dbt-utils accepted_range 테스트 포함
│           ├── mart_action_items.sql
│           └── mart_minutes.sql
└── app/
    └── dashboard.py            # Streamlit 대시보드 (위젯 4종 + Slack 사이드바)
```

---

## 실행 방법

### 사전 준비

```bash
# 1. 환경변수 설정
cp .env.example .env          # POSTGRES_USER, POSTGRES_PASSWORD, GEMINI_API_KEY 입력
cp dbt_project/profiles.example.yml dbt_project/profiles.yml

# 2. Postgres 컨테이너 실행 + 패키지 설치
make setup
```

### 파이프라인 실행

```bash
# 파이프라인 실행 + 대시보드 자동 시작 (권장)
make demo

# 개별 실행
make run        # DB초기화 → ingest → dbt staging → extract → dbt marts
make test       # dbt test 16개
make dashboard  # Streamlit 대시보드만 실행
```

### LLM 실제 호출 (Gemini 2.5 Flash)

`.env` 파일에 `LLM_MODE=real`, `GEMINI_API_KEY`를 설정한 뒤:

```bash
make demo
```

---

## 대시보드 구성

**메인 화면 (위젯 4종 + 요약)**

| # | 섹션 | 내용 |
|---|---|---|
| - | 상태 요약 | 전체 / Open / Done / Blocked 메트릭 카드 |
| 1 | **회의·액션아이템 발생 추이** | 날짜별 액션아이템 건수 바차트 |
| 2 | **담당자별 미완료 Top 5** | status=open 필터 + 담당자별 건수 내림차순 바차트 |
| 3 | **캠페인/광고주별 반복 이슈 키워드** | BoW 방식 키워드 빈도 바차트 (회의별) |
| 4 | **LLM 신뢰도 분포 + 드릴다운** | confidence 히스토그램 + 저신뢰도 항목 테이블 |
| - | **주요 의사결정** | 회의별 요약 + 결정사항 expander |

**사이드바**

| 섹션 | 내용 |
|---|---|
| **새 회의 업로드** | JSON 업로드 → 화자 이름 수정 → 파이프라인 실행 버튼 |
| **Slack 알림 페이로드** | 미완료 항목 JSON 미리보기 + 다운로드 |

업로드 흐름:
```
JSON 파일 업로드
  → 발화자 자동 감지 (이름 수정 가능)
  → 파이프라인 실행 버튼
  → st.status() 5단계 진행 표시
     ① DB 초기화 → ② ingest → ③ dbt staging → ④ LLM 추출 → ⑤ dbt marts
  → 결과 화면 자동 갱신
```

---

## 설계 원칙

1. **LLM 출력을 신뢰 가능한 자산으로** — structured output + pydantic 검증 + `confidence` / `source_utterance_id` / `is_ambiguous` 3개 필드로 추출 근거를 데이터에 동봉
2. **모든 단계가 재실행에 안전** — 해시 기반 ID + `ON CONFLICT` upsert로 멱등성 확보
3. **원천 데이터는 외부로 나가지 않음** — STT 포함 모든 처리가 로컬 경계 안에서 완결

---

## 프롬프트 설계 근거

`src/extract.py`의 `_build_action_items_prompt()` 구현 기반.

### 도메인 컨텍스트 주입 (`_DOMAIN_CONTEXT`)
SA·DA·CPM·ROAS·A/B 테스트·CTA·소재·세팅 등 광고 마케팅 약어 사전을 프롬프트에 직접 주입. LLM이 도메인 용어를 일반 의미로 오해하는 환각을 사전 차단.

### 잡음 처리 지침 (`_NOISE_INSTRUCTIONS`)
- "알겠습니다", "네, 맞습니다" 등 단순 수긍 발화는 액션아이템 제외
- R&R 핑퐁 구간에서는 **최종 명시적 확인 발화**를 assignee 근거로 사용
- 담당자 불명확 시 추측 금지 → `assignee=null + is_ambiguous=true` 강제
- 기한 미명시 시 → `due_date=null`, 상대 표현("이번 주") → `due_is_inferred=true`

### few-shot 예시 (`_FEW_SHOT`)
R&R이 3인 대화에서 핑퐁되다가 C가 최종 확인하는 예시를 제공.  
`assignee=C`, `source_quote=C의 발화`로 추출하는 패턴을 LLM에 학습시킴.

### 스키마 강제 + 검증·재시도
1. pydantic `ActionItemSchema`로 LLM 출력 검증 (confidence 범위, 필수 필드)
2. 스키마 위반 시 `error_hint`를 프롬프트에 포함해 최대 3회 재시도
3. 최종 실패 시 `confidence=0 + is_ambiguous=true` 항목으로 검수 큐에 보존 (누락 방지)

---

## 가정 사항

- **STT 대체**: 외부 SaaS API로 원천 데이터 전송이 금지되어 제공 transcript JSON을 그대로 사용. `BaseTranscriber` 인터페이스로 추후 로컬 Whisper 교체 비용 최소화.
- **단일 회의 PoC**: 주차별 추이·반복 키워드 위젯은 현재 1건 데이터라 단조롭지만, 다회의 적재 시 즉시 의미 있는 차트로 동작하는 구조로 설계.
- **멱등성**: `hash(meeting_id + normalize(content))` 기반 PK + `ON CONFLICT DO UPDATE` — 파이프라인 재실행 시 중복 적재 없음.
- **LLM_MODE=mock 기본값**: `GEMINI_API_KEY` 없이도 전체 파이프라인 동작. `LLM_MODE=real` 설정 시 Gemini 2.5 Flash 실제 호출.
- **화자 역할 정보**: 현재 파이프라인은 화자 이름만 사용. 역할(팀장/마케터 등)은 프롬프트 도메인 컨텍스트로 처리하며, DB 스키마 확장 없이 대응 가능.

---

## 입력 포맷 지원

`FileTranscriber`는 두 가지 JSON 포맷을 자동 감지합니다.

**구 포맷** (`utterances` 키 기반)
```json
{
  "meeting_id": "meet_001",
  "title": "주간 미디어 운영 회의",
  "date": "2026-06-01",
  "participants": ["홍길동", "김민지"],
  "utterances": [
    {"speaker": "홍길동", "content": "...", "timestamp": "2026-06-01T10:00:00Z"}
  ]
}
```

**신 포맷** (`segments` 키 기반 — STT 출력 형식)
```json
{
  "language": "ko",
  "speakers": [{"name": "수아", "role": "퍼포먼스 마케터"}],
  "segments": [
    {"id": 1, "line_no": 1, "speaker": "수아", "role": "...", "text": "..."}
  ]
}
```

신 포맷은 `meeting_id`를 파일명 해시로 자동 생성합니다.

---

## 향후 확장 로드맵 (STT)

```
Step 1  ✅ FileTranscriber — JSON 파일 (구/신 포맷 자동 감지)
Step 2  🔲 WhisperTranscriber — mp3/wav 음성 파일 → 로컬 Whisper STT
Step 3  🔲 MicTranscriber — 마이크 실시간 녹음 → Whisper → 파이프라인
```

`BaseTranscriber` 인터페이스를 구현하면 새 입력 소스를 추가해도 파이프라인 코드는 변경 불필요.

---

## 검증 결과

`make run` + `make test` 전체 실행 결과:

```
dbt test: 16/16 PASS
  - stg_utterances: unique, not_null (4개)
  - mart_action_items: unique, not_null, accepted_range(confidence), accepted_values(status) (6개)
  - mart_minutes: unique, not_null (3개)
  - sources: 3개
```
