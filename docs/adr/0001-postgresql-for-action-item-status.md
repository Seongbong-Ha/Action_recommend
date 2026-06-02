# ADR 0001 — PostgreSQL을 ActionItem 저장소로 선택

## 상태
확정

## 맥락
ActionItem은 LLM이 추출한 뒤 사용자가 `status`(open/done/blocked)를 직접 업데이트하는 OLTP 워크로드를 가정한다. 담당자 100명이 동시에 자신의 항목 상태를 변경하는 시나리오에서 동시 쓰기 충돌을 안전하게 처리해야 한다.

## 결정
PostgreSQL을 단일 저장소로 사용한다. dbt로 staging/mart 뷰를 구성하고, Python(psycopg2)으로 raw 테이블에 직접 쓴다.

## 대안
- **DuckDB / SQLite**: 단일 사용자 분석 워크로드에 적합하나 동시 쓰기를 지원하지 않음. status 업데이트 시나리오와 맞지 않음.
- **파일 기반(JSON/Parquet)**: 분석은 쉽지만 부분 업데이트(status 변경)가 불가능.

## 결과
- ON CONFLICT DO UPDATE 패턴으로 멱등 upsert 구현 가능.
- `status` 컬럼을 upsert SET 절에서 제외해 재추출 시 사용자 변경값 보존.
- PoC에서 상태 변경 UI는 미구현 상태 — `st.data_editor` 또는 Slack Interactive Components로 추가 예정.
