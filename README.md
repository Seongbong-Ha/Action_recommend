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
| **STT** | Transcript JSON 직접 사용 (Transcriber 인터페이스) | 외부 API 유출 금지 원칙 + 시간 제약. STT를 `Transcriber` 추상 인터페이스 뒤에 두어 추후 로컬 Whisper 교체 비용을 0으로 유지. |
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
transcript JSON
  → ① ingest.py          raw_utterances (Postgres, 불변)
  → ② dbt staging        stg_utterances (화자 정규화, 잡음 제거)
  → ③ extract.py + LLM   action_items_raw / raw_minutes (pydantic 검증 + upsert)
  → ④ dbt marts + test   mart_action_items / mart_minutes
  → ⑤ Streamlit          대시보드 (위젯 4종) / Slack JSON 페이로드
```

- **Python**: 추출·적재(EL) + LLM 로직
- **dbt**: SQL 변환(T) + 데이터 품질 테스트

---

## 실행 방법

```bash
# 1. Postgres 컨테이너 실행
docker-compose up -d

# 2. 파이프라인 전체 실행 (ingest → dbt staging → extract → dbt marts → dbt test)
make run

# 3. 대시보드 실행
make dashboard
```

LLM 실제 호출을 사용하려면:
```bash
LLM_MODE=real make run
```

---

## 설계 원칙

1. **LLM 출력을 신뢰 가능한 자산으로** — structured output + pydantic 검증 + `confidence` / `source_utterance_id` / `is_ambiguous` 3개 필드로 추출 근거를 데이터에 동봉
2. **모든 단계가 재실행에 안전** — 해시 기반 ID + `ON CONFLICT` upsert로 멱등성 확보
3. **원천 데이터는 외부로 나가지 않음** — STT 포함 모든 처리가 로컬 경계 안에서 완결
