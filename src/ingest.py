import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from src.database import get_cursor, init_db
from src.transcriber import FileTranscriber, Meeting


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _utterance_id(meeting_id: str, speaker: str, timestamp: Optional[str], content: str) -> str:
    ts = timestamp if timestamp is not None else ""
    raw = f"{meeting_id}:{speaker}:{ts}:{content}"
    return _hash(raw)


def coerce_utterance_timestamp(
    timestamp: Optional[str],
    meeting_date: str,
) -> Optional[datetime]:
    if timestamp is None:
        return None

    value = str(timestamp).strip()
    if not value:
        return None

    try:
        offset_seconds = float(value)
    except ValueError:
        normalized_value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized_value)

    base_date = date.fromisoformat(meeting_date)
    return datetime.combine(base_date, time.min) + timedelta(seconds=offset_seconds)


def ingest_meeting(meeting: Meeting) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO raw_meetings (meeting_id, title, date, participants, ingested_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (meeting_id) DO UPDATE SET
                title        = EXCLUDED.title,
                date         = EXCLUDED.date,
                participants = EXCLUDED.participants,
                ingested_at  = EXCLUDED.ingested_at
            """,
            (
                meeting.meeting_id,
                meeting.title,
                meeting.date,
                json.dumps(meeting.participants, ensure_ascii=False),
                datetime.now(timezone.utc),
            ),
        )

        for utt in meeting.utterances:
            uid = _utterance_id(meeting.meeting_id, utt.speaker, utt.timestamp, utt.content)
            cur.execute(
                """
                INSERT INTO raw_utterances (utterance_id, meeting_id, speaker, content, timestamp, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (utterance_id) DO NOTHING
                """,
                (
                    uid,
                    meeting.meeting_id,
                    utt.speaker,
                    utt.content,
                    coerce_utterance_timestamp(utt.timestamp, meeting.date),
                    datetime.now(timezone.utc),
                ),
            )

    print(f"적재 완료: {meeting.meeting_id} | 발화 {len(meeting.utterances)}건")


if __name__ == "__main__":
    init_db()
    transcriber = FileTranscriber()
    meeting = transcriber.load("data/sample_meeting.json")
    ingest_meeting(meeting)
