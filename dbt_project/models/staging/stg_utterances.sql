WITH source AS (
    SELECT * FROM raw_utterances
),

-- 잡음성 단독 발화 제거 (1~2음절 감탄사 등)
filtered AS (
    SELECT *
    FROM source
    WHERE LENGTH(TRIM(content)) > 5
),

-- 화자명 정규화 (호칭 제거)
normalized AS (
    SELECT
        utterance_id,
        meeting_id,
        REGEXP_REPLACE(speaker, '(님|씨|팀장|대리|부장)$', '') AS speaker,
        content,
        timestamp,
        ingested_at
    FROM filtered
),

-- 동일 meeting_id + speaker + content 중복 발화 제거 (가장 빠른 timestamp 유지)
deduped AS (
    SELECT DISTINCT ON (meeting_id, speaker, content)
        utterance_id,
        meeting_id,
        speaker,
        content,
        timestamp,
        ingested_at
    FROM normalized
    ORDER BY meeting_id, speaker, content, timestamp ASC
)

SELECT * FROM deduped
