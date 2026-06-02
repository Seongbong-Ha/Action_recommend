# Domain Glossary

## ActionItem
회의 발화록에서 LLM이 추출한 실행 과제 단위.
`content`, `assignee`, `due_date`, `confidence`, `source_utterance_id`, `is_ambiguous`, `related_campaign`으로 구성.

## due_is_inferred
기한이 언급됐으나 절대 날짜를 확정할 수 없는 경우의 플래그. `due_date=null + due_is_inferred=False`(기한 언급 없음)와 구분.
- `due_date=null + due_is_inferred=False`: 기한이 전혀 언급되지 않음
- `due_date=null + due_is_inferred=True`: "이번 주 안으로"처럼 언급됐으나 절대 날짜 미확정 → 담당자에게 기한 확인 요청 신호
**현재 구현 한계**: 대시보드에 `_(추론)_` 레이블만 있고 다음 행동(확인 요청 버튼, Slack 명시)이 없어 정보가 아닌 노이즈에 가까움.
**근본 개선 방향**: LLM이 "이번 주 안으로" 같은 상대 표현을 회의 날짜 기준으로 절대 날짜로 변환해 `due_date`에 채우고 `due_is_inferred=True` 표시. 프롬프트에 회의 날짜가 이미 주입되어 있어 기술적으로 즉시 가능. 이 경우 `due_date=null + due_is_inferred=True`는 날짜 변환 실패 에러 케이스로만 남음.

## source_utterance_id
ActionItem의 근거가 된 발화(`Utterance`)를 가리키는 외래 참조.

**현재 구현**: LLM이 `source_quote`(발화 원문 텍스트)를 반환하면 Python(`_match_utterance_id`)이 fuzzy matching으로 사후 연결.
**확정된 방향**: 프롬프트에 `[uid_xxx]` 레이블을 붙인 발화록을 넘겨 LLM이 `source_utterance_id`를 직접 반환하도록 변경 예정. fuzzy matching 로직 제거 및 `ActionItemSchema`에 필수 필드로 승격.
**현재 방식의 한계**: LLM이 발화를 재표현하면 매칭이 깨지며, 임계값 0.6은 근거 없는 매직 넘버.

## Utterance
회의 참가자의 발화 한 줄. `speaker`, `content`, `timestamp`로 구성.
`utterance_id`는 `meeting_id:speaker:timestamp:content`의 SHA-256 앞 16자리.

## 파이프라인 오케스트레이션
ingest → dbt staging → LLM extract → dbt marts 순서를 `app/dashboard.py`의 `_run_pipeline()`이 담당.
**설계 근거**: 파이프라인 트리거는 파일 업로드 이벤트이며, 업로드 UX가 대시보드에 있으므로 오케스트레이션을 대시보드에 두는 것이 UX상 자연스럽다. PoC 규모(단일 프로세스)에서 별도 `pipeline.py` 분리는 오버엔지니어링으로 판단.
**프로덕션 확장 시**: 파이프라인 로직을 `src/pipeline.py`로 분리하고 대시보드·CLI·스케줄러가 공통 함수를 임포트하는 구조로 전환.

## 테이블 명명 규칙
모든 raw 테이블은 `raw_` 접두사로 통일: `raw_meetings`, `raw_utterances`, `raw_action_items`, `raw_minutes`.
dbt mart 테이블은 `mart_` 접두사: `mart_action_items`, `mart_minutes`.

## Meeting
회의 한 건. `meeting_id`, `title`, `date`, `participants`, `utterances[]`로 구성.
`meeting_id`는 파일명 기반 SHA-256 앞 12자리 또는 JSON 내 명시값.

## related_campaign
ActionItem의 발화에서 언급된 캠페인명. LLM이 발화 원문에서 직접 추출한 자유 텍스트. 언급 없으면 `null` (강제 추측 금지).
**표기 불일치 위험**: 동일 캠페인이 "구글 SA" / "Google SA" / "구글SA" 등으로 달리 표기되면 대시보드 그룹핑이 분리됨.
**현재 대응**: few-shot 예시에 표준 표기("구글 SA", "카카오 DA") 명시로 단일 회의 범위에서 충분.
**프로덕션 확장 후보**: ① 캠페인 엔티티 테이블 + canonical name 매핑 레이어; ② 발화록에 캠페인 목록 주입 후 LLM 정규화; ③ 임베딩 유사도 매칭. raw 자유 텍스트 저장 구조는 세 방향 모두로 확장 가능하도록 열어둠.

## status
ActionItem의 처리 상태. `open` / `done` / `blocked` 세 값만 허용.
항상 `open`으로 삽입되며, ON CONFLICT DO UPDATE SET에서 `status`는 제외 — 재추출 시 사용자가 변경한 상태가 보존됨 (의도된 설계, 구현 확인).
**미구현**: 상태 변경 UI 없음. 변경 방법: ① `st.data_editor` 기반 인라인 편집 테이블; ② Slack Interactive Components '완료' 버튼 + webhook.
**설계 근거**: 100명이 동시에 자신의 ActionItem을 업데이트하는 OLTP 시나리오를 가정 → PostgreSQL 선택의 핵심 이유.

## is_ambiguous
발화 원천의 구조적 불완전성을 나타내는 플래그. LLM이 아무리 잘 해석해도 원천 발화 자체가 불완전한 케이스 — 담당자가 특정되지 않았거나 결정이 흐릿하게 끝난 경우.
`confidence`(LLM 추출 확신도)와 직교하는 신호. 예: `confidence=0.42, is_ambiguous=False` = "담당자는 명확하나 이게 진짜 ActionItem인지 불확실".
**현재 구현 한계**: 프롬프트에 두 필드의 구분이 명시되어 있지 않아 LLM이 중복 신호로 해석할 수 있음. 대시보드에서 `is_ambiguous` 전용 검수 큐 미구현 (체크박스 표시만 존재).
**개선 방향 후보**: ① 통합 — `is_ambiguous=True`이면 confidence 자동 저하 강제; ② 분리 강화 — 대시보드에 독립 검수 섹션 추가. 실제 데이터 기반 판단 예정.

## confidence
"이 항목이 ActionItem으로 유효하다"는 LLM의 종합적 자기 평가 (0.0~1.0).
발화가 명시적 ActionItem인지, assignee가 특정됐는지, 기한이 명시됐는지를 단일 값으로 통합.
0.7 미만은 저신뢰도로 분류되어 대시보드 검수 큐에 표시 (임계값은 실증 데이터 기반 재설정 예정).
**의도적 단순화**: PoC 목적("사람이 검수해야 하는가")에는 단일 값으로 충분하다고 판단. assignee_confidence 등 세분화는 다음 단계 과제.
