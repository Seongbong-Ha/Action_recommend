WITH minutes AS (
    SELECT * FROM {{ source('public', 'raw_minutes') }}
),

meetings AS (
    SELECT * FROM {{ source('public', 'raw_meetings') }}
)

SELECT
    mn.meeting_id,
    m.title         AS meeting_title,
    m.date          AS meeting_date,
    mn.summary,
    mn.decisions,
    mn.extracted_at AS updated_at
FROM minutes mn
LEFT JOIN meetings m USING (meeting_id)
