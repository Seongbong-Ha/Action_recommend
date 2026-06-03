# 📋 AI 활용 내역 (AI_USAGE.md)

이 문서는 모비데이즈 AI Tech Lab 사전과제 진행 과정에서 **AI 도구를 주도적으로 제어하고 비판적으로 검토·수정한 과정**을 투명하게 기록한 문서입니다. 

> [!IMPORTANT]
> **핵심 개발 철학 (지원자의 생각의 흐름)**
> *   **비용보다 리스크 우선 (Risk over Cost)**: 단순 회의록 정리 시간 단축(비용 절감)보다 **액션아이템 누락 차단(리스크 제거)**을 파이프라인 최우선 목표로 정의했습니다.
> *   **명시적 Null 설계**: LLM의 무리한 추측(환각)을 방어하기 위해, 담당자나 기한이 흐릿할 경우 과감하게 `assignee=NULL` 및 `is_ambiguous=TRUE`로 보존하여 사람의 검수 큐로 보내는 설계가 더 안전하다고 판단했습니다.
> *   **2단 데이터 방어벽**: 신뢰할 수 없는 LLM 출력을 정제하기 위해 **적재 전(Pydantic Schema 강제 및 Retry) + 적재 후(dbt Marts 데이터 품질 테스트)**의 강력한 2단 검증망을 구축했습니다.

---

## 1. 사용한 AI 도구 및 선택 이유

| 도구 | 주요 용도 | 선택 이유 |
|---|---|---|
| **Claude Code** | 코드 생성·편집, 문서화, 파이프라인 검증 | 대화 흐름 속에서 다수 파일의 컨텍스트를 안정적으로 유지하며 파일 수정 및 터미널 검증을 끊김 없이 일괄 처리 가능 |
| **Codex** | 코드베이스 점검, 선택 가산점 구현, README·AI_USAGE 최신화, git 커밋 | 로컬 저장소의 파일·테스트·git 상태를 함께 확인하면서 요구사항 반영 여부를 검증하고, 작은 단위의 코드/문서 변경을 안전하게 적용하기 적합 |
| **Antigravity** | 계획 검토, 테스트 설계 및 코드 리뷰 | 마일스톤의 유효성, dbt 테스트 커버리지, 예외 상황 대응 등 아키텍처 관점에서의 제3자 검토자 역할 수행 |

---

## 2. 컨텍스트 제공 및 프롬프트 제어 전략

1. **컨텍스트 우선 주입**: 코드 작성 지시 전, `기획안_초안.md`와 사전과제 명세서(`과제.md`)를 먼저 학습시켜 프로젝트 전체 아키텍처와 도메인 의사결정의 일관성을 확보했습니다.
2. **비판적 에이전트 역할 부여**: 단순 코드 작성이 아니라 "설계상 보완할 엣지케이스나 누락 요소를 먼저 지적해달라"는 비판적 검토 피드백 루프를 적용했습니다.
3. **보안 및 스코프 제약**: 민감 설정이 파일에 하드코딩되지 않도록 `.env` 및 `profiles.example.yml` 파일 설계 범위를 명확히 제한했습니다.

---

## 3. AI 결과물을 비판적으로 검토하고 직접 수정한 핵심 판단 사례

아래 사례들은 AI가 생성한 결과를 그대로 수용하지 않고, 과제 요구사항·운영 맥락·보안 기준에 맞춰 직접 판단해 수정한 항목입니다.

| 구분 | AI 초안 / 제안 | 직접 수정한 판단 | 이유 |
|---|---|---|---|
| 마일스톤 현실화 | Day 1~5 형태의 이상적인 일정 제안 | 마감 시한(6/3)을 기준으로 M1 파이프라인, M2 추출, M3 대시보드 중심의 3단계 계획으로 압축 | 제한된 시간 안에서 핵심 평가 요소를 먼저 완성하기 위함 |
| 회의록 스키마 분리 | 발화 테이블에서 요약 메타데이터까지 함께 처리 | `raw_minutes`와 `mart_minutes`를 분리하고, 회의 요약과 액션아이템을 별도 생명주기로 관리 | 단일 테이블 과밀화를 피하고 재처리·확장성을 확보 |
| PostgreSQL 선택 근거 | "PostgreSQL 사용" 수준의 결론 중심 설명 | SQLite/DuckDB/PostgreSQL 비교표와 MVCC, 동시 쓰기, upsert 근거를 README에 명시 | 100명 사용 환경에서 status 업데이트가 발생하는 OLTP 워크로드를 설명하기 위함 |
| 보안 설정 | 평문 `profiles.yml` 또는 gitignore만으로 차단 | `profiles.example.yml`은 `env_var()` 기반으로 제공하고, 실제 `profiles.yml`과 `.env`는 `.gitignore`에 등록 | DB 접속 정보가 저장소에 노출되는 리스크 방지 |
| dbt 실행 안정성 | dbt 전역 옵션 순서를 잘못 둔 명령 형태 | `dbt run --project-dir ... --profiles-dir ...` 구조로 Makefile 수정 | 실제 CLI 실행 오류를 검증 과정에서 바로잡음 |
| 데이터 품질 테스트 | dbt 기본 테스트만 사용 | `dbt-utils accepted_range`로 `confidence` 0.0~1.0 범위 검증 추가 | LLM 신뢰도 값의 데이터 품질을 적재 후에도 검증 |
| 멱등 키 설계 | 자동 증가 ID 또는 단순 삽입 중심 설계 | `meeting_id + speaker + timestamp + content` 기반 `utterance_id`, `meeting_id + content` 기반 `action_item_id` 해시 사용 | 재실행 시 중복 적재를 막고 동일 입력의 동일 결과를 보장 |
| Few-shot 보강 | 명시적 R&R 예시 중심 | 암묵적 담당자, 단순 수긍 필터링, 상대적 기한, 캠페인명 추출 예시 추가 | 한국어 광고 운영 회의의 흐릿한 결정과 R&R을 안전하게 구조화 |
| 구조화 출력 강화 | JSON 출력 지시를 프롬프트에만 의존 | Gemini `response_schema` + Pydantic 검증 + 3회 재시도·폴백 구조로 변경 | 신뢰할 수 없는 LLM 출력을 검증 가능한 데이터로 만들기 위함 |
| 대시보드 우선순위 | 차트 나열 중심 구성 | 기한 초과, 담당자별 미완료, 캠페인별 미완료, 저신뢰도 드릴다운을 전면 배치 | 운영자가 "지금 누가 무엇을 해야 하는지" 바로 판단하도록 설계 |

---

## 4. 구현 단계별 AI 기여와 지원자의 직접적 기술 개입 요약

리뷰어의 효율적인 검토를 위해 마일스톤 전반에 걸친 AI의 작업 영역과 지원자의 검증 포인트를 일목요연하게 정리합니다.

| 마일스톤 / 단계 | AI 수행 및 기여 작업 | 지원자 직접 개입 및 검증 포인트 (철학 반영) |
|---|---|---|
| **M1. 수집 파이프라인**<br>*(transcriber / ingest)* | - 구/신 포맷 transcript 파싱<br>- sample_meeting.json 데이터 생성<br>- DDL 초기화 뼈대 설계 | - **raw_meetings 테이블 추가**: 회의 메타데이터 분리 설계<br>- **stg_utterances 정제 임계값 튜닝**: 단답형 의미 보존 조율<br>- **config.py 보안 정책**: `.env` 미작성 시 구동 차단 강제 |
| **M2. LLM AI 추출**<br>*(extract / dbt marts)* | - Pydantic JSON Schema 검증 모델 작성<br>- Gemini 2.5 Flash 호출 및 매핑 코드 작성<br>- dbt Marts 비정규화 모델링 | - **3회 실패 시 confidence=0 폴백 설계**: 실패 건 누락 차단<br>- **dbt-utils accepted_range 데이터 테스트 도입**: 적재 후 2차 방어<br>- **test_extract_validation.py 구축**: 12가지 엣지케이스 단위 테스트 검증망 구축 |
| **M3. Streamlit 대시보드**<br>*(app / dashboard)* | - Streamlit 레이아웃 및 4대 핵심 위젯 구현<br>- Slack Payload 템플릿 구성 | - **예외 안전성 설계**: 데이터가 없는 초기 상태에서도 앱이 깨지지 않고 업로더를 띄우도록 `df.empty` 조건문 예외 처리<br>- **BoW 불용어 사전 강화**: 광고 도메인 무의미 용어 추가 차단 |
| **선택 가산점 연동**<br>*(WhisperX / Slack)* | - WhisperX 오디오 STT + pyannote diarization 연동 뼈대 코드 구현 | - 테스트 mp3가 자동 추정 시 2명으로 병합되는 문제를 확인하고, 검증용 transcript 기준 화자 3명을 `expected_speaker_count` 힌트로 전달하도록 보완<br>- **Slack Webhook 실제 전송 UI 연동**: 전송 결과 피드백 바인딩 |
| **M4. LLM 추출 강화**<br>*(extract.py / database.py / dbt)* | - Few-shot 예시 4종 작성 (R&R 핑퐁·암묵적 담당자·단순 수긍 필터링·상대적 기한)<br>- `related_campaign` 필드 스키마·DDL·upsert·dbt mart 전 계층 반영<br>- Slack 페이로드에 confidence 레벨(🟢/🔴) 및 캠페인 정보 표시 추가 | - **암묵적 R&R 지침 설계**: 직무 맥락 기반 담당자 추론 규칙을 `_NOISE_INSTRUCTIONS`에 명문화 — AI 초안은 명시적 R&R만 처리했으나 한국 광고 조직 회의에서 직무 기반 암묵적 R&R이 빈번함을 인지하고 지침 보완을 직접 지시<br>- **related_campaign null 정책 강제**: 캠페인 미언급 시 강제 추측 금지 원칙을 few-shot 및 지침에 명시 — 없는 캠페인을 억지로 채우면 그룹핑 왜곡이 생김을 판단하여 추가 |
| **M5. 대시보드 위젯 확장**<br>*(app/dashboard.py)* | - 캠페인별 미완료 건수 bar chart (related_campaign 기준)<br>- 기한 초과 현황 경고 + 드릴다운 테이블<br>- 캠페인별 반복 이슈 키워드 분석을 meeting_title → related_campaign 기준으로 전환<br>- 메트릭 행에 기한 초과 카운트 추가 | - **위젯 선정 기준 설계**: 단순 조회 화면이 아니라 "지금 당장 누가 무엇을 해야 하는가"를 즉시 판단할 수 있는 운영 관점의 위젯 구성을 직접 정의. 기한 초과 및 캠페인별 리스크 집중화는 광고 운영 특성상 직접 누락 차단 목적으로 선정<br>- **related_campaign 기반 그룹핑 전환 판단**: 기존 meeting_title 기반 키워드 분석은 회의 단위로 묶여 캠페인 반복 패턴을 감지하지 못하는 한계를 직접 인지하고, LLM이 추출한 related_campaign 필드로 전환을 지시 |
| **M6. LLM 구조화 출력 강화**<br>*(src/extract.py / tests/)* | - `_ACTION_ITEMS_SCHEMA` / `_MINUTES_SCHEMA` Gemini API Schema 형식 dict 정의<br>- `_call_gemini(prompt, schema)` 시그니처 변경 및 `response_schema` 파라미터 적용<br>- 테스트 mock 함수 시그니처 `(prompt, schema)` 동기화 | - **보완 시점 판단**: AI가 코드 리뷰 과정에서 `response_mime_type`만으로는 스키마 강제력이 프롬프트 의존에 머문다는 점을 지적하였고, `response_schema` 적용을 직접 승인·지시<br>- **dict 직접 정의 판단**: Pydantic `model_json_schema()`가 `$defs` 구조를 생성해 Gemini API가 파싱 불가임을 확인하고, OpenAPI-like dict로 직접 정의하는 방식을 채택하도록 결정 |
| **M7. pgvector 유사 의사결정 검색 + 시연 시드 데이터**<br>*(docker-compose / database.py / embeddings.py / seed.py / extract.py / dashboard.py)* | - `docker-compose.yml`: `postgres:15` → `pgvector/pgvector:pg15` 이미지 교체<br>- `database.py`: `CREATE EXTENSION vector`, `raw_minutes.embedding vector(768)` 컬럼, HNSW 인덱스 DDL 추가<br>- `src/embeddings.py` 신규: 토픽 클러스터(예산/소재/온보딩) 기반 결정론적 mock 임베딩 모듈<br>- `src/seed.py` 신규: 2주 분량(4개 회의) 시드 데이터 + 토픽 임베딩 삽입, `make seed` 타겟 추가<br>- `config.py` / `extract.py`: `EMBEDDING_MODE=mock` 기본값과 real 실패 시 `mock_embed()` fallback 적용<br>- `dashboard.py`: 유사 의사결정 검색 섹션 추가, LLM_MODE 게이트 제거 | - **pgvector vs 인메모리 선택 근거 판단**: 과제 명세의 "100명 사용, 4주 운영" 조건을 직접 검토하고, 인메모리 numpy 방식은 수백 건 누적 시 무너진다는 점을 판단해 pgvector를 선택하도록 결정<br>- **mock 임베딩 벡터 공간 통일 설계**: seed.py(저장)와 extract.py(검색 쿼리)가 동일 벡터 공간을 공유해야 mock 모드에서 유사 검색이 실제로 동작한다는 점을 파악하고, `src/embeddings.py` 공유 모듈 분리 구조를 직접 설계 방향으로 제시<br>- **시드 토픽 클러스터 설계**: meet_seed_01(예산 사전정렬)과 meet_seed_03(성과/예산 재배분)이 동일 `_BASE_BUDGET` 벡터 근처에 위치하도록 seed 배치를 직접 설계 — "예산 증액" 검색 시 두 회의가 함께 상위 노출되는 시연 시나리오를 의도<br>- **시연 안정성 보강**: Gemini 임베딩 모델이 API 버전별로 지원 차이가 있어 real 호출이 실패할 수 있음을 확인하고, LLM real 호출과 임베딩 검색 모드를 분리해 pgvector 검색 시연이 끊기지 않도록 결정 |

---

## 5. 코드 리뷰와 품질 개선 요약

AI 리뷰는 단순 제안이 아니라 실제 실행·테스트로 검증했습니다. 대표적으로 다음 문제를 수정했습니다.

| 개선 영역 | 수정 내용 | 검증 |
|---|---|---|
| 의존성 호환성 | dbt 1.7.x와 충돌하던 `protobuf` 버전을 `<5.0.0`으로 고정 | `make run` 경로 정상화 |
| source 연결 품질 | `source_quote` 공백/부분 문자열 오매칭을 방지하고, difflib 기반 fallback을 추가 | 수동 케이스와 단위 테스트로 확인 |
| 멱등성 보존 | 재추출 시 기존 `source_utterance_id`가 NULL로 덮이지 않도록 `COALESCE` 적용 | 재실행 시 근거 링크 보존 |
| dbt lineage | `mart_action_items`가 raw를 직접 참조하지 않도록 `stg_action_items`를 추가 | dbt 모델 파싱 및 테스트 통과 |
| 대시보드 안정성 | 임시 업로드 파일 삭제, DB connection close, dbt 에러 메시지 노출 추가 | 장시간 실행·오류 상황 대응력 개선 |

현재 검증 기준은 `PATH=.venv/bin:$PATH make test`의 dbt 테스트 **20/20 PASS**, `PATH=.venv/bin:$PATH make test-unit`의 단위 테스트 **26/26 PASS**입니다.

---

## 6. Codex 기반 제출 전 최종 보강

마지막 단계에서는 Codex로 `과제.md`의 필수·선택 요구사항을 다시 대조하고, 부족한 가산점 항목과 문서 가독성을 보강했습니다.

| 보강 항목 | 수행 내용 | 판단 근거 |
|---|---|---|
| README 최신화 | 실행 방법, 테스트 개수, 실제 테이블명, 대시보드 한계 표현을 현재 코드 기준으로 정정 | 문서와 실행 결과가 어긋나면 평가자가 불필요한 의심을 가질 수 있음 |
| 4주 운영·검증 계획 | README에 주차별 목표, KPI, 운영 액션, KPI 설정 근거 추가 | 기능 구현 이후 어떤 기준으로 확대 적용할지 보여주기 위함 |
| 추출 품질 평가 코드 | `data/golden_action_items.json`, `src/evaluate.py`, `tests/test_evaluate_metrics.py`, `make evaluate` 추가 | precision / recall / F1을 샘플 golden set 기준으로 측정 가능한 구조 확보 |
| 상태 업데이트 루프 | `src/action_items.py`와 Streamlit `st.data_editor`를 추가해 `open/done/blocked` 상태 수정 및 mart 동기화 구현 | 선택 가산점 항목인 액션아이템 진행상황 업데이트 루프를 실제 운영 화면에 연결 |
| WhisperX 화자 수 보정 | `WhisperTranscriber(expected_speaker_count=3)` 옵션과 Streamlit 예상 화자 수 입력 추가 | 테스트 mp3의 실제 화자 수가 3명임을 검증용 JSON으로 알고 있으므로 pyannote 자동 추정 오류를 힌트로 보정 |
| STT timestamp 정규화 | WhisperX의 초 단위 오프셋(`"0.19"`)을 회의 날짜 기준 `timestamp`로 변환하는 적재 전처리와 단위 테스트 추가 | DB 컬럼은 `TIMESTAMP`인데 오디오 offset 문자열이 직접 들어가면 Postgres 적재가 실패하므로 테스트 중 발견한 오류를 회귀 테스트로 고정 |
| 대표 캠페인 fallback | 회의 초반 단일 캠페인명을 감지하고 STT 오타성 표현을 제한적으로 정규화해 `related_campaign`이 비어 있는 액션아이템에 보정 | 액션 발화마다 캠페인명이 반복되지 않는 실제 회의 패턴에서 전부 `미연결`로 집계되는 문제를 완화 |
| 재추출 stale 항목 정리 | 같은 회의를 재추출할 때 최신 action item ID 목록에 없는 기존 항목 삭제 | LLM 문구 변화로 이전 `related_campaign=null` 항목이 계속 대시보드에 남는 문제 방지 |
| 장시간 작업 피드백 개선 | WhisperX 처리와 파이프라인 실행에 단계별 `st.status` 로그, 경과 시간, 완료 요약 추가 | 테스트 중 사용자가 진행 여부를 판단하기 어렵다는 피드백을 반영해 평가 시연 안정성 개선 |
| 업로드 테스트 데이터 격리 | `make dashboard`와 대시보드 파이프라인 실행 시 `reset_db()`로 기존 raw/mart 데이터를 삭제한 뒤 현재 업로드 파일만 적재 | 샘플 데이터와 mp3 테스트 결과가 섞이면 검증자가 결과 출처를 혼동할 수 있어 시연 경로를 분리 |
| 원커맨드 제출 데모 정리 | `make demo`가 `run → test → evaluate → seed → dashboard`를 순서대로 실행하도록 Makefile과 README를 수정 | 평가 기준의 "하나의 명령어로 end-to-end 가능"에 맞춰 파이프라인, 품질 평가, 임베딩 검색 시드, 대시보드 확인을 한 번에 시연하기 위함 |
| Gemini 모델 설정 분리 | `GEMINI_MODEL` 환경변수를 추가해 `gemini-2.5-flash`, `gemini-3.5-flash` 등 사용 가능 모델을 코드 수정 없이 전환 | API 한도나 모델 가용성 변화가 있어도 제출 직전 설정 변경만으로 real PoC를 복구할 수 있게 하기 위함 |
| DB 스키마 설명 | README에 raw, staging, mart 레이어와 핵심 필드 설계 이유 추가 | 과제 요구사항의 데이터 스키마 설계 근거를 README에서 바로 확인 가능하게 함 |

`make evaluate`는 샘플 golden set 기준 precision 1.00, recall 1.00, F1 1.00으로 실행되었지만, 이 수치는 단일 회의 회귀 검증 결과입니다. 일반 성능으로 과장하지 않기 위해 README에는 4주 운영 1주차에 golden set을 5~10건으로 확장하는 계획을 함께 명시했습니다. 상태 업데이트는 `raw_action_items.status`에 저장하고, LLM 재추출 upsert가 `status`를 덮어쓰지 않는 기존 설계와 연결했습니다.

---

## 7. AI 도움 없이 전적으로 지원자가 직접 설계한 철학적 영역

*   **비용 vs 리스크의 가치 판단**: 회의 요약 시간 단축보다 **액션아이템 누락 차단**이 광고주 마케팅 일정을 수호하는 핵심 리스크 제어 영역임을 재정의했습니다.
*   **is_ambiguous 메타 필드 설계**: LLM에게 책임을 묻고 억지 담당자를 뽑게 만드는 대신, 애매한 R&R은 `is_ambiguous=true`로 표시하여 대시보드 검수 큐로 모이도록 설계했습니다. 이는 기술 오류에 대처하는 **인간 협업(Human-in-the-loop) 아키텍처**를 독창적으로 적용한 사례입니다.
*   **STT 확장 3단계 로드맵 구축**: `BaseTranscriber` 추상 인터페이스를 사전에 설계하여 JSON 업로드(Step 1) → 로컬 오디오 STT(Step 2) → 실시간 마이크(Step 3)까지 코어 엔진 변경 없이 연결 가능한 **확장성 높은 인터페이스 지향 아키텍처**를 구상했습니다.
