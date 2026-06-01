WITH action_items AS (
    SELECT * FROM {{ source('public', 'action_items_raw') }}
),

meetings AS (
    SELECT * FROM {{ source('public', 'raw_meetings') }}
)

SELECT
    ai.action_item_id,
    ai.meeting_id,
    m.title              AS meeting_title,
    m.date               AS meeting_date,
    ai.content,
    ai.assignee,
    ai.due_date,
    ai.due_is_inferred,
    ai.confidence,
    ai.source_utterance_id,
    ai.source_quote,
    ai.is_ambiguous,
    ai.status,
    ai.extracted_at
FROM action_items ai
LEFT JOIN meetings m USING (meeting_id)
