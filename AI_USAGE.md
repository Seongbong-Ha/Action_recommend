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
| **Antigravity** | 계획 검토, 테스트 설계 및 코드 리뷰 | 마일스톤의 유효성, dbt 테스트 커버리지, 예외 상황 대응 등 아키텍처 관점에서의 제3자 검토자 역할 수행 |

---

## 2. 컨텍스트 제공 및 프롬프트 제어 전략

1. **컨텍스트 우선 주입**: 코드 작성 지시 전, `기획안_초안.md`와 사전과제 명세서(`과제.md`)를 먼저 학습시켜 프로젝트 전체 아키텍처와 도메인 의사결정의 일관성을 확보했습니다.
2. **비판적 에이전트 역할 부여**: 단순 코드 작성이 아니라 "설계상 보완할 엣지케이스나 누락 요소를 먼저 지적해달라"는 비판적 검토 피드백 루프를 적용했습니다.
3. **보안 및 스코프 제약**: 민감 설정이 파일에 하드코딩되지 않도록 `.env` 및 `profiles.example.yml` 파일 설계 범위를 명확히 제한했습니다.

---

## 3. AI 결과물을 비판적으로 검토하고 직접 수정한 판단 사례 (7종)

### 💡 사례 1 — plan.md 마일스톤 현실화 및 우선순위 재정렬
* **AI 초안**: 이상적인 순서에 따라 Day 1~5 구조로 여유롭게 마일스톤을 쪼개어 제안했습니다.
* **직접 수정**: 마감 시한(6/3) 및 우선순위를 고려하여 3단계 마일스톤으로 통합하고, 핵심 파이프라인(M1~M2)을 선배치한 후 Streamlit 대시보드(M3)를 마감 당일 일정으로 타이트하게 압축 조정했습니다.
* **수정 이유**: AI는 비즈니스 마감의 제약 조건을 실제 인간처럼 압박감 있게 반영하지 못하므로, 한정된 리소스에서 최선의 퀄리티를 보장하기 위한 리스크 관리를 직접 조율했습니다.

### 💡 사례 2 — mart_minutes 설계 보완 (회의록과 메타데이터 분리)
* **AI 제안**: `stg_utterances`에서 회의 메타데이터를 조인해 요약본을 적재하도록 가이드했습니다.
* **직접 수정**: 발화(Utterances) 테이블과 회의록(Minutes) 테이블의 물리적인 책임을 분리하고, `extract.py`에서 LLM 요약 시 메타데이터를 바인딩하여 `raw_minutes` -> `mart_minutes`로 변환 및 조인하도록 다차원 스키마를 신설했습니다.
* **수정 이유**: 단일 테이블에 너무 많은 책임을 지우는 것은 결합도를 높여 멱등성 및 확장성을 해치기 때문에, 단일 책임 원칙(SRP)에 근거하여 DB 스키마 구조를 정규화 레이어로 수정했습니다.

### 💡 사례 3 — DB 비교 검증 표 및 Postgres 당위성 명문화
* **AI 초안**: README 파일에 단순히 "PostgreSQL을 사용했다"며 결론 중심의 한 줄 텍스트만 서술했습니다.
* **직접 수정**: SQLite와 DuckDB의 장단점을 명확히 대조하는 기술 비교표를 설계하도록 지시하고, 사내 100명 사용 환경에서의 동시 쓰기(OLTP WAL 락 이슈)를 해결하기 위한 MVCC(다중 버전 동시성 제어) 필요성을 PostgreSQL 선정 근거로 강하게 피력했습니다.
* **수정 이유**: 기술의 '선택'보다 '왜 다른 선택지를 버렸는지'를 대조해 주는 것이 설계 의사결정의 기술력을 평가자에게 강력하게 전달하기 때문입니다.

### 💡 사례 4 — profiles.yml env_var 보안 처리 및 예제 분리 (2차 수정)
* **AI 초안**: DB 비밀번호가 평문으로 들어간 `profiles.yml`을 레포 안에 그대로 두고 `.gitignore` 차단만 제안했습니다.
* **직접 수정**: `profiles.yml` 내의 호스트, 유저, 패스워드를 dbt `env_var()` 기반으로 전면 수정하여 하드코딩을 완전히 거세하고, 온보딩 가이드용 `profiles.example.yml`을 신설한 후 `.gitignore`에 원본 파일을 이중 잠금 처리했습니다.
* **수정 이유**: 협업 환경이나 CI/CD 배포 시 파일이 유출되더라도 계정 정보가 평문 노출되는 사고를 원천 방어하기 위해 프로덕션 레벨의 보안 정책을 강제했습니다.

### 💡 사례 5 — Makefile dbt CLI 전역 옵션 순서 버그 수정
* **AI 초안**: `DBT` 변수에 전역 플래그를 결합하여 `dbt --profiles-dir ./dbt_project run` 형태로 선언했습니다.
* **직접 수정**: dbt CLI의 인자 순서 요구 조건에 맞추어 `dbt run --profiles-dir ./dbt_project` 구조로 옵션을 명령 뒤쪽으로 명시 이동시켰습니다.
* **수정 이유**: AI는 툴의 세부 버전별 CLI 인풋 정합성을 놓치고 빌드 오류를 낼 수 있으므로, 실제 런타임 검증을 통해 발생한 `No such option` 오류를 식별하고 직접 바로잡았습니다.

### 💡 사례 6 — dbt-utils 의존성 누락 발견 및 데이터 검증 강화
* **AI 초안**: dbt 기본 내장 테스트만 사용하여 `confidence` (0.0 ~ 1.0) 범위를 텍스트 유효성 검사 수준으로 처리하려 했습니다.
* **직접 수정**: `packages.yml`에 `dbt-utils` 라이브러리를 추가하여 `accepted_range` 테스트를 명시하고, `make setup` 시 `dbt deps` 패키지 설치 단계가 유기적으로 실행되도록 Makefile에 포함시켰습니다.
* **수정 이유**: 부동소수점의 상한/하한 경계 검증은 내장 테스트로 불가능하므로 패키지 종속성을 초기에 완벽하게 구축하여 파이프라인 적재 후 데이터 정합성을 철저히 지켰습니다.

### 💡 사례 7 — utterance_id의 멱등적 자연 키(Natural Key) 강제
* **AI 초안**: 발화 고유 식별자(`utterance_id`)를 데이터베이스 `SERIAL` 자동 증가 값으로 설계하려 했습니다.
* **직접 수정**: SERIAL 키는 재실행 시 무조건 중복 적재를 유발해 멱등성을 깨뜨리므로, `meeting_id + speaker + timestamp + content`를 해싱한 SHA-256 기반 문자열 고유 키를 정의하여 `ON CONFLICT DO NOTHING`으로 적재를 멱등화했습니다.
* **수정 이유**: 파이프라인의 핵심은 "몇 번을 재실행해도 DB에 중복 유입이 없고 동일 결과가 보장되어야 한다"는 멱등성 원칙이기 때문입니다.

### 💡 사례 8 — LLM Few-shot 설계: 광고 도메인 암묵적 R&R 케이스 추가
* **AI 초안**: few-shot 예시가 명시적 R&R 핑퐁 1종만 존재하여 한국어 광고 운영 회의의 다양한 패턴을 커버하지 못했습니다.
* **직접 수정**: ① 직무 맥락 기반 암묵적 담당자 추론, ② 단순 수긍 필터링(빈 배열 반환), ③ 상대적 기한 + `related_campaign` 추출 케이스를 직접 시나리오 설계하여 few-shot을 4종으로 확장했습니다.
* **수정 이유**: 광고 대행사 운영 회의에서 "제가 DA 성과 분석 담당이니까"처럼 직무 맥락으로 R&R이 암묵적으로 결정되는 패턴이 빈번함을 알고 있었습니다. 이 케이스를 few-shot 없이 LLM에 위임하면 할루시네이션으로 잘못된 assignee가 배정되거나 누락될 위험이 있어 직접 설계를 지시했습니다.

### 💡 사례 10 — Gemini `response_schema` 적용: 모델 레벨 JSON 스키마 강제
* **AI 초안 검토**: `GenerationConfig`에 `response_mime_type="application/json"`만 사용하고 JSON 구조는 프롬프트 텍스트로만 명시했습니다. 이 방식은 LLM이 프롬프트를 따르지 않아 스키마가 무너질 경우 Pydantic 레이어까지 오류가 도달하는 단일 방어 구조였습니다.
* **직접 수정 지시**: 구조화 출력 보장을 프롬프트 의존에서 모델 레벨로 격상하도록 지시했습니다. `_ACTION_ITEMS_SCHEMA`와 `_MINUTES_SCHEMA`를 Gemini API Schema 형식(OpenAPI-like dict)으로 직접 정의하고 `response_schema` 파라미터로 주입하는 방식을 채택했습니다.
* **수정 이유**: Pydantic `model_json_schema()`는 `$defs`/`$ref`를 생성하여 Gemini API가 파싱하지 못하는 구조여서 dict 직접 정의가 불가피했습니다. 이 변경으로 모델 생성 단계(1차)와 Pydantic 파싱 단계(2차)가 독립적으로 작동하는 진정한 2중 방어 구조가 완성되었습니다.

### 💡 사례 9 — 대시보드 위젯 설계: 운영 관점 재정의
* **AI 초안**: 기본 위젯(추이·담당자별 Top N·confidence 분포)을 동일한 비중으로 나열했습니다.
* **직접 수정**: "지금 당장 누가 무엇을 해야 하는가"를 즉시 판단하는 운영 관점에서 **기한 초과 현황** 및 **캠페인별 미완료 건수** 위젯을 신설하고, 캠페인별 키워드 분석의 그룹핑 기준을 `meeting_title`에서 `related_campaign`으로 전환하도록 지시했습니다.
* **수정 이유**: 광고 운영에서 캠페인 단위 미완료 누적과 기한 초과는 광고주 대응 지연으로 직결되는 리스크입니다. AI는 데이터가 있으면 모두 보여주는 방향으로 설계하는 경향이 있어, 실제 운영자가 가장 먼저 확인해야 할 정보를 앞에 배치하는 우선순위 재설계를 직접 수행했습니다.

---

## 4. 구현 단계별 AI 기여와 지원자의 직접적 기술 개입 요약

리뷰어의 효율적인 검토를 위해 마일스톤 전반에 걸친 AI의 작업 영역과 지원자의 검증 포인트를 일목요연하게 정리합니다.

| 마일스톤 / 단계 | AI 수행 및 기여 작업 | 지원자 직접 개입 및 검증 포인트 (철학 반영) |
|---|---|---|
| **M1. 수집 파이프라인**<br>*(transcriber / ingest)* | - 구/신 포맷 transcript 파싱<br>- sample_meeting.json 데이터 생성<br>- DDL 초기화 뼈대 설계 | - **raw_meetings 테이블 추가**: 회의 메타데이터 분리 설계<br>- **stg_utterances 정제 임계값 튜닝**: 단답형 의미 보존 조율<br>- **config.py 보안 정책**: `.env` 미작성 시 구동 차단 강제 |
| **M2. LLM AI 추출**<br>*(extract / dbt marts)* | - Pydantic JSON Schema 검증 모델 작성<br>- Gemini 2.5 Flash 호출 및 매핑 코드 작성<br>- dbt Marts 비정규화 모델링 | - **3회 실패 시 confidence=0 폴백 설계**: 실패 건 누락 차단<br>- **dbt-utils accepted_range 데이터 테스트 도입**: 적재 후 2차 방어<br>- **test_extract_validation.py 구축**: 10가지 엣지케이스 단위 테스트 검증망 구축 |
| **M3. Streamlit 대시보드**<br>*(app / dashboard)* | - Streamlit 레이아웃 및 4대 핵심 위젯 구현<br>- Slack Payload 템플릿 구성 | - **예외 안전성 설계**: 데이터가 없는 초기 상태에서도 앱이 깨지지 않고 업로더를 띄우도록 `df.empty` 조건문 예외 처리<br>- **BoW 불용어 사전 강화**: 광고 도메인 무의미 용어 추가 차단 |
| **선택 가산점 연동**<br>*(WhisperX / Slack)* | - WhisperX 오디오 STT + pyannote diarization 연동 뼈대 코드 구현 | - **WhisperX 3.8.6 CLI 버그 패치**: pyannote 인증 관련 토큰 누락 디버깅<br>- **Slack Webhook 실제 전송 UI 연동**: 전송 결과 피드백 바인딩 |
| **M4. LLM 추출 강화**<br>*(extract.py / database.py / dbt)* | - Few-shot 예시 4종 작성 (R&R 핑퐁·암묵적 담당자·단순 수긍 필터링·상대적 기한)<br>- `related_campaign` 필드 스키마·DDL·upsert·dbt mart 전 계층 반영<br>- Slack 페이로드에 confidence 레벨(🟢/🔴) 및 캠페인 정보 표시 추가 | - **암묵적 R&R 지침 설계**: 직무 맥락 기반 담당자 추론 규칙을 `_NOISE_INSTRUCTIONS`에 명문화 — AI 초안은 명시적 R&R만 처리했으나 한국 광고 조직 회의에서 직무 기반 암묵적 R&R이 빈번함을 인지하고 지침 보완을 직접 지시<br>- **related_campaign null 정책 강제**: 캠페인 미언급 시 강제 추측 금지 원칙을 few-shot 및 지침에 명시 — 없는 캠페인을 억지로 채우면 그룹핑 왜곡이 생김을 판단하여 추가 |
| **M5. 대시보드 위젯 확장**<br>*(app/dashboard.py)* | - 캠페인별 미완료 건수 bar chart (related_campaign 기준)<br>- 기한 초과 현황 경고 + 드릴다운 테이블<br>- 캠페인별 반복 이슈 키워드 분석을 meeting_title → related_campaign 기준으로 전환<br>- 메트릭 행에 기한 초과 카운트 추가 | - **위젯 선정 기준 설계**: 단순 조회 화면이 아니라 "지금 당장 누가 무엇을 해야 하는가"를 즉시 판단할 수 있는 운영 관점의 위젯 구성을 직접 정의. 기한 초과 및 캠페인별 리스크 집중화는 광고 운영 특성상 직접 누락 차단 목적으로 선정<br>- **related_campaign 기반 그룹핑 전환 판단**: 기존 meeting_title 기반 키워드 분석은 회의 단위로 묶여 캠페인 반복 패턴을 감지하지 못하는 한계를 직접 인지하고, LLM이 추출한 related_campaign 필드로 전환을 지시 |
| **M6. LLM 구조화 출력 강화**<br>*(src/extract.py / tests/)* | - `_ACTION_ITEMS_SCHEMA` / `_MINUTES_SCHEMA` Gemini API Schema 형식 dict 정의<br>- `_call_gemini(prompt, schema)` 시그니처 변경 및 `response_schema` 파라미터 적용<br>- 테스트 mock 함수 시그니처 `(prompt, schema)` 동기화 | - **보완 시점 판단**: AI가 코드 리뷰 과정에서 `response_mime_type`만으로는 스키마 강제력이 프롬프트 의존에 머문다는 점을 지적하였고, `response_schema` 적용을 직접 승인·지시<br>- **dict 직접 정의 판단**: Pydantic `model_json_schema()`가 `$defs` 구조를 생성해 Gemini API가 파싱 불가임을 확인하고, OpenAPI-like dict로 직접 정의하는 방식을 채택하도록 결정 |

---

### 💡 사례 11 — 코드베이스 시니어 리뷰 후 품질 개선 (Phase 2 리팩토링)
* **AI 리뷰 수행 항목**: ① `protobuf==6.33.6`이 dbt 1.7.x와 비호환(MessageToJson 인자 제거)되어 `make run`이 dbt marts 단계에서 항상 중단되는 버그 발견 → `requirements.txt`에 `protobuf>=4.0.0,<5.0.0` 핀 추가; ② `ingest.py`의 `_utterance_id`가 `timestamp=None`일 때 `"None"` 문자열을 해시에 포함시키는 버그 → 빈 문자열로 정규화; ③ `_match_utterance_id`가 LLM이 발화를 재표현하면 NULL을 반환하는 문제 → 정규화(소문자·공백 제거) 2차 매칭 및 difflib 유사도 0.6 기반 fallback 추가; ④ mock의 confidence 값이 0.82~0.95에 몰려 드릴다운 위젯이 "저신뢰도 항목 없음"만 표시되는 문제 → confidence=0.42 테스트 케이스 1건 추가; ⑤ few-shot에 "지시형 발화(팀장이 제3자에게 업무 지시)" 패턴이 없어 LLM이 이를 처리하지 못할 수 있는 문제 → 예시 5 추가; ⑥ `extract.py` `_load_stg_utterances`의 `ORDER BY timestamp`에 `NULLS LAST` 명시적 추가.
* **직접 개입 판단**: protobuf 버전 다운그레이드 후 google-generativeai·streamlit 호환성 확인 필요 → 패키지 임포트 테스트로 직접 검증. opentelemetry-proto dependency conflict는 streamlit 실행에 영향 없음을 확인하고 수용 판단.
* **수정 이유**: make run이 중단되는 버그는 평가자가 파이프라인을 전혀 실행할 수 없게 하는 致命的 결함이었고, _match_utterance_id의 NULL 반환은 source_utterance_id 필드 품질을 실질적으로 저해하기 때문입니다.

### 💡 사례 12 — 멀티 앵글 자동 코드 리뷰 및 버그 수정 (Phase 3 품질 개선)
* **AI 리뷰 수행 항목**: 7개 독립 앵글(라인별 스캔·삭제 행동 감사·크로스파일 추적·재사용·단순화·효율·추상 레이어)로 후보를 병렬 수집한 뒤 검증 에이전트가 CONFIRMED/PLAUSIBLE/REFUTED 판정. 최종 확정 버그 6건 도출.
* **AI가 발견·수정한 버그 6건**:
  ① `_match_utterance_id`: `source_quote=""` 시 `"" in str`이 항상 True → 폴백 항목이 무조건 첫 번째 발화에 오귀속 → **진입부 `if not source_quote: return None` 추가**;
  ② 역방향 substring 검사(`nc in norm_quote`, `utt["content"] in source_quote`) → 짧은 필러 발화가 긴 source_quote에 오매칭 → **단방향(`quote in content`)만 허용하도록 조건 제거**;
  ③ `_upsert_action_items` ON CONFLICT 절이 `source_utterance_id`를 무조건 덮어씀 → 재추출 시 기존 유효 링크가 NULL로 파괴 → **`COALESCE(EXCLUDED.source_utterance_id, action_items_raw.source_utterance_id)` 적용**;
  ④ `stg_utterances.sql` DISTINCT ON 중복제거 ORDER BY에 `NULLS LAST` 누락 → NULL timestamp 행이 실 timestamp 행보다 우선 선택 → **`ORDER BY ... timestamp ASC NULLS LAST` 수정**;
  ⑤ `_call_gemini`에서 `json.loads(response.text)` 호출 시 `response.text`가 None이면 `TypeError`로 실패, `finish_reason` 정보 소실 → **None 조기 검사 후 `ValueError`(finish_reason 포함) 명시적 raise**;
  ⑥ `_norm` 중첩 함수가 `_normalize_content`와 목적·방식이 달라 혼동 유발 → **`_normalize_for_match`로 모듈 레벨 승격, `difflib` import 상단 이동, 주석으로 용도 명시**.
* **직접 개입 판단**: 6건 모두 AI 리뷰·수정 결과를 승인. 수정 후 `pytest 12/12 PASS` 및 수동 입력 케이스 4종 검증으로 회귀 없음 확인.
* **수정 이유**: ①②는 폴백 실행 시마다 source_utterance_id가 잘못 저장되는 무결성 오염이고, ③은 재실행 시 기존 정상 데이터를 파괴하는 멱등성 위반이며, ④는 dbt 중복제거 레이어가 의도와 반대로 동작하는 결함이고, ⑤⑥은 운영 중 원인 추적을 불가능하게 만드는 침묵 실패 패턴이기 때문입니다.

### 💡 사례 13 — grill-with-docs: 설계 결정 심층 검증 및 도메인 문서화
* **사용 도구**: `grill-with-docs` — Matt Pocock이 공개한 Claude Code 커스텀 스킬 (`npx skills add mattpocock/claude-code-skills`로 설치, `.agents/skills/`에 위치). 설계·계획을 면접관처럼 질문 공세로 검증하고, 용어가 확정될 때마다 `CONTEXT.md`에 인라인 업데이트하며, ADR 기준을 충족하는 결정에 한해 `docs/adr/`에 기록하는 구조화된 설계 검토 스킬입니다.
* **AI 수행 항목**: 8개 핵심 설계 결정을 순차 질문으로 검증. 코드베이스를 탐색하며 용어·코드 불일치를 즉시 지적하고, 결정 확정 시 `CONTEXT.md`에 인라인 반영.
* **도출된 설계 결정 및 지원자 판단 개입 사례**:
  ① `source_utterance_id` 연결 전략 — AI가 "LLM 직접 선택 vs Python fuzzy matching" 중 LLM 직접 선택이 더 올바른 설계임을 지적. **지원자 판단**: 초기 설계 시 LLM 출력 스키마 최소화에 집중하다 연결 책임을 후처리로 미룬 점 인정, 다음 버전 개선 방향 확정;
  ② `confidence` 단일 값 — AI가 "무엇에 대한 신뢰도인지 정의 부재" 지적. **지원자 판단**: PoC에서 "검수 필요 여부 판단"이라는 단일 목적에 충분하다는 근거로 단순화 유지 결정;
  ③ `status` 재추출 덮어쓰기 버그 — AI가 버그라고 지적. **지원자 판단**: 코드를 직접 확인하니 `ON CONFLICT DO UPDATE SET`에 `status`가 없어 **버그가 실제로 존재하지 않음** 반증 — AI 지적을 그대로 수용하지 않고 코드 검증으로 기각;
  ④ `action_items_raw` 명명 불일치 — AI가 `raw_` 접두사 규칙과 불일치함을 지적. **지원자 판단**: 실수로 인정하고 즉시 `raw_action_items`로 전체 통일;
  ⑤ `pipeline.py` 분리 제안 — AI가 파이프라인 로직을 별도 모듈로 분리하자고 제안. **지원자 판단**: 과제 PoC 규모에서 오버엔지니어링으로 기각;
  ⑥ `due_is_inferred` 미활용 — AI가 레이블만 있고 다음 행동이 없다고 지적. **지원자 판단**: LLM이 상대 표현을 절대 날짜로 변환하는 방향이 근본 개선임을 확인.
* **산출물**: `CONTEXT.md` (도메인 용어 8종), `docs/adr/0001` (PostgreSQL 선택 ADR), `raw_action_items` 명명 통일.

### 💡 사례 14 — 시니어 개발자 관점 코드 리뷰 후 추가 품질 개선
* **AI 리뷰 수행 항목**: 명세서 준수·기능 정확성·코드 품질·성능·보안 5개 축으로 코드 전체를 재검토. 79/100점 진단 및 주요 버그 5건 도출.
* **AI가 발견·수정한 사항**:
  ① `dashboard.py` `NamedTemporaryFile(delete=False)` 후 `finally` 블록 없음 → 음성 파일이 `/tmp`에 무한 누적(보안 제약 위반) → **`finally: Path(tmp_path).unlink(missing_ok=True)` 추가**;
  ② `load_action_items()` / `load_minutes()`에서 예외 시 `conn.close()` 미호출 → DB 커넥션 누수 → **`conn = None` 초기화 + `finally: if conn: conn.close()` 패턴으로 수정**;
  ③ `_dbt_run()` 실패 시 `stderr` 무시 → UI에서 원인 파악 불가 → **`st.error(result.stderr)` 노출 추가**;
  ④ `mart_action_items.sql`이 `raw_action_items`를 `source()`로 직접 참조 → raw → mart 직결로 dbt 설계 원칙 위반 → **`stg_action_items.sql` 신규 추가, mart에서 `ref('stg_action_items')`로 변경**;
  ⑤ `_call_gemini()` 내부에 `import genai` + `genai.configure()` 위치 → 매 호출마다 전역 상태 재설정 → **모듈 상단으로 이동, `if GEMINI_API_KEY` 조건부 초기화**.
* **직접 개입 판단**: 5건 모두 AI 리뷰·수정 승인. `pytest 12/12 PASS` + `dbt compile` 4모델 정상 파싱으로 회귀 없음 확인.
* **수정 이유**: ①②는 장시간 운영 시 리소스 누수가 발생하는 실질적 장애 원인이고, ③은 운영 중 디버깅을 원천 차단하는 구조이며, ④는 dbt lineage 단절로 데이터 품질 추적을 어렵게 만들기 때문입니다.

---

## 5. AI 도움 없이 전적으로 지원자가 직접 설계한 철학적 영역

*   **비용 vs 리스크의 가치 판단**: 회의 요약 시간 단축보다 **액션아이템 누락 차단**이 광고주 마케팅 일정을 수호하는 핵심 리스크 제어 영역임을 재정의했습니다.
*   **is_ambiguous 메타 필드 설계**: LLM에게 책임을 묻고 억지 담당자를 뽑게 만드는 대신, 애매한 R&R은 `is_ambiguous=true`로 표시하여 대시보드 검수 큐로 모이도록 설계했습니다. 이는 기술 오류에 대처하는 **인간 협업(Human-in-the-loop) 아키텍처**를 독창적으로 적용한 사례입니다.
*   **STT 확장 3단계 로드맵 구축**: `BaseTranscriber` 추상 인터페이스를 사전에 설계하여 JSON 업로드(Step 1) → 로컬 오디오 STT(Step 2) → 실시간 마이크(Step 3)까지 코어 엔진 변경 없이 연결 가능한 **확장성 높은 인터페이스 지향 아키텍처**를 구상했습니다.
