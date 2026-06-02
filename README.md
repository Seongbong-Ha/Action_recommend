# 🎬 Action Recommend — 회의 액션아이템 자동 추출 PoC

모비데이즈 AI Tech Lab 사전과제 제출물입니다.  
회의 transcript 분석 → 액션아이템 자동 추출 및 검증 → 분석 대시보드 및 Slack 알림까지 이어지는 **End-to-End 데이터·AI 파이프라인**을 구축했습니다.

**빠른 확인 경로**: `make setup`으로 환경을 준비한 뒤 `make run`으로 파이프라인을 실행하고, `make dashboard`로 결과를 확인합니다. `python`/`dbt` 명령을 찾지 못하는 환경에서는 먼저 `source .venv/bin/activate`를 실행하세요.

> [!IMPORTANT]
> **핵심 설계 철학 (Core Engineering Philosophies)**
> 1. **비용보다 리스크 우선 (Risk over Cost)**: 단순 회의록 정리 시간 단축보다 **액션아이템 누락 차단(리스크 해결)**을 최우선 목표로 둡니다. 흐릿하게 결정된 안건을 임의로 폐기하거나 환각으로 채우는 대신 `is_ambiguous=TRUE` 플래그 및 `assignee=NULL` 형태로 보존하여 인간 검수 큐로 보내는 **명시적 Null 설계**를 구축했습니다.
> 2. **2단 데이터 품질 보증망**: 신뢰성이 낮은 LLM 출력을 DB 적재 전 **Pydantic 스키마 검증 및 피드백 기반 3회 재시도-폴백** 단계에서 1차로 필터링하고, 적재 후 **dbt-core + dbt-utils 데이터 정합성 테스트**로 2차 검증하는 강력한 방어망을 구성했습니다.
> 3. **철저한 멱등성(Idempotency) 보장**: 해시 기반 고유 식별자(`action_item_id`, `utterance_id`)를 강제하여 파이프라인을 몇 번이고 재실행해도 중복이나 깨짐이 없는 안전성을 보장합니다.

---

## 🛠️ 기술 스택 및 선정 이유

| 영역 | 선택 | 선정 이유 |
|---|---|---|
| **Database** | PostgreSQL + pgvector (Docker Compose) | 사내 약 100명 사용 환경의 동시 쓰기 상황(액션아이템 상태 업데이트) 대응을 위해 MVCC 및 upsert를 지원하는 유일한 선택지. pgvector 확장으로 임베딩 유사 검색까지 동일 DB에서 처리. (SQLite/DuckDB 단점 극복) |
| **Data Transformation** | dbt-core + dbt-utils | `ref()` 기반 자동 lineage 구조 제공 및 `schema.yml` 선언형 데이터 테스트를 통한 적재 후 2차 품질 보증 확보. |
| **LLM** | Gemini API + Mock 토글 (`LLM_MODE`) | 멱등성과 무중단 검증을 위해 Mock 고정 출력을 기본값으로 보장하며, 환경변수 전환으로 무료 티어 Gemini 2.5 Flash 호출 실 PoC 가능. |
| **Validation** | Pydantic v2 | LLM 출력의 포맷 붕괴 및 유효 한계값 이탈을 적재 전 단계에서 원천 차단. |
| **STT / Audio** | 제공 JSON 사용 (WhisperX 연동) | 원천 데이터의 외부 SaaS 유출 금지 보안 원칙 준수. `BaseTranscriber` 추상 인터페이스를 도입해 추후 로컬 Whisper 모듈 교체 비용 최소화. |
| **Dashboard** | Streamlit | Python 단일 스택을 유지하며 코드로 풍부한 위젯·드릴다운 화면을 빠르게 구성. |

### 📊 데이터베이스 비교 및 PostgreSQL 선택 근거

| 항목 | SQLite | DuckDB | PostgreSQL (선택) |
|---|---|---|---|
| **아키텍처** | 파일 기반, 서버리스 | 파일 기반, 서버리스 | 클라이언트-서버 |
| **동시 쓰기** | WAL 모드에서도 단일 writer (병목) | 멀티 프로세스 동시 쓰기 미지원 | **MVCC 기반 다중 동시 쓰기 완벽 지원** |
| **Upsert 지원** | 제한적 (`INSERT OR REPLACE`) | 제한적 (`INSERT OR REPLACE`) | **`ON CONFLICT DO UPDATE` 완전 지원** |
| **JSONB 지원** | 미지원 (TEXT 적재) | JSON 지원 (인덱싱 제한) | **JSONB 네이티브 지원 및 인덱싱** |
| **선정이유** | 사내 100명 다중 동시 트래킹 환경에서 SQLite/DuckDB는 쓰기 락 충돌 우려가 큼. **Postgres**는 MVCC 기반 동시성 제어 및 강력한 upsert를 지원하여 PoC 단계와 향후 실 운영 환경의 데이터 마이그레이션 장벽을 없애는 최적의 선택지입니다. |

---

## 🌐 아키텍처 및 데이터 흐름

```
[입력 소스]
  - FileTranscriber (JSON 구/신 포맷 감지)    ← 기본 검증 경로
  - WhisperTranscriber (mp3/wav)             ← 가산점 경로 (WhisperX STT + pyannote)
        ↓ Meeting 객체화 (화자 이름 보정 적용)
  → ① ingest.py          raw_meetings / raw_utterances (Postgres 무가공 적재)
  → ② dbt staging        stg_utterances (화자 직급 정규화, 잡음 발화 및 중복 제거)
  → ③ extract.py + LLM   raw_action_items / raw_minutes (pydantic 적재 전 검증 + 3회 재시도)
  → ④ dbt marts + test   mart_action_items / mart_minutes (비정규화 마트 생성 + dbt test 20개 검증)
  → ⑤ Streamlit          대시보드 시각화 / Slack Incoming Webhook (Block Kit 페이로드 전송)
```

**모듈 책임 분리 기준**: API 호출 및 파싱, LLM 비즈니스 로직(AI 추출 및 Pydantic 1차 검증)은 **Python**이 담당하고, 정형 데이터 변환 및 데이터셋 결합, 최종 품질 검증(dbt test)은 **dbt**가 책임집니다. "Python이 무엇을 추출할지 결정하고, dbt가 추출된 데이터의 결함 여부를 보증"합니다.

---

## 🧱 데이터베이스 스키마 설계

스키마는 **원천 보존(raw) → 정제(staging) → 분석·분배(mart)** 3단계로 나눴습니다. raw 테이블은 Python에서 직접 적재하고, staging/mart는 dbt 모델로 관리합니다. 이렇게 나눈 이유는 원본 transcript를 언제든 재처리할 수 있게 보존하면서도, 대시보드와 Slack은 조인 부담 없이 mart 테이블만 읽도록 하기 위해서입니다.

| 레이어 | 테이블 / 모델 | 역할 | 설계 이유 |
|---|---|---|---|
| raw | `raw_meetings` | 회의 메타데이터 저장 (`meeting_id`, 제목, 날짜, 참가자) | 회의 단위 재처리·추적의 기준점. 참가자 목록은 구조 변화가 쉬워 `JSONB`로 보존 |
| raw | `raw_utterances` | 화자별 원천 발화 저장 | STT/transcript 원본을 불변에 가깝게 보존해 LLM 추출 실패 시 재처리 가능 |
| raw | `raw_action_items` | LLM 추출 액션아이템 저장 | `action_item_id` 해시 키와 `ON CONFLICT` upsert로 멱등성 확보. `confidence`, `source_quote`, `is_ambiguous`로 검수 가능성 보장 |
| raw | `raw_minutes` | 회의 요약과 결정사항 저장. `embedding vector(768)` 컬럼 포함 | 회의록 요약은 액션아이템과 생명주기가 달라 별도 테이블로 분리. pgvector HNSW 인덱스로 코사인 유사도 검색 지원 |
| staging | `stg_utterances`, `stg_action_items` | 화자 정규화, 짧은 잡음 발화 제거, 중복 제거, raw pass-through | raw 원본을 건드리지 않고 분석 전 정제 규칙을 dbt lineage 안에서 관리 |
| mart | `mart_action_items`, `mart_minutes` | 대시보드·Slack·평가 CLI용 최종 조회 테이블 | 회의 제목·날짜를 비정규화해 운영 화면이 단일 테이블 중심으로 빠르게 읽도록 설계 |

`raw_action_items`의 핵심 필드는 다음 기준으로 정의했습니다.

| 필드 | 목적 |
|---|---|
| `action_item_id` | `meeting_id + 정규화된 content` 기반 해시. 재실행 시 중복 생성 방지 |
| `assignee`, `due_date`, `status` | 담당자·기한·진행상태를 운영 추적 단위로 관리. `status`는 재추출 시 덮어쓰지 않아 사용자 변경값 보존 |
| `confidence` | LLM 추출 신뢰도. 낮은 값은 대시보드 검수 큐로 이동 |
| `source_utterance_id`, `source_quote` | 추출 근거를 원 발화와 연결해 환각 여부를 확인 |
| `is_ambiguous`, `due_is_inferred` | 한국어 회의의 흐릿한 R&R과 상대적 기한을 버리지 않고 검수 대상으로 보존 |
| `related_campaign` | 캠페인별 미완료 현황과 반복 이슈 키워드 분석의 그룹핑 기준 |

---

## 📂 디렉토리 구조

```
Action_recommend/
├── Makefile                    # 파이프라인 setup, run, test, dashboard 일괄 제어 오케스트레이터
├── README.md                   # 시스템 및 프롬프트 설계 사상 안내서
├── AI_USAGE.md                 # AI 협업 내역 및 지원자 직접 개입 판단 사례서
├── docker-compose.yml          # PostgreSQL 환경 구성 (.env 보안 변수 바인딩)
├── requirements.txt            # 기본 코어 의존성 (requests, pytest 포함)
├── requirements-whisperx.txt   # WhisperX STT 확장 설치 전용 의존성
├── data/
│   └── golden_action_items.json # 추출 품질 평가용 수동 정답셋
├── tests/
│   ├── test_extract_validation.py  # LLM 신뢰화 핵심 로직 유효성 단위 테스트 (12개)
│   ├── test_action_items.py        # status 값 검증 테스트
│   └── test_evaluate_metrics.py    # precision/recall/F1 계산 로직 테스트
├── src/
│   ├── action_items.py          # 액션아이템 status 업데이트 도메인 함수
│   ├── config.py               # 환경 변수, DB URI, LLM_MODE 관리
│   ├── database.py             # raw DDL 초기화 (pgvector extension, HNSW 인덱스 포함)
│   ├── transcriber.py          # 구/신 JSON 로더 및 WhisperX STT 어댑터
│   ├── ingest.py               # 원천 데이터 적재 및 멱등 해시 생성
│   ├── extract.py              # LLM 추출, 3회 재시도-폴백 루프 및 Pydantic 바인딩
│   ├── embeddings.py           # 토픽 클러스터 mock 임베딩 (예산/소재/온보딩) — real 모드는 Gemini
│   ├── seed.py                 # 시연용 시드 데이터 적재 (4개 회의 + mock 임베딩)
│   └── evaluate.py             # golden set 기반 추출 품질 평가 CLI
├── dbt_project/
│   ├── dbt_project.yml         # dbt 프로젝트 설정
│   ├── profiles.example.yml    # env_var 기반 안전 프로필 양식
│   └── models/
│       ├── staging/            # 화자 정규화, 5글자 이하 단독 잡음 및 중복 제거 레이어
│       └── marts/              # 비정규화 조인 마트 및 dbt-utils 범위 테스트 레이어
└── app/
    └── dashboard.py            # Streamlit 대시보드 (위젯 8종 + Slack 전송 사이드바)
```

---

## 🚀 실행 방법

### 1. 사전 준비 (설정 구축)

```bash
# 가상환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate

# 환경 변수 복사 및 필수 설정 정보(GEMINI_API_KEY 등) 기입
cp .env.example .env

# dbt 보안 접속 프로필 템플릿 복사
cp dbt_project/profiles.example.yml dbt_project/profiles.yml

# Postgres 컨테이너 기동 + 패키지 설치 + dbt packages(dbt-utils) 종속성 일괄 다운로드
make setup
```

### 2. 파이프라인 통합 데모 실행

```bash
# 전체 파이프라인(ingest → dbt staging → extract → dbt marts)을 일괄 실행하고 대시보드를 즉시 가동합니다.
make demo
```

*   **개별 제어 스크립트**:
    *   `make run`: 전체 ETL 데이터 파이프라인 순차 구동 및 동기화.
    *   `make seed`: 2주 분량(4개 회의) 시연용 시드 데이터 및 토픽 임베딩 적재. DB 초기화 후 유사 검색 시연에 필요한 기준 데이터를 빠르게 복원.
    *   `make test`: 20개의 dbt 데이터 품질 및 무결성 테스트 동작.
    *   `make test-unit`: Pydantic, 재시도-폴백, status 검증, STT 화자 수·timestamp 정규화, 대표 캠페인 fallback, 평가 지표 계산 로직 단위 테스트 26개 구동.
    *   `make evaluate`: `data/golden_action_items.json` 기준 precision / recall / F1 및 필드 정확도 계산.
    *   `make reset-data`: raw/mart 테이블 데이터를 비워 테스트 시작 상태로 초기화.
    *   `make dashboard`: 기존 raw/mart 데이터를 비운 뒤 Streamlit 대시보드 웹 구동.

> [!TIP]
> `python` 또는 `dbt` 명령을 찾지 못하는 환경에서는 가상환경을 활성화한 뒤 실행하세요. 비활성 셸에서 검증할 경우 `PATH=.venv/bin:$PATH make run`처럼 `.venv/bin`을 PATH 앞에 붙여도 동일하게 동작합니다.

---

## 🎙️ WhisperX STT + 화자 분리 검증 경로

`test_data/ko_meeting_3speakers_4min_faster.mp3`는 로컬 STT 테스트용 음성이고, `test_data/ko_meeting_3speakers.json`은 같은 회의의 검증용 transcript입니다. 검증용 JSON 기준 화자는 `수아`, `지훈`, `채린` 3명입니다.

WhisperX/pyannote diarization은 자동 추정만 사용할 경우 짧은 발화나 비슷한 음색을 병합해 2명으로 감지할 수 있습니다. 이를 보완하기 위해 `WhisperTranscriber`는 `expected_speaker_count` 옵션을 지원하고, Streamlit 음성 업로드 UI에서는 **예상 화자 수 기본값을 3명**으로 제공합니다. 실제 회의에서 화자 수를 모르면 `0`으로 설정해 자동 추정을 사용할 수 있습니다.

```bash
pip install -r requirements-whisperx.txt
# .env에 HUGGINGFACE_TOKEN 설정 후
PATH=.venv/bin:$PATH make dashboard
```

대시보드 사이드바에서 mp3 파일을 업로드하면 다음 순서로 처리됩니다.

1. WhisperX로 한국어 음성 인식
2. WhisperX align 모델로 단어 정렬
3. pyannote diarization에 `min_speakers=max_speakers=3` 힌트 전달
4. 감지된 speaker label을 사용자가 `수아/지훈/채린` 등 실제 이름으로 보정
5. 동일한 ingest → dbt staging → LLM extract → dbt marts 파이프라인 실행

WhisperX와 파이프라인 실행은 모두 Streamlit `st.status`로 단계별 진행 로그와 소요 시간을 표시합니다. 장시간 걸리는 구간이 있더라도 모델 로드, 음성 인식, 단어 정렬, 화자 분리, dbt 실행, LLM 추출 중 어느 단계인지 화면에서 확인할 수 있습니다.

`make dashboard` 또는 대시보드에서 업로드 파일로 `파이프라인 실행`을 누르면 기존 raw/mart 데이터(`raw_meetings`, `raw_utterances`, `raw_action_items`, `raw_minutes`, `mart_action_items`, `mart_minutes`)를 먼저 비운 뒤 현재 업로드한 회의만 적재합니다. 따라서 샘플 데이터와 직접 테스트한 mp3 결과가 섞이지 않습니다. 반대로 `make run`과 `make demo`는 제출 데모 확인을 위한 `data/sample_meeting.json` 샘플 적재 경로로 남겨두었습니다.

---

## 🎯 프롬프트 설계 철학 및 엔지니어링 근거

`src/extract.py`에 구현된 프롬프트는 단순 지시를 넘어 **비결정적인 LLM 출력을 결정적인 정형 데이터로 변환**하기 위해 3대 원칙 하에 설계되었습니다.

1. **도메인 컨텍스트 주입 (`_DOMAIN_CONTEXT`)**
   * SA, DA, ROAS, CPM 등 광고 마케팅 약어 사전을 주입하여 LLM이 도메인 약어를 잡음으로 오해해 환각을 내는 현상을 예방했습니다.
2. **암묵적 R&R의 안전한 구조화 (`_NOISE_INSTRUCTIONS` & `_FEW_SHOT` 4종)**
   * 한국어 회의 특유의 4가지 패턴을 few-shot으로 커버했습니다: ① **R&R 핑퐁** (최종 명시적 확인 발화자를 assignee로 매핑), ② **직무 맥락 기반 암묵적 담당자 추론** ("제가 DA 성과 분석 담당이니까"처럼 직무·역할로 자신이 담당임을 암묵적으로 밝히는 케이스), ③ **단순 수긍 필터링** ("네, 맞습니다" 등 확인·동의 발화는 액션아이템 아님), ④ **상대적 기한 처리** ("이번 주 금요일"은 `due_is_inferred=true` 표시).
   * **(핵심 철학)**: 담당자가 모호할 경우 억지로 가짜 담당자를 조작하는 대신 `assignee=NULL` 및 `is_ambiguous=TRUE`로 보존하여 대시보드 검수 테이블로 모이게 설계했습니다.
3. **`related_campaign` 필드로 캠페인 단위 추적**
   * 발화에서 언급된 캠페인명(구글 SA, 카카오 DA, 네이버 SA 등)을 LLM이 직접 추출해 `related_campaign` 컬럼에 저장합니다.
   * 액션아이템 발화에는 캠페인명이 없지만 회의 초반 5개 발화 안에 단일 대표 캠페인(예: `노바드림 다음달 캠페인`)이 명확히 등장하면, 해당 값을 `related_campaign` fallback으로 채웁니다. STT가 `다음달`을 `다음 빨`처럼 잘못 받아쓴 경우도 제한적으로 정규화하며, 여러 캠페인 후보가 있으면 강제 추측하지 않고 `null`로 둡니다.
   * 이 필드를 대시보드의 캠페인별 미완료 건수 및 반복 이슈 키워드 위젯에서 그룹핑 기준으로 활용합니다.
4. **3중 구조화 출력 보장 및 3회 피드백 재시도**
   * **1차 (모델 레벨)**: Gemini `GenerationConfig`에 `response_schema` 파라미터를 직접 주입해, 모델이 토큰을 생성하는 시점에 JSON 스키마를 강제합니다. 이 단계에서 구조 불일치를 원천 차단합니다.
   * **2차 (파싱 레벨)**: `json.loads` 이후 Pydantic `model_validate()`로 타입, `confidence` 범위(0.0~1.0), 필수 필드 누락을 재검증합니다. 두 레이어가 독립적으로 작동하여 어느 한쪽이 뚫려도 나머지가 막습니다.
   * 에러 발생 시 `error_hint`를 다음 프롬프트에 `[이전 시도 오류 — 반드시 수정]` 섹션으로 동봉해 최대 3회 재시도하고, 최종 실패 시 `confidence=0.0`, `is_ambiguous=TRUE` 폴백으로 검수 테이블에 보존합니다.

---

## 📊 대시보드 위젯 설계 근거

Streamlit 대시보드는 단순 데이터 열람을 넘어 **"지금 당장 누가 무엇을 해야 하는가"를 운영자가 즉각 판단할 수 있도록** 8개 위젯을 설계했습니다.

| 위젯 | 구현 근거 |
|---|---|
| **상태 요약 메트릭** (전체 / Open / Done / Blocked / **기한 초과**) | 랜딩 즉시 전체 현황을 숫자로 파악. 기한 초과 카운트를 별도 강조해 즉각 액션이 필요한 규모를 명시 |
| **회의·액션아이템 발생 추이** | 현재 PoC는 `meeting_date` 기준 날짜별 액션아이템 생성 건수를 표시합니다. 다중 회의 적재 시 주차 단위 집계로 확장 가능한 구조입니다. |
| **담당자별 미완료 Top N** | 특정 인원에 업무가 편중되는 현상을 조기 감지하여 선제적 R&R 재배분을 유도. 광고 운영 조직에서 특정 AE에 미완료가 집중되면 캠페인 지연 리스크가 직결됨 |
| **캠페인별 미완료 건수** | LLM이 발화에서 추출한 `related_campaign`과 회의 초반 대표 캠페인 fallback을 기준으로 집계. 특정 캠페인(구글 SA, 카카오 DA, 노바드림 다음달 캠페인 등)에 미완료가 집중될 경우 해당 광고주 대응이 늦어지는 리스크를 가시화 |
| **캠페인별 반복 이슈 키워드** | `related_campaign` 기준으로 BoW 키워드를 집계하여 동일 캠페인에서 반복적으로 등장하는 문제 패턴(소재, 예산, 검수 등)을 탐지. 광고주 차원 분석은 광고주 식별 컬럼 추가 시 같은 집계 방식으로 확장 가능 |
| **LLM 신뢰도 분포 + 저신뢰도 드릴다운** | confidence 히스토그램으로 LLM 추출 품질을 모니터링. `confidence < 0.7` 항목을 드릴다운 테이블로 노출해 human-in-the-loop 검수 큐 역할을 수행 |
| **기한 초과 현황** | `status=open` 이고 `due_date < 오늘`인 항목을 경고와 함께 테이블로 표시. 누락 위험이 가장 높은 항목을 우선순위화하여 운영자 즉각 대응 유도 |
| **액션아이템 상태 업데이트** | `st.data_editor`에서 `open/done/blocked` 상태만 수정 가능. 저장 시 `raw_action_items.status`를 업데이트하고 dbt marts를 재빌드해 대시보드와 Slack 산출물 기준을 동기화 |
| **유사 의사결정 검색** | 검색어를 임베딩(mock: 토픽 클러스터, real: Gemini)으로 변환해 pgvector `<=>` 코사인 거리로 과거 회의 TOP-5 반환. `make seed` 시드 데이터 적재 후 mock 모드에서도 즉시 시연 가능 |

---

## 📈 검증 완료 내역

*   **통합 파이프라인**: `PATH=.venv/bin:$PATH make run` 구동 시 DB 초기화 → 샘플 ingest → dbt staging → LLM extract → dbt marts 전체 흐름 완료.
*   **업로드 기반 테스트 격리**: `make dashboard`와 대시보드의 `파이프라인 실행`은 기존 raw/mart 데이터를 삭제한 뒤 현재 업로드한 회의만 처리하도록 구성해 샘플 데이터와 테스트 결과가 섞이지 않음.
*   **dbt 데이터 품질 테스트**: `PATH=.venv/bin:$PATH make test` 구동 시 stg_utterances, stg_action_items, mart_action_items, mart_minutes의 무결성 테스트 **20/20 PASS**.
*   **LLM 신뢰화 및 평가 단위 테스트**: `PATH=.venv/bin:$PATH make test-unit` 구동 시 Pydantic 경계값, nullability 보존, `related_campaign` 필드 및 대표 캠페인 fallback 검증, 3회 시도 실패 시 강제 폴백, 2회차 성공 조기 차단, status 검증, STT 화자 수 힌트 및 timestamp 정규화 검증, precision/recall/F1 계산 로직 등 **26/26 PASS**.

### 추출 품질 평가

`make evaluate`는 `data/golden_action_items.json`의 수동 정답셋과 `mart_action_items`의 최종 추출 결과를 비교합니다. 단순 문자열 완전 일치가 아니라 `content` 유사도 0.75 이상을 같은 액션아이템으로 매칭해 PoC 단계의 표현 차이를 허용합니다.

```bash
PATH=.venv/bin:$PATH make evaluate
```

평가 결과는 액션아이템 탐지 품질과 구조화 필드 품질을 분리해 출력합니다.

| 지표 | 의미 |
|---|---|
| `precision` / `recall` / `F1` | golden set 대비 액션아이템 탐지 성능 |
| `assignee_accuracy` | 매칭된 액션아이템 중 담당자 일치율 |
| `due_date_accuracy` | 매칭된 액션아이템 중 기한 일치율 |
| `campaign_accuracy` | 매칭된 액션아이템 중 캠페인명 일치율 |
| `source_quote_match_rate` | 근거 발화 인용이 golden set과 연결되는 비율 |
| `low_confidence_ratio` | 추출 결과 중 human review 대상(`confidence < 0.7`) 비율 |

현재 golden set은 샘플 회의 1건 기준의 회귀 검증 도구입니다. 4주 운영 계획의 1주차에는 회의 5~10건으로 golden set을 확장해 지표의 대표성을 높이는 것을 목표로 둡니다.

현재 샘플 데이터 기준 실행 결과는 다음과 같습니다.

```text
precision: 1.00
recall:    1.00
f1:        1.00
tp/fp/fn:  4/0/0
assignee_accuracy:       1.00
due_date_accuracy:       0.75
campaign_accuracy:       1.00
source_quote_match_rate: 1.00
low_confidence_ratio:    0.00
```

> [!NOTE]
> **의존성 호환성 참고**: dbt-core 1.7.x는 `protobuf<5.0.0`을 요구합니다. `requirements.txt`에 버전 핀이 명시되어 있으므로 `make setup` 실행 시 자동으로 올바른 버전이 설치됩니다.

---

## 🗓️ 4주 운영·검증 계획

PoC 도입 후 4주는 기능 확장보다 **추출 품질, 검수 부담, 액션아이템 누락 감소**를 수치로 확인하는 기간으로 둡니다. 운영자는 대시보드의 저신뢰도 드릴다운과 기한 초과 현황을 매주 검수하고, 그 결과를 다음 프롬프트·스키마 개선에 반영합니다.

| 주차 | 목표 | 확인 지표 | 운영 액션 |
|---|---|---|---|
| 1주차 | 기준선 수집 및 수동 검수 체계 확립 | 회의당 추출 액션아이템 수, `confidence < 0.7` 비율, `is_ambiguous=true` 비율 | 샘플 회의 5~10건을 수동 라벨링하여 golden set 생성. 누락/오탐 유형을 R&R 모호, 기한 모호, 단순 수긍 오탐으로 분류 |
| 2주차 | 추출 품질 1차 개선 | precision, recall, F1, source_quote 매칭률 | 1주차 오류 유형을 few-shot과 도메인 지침에 반영. `source_quote`가 원 발화와 연결되지 않는 케이스를 별도 점검 |
| 3주차 | 운영 부담과 상태 추적 검증 | 담당자별 미완료 Top N, 기한 초과 건수, 저신뢰도 검수 소요 시간 | 담당자가 실제로 확인해야 하는 항목을 우선순위화. `open/done/blocked` 상태 업데이트 루프 도입 여부 판단 |
| 4주차 | 도입 효과 판단 | 회의 후 정리 시간, 액션아이템 누락률, 저신뢰도 재검수 비율, 사용자 피드백 | Before/After를 비교해 확대 적용 여부 결정. 목표 미달 시 STT 품질, 프롬프트, 스키마, human review 기준 중 병목을 분리 |

**초기 성공 기준**

*   수동 golden set 기준 action item recall 0.85 이상.
*   낮은 신뢰도(`confidence < 0.7`) 항목의 human review 완료율 95% 이상.
*   회의 후 정리·이관 시간 30~60분에서 10~15분 수준으로 감소.
*   `source_quote` 또는 `source_utterance_id`로 근거를 확인할 수 없는 항목 5% 이하.

**KPI 설정 근거**

*   **Recall 0.85 이상**: 본 PoC의 1순위 목표는 시간 단축보다 액션아이템 누락 방지입니다. 완전 자동화를 목표로 하는 것이 아니라 human review를 전제로 하므로, 1차 추출 단계에서 실제 액션아이템의 85% 이상을 검수 큐에 올리면 남은 15%는 저신뢰도·모호 항목 리뷰와 주간 샘플링으로 보완 가능한 수준으로 봤습니다. 반대로 recall이 0.8 미만이면 운영자가 여전히 회의록 전체를 다시 읽어야 하므로 자동화 효과가 약합니다.
*   **Human review 완료율 95% 이상**: `confidence < 0.7` 또는 `is_ambiguous=true` 항목은 시스템이 스스로 불확실성을 표시한 케이스입니다. 이 큐가 방치되면 "누락을 플래그로 보존한다"는 설계가 실제 운영 효과로 이어지지 않으므로, 근무일 기준 대부분의 검수 대상이 처리되는 95%를 최소 운영 기준으로 잡았습니다.
*   **정리·이관 시간 10~15분**: 과제 배경의 회의 후 수기 정리 시간은 30~60분입니다. 자동 초안 생성 후 사람은 저신뢰도 항목 검수, 담당자·기한 확인, Slack 공유만 수행한다고 가정하면 기존 대비 약 70% 이상 단축된 10~15분이 현실적인 PoC 목표입니다.
*   **근거 연결 실패율 5% 이하**: LLM 추출 결과가 `source_quote` 또는 `source_utterance_id`로 원 발화에 연결되지 않으면 검수자가 환각 여부를 판단하기 어렵습니다. 근거 연결 실패가 5%를 넘으면 신뢰도 점수와 별개로 운영자가 수동 확인해야 하는 부담이 커지므로, 추적 가능성을 보장하기 위한 품질 하한으로 설정했습니다.

---

## 💡 가정 사항 (Assumptions)

*   **STT 대체 경로**: 외부 SaaS로 음성 유출이 금지된 보안 원칙을 완벽히 방어하고자, GUI에서 업로드된 음성은 로컬 내에서 WhisperX를 이용해 전 처리됩니다.
*   **Real 모드 멱등성 한계**: mock 모드는 완전한 멱등성을 보장하나, real 모드에서 LLM이 동일 발화를 다르게 파싱할 경우 중복이 생길 수 있음을 인지하고 있습니다. 실 환경에서는 `source_utterance_id` 기준의 DB unique 제약조건 고도화를 대안으로 고려하고 있으며 PoC 한계로 이를 README에 기재했습니다.
*   **단일 회의 한계**: 현재 PoC는 1건 회의 기준으로 기동되며 대시보드는 날짜별 추이를 표시합니다. 다중 회의 적재 후 주차별 집계 컬럼을 추가하면 주간 운영 추이 분석으로 확장 가능합니다.
