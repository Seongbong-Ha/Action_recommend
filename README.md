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
| **Database** | PostgreSQL (Docker Compose) | 사내 약 100명 사용 환경의 동시 쓰기 상황(액션아이템 상태 업데이트) 대응을 위해 MVCC 및 upsert를 지원하는 유일한 선택지. (SQLite/DuckDB 단점 극복) |
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

## 📂 디렉토리 구조

```
Action_recommend/
├── Makefile                    # 파이프라인 setup, run, test, dashboard 일괄 제어 오케스트레이터
├── README.md                   # 시스템 및 프롬프트 설계 사상 안내서
├── AI_USAGE.md                 # AI 협업 내역 및 지원자 직접 개입 판단 사례서
├── docker-compose.yml          # PostgreSQL 환경 구성 (.env 보안 변수 바인딩)
├── requirements.txt            # 기본 코어 의존성 (requests, pytest 포함)
├── requirements-whisperx.txt   # WhisperX STT 확장 설치 전용 의존성
├── tests/
│   └── test_extract_validation.py  # LLM 신뢰화 핵심 로직 유효성 단위 테스트 (12개)
├── src/
│   ├── config.py               # 환경 변수, DB URI, LLM_MODE 관리
│   ├── database.py             # raw DDL 초기화 및 커넥션 풀링
│   ├── transcriber.py          # 구/신 JSON 로더 및 WhisperX STT 어댑터
│   ├── ingest.py               # 원천 데이터 적재 및 멱등 해시 생성
│   └── extract.py              # LLM 추출, 3회 재시도-폴백 루프 및 Pydantic 바인딩
├── dbt_project/
│   ├── dbt_project.yml         # dbt 프로젝트 설정
│   ├── profiles.example.yml    # env_var 기반 안전 프로필 양식
│   └── models/
│       ├── staging/            # 화자 정규화, 5글자 이하 단독 잡음 및 중복 제거 레이어
│       └── marts/              # 비정규화 조인 마트 및 dbt-utils 범위 테스트 레이어
└── app/
    └── dashboard.py            # Streamlit 대시보드 (위젯 7종 + Slack 전송 사이드바)
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
    *   `make test`: 20개의 dbt 데이터 품질 및 무결성 테스트 동작.
    *   `make test-unit`: Pydantic 및 재시도-폴백 로직 유효성 단위 테스트 12개 구동.
    *   `make dashboard`: Streamlit 대시보드 웹 구동.

> [!TIP]
> `python` 또는 `dbt` 명령을 찾지 못하는 환경에서는 가상환경을 활성화한 뒤 실행하세요. 비활성 셸에서 검증할 경우 `PATH=.venv/bin:$PATH make run`처럼 `.venv/bin`을 PATH 앞에 붙여도 동일하게 동작합니다.

---

## 🎯 프롬프트 설계 철학 및 엔지니어링 근거

`src/extract.py`에 구현된 프롬프트는 단순 지시를 넘어 **비결정적인 LLM 출력을 결정적인 정형 데이터로 변환**하기 위해 3대 원칙 하에 설계되었습니다.

1. **도메인 컨텍스트 주입 (`_DOMAIN_CONTEXT`)**
   * SA, DA, ROAS, CPM 등 광고 마케팅 약어 사전을 주입하여 LLM이 도메인 약어를 잡음으로 오해해 환각을 내는 현상을 예방했습니다.
2. **암묵적 R&R의 안전한 구조화 (`_NOISE_INSTRUCTIONS` & `_FEW_SHOT` 4종)**
   * 한국어 회의 특유의 4가지 패턴을 few-shot으로 커버했습니다: ① **R&R 핑퐁** (최종 명시적 확인 발화자를 assignee로 매핑), ② **직무 맥락 기반 암묵적 담당자 추론** ("제가 DA 성과 분석 담당이니까"처럼 직무·역할로 자신이 담당임을 암묵적으로 밝히는 케이스), ③ **단순 수긍 필터링** ("네, 맞습니다" 등 확인·동의 발화는 액션아이템 아님), ④ **상대적 기한 처리** ("이번 주 금요일"은 `due_is_inferred=true` 표시).
   * **(핵심 철학)**: 담당자가 모호할 경우 억지로 가짜 담당자를 조작하는 대신 `assignee=NULL` 및 `is_ambiguous=TRUE`로 보존하여 대시보드 검수 테이블로 모이게 설계했습니다.
3. **`related_campaign` 필드로 캠페인 단위 추적**
   * 발화에서 언급된 캠페인명(구글 SA, 카카오 DA, 네이버 SA 등)을 LLM이 직접 추출해 `related_campaign` 컬럼에 저장합니다. 언급이 없으면 `null`로 설정하여 강제 추측을 방지합니다.
   * 이 필드를 대시보드의 캠페인별 미완료 건수 및 반복 이슈 키워드 위젯에서 그룹핑 기준으로 활용합니다.
4. **3중 구조화 출력 보장 및 3회 피드백 재시도**
   * **1차 (모델 레벨)**: Gemini `GenerationConfig`에 `response_schema` 파라미터를 직접 주입해, 모델이 토큰을 생성하는 시점에 JSON 스키마를 강제합니다. 이 단계에서 구조 불일치를 원천 차단합니다.
   * **2차 (파싱 레벨)**: `json.loads` 이후 Pydantic `model_validate()`로 타입, `confidence` 범위(0.0~1.0), 필수 필드 누락을 재검증합니다. 두 레이어가 독립적으로 작동하여 어느 한쪽이 뚫려도 나머지가 막습니다.
   * 에러 발생 시 `error_hint`를 다음 프롬프트에 `[이전 시도 오류 — 반드시 수정]` 섹션으로 동봉해 최대 3회 재시도하고, 최종 실패 시 `confidence=0.0`, `is_ambiguous=TRUE` 폴백으로 검수 테이블에 보존합니다.

---

## 📊 대시보드 위젯 설계 근거

Streamlit 대시보드는 단순 데이터 열람을 넘어 **"지금 당장 누가 무엇을 해야 하는가"를 운영자가 즉각 판단할 수 있도록** 7개 위젯을 설계했습니다.

| 위젯 | 구현 근거 |
|---|---|
| **상태 요약 메트릭** (전체 / Open / Done / Blocked / **기한 초과**) | 랜딩 즉시 전체 현황을 숫자로 파악. 기한 초과 카운트를 별도 강조해 즉각 액션이 필요한 규모를 명시 |
| **회의·액션아이템 발생 추이** | 현재 PoC는 `meeting_date` 기준 날짜별 액션아이템 생성 건수를 표시합니다. 다중 회의 적재 시 주차 단위 집계로 확장 가능한 구조입니다. |
| **담당자별 미완료 Top N** | 특정 인원에 업무가 편중되는 현상을 조기 감지하여 선제적 R&R 재배분을 유도. 광고 운영 조직에서 특정 AE에 미완료가 집중되면 캠페인 지연 리스크가 직결됨 |
| **캠페인별 미완료 건수** | LLM이 발화에서 추출한 `related_campaign` 필드를 기준으로 집계. 특정 캠페인(구글 SA, 카카오 DA 등)에 미완료가 집중될 경우 해당 광고주 대응이 늦어지는 리스크를 가시화 |
| **캠페인별 반복 이슈 키워드** | `related_campaign` 기준으로 BoW 키워드를 집계하여 동일 캠페인에서 반복적으로 등장하는 문제 패턴(소재, 예산, 검수 등)을 탐지. 광고주 차원 분석은 광고주 식별 컬럼 추가 시 같은 집계 방식으로 확장 가능 |
| **LLM 신뢰도 분포 + 저신뢰도 드릴다운** | confidence 히스토그램으로 LLM 추출 품질을 모니터링. `confidence < 0.7` 항목을 드릴다운 테이블로 노출해 human-in-the-loop 검수 큐 역할을 수행 |
| **기한 초과 현황** | `status=open` 이고 `due_date < 오늘`인 항목을 경고와 함께 테이블로 표시. 누락 위험이 가장 높은 항목을 우선순위화하여 운영자 즉각 대응 유도 |

---

## 📈 검증 완료 내역

*   **통합 파이프라인**: `PATH=.venv/bin:$PATH make run` 구동 시 DB 초기화 → ingest → dbt staging → LLM extract → dbt marts 전체 흐름 완료.
*   **dbt 데이터 품질 테스트**: `PATH=.venv/bin:$PATH make test` 구동 시 stg_utterances, stg_action_items, mart_action_items, mart_minutes의 무결성 테스트 **20/20 PASS**.
*   **LLM 신뢰화 단위 테스트**: `PATH=.venv/bin:$PATH make test-unit` 구동 시 Pydantic 경계값, nullability 보존, `related_campaign` 필드 검증, 3회 시도 실패 시 강제 폴백 및 2회차 성공 조기 차단 등 **12/12 PASS**.

> [!NOTE]
> **의존성 호환성 참고**: dbt-core 1.7.x는 `protobuf<5.0.0`을 요구합니다. `requirements.txt`에 버전 핀이 명시되어 있으므로 `make setup` 실행 시 자동으로 올바른 버전이 설치됩니다.

---

## 💡 가정 사항 (Assumptions)

*   **STT 대체 경로**: 외부 SaaS로 음성 유출이 금지된 보안 원칙을 완벽히 방어하고자, GUI에서 업로드된 음성은 로컬 내에서 WhisperX를 이용해 전 처리됩니다.
*   **Real 모드 멱등성 한계**: mock 모드는 완전한 멱등성을 보장하나, real 모드에서 LLM이 동일 발화를 다르게 파싱할 경우 중복이 생길 수 있음을 인지하고 있습니다. 실 환경에서는 `source_utterance_id` 기준의 DB unique 제약조건 고도화를 대안으로 고려하고 있으며 PoC 한계로 이를 README에 기재했습니다.
*   **단일 회의 한계**: 현재 PoC는 1건 회의 기준으로 기동되며 대시보드는 날짜별 추이를 표시합니다. 다중 회의 적재 후 주차별 집계 컬럼을 추가하면 주간 운영 추이 분석으로 확장 가능합니다.
