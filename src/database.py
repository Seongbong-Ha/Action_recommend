import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from src.config import DATABASE_URL

DDL_STATEMENTS = [
    """
    CREATE EXTENSION IF NOT EXISTS vector
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_meetings (
        meeting_id      VARCHAR PRIMARY KEY,
        title           VARCHAR NOT NULL,
        date            DATE NOT NULL,
        participants    JSONB,
        ingested_at     TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_utterances (
        utterance_id    VARCHAR PRIMARY KEY,
        meeting_id      VARCHAR NOT NULL REFERENCES raw_meetings(meeting_id),
        speaker         VARCHAR NOT NULL,
        content         TEXT NOT NULL,
        timestamp       TIMESTAMP,
        ingested_at     TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_raw_utterances_meeting_id
        ON raw_utterances (meeting_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_action_items (
        action_item_id      VARCHAR PRIMARY KEY,
        meeting_id          VARCHAR NOT NULL,
        content             TEXT NOT NULL,
        assignee            VARCHAR,
        due_date            DATE,
        due_is_inferred     BOOLEAN DEFAULT FALSE,
        confidence          FLOAT NOT NULL,
        source_utterance_id VARCHAR,
        source_quote        TEXT,
        is_ambiguous        BOOLEAN DEFAULT FALSE,
        status              VARCHAR DEFAULT 'open',
        extracted_at        TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_raw_action_items_meeting_id
        ON raw_action_items (meeting_id)
    """,
    """
    ALTER TABLE raw_action_items
        ADD COLUMN IF NOT EXISTS related_campaign VARCHAR
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_minutes (
        meeting_id      VARCHAR PRIMARY KEY,
        summary         TEXT NOT NULL,
        decisions       JSONB,
        embedding       vector(768),
        extracted_at    TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    ALTER TABLE raw_minutes
        ADD COLUMN IF NOT EXISTS embedding vector(768)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_raw_minutes_embedding
        ON raw_minutes USING hnsw (embedding vector_cosine_ops)
    """,
]


def get_connection():
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def get_cursor(commit: bool = False):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
            if commit:
                conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for stmt in DDL_STATEMENTS:
                cur.execute(stmt)
        conn.commit()
        print("DB 초기화 완료: 테이블 4개 생성 (raw_meetings, raw_utterances, raw_action_items, raw_minutes)")
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"DB 초기화 실패: {e}") from e
    finally:
        conn.close()


def reset_db():
    init_db()
    with get_cursor(commit=True) as cur:
        table_names = [
            "mart_action_items",
            "mart_minutes",
            "raw_action_items",
            "raw_minutes",
            "raw_utterances",
            "raw_meetings",
        ]
        cur.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename = ANY(%s)
            """,
            (table_names,),
        )
        existing_tables = [row["tablename"] for row in cur.fetchall()]
        if existing_tables:
            cur.execute(
                sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(name) for name in existing_tables)
                )
            )
    print("DB 데이터 초기화 완료: raw/mart 테이블 비움")


if __name__ == "__main__":
    init_db()
