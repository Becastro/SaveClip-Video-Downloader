import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


class LocalStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rate_windows (
                    window_key TEXT PRIMARY KEY,
                    request_count INTEGER NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def set_task_state(self, task_id: str, fields: dict[str, object]) -> None:
        from app.task_state import validate_transition

        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            state = json.loads(row["state"]) if row else {}
            if "status" in fields:
                validate_transition(
                    state.get("status"),
                    str(fields["status"]),
                )
            state.update(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else str(value)
                    for key, value in fields.items()
                }
            )
            connection.execute(
                """
                INSERT INTO tasks(task_id, state, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (task_id, json.dumps(state, ensure_ascii=False), time.time()),
            )

    def get_task_state(self, task_id: str) -> dict[str, str]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return json.loads(row["state"]) if row else {}

    def delete_task(self, task_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

    def delete_expired_terminal_tasks(self, cutoff: float) -> None:
        from app.task_state import TERMINAL_STATUSES

        terminal_states = tuple(TERMINAL_STATUSES)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT task_id, state FROM tasks WHERE updated_at <= ?",
                (cutoff,),
            ).fetchall()
            expired_ids = [
                row["task_id"]
                for row in rows
                if json.loads(row["state"]).get("status") in terminal_states
            ]
            connection.executemany(
                "DELETE FROM tasks WHERE task_id = ?",
                ((task_id,) for task_id in expired_ids),
            )

    def increment_rate_window(self, key: str, expiry_seconds: int) -> int:
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM rate_windows WHERE expires_at <= ?", (now,))
            connection.execute(
                """
                INSERT INTO rate_windows(window_key, request_count, expires_at)
                VALUES (?, 1, ?)
                ON CONFLICT(window_key) DO UPDATE SET
                    request_count = request_count + 1
                """,
                (key, now + expiry_seconds),
            )
            row = connection.execute(
                "SELECT request_count FROM rate_windows WHERE window_key = ?",
                (key,),
            ).fetchone()
        return int(row["request_count"])
