from src.database import get_cursor

VALID_STATUSES = {"open", "done", "blocked"}


def validate_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in VALID_STATUSES:
        allowed = ", ".join(sorted(VALID_STATUSES))
        raise ValueError(f"지원하지 않는 status입니다: {status}. 허용값: {allowed}")
    return normalized


def update_action_item_status(action_item_id: str, status: str) -> None:
    normalized_status = validate_status(status)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE raw_action_items
            SET status = %s
            WHERE action_item_id = %s
            """,
            (normalized_status, action_item_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"action_item_id를 찾을 수 없습니다: {action_item_id}")
