SELECT
    action_item_id,
    meeting_id,
    content,
    assignee,
    due_date,
    due_is_inferred,
    confidence,
    source_utterance_id,
    source_quote,
    is_ambiguous,
    related_campaign,
    status,
    extracted_at
FROM {{ source('public', 'raw_action_items') }}
