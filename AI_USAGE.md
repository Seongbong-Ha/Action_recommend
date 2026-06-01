# AI 활용 내역 (AI_USAGE.md)

---

## 1. 사용한 AI 도구

| 도구 | 주요 용도 |
|---|---|
| **Claude Code** (Anthropic, claude-sonnet-4-6) | 코드 생성·편집, 문서 작성, 파이프라인 실행 및 검증 |
| **Antigravity** | 계획 수립, 코드 검토, 테스트 설계 |

### Claude Code를 선택한 이유

- **컨텍스트 유지**: 대화 흐름 속에서 기획안·plan.md·README를 함께 읽고 일관된 판단을 내릴 수 있음
- **코드 + 문서 동시 작업**: 파일 읽기·편집·터미널 실행을 한 에이전트 안에서 처리 가능
- **비판적 피드백**: 단순 생성이 아니라 "이 부분이 빠졌다", "이 설계는 문제가 있다"는 식의 검토 역할을 수행할 수 있음

### Antigravity를 선택한 이유

- **계획 수립**: 마일스톤 구조·우선순위·일정 설계 단계에서 전체 흐름을 검토하고 구조화하는 데 활용
- **코드 검토**: 생성된 코드의 설계 원칙 준수 여부, 엣지케이스 누락, 개선 포인트를 독립적 시각으로 리뷰
- **테스트 설계**: dbt 테스트 커버리지, 멱등성 검증 시나리오 등 품질 보증 전략 수립에 활용

---

## 2. 컨텍스트 제공 방식 및 프롬프트 전략

### 컨텍스트 파일 제공 순서
1. `기획안_초안.md` — 프로젝트 전체 설계 의사결정 근거 문서를 먼저 읽히고 숙지시킴
2. `plan.md` (초안) — 기획안을 바탕으로 작성한 구현 계획서를 검토 요청

### 주요 프롬프트 방식
- **숙지 먼저**: 코드 작성 전 "기획서 읽고 내용 확실히 숙지해줘"로 문서를 컨텍스트로 주입
- **검토 요청**: "피드백 부탁해" — 단순 수행이 아닌 비판적 검토 역할 부여
- **컨펌 단계**: 수정 후 "마지막 컨펌 부탁해"로 최종 검토 루프를 돌림
- **범위 제한**: README 작성 시 "기술 스택 선정 이유"로 범위를 명확히 지정하여 불필요한 내용 생성 방지

---

## 3. AI 결과물을 직접 수정한 판단 사례

### 사례 1 — plan.md 마일스톤 날짜 재조정

**AI 초안**: Milestone 1~5를 Day 1~5(5일치) 구조로 작성  
**직접 수정**: Milestone을 3개로 통합하고 6/1, 6/2, 6/3(마감일) 실제 날짜로 재편

**수정 이유**: AI는 "논리적으로 충분한 일정"을 짰지만, 마감이 6/3이라는 제약을 반영하지 못했음. 단순히 날짜를 바꾸는 게 아니라 Milestone 3(대시보드)를 마감일 당일로 배치하고, Milestone 1~2에 핵심 파이프라인을 몰아야 한다는 우선순위 판단이 필요했음.

---

### 사례 2 — mart_minutes 설계 보완

**AI 피드백**: "`mart_minutes`의 `title`, `date`를 어디서 조인할지 소스가 없다"고 지적  
**직접 수정**: `raw_minutes` 테이블에 `title`, `date` 컬럼을 추가하는 대신, `extract.py`에서 LLM 요약 생성 시 회의 메타데이터를 함께 적재하는 방식으로 설계 변경. `raw_minutes` → `mart_minutes` 흐름을 plan.md에 명시.

**수정 이유**: AI가 문제를 짚어줬지만 해결 방향은 내가 결정해야 했음. `raw_utterances`에 meeting 메타 컬럼을 추가하는 방법도 있었으나, 발화(utterance)와 회의 요약(minutes)은 책임이 다르므로 별도 테이블로 분리하는 것이 설계 원칙(단일 책임)에 맞다고 판단.

---

### 사례 3 — DB 비교표 서술 방식 결정

**AI 초안**: README DB 선정 이유를 한 줄 텍스트로 작성  
**직접 수정 요청**: "각 DB 장단점을 표로 작성하고, 그걸 기반으로 PostgreSQL 선택 이유를 설명하는 방식"으로 구조를 지정

**수정 이유**: 평가자 입장에서 "왜 다른 선택지를 버렸는지"를 보여주는 것이 단순히 "PostgreSQL을 선택했다"는 서술보다 설득력 있음. AI는 결론을 바로 쓰려 했지만, 비교 과정을 드러내는 것이 기술적 판단력을 보여주는 데 더 효과적이라고 판단.

---

### 사례 4 — profiles.yml 보안 처리 방식 결정 (1차 → 2차 수정)

**1차 결정**: `~/.dbt/profiles.yml` 전역 경로 대신, 레포 안에 두되 `.gitignore`로 차단하는 방식 선택  
**문제 발견**: 실제 `.gitignore`에 `dbt_project/profiles.yml` 항목이 누락되어 있었고, 비밀번호가 평문으로 하드코딩된 채 커밋된 상태였음. 문서와 실제 상태가 불일치.

**2차 수정 (코드 리뷰 후)**:
- `profiles.yml`을 `env_var()` 기반으로 전면 수정 (하드코딩 제거)
- `.gitignore`에 `dbt_project/profiles.yml` 추가
- `dbt_project/profiles.example.yml` 생성 (온보딩 가이드)

**교훈**: 문서에 "gitignore로 차단"이라고 썼으면 실제 .gitignore 파일을 열어 항목이 있는지 반드시 확인해야 함.

---

### 사례 5 — Makefile dbt 옵션 순서 버그 수정

**AI 초안**: `Makefile`의 `DBT` 변수를 `dbt --profiles-dir ./dbt_project`로 선언하여 전역 옵션처럼 사용  
**직접 수정**: dbt CLI는 `dbt [subcommand] --profiles-dir ...` 순서를 요구하므로, `DBT := dbt`로 변수를 단순화하고 `--profiles-dir` 옵션을 각 커맨드 라인에 명시적으로 이동

**수정 이유**: AI가 생성한 Makefile은 `dbt --profiles-dir run` 순서로 작성되어 실제 실행 시 "No such option '--profiles-dir'" 오류가 발생했음. 올바른 순서는 `dbt run --profiles-dir`로, 옵션이 서브커맨드 뒤에 와야 함. `make run` 실행 검증 단계에서 직접 오류를 확인하고 수정.

---

### 사례 6 — dbt-utils 의존성 누락 발견 및 데이터 검증 강화

**AI 초안**: dbt 기본 내장 테스트만 사용하여 `confidence` (0.0 ~ 1.0) 범위를 검증하려 함.  
**직접 수정**: dbt 기본 테스트(`unique`, `not_null` 등)로는 부동소수점 범위(Range) 테스트가 불가능함을 발견하고, `dbt_project/packages.yml`에 `dbt-utils` 라이브러리를 직접 명시하여 `dbtdeps` 설치 단계를 추가하도록 지시.

**수정 이유**: AI는 confidence 컬럼의 한계 검증을 단순한 schema validation으로 처리하려 했으나, 실제 프로덕션 레벨의 정밀한 품질 관리를 위해서는 `dbt-utils`의 `accepted_range` 테스트가 필수적임. AI가 생략한 패키지 종속성을 초기에 잡아내어 빌드 안정성을 확보함.

---

### 사례 7 — utterance_id의 멱등적 데이터 타입 강제

**AI 초안**: raw 발화 테이블 설계에서 `utterance_id`를 `SERIAL`과 `VARCHAR`로 혼용하여 기재함.  
**직접 수정**: `SERIAL`과 같은 자동 증가 정수형 PK는 파이프라인 재실행 시 중복 유입에 취약하며 멱등성을 깨뜨리므로, `meeting_id + speaker + timestamp + content(hash)`의 해시 기반 `VARCHAR`로 고정하도록 지시.

**수정 이유**: 원천 데이터 수집(EL) 및 dbt 변환(T)을 무한히 재실행해도 항상 동일한 상태를 유지해야 하는 '멱등성(Idempotency)' 원칙을 엄격하게 지키기 위해, 자동 증가형 키를 차단하고 해시 기반의 자연 키(Natural Key) 성격의 고유 식별자를 직접 명문화함.

---

## 4. 구현 단계 AI 활용 내역

### [Milestone 1] 수집 파이프라인 (transcriber.py / ingest.py / dbt staging)

**AI가 수행한 작업**
- `data/sample_meeting.json`: plan.md 섹션 3 스키마 기반으로 광고 미디어 도메인 16발화 샘플 데이터 생성
- `src/transcriber.py`: `BaseTranscriber` 추상 인터페이스 + `FileTranscriber` 구현
- `src/ingest.py`: SHA-256 해시 기반 `utterance_id` 생성 + `ON CONFLICT` upsert 적재
- `dbt_project/` 초기화: `dbt_project.yml`, `profiles.yml`, `packages.yml`, `stg_utterances.sql`, `schema.yml`

**프롬프트 방식**
- "sample_meeting.json → transcriber.py → ingest.py 순서로 진행" — 순서를 명시해 단계별로 실행
- 작업 완료마다 `python -m src.ingest` 실행 및 DB 직접 조회로 실제 적재 여부 검증 지시

**직접 개입한 판단**
- `raw_meetings` 테이블 추가: AI 초안에는 없었으나, `mart_minutes`의 `title`/`date` 조인 소스 문제를 해결하기 위해 meeting 메타데이터 전용 테이블을 별도로 두도록 설계 변경 지시
- `config.py` 보안 수정: AI가 `os.getenv("POSTGRES_PASSWORD", "mobidays1234")`처럼 패스워드 기본값을 코드에 하드코딩한 것을 발견하고, 민감 정보는 `.env` 필수 로드로 강제하도록 직접 수정 지시
- `stg_utterances.sql` 잡음 제거 기준: "LENGTH > 5" 조건은 AI가 제안했으나, 광고 도메인 단답 발화("네", "알겠습니다")가 의미 있는 발화임을 고려해 기준을 최소화하도록 검토 후 유지 결정

---

---

### [Milestone 2] AI 추출 파이프라인 (extract.py / dbt marts / schema.yml)

**AI가 수행한 작업**
- `src/extract.py`: `ActionItemSchema` / `MinutesSummarySchema` Pydantic 모델, Mock LLM 데이터, Gemini API 호출, 3회 재시도 로직, `_match_utterance_id()` 발화 매핑, `_upsert_action_items()` / `_upsert_minutes()` upsert 구현
- `dbt_project/models/marts/mart_action_items.sql`: `action_items_raw` + `raw_meetings` LEFT JOIN 비정규화
- `dbt_project/models/marts/mart_minutes.sql`: `raw_minutes` + `raw_meetings` LEFT JOIN
- `dbt_project/models/marts/schema.yml`: `dbt-utils accepted_range`, `accepted_values` 테스트 선언

**프롬프트 방식**
- "extract.py → dbt marts 순서로, plan.md 섹션 4.3~4.4 스키마를 그대로 반영해줘"
- 각 단계 완료 후 `python -m src.extract` 실행 및 DB 직접 조회로 실제 데이터 확인 지시

**직접 개입한 판단**
- `_extract_action_items` 폴백 설계 확인: 3회 재시도 후 최종 실패 시 `confidence=0` + `is_ambiguous=True` 항목을 검수 큐로 보내는 방식이 설계 원칙과 맞는지 검토 후 승인
- 프롬프트 품질 결정: 도메인 약어 사전(`_DOMAIN_CONTEXT`), 잡음 처리 지침(`_NOISE_INSTRUCTIONS`), R&R 핑퐁 few-shot 예시(`_FEW_SHOT`) 3개 섹션 구조는 AI 제안을 그대로 채택. 광고 도메인 특화 문구("SA", "DA", "소재" 등)는 검토 후 유지 결정

---

### [Milestone 3] Streamlit 대시보드 (dashboard.py)

**AI가 수행한 작업**
- `app/dashboard.py`: `mart_action_items` / `mart_minutes` 쿼리, 위젯 4종(메트릭·바차트·저신뢰도 테이블·의사결정 expander), Slack JSON 페이로드 생성 및 사이드바 다운로드 버튼 구현

**프롬프트 방식**
- "plan.md Milestone 3 요구사항을 기준으로 dashboard.py 구현. `mart_action_items`, `mart_minutes` 테이블을 읽는 위젯 4종 + Slack 사이드바"

**직접 개입한 판단**
- `@st.cache_data(ttl=60)` 캐싱 적용 여부: AI가 제안한 60초 TTL을 실시간성과 DB 부하 사이 적정값으로 판단하여 채택
- 빈 데이터 처리 방식: `df.empty`일 때 `st.warning` + `st.stop()`으로 조기 종료하는 패턴은 AI 초안에 없었으나, 파이프라인 미실행 상태에서 앱을 열었을 때 스택트레이스 대신 명확한 안내 메시지를 보여줘야 한다고 판단해 추가 지시

---

### [전체 검증] end-to-end 파이프라인 통합 테스트

**AI가 수행한 작업**
- `make run` → `make test` → `make dashboard` 순서로 전체 파이프라인 검증
- dbt 16개 테스트 전체 PASS 확인
- `make demo` 타겟 추가: 파이프라인 실행 + 대시보드 시작을 단일 명령으로 처리
- Gemini 모델 `gemini-1.5-flash` → `gemini-2.5-flash` 교체 (v1beta API 지원 종료 대응)
- `LLM_MODE=real` 실제 호출 검증: 액션아이템 4건 추출, confidence 0.95~0.98, dbt test 16/16 PASS

**직접 개입한 판단**
- Makefile 버그 발견(사례 5 참고) 및 수정 지시
- Gemini 모델 교체 시 `gemini-2.0-flash` 대신 `gemini-2.5-flash` 선택 — 최신 안정 모델로 성능 우선

---

---

### [Step 1] FileTranscriber 신 포맷 지원

**AI가 수행한 작업**
- `src/transcriber.py`: 신 포맷(`segments` 키) 자동 감지 로직 추가
  - `Utterance.timestamp` → `Optional[str] = None` 변경
  - `_load_legacy()` / `_load_new()` 분리, 파일명 해시 기반 `meeting_id` 자동 생성
- 신 포맷 데이터(37발화) 전체 ingest 검증

**프롬프트 방식**
- 실제 test_data JSON 구조를 보여주고 "기존 FileTranscriber가 두 포맷을 모두 처리하게 수정해줘"

**직접 개입한 판단**
- STT 확장 로드맵 구상: JSON 파일 → mp3/Whisper → 마이크 실시간 3단계 방향은 직접 설계
- `BaseTranscriber` 인터페이스가 이미 이 확장을 수용하는 구조임을 확인하고 Step 1~3 로드맵 확정

---

### [Step 2 - A] WhisperTranscriber — mp3 STT + 화자 분리

**AI가 수행한 작업**
- `src/transcriber.py`: `WhisperTranscriber` 클래스 구현
  - whisperx STT (faster-whisper 백엔드) + pyannote 화자 분리 통합
  - `whisperx.diarize.DiarizationPipeline` 올바른 API 경로 탐색 및 적용
  - mp3/wav/m4a/flac 지원을 위한 `AUDIO_EXTENSIONS` 상수 추가
- `src/config.py`: `HUGGINGFACE_TOKEN` 환경변수 추가
- `app/dashboard.py`: 음성 파일 업로드 시 `WhisperTranscriber` 자동 선택
- `requirements-whisperx.txt`: 선택 설치 파일 분리
- `.env.example`: `HUGGINGFACE_TOKEN` 및 모델 동의 안내 추가

**직접 개입한 판단**
- whisperx 3.8.6 API 변경 대응: `DiarizationPipeline` 위치(`whisperx.diarize`), 파라미터명(`use_auth_token` → `token`) 오류를 직접 디버깅하여 수정 지시
- pyannote 모델 동의: `speaker-diarization-3.1` → 실제 로드되는 모델이 `speaker-diarization-community-1`임을 확인하고 해당 모델 동의 진행 결정
- 속도 문제 인식: CPU 환경에서 4분 음성 처리에 5~8분 소요 → 현재는 기능 구현 완료 상태로 유지, 사전 처리 CLI 스크립트 추가는 후순위로 결정

---

### [Step 2 - B] 대시보드 파이프라인 실행 UI

**AI가 수행한 작업**
- `app/dashboard.py` 사이드바 "새 회의 업로드" 섹션 구현
  - `st.file_uploader` → `FileTranscriber` 파싱 → 발화자 감지
  - 화자 이름 수정 입력 폼 (session_state로 재실행 간 유지)
  - 파이프라인 실행 버튼 → `st.status()` 5단계 진행 표시
  - 완료 후 `st.cache_data.clear()` + `st.rerun()` 결과 화면 자동 갱신
- `_run_pipeline()` 함수: Python 직접 임포트 방식으로 ingest·extract 호출, dbt는 subprocess

**프롬프트 방식**
- "사이드바에 JSON 업로드 → 화자 매핑 → 파이프라인 실행 흐름을 구현해줘"
- 기획안 v2 섹션 3.4(사이드바 채택), 3.5(Python 직접 임포트) 결정사항을 그대로 반영

**직접 개입한 판단**
- pyannote.audio(화자 분리) 후순위로 보류 결정 — HuggingFace 라이선스 동의 자동화 불가 + 과제 외부 의존성 제약
- WhisperX 없이 JSON 업로드 → 파이프라인 실행 흐름을 먼저 완성하는 B 경로 선택
- `df.empty` 시 `st.stop()` 제거 결정 — 데이터 없는 초기 상태에서도 업로드 섹션 접근 가능해야 함

---

### [대시보드 위젯 명세 일치 + README 보완]

**AI가 수행한 작업**
- 대시보드 위젯 명세와 현재 구현 갭 분석
- `app/dashboard.py` 전면 수정:
  - 섹션1: 날짜별 발생 추이 바차트 (`meeting_date` 기준 groupby)
  - 섹션2: 미완료(open) Top 5 — `status='open'` 필터 + 내림차순 정렬
  - 섹션3 (신규): 캠페인/광고주별 키워드 — BoW(`_extract_keywords`), STOPWORDS 기반 불용어 제거
  - 섹션4: confidence 히스토그램(0.1 버킷) + 기존 드릴다운 테이블 유지
- `README.md`에 **프롬프트 설계 근거**, **가정 사항** 섹션 신규 추가
- Plan 모드로 구현 전 설계 검토 진행

**프롬프트 방식**
- 과제.md 전문을 읽힌 뒤 갭 분석 요청 → 계획 수립 → Plan 모드 승인 후 구현
- "konlpy 사용 금지, 공백 분리 + 불용어 방식으로 BoW 구현" 제약 명시

**직접 개입한 판단**
- 위젯 명세와 현재 구현 불일치를 직접 발견하고 수정 우선순위 결정
- BoW 키워드 STOPWORDS 목록: AI 초안에 기본 조사만 있었으나 광고 도메인 범용 단어("완료", "확인", "진행" 등) 추가 지시
- Plan 모드 사용: 구현 전 설계를 검토하고 승인하는 방식 선택 — 마감 직전 대형 변경에 대한 리스크 관리

---

## 5. AI를 사용하지 않은 판단 영역

- **1순위 페인포인트 결정** (액션아이템 누락 > 정리 시간): 기획안 작성 시 직접 판단
- **`is_ambiguous` 필드 도입**: "흐릿한 결정을 버리지 않고 플래그로 보존"하는 아이디어는 직접 설계
- **마감 일정 기준 우선순위 조정**: AI는 이상적인 일정을 제안하지만, 무엇을 버리고 무엇을 지킬지는 직접 결정
- **STT 확장 로드맵 방향**: JSON → mp3 → 마이크 3단계 구조는 직접 구상. `BaseTranscriber` 인터페이스가 이를 수용하는 구조임을 확인한 뒤 진행 방향 결정
